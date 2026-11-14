"""套件用例发现：受控来源 -> 平台固定代码副本 -> pytest --collect-only。

为什么用子进程而不是 import 测试文件：夹具（conftest）有副作用，任何 in-process
收集都会把被测项目的模块灌进本进程的 sys.modules / 全局状态，还可能污染
locale、logging、事件的全局钩子。子进程是唯一的隔离边界。

纪律
----
- 本模块**不 import 任何 vendor 包**，只按路径起子进程（development-plan.md §5.2）。
- 浏览器不能把任意宿主路径当成可信来源。来源先按预配置可信根解析，再做
  包含性 / 符号链接 / 交接点（reparse point）检查；通过后复制成平台管理的
  固定副本，发现只在副本上跑。来源在复制期间变化（内容、文件集合、目录身份）
  一律中止，不发布副本。
- 副本摘要（逐文件 sha256 + 树摘要）写进 suite_versions.manifest.code_copy；
  执行前用 verify_code_copy 复验，缺失/损坏即阻断，绝不回退到来源目录。

环境变量
--------
- TESTDOCK_TRUSTED_SUITE_ROOTS：预配置可信根，os.pathsep 分隔；缺省仓库根。
- TESTDOCK_CODE_COPIES_DIR：固定副本根目录；缺省 <data_dir>/code-copies。
- TESTDOCK_SUITE_SOURCES：预配置来源（JSON 数组），浏览器只传 source_id；
  未配置时来源列表为空，登记/发现一律拒绝（不回退到任意宿主路径）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: collect-only 的超时（秒）。套件很大时 collect 也可能慢，给足 120s。
DISCOVER_TIMEOUT_S = 120
#: 失败时回给前端的 stderr 尾巴行数（需求：末 200 行）
STDERR_TAIL_LINES = 200

#: manifest.code_copy 的形状版本
CODE_COPY_SCHEMA_VERSION = 1
#: 副本旁车文件后缀（放在副本目录外，不参与副本摘要）
CODE_COPY_SIDECAR_SUFFIX = ".code-copy.json"

#: 复制/校验时跳过的缓存目录与临时文件（与 domain/artifacts.py 同一口径）
_SKIP_DIR_NAMES = frozenset(
    {".pytest_cache", "__pycache__", ".git", ".cache", ".ipynb_checkpoints"}
)
_SKIP_SUFFIXES = frozenset({".pyc", ".pyo", ".tmp", ".part", ".swp"})

#: Windows reparse point 属性（junction / symlink / mount point）
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class DiscoverErrorKind:
    """失败分类。路由层据此选 code，本模块不关心 HTTP。"""

    ROOT_MISSING = "root_missing"
    ROOT_NOT_DIR = "root_not_dir"
    TIMEOUT = "timeout"
    FAILED = "failed"
    NO_TESTS = "no_tests"
    PYTEST_MISSING = "pytest_missing"


class SourceBoundaryError(Exception):
    """来源边界校验失败（越界 / 链接逃逸 / 来源缺失或非目录）。"""

    def __init__(self, code: str, message: str, *, source_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.source_id = source_id


class CodeCopyError(Exception):
    """固定副本创建/校验失败（来源变化、磁盘不足、摘要损坏或缺失）。"""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class DiscoverResult:
    ok: bool
    node_ids: list[str] = field(default_factory=list)
    returncode: int | None = None
    stderr_tail: list[str] = field(default_factory=list)
    error: str | None = None
    command: list[str] = field(default_factory=list)

    def as_manifest_extra(self) -> dict[str, object]:
        return {"discover": {"command": self.command, "returncode": self.returncode}}


@dataclass(frozen=True)
class ResolvedSource:
    """通过边界校验的真实来源目录。"""

    source_id: str
    path: Path
    trusted_root: Path
    identity: tuple[int, int]


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def configured_trusted_roots() -> list[Path]:
    """预配置可信根（TESTDOCK_TRUSTED_SUITE_ROOTS，缺省仓库根）。"""
    raw = os.environ.get("TESTDOCK_TRUSTED_SUITE_ROOTS", "").strip()
    if raw:
        roots: list[Path] = []
        for item in raw.split(os.pathsep):
            item = item.strip()
            if not item:
                continue
            roots.append(Path(os.path.expanduser(item)).resolve())
        return roots
    from ..config import settings

    return [settings.repo_root.resolve()]


def configured_code_copies_root() -> Path:
    """固定副本根目录（TESTDOCK_CODE_COPIES_DIR，缺省 <data_dir>/code-copies）。"""
    raw = os.environ.get("TESTDOCK_CODE_COPIES_DIR", "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    from ..config import settings

    return (settings.data_dir / "code-copies").resolve()


#: 预配置套件来源（JSON 数组）。浏览器只认 source_id，永远不传宿主路径。
#: 形状：[{"id": "demo-ui", "name": "演示 UI 套件", "path": "D:/suites/demo-ui",
#:        "test_types": ["ui", "joint"]}]
SUITE_SOURCES_ENV = "TESTDOCK_SUITE_SOURCES"

#: 来源为空时给浏览器看的提示。空数组本身不解释"为什么没有可选来源"，
#: 页面需要一句明确的"该由宿主配置"，而不是一个可以随便填路径的输入框。
EMPTY_SUITE_SOURCES_HINT = (
    f"未配置可信套件来源：需要宿主预配置 {SUITE_SOURCES_ENV} 后才能登记或发现套件。"
    "浏览器只能选择 source_id，不能指定宿主路径。"
)


@dataclass(frozen=True)
class SuiteSource:
    """一条预配置来源。path 只在本进程内使用，对外视图必须剔除。"""

    id: str
    name: str
    path: Path
    test_types: tuple[str, ...]

    def public_view(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "test_types": list(self.test_types)}


def configured_suite_sources() -> list[SuiteSource]:
    """解析 TESTDOCK_SUITE_SOURCES；未配置返回空列表（不是错误）。"""
    raw = os.environ.get(SUITE_SOURCES_ENV, "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise SourceBoundaryError(
            "source_config_invalid", f"{SUITE_SOURCES_ENV} 不是合法 JSON"
        ) from exc
    if not isinstance(payload, list):
        raise SourceBoundaryError(
            "source_config_invalid", f"{SUITE_SOURCES_ENV} 必须是数组"
        )

    sources: list[SuiteSource] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise SourceBoundaryError(
                "source_config_invalid", f"{SUITE_SOURCES_ENV} 的每一项都必须是对象"
            )
        source_id = str(item.get("id") or "").strip()
        raw_path = str(item.get("path") or "").strip()
        if not source_id or not raw_path:
            raise SourceBoundaryError(
                "source_config_invalid", "来源必须同时提供 id 与 path"
            )
        if source_id in seen:
            raise SourceBoundaryError(
                "source_config_invalid", f"来源 id 重复：{source_id}"
            )
        seen.add(source_id)
        test_types = item.get("test_types") or ["ui", "performance", "joint"]
        if not isinstance(test_types, list) or not test_types:
            raise SourceBoundaryError(
                "source_config_invalid", f"来源 {source_id} 的 test_types 必须是非空数组"
            )
        sources.append(
            SuiteSource(
                id=source_id,
                name=str(item.get("name") or source_id),
                path=Path(os.path.expanduser(raw_path)),
                test_types=tuple(str(t) for t in test_types),
            )
        )
    return sources


def list_suite_sources() -> list[dict[str, Any]]:
    """对外视图：只给 source_id / 显示名 / 适用类型，不含宿主绝对路径。"""
    return [source.public_view() for source in configured_suite_sources()]


def suite_sources_hint(items: list[dict[str, Any]]) -> str | None:
    """来源为空时的明确提示；有来源则无需提示（返回 None）。"""
    return None if items else EMPTY_SUITE_SOURCES_HINT


def resolve_configured_source(
    source_id: str, *, test_type: str | None = None
) -> ResolvedSource:
    """按 source_id 取预配置来源，再做与 resolve_source 相同的边界校验。"""
    wanted = (source_id or "").strip()
    if not wanted:
        raise SourceBoundaryError("source_missing", "source_id 不能为空")
    sources = {source.id: source for source in configured_suite_sources()}
    source = sources.get(wanted)
    if source is None:
        raise SourceBoundaryError(
            "source_not_configured",
            f"来源 {wanted!r} 不在预配置来源列表内",
            source_id=wanted,
        )
    if test_type and test_type not in source.test_types:
        raise SourceBoundaryError(
            "source_type_mismatch",
            f"来源 {wanted!r} 不适用于 {test_type} 套件",
            source_id=wanted,
        )
    resolved = resolve_source(str(source.path), trusted_roots=[source.path.parent])
    return ResolvedSource(
        source_id=source.id,
        path=resolved.path,
        trusted_root=resolved.trusted_root,
        identity=resolved.identity,
    )


# --------------------------------------------------------------------------- #
# 来源边界
# --------------------------------------------------------------------------- #
def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def _is_within(path: Path | str, root: Path | str) -> bool:
    """path 是否在 root 之下（Windows 大小写不敏感，纯词法）。"""
    child = _norm(path)
    parent = _norm(root)
    if child == parent:
        return True
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # 不同盘符
        return False


def _is_link_like(path: Path) -> bool:
    """symlink 或 Windows junction / mount point（reparse point）。"""
    try:
        info = os.lstat(path)
    except (FileNotFoundError, OSError):
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _reject_tree_links(root: Path, *, source_id: str) -> None:
    """来源目录树内的符号链接/交接点在解析期即拒绝（复制前 fail-fast）。

    与副本扫描（_iter_regular_files）同一套跳过规则；区别在错误类型——这里
    是来源边界问题（SourceBoundaryError / source_symlink），登记阶段就该给
    浏览器明确原因，而不是等到复制才以 code_copy_corrupt 失败（工单 03）。
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames:
            if name in _SKIP_DIR_NAMES:
                continue
            if _is_link_like(Path(dirpath) / name):
                raise SourceBoundaryError(
                    "source_symlink",
                    "来源目录内包含符号链接或交接点，拒绝越界读取",
                    source_id=source_id,
                )
        for name in filenames:
            if Path(name).suffix.lower() in _SKIP_SUFFIXES:
                continue
            if _is_link_like(Path(dirpath) / name):
                raise SourceBoundaryError(
                    "source_symlink",
                    "来源目录内包含符号链接，拒绝越界读取",
                    source_id=source_id,
                )


def _reject_link_components(path: Path, root: Path) -> None:
    """从可信根到目标路径的每一级都拒绝链接/交接点。"""
    if _is_link_like(root):
        raise SourceBoundaryError(
            "source_symlink", "可信来源根本身是链接/交接点，拒绝作为来源"
        )
    try:
        relative = path.relative_to(root)
    except ValueError as exc:  # 词法上已经越界
        raise SourceBoundaryError(
            "source_outside_trusted_root", "来源路径不在预配置可信目录内"
        ) from exc
    current = root
    for part in relative.parts:
        current = current / part
        if _is_link_like(current):
            raise SourceBoundaryError(
                "source_symlink",
                "来源路径包含符号链接或交接点，拒绝越界读取",
                source_id=path.name,
            )


def _source_identity(path: Path) -> tuple[int, int]:
    info = os.stat(path, follow_symlinks=False)
    return int(getattr(info, "st_dev", 0)), int(getattr(info, "st_ino", 0))


def resolve_source(
    raw: str | None, *, trusted_roots: Iterable[Path | str] | None = None
) -> ResolvedSource:
    """把浏览器给的值解析成可信根内的真实来源目录。

    接受两种写法：
    - 预配置 source_id / 相对路径：在可信根下查找同名目录；
    - 绝对路径：只允许落在某个可信根内。

    以下情况一律拒绝：`..` 穿越、越界、符号链接/交接点逃逸、来源不存在或不是目录。
    """
    text = (raw or "").strip()
    if not text:
        raise SourceBoundaryError("source_missing", "来源不能为空")

    roots = [
        Path(os.path.expanduser(str(r))).resolve()
        for r in (trusted_roots or configured_trusted_roots())
    ]
    if not roots:
        raise SourceBoundaryError("source_not_configured", "没有配置可信套件来源目录")

    expanded = Path(os.path.expanduser(text))
    source_id = expanded.name if expanded.name not in ("", ".", "..") else "source"

    if expanded.is_absolute():
        candidates = [Path(os.path.abspath(expanded))]
    else:
        if ".." in expanded.parts:
            raise SourceBoundaryError(
                "source_outside_trusted_root", "来源路径不允许包含 '..'", source_id=source_id
            )
        candidates = [Path(os.path.abspath(root / expanded)) for root in roots]

    outside_error: SourceBoundaryError | None = None
    for candidate in candidates:
        containing = next((root for root in roots if _is_within(candidate, root)), None)
        if containing is None:
            outside_error = SourceBoundaryError(
                "source_outside_trusted_root",
                "来源路径不在预配置可信目录内",
                source_id=source_id,
            )
            continue
        _reject_link_components(candidate, containing)
        if not candidate.exists():
            continue
        if not candidate.is_dir():
            raise SourceBoundaryError(
                "source_not_dir", "来源不是目录", source_id=source_id
            )
        real = Path(os.path.realpath(candidate))
        if not _is_within(real, containing):
            raise SourceBoundaryError(
                "source_symlink", "来源真实路径逃逸出可信目录", source_id=source_id
            )
        # 树内链接同样在解析期拒绝：后续复制虽会兜底（code_copy_corrupt），
        # 但登记时就给出明确的越界原因（工单 03 / test_rejects_symlink_inside_source）。
        _reject_tree_links(real, source_id=source_id)
        return ResolvedSource(
            source_id=source_id,
            path=real,
            trusted_root=containing,
            identity=_source_identity(real),
        )

    if outside_error is not None and expanded.is_absolute():
        raise outside_error
    # 相对 source_id 在可信根下不存在：按缺失拒绝，不暴露宿主目录。
    raise SourceBoundaryError("source_missing", "来源不存在", source_id=source_id)


# --------------------------------------------------------------------------- #
# 固定代码副本
# --------------------------------------------------------------------------- #
def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_regular_files(root: Path) -> list[tuple[str, Path, os.stat_result]]:
    """列出副本/来源中的普通文件（跳过缓存，拒绝链接）。"""
    if not root.is_dir():
        raise CodeCopyError("code_copy_missing", "固定代码副本目录不存在")
    entries: list[tuple[str, Path, os.stat_result]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        kept: list[str] = []
        for name in sorted(dirnames):
            child = Path(dirpath) / name
            if name in _SKIP_DIR_NAMES:
                continue
            if _is_link_like(child):
                raise CodeCopyError("code_copy_corrupt", "副本内包含符号链接或交接点")
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() in _SKIP_SUFFIXES:
                continue
            if _is_link_like(path):
                raise CodeCopyError("code_copy_corrupt", "副本内包含符号链接")
            info = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                continue
            entries.append((path.relative_to(root).as_posix(), path, info))
    entries.sort(key=lambda item: item[0])
    return entries


def _copy_and_hash(src: Path, dst: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as source_handle, open(dst, "wb") as target_handle:
        for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
            digest.update(chunk)
            target_handle.write(chunk)
            size += len(chunk)
    try:
        shutil.copystat(src, dst)
    except OSError:  # 只影响元数据，不影响摘要
        pass
    return digest.hexdigest(), size


def tree_digest(files: Iterable[dict[str, Any]]) -> str:
    """文件清单 -> 稳定树摘要（路径 + 内容摘要 + 大小，按路径排序）。"""
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda entry: str(entry["path"])):
        digest.update(str(item["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["size"]).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _source_changed(
    source: ResolvedSource,
    entries: list[dict[str, Any]],
    before: list[tuple[str, Path, os.stat_result]],
) -> str | None:
    """复制完成后复验来源；返回变化原因，未变化返回 None。"""
    try:
        if _source_identity(source.path) != source.identity:
            return "来源目录身份变化（疑似被替换）"
    except OSError:
        return "来源目录已消失"
    for item, (_rel, src_path, stat_before) in zip(entries, before, strict=True):
        try:
            stat_now = os.stat(src_path, follow_symlinks=False)
        except OSError:
            return f"来源文件已消失: {item['path']}"
        if int(stat_now.st_size) != int(item["size"]):
            return f"来源文件大小变化: {item['path']}"
        if int(getattr(stat_now, "st_mtime_ns", 0)) != int(getattr(stat_before, "st_mtime_ns", 0)):
            return f"来源文件修改时间变化: {item['path']}"
        try:
            if _sha256_file(src_path) != item["sha256"]:
                return f"来源文件内容变化: {item['path']}"
        except OSError:
            return f"来源文件不可读: {item['path']}"
    try:
        current = {rel for rel, _path, _stat in _iter_regular_files(source.path)}
    except CodeCopyError:
        return "来源目录在复制期间出现链接或不可读项"
    expected = {item["path"] for item in entries}
    if current != expected:
        added = sorted(current - expected)
        removed = sorted(expected - current)
        return f"来源文件集合变化（新增 {added[:3]}，删除 {removed[:3]}）"
    return None


def copy_source(
    source: ResolvedSource,
    *,
    copies_root: Path | str | None = None,
    copy_id: str | None = None,
    on_file_copied: Callable[[str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """把可信来源复制成平台固定副本，返回 (副本目录, code_copy 摘要)。

    复制期间来源内容、文件集合或目录身份变化 -> CodeCopyError('source_changed')，
    不发布副本（staging 保留，便于诊断；本模块不自动清理）。
    """
    root = Path(copies_root or configured_code_copies_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    copy_id = copy_id or uuid.uuid4().hex
    destination = root / copy_id
    staging = root / f".staging-{copy_id}"

    try:
        before = _iter_regular_files(source.path)
    except CodeCopyError as exc:
        raise CodeCopyError(
            "source_changed", f"来源不可复制：{exc.message}"
        ) from exc

    total = sum(int(item[2].st_size) for item in before)
    free = shutil.disk_usage(root).free
    if total > free:
        raise CodeCopyError(
            "disk_full",
            "磁盘空间不足，无法创建固定代码副本",
            details={"required_bytes": total, "free_bytes": int(free)},
        )

    if staging.exists():
        raise CodeCopyError("copy_failed", "副本暂存目录已存在，拒绝覆盖")
    staging.mkdir(parents=True)
    entries: list[dict[str, Any]] = []
    try:
        for rel, src_path, _stat_before in before:
            dst = staging / rel
            try:
                digest, size = _copy_and_hash(src_path, dst)
            except OSError as exc:
                raise CodeCopyError(
                    "source_changed", f"复制期间来源不可读：{rel}"
                ) from exc
            entries.append({"path": rel, "sha256": digest, "size": size})
            if on_file_copied is not None:
                on_file_copied(rel)

        changed = _source_changed(source, entries, before)
        if changed is not None:
            raise CodeCopyError(
                "source_changed", f"复制期间来源发生变化，已中止：{changed}"
            )

        code_copy = {
            "schema_version": CODE_COPY_SCHEMA_VERSION,
            "copy_id": copy_id,
            "root_rel": copy_id,
            "tree_sha256": tree_digest(entries),
            "file_count": len(entries),
            "files": entries,
            "source_id": source.source_id,
            "copied_at": datetime.now(UTC).isoformat(),
        }
        if destination.exists():
            raise CodeCopyError("copy_failed", "固定副本目录已存在，拒绝覆盖")
        os.replace(staging, destination)
        _write_sidecar(root, code_copy)
        return destination, code_copy
    except Exception:
        # 不发布半成品：staging 保留（规格明确本期不实现自动清理）。
        raise


def _write_sidecar(copies_root: Path, code_copy: dict[str, Any]) -> None:
    sidecar = copies_root / f"{code_copy['copy_id']}{CODE_COPY_SIDECAR_SUFFIX}"
    payload = {"schema_version": CODE_COPY_SCHEMA_VERSION, "code_copy": code_copy}
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def load_code_copy_sidecar(copy_root: Path | str) -> dict[str, Any] | None:
    """读取副本旁车里的 code_copy 摘要；不存在/损坏返回 None。"""
    path = Path(copy_root)
    sidecar = path.parent / f"{path.name}{CODE_COPY_SIDECAR_SUFFIX}"
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    code_copy = payload.get("code_copy")
    return code_copy if isinstance(code_copy, dict) else None


def verify_code_copy(
    code_copy: Any, *, copies_root: Path | str | None = None
) -> Path:
    """校验固定副本完整可用，返回副本绝对目录（不返回给浏览器）。

    任何缺失、损坏、清单不一致都抛 CodeCopyError；调用方不得回退到来源目录。
    """
    if not isinstance(code_copy, dict):
        raise CodeCopyError("code_copy_missing", "缺少固定代码副本摘要")
    if code_copy.get("schema_version") != CODE_COPY_SCHEMA_VERSION:
        raise CodeCopyError("code_copy_corrupt", "固定代码副本摘要版本不支持")
    root_rel = code_copy.get("root_rel")
    files = code_copy.get("files")
    if not isinstance(root_rel, str) or not root_rel or Path(root_rel).is_absolute():
        raise CodeCopyError("code_copy_corrupt", "固定代码副本路径非法")
    if ".." in Path(root_rel).parts:
        raise CodeCopyError("code_copy_corrupt", "固定代码副本路径越界")
    if not isinstance(files, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and isinstance(item.get("sha256"), str)
        and isinstance(item.get("size"), int)
        for item in files
    ):
        raise CodeCopyError("code_copy_corrupt", "固定代码副本文件清单非法")
    if code_copy.get("file_count") != len(files):
        raise CodeCopyError("code_copy_corrupt", "固定代码副本文件数与清单不一致")

    copies_root_path = Path(copies_root or configured_code_copies_root()).resolve()
    copy_root = (copies_root_path / root_rel).resolve()
    if not _is_within(copy_root, copies_root_path):
        raise CodeCopyError("code_copy_corrupt", "固定代码副本路径越界")
    if not copy_root.is_dir():
        raise CodeCopyError("code_copy_missing", "固定代码副本目录缺失")
    if _is_link_like(copy_root):
        raise CodeCopyError("code_copy_corrupt", "固定代码副本目录是链接/交接点")

    try:
        actual_entries = _iter_regular_files(copy_root)
    except CodeCopyError:
        raise
    try:
        actual = {
            rel: {"sha256": _sha256_file(path), "size": int(info.st_size)}
            for rel, path, info in actual_entries
        }
    except OSError as exc:
        raise CodeCopyError("code_copy_corrupt", "固定代码副本文件不可读") from exc
    expected = {item["path"]: {"sha256": item["sha256"], "size": item["size"]} for item in files}
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise CodeCopyError(
            "code_copy_corrupt",
            "固定代码副本文件集合与摘要不一致",
            details={"missing": missing[:5], "extra": extra[:5]},
        )
    for rel, item in expected.items():
        if actual[rel]["size"] != item["size"] or actual[rel]["sha256"] != item["sha256"]:
            raise CodeCopyError(
                "code_copy_corrupt",
                f"固定代码副本文件摘要不一致: {rel}",
                details={"path": rel},
            )
    if code_copy.get("tree_sha256") != tree_digest(files):
        raise CodeCopyError("code_copy_corrupt", "固定代码副本树摘要不一致")
    return copy_root


# --------------------------------------------------------------------------- #
# 路由层入口：解析 + 复制，返回固定副本根
# --------------------------------------------------------------------------- #
def _source_api_error(exc: SourceBoundaryError):
    from ..errors import discover_failed

    error = discover_failed(exc.message, [], None)
    error.extra_details = {
        **error.extra_details,
        "reason": exc.code,
        **({"source_id": exc.source_id} if exc.source_id else {}),
    }
    return error


def _copy_api_error(exc: CodeCopyError):
    from ..errors import discover_failed

    error = discover_failed(exc.message, [], None)
    error.extra_details = {
        **error.extra_details,
        "reason": exc.code,
        **exc.details,
    }
    return error


def resolve_suite_root(raw: str | None, *, vendor_dir: str | None = None) -> Path | None:
    """解析来源并形成固定副本，返回副本目录（供 collect_suite 使用）。

    返回 None 表示没配置。越界 / 链接逃逸 / 来源变化 / 磁盘不足都抛 422
    discover_failed（details.reason 给出细分原因），不把宿主绝对路径回给浏览器。
    """
    if not raw or not raw.strip():
        return None
    try:
        source = resolve_source(raw)
        copy_root, _code_copy = copy_source(source)
    except SourceBoundaryError as exc:
        raise _source_api_error(exc) from exc
    except CodeCopyError as exc:
        raise _copy_api_error(exc) from exc
    return copy_root


def _repo_root() -> Path:
    # server/app/integrations/discover.py -> 上溯三级到仓库根
    return Path(__file__).resolve().parents[3]


def _python_for_discover() -> str:
    """用当前解释器：保证 pytest 版本与平台自己装的一致（避免 PATH 上的另一个 python）。"""
    return sys.executable or "python"


def _tail(lines: list[str], n: int = STDERR_TAIL_LINES) -> list[str]:
    return lines[-n:] if len(lines) > n else lines


def parse_collected_node_ids(stdout: str) -> list[str]:
    """从 pytest --collect-only -q 的输出里抽出 nodeid。

    输出形如：
        tests/test_a.py::test_one
        tests/test_b.py::TestK::test_m

        no tests ran in 0.01s
    只取含 "::" 的行，且跳过错误段（"ERROR ..."）与 summary 行。
    --collect-only -q 在收集报错时返回码非 0，这时调用方不会用它。
    """
    node_ids: list[str] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line or "::" not in line:
            continue
        # 收集错误会被打印成 "ERROR tests/x.py - ImportError..."，带 :: 时也不该算用例
        if line.startswith("ERROR ") or line.startswith("error "):
            continue
        if line.startswith("=") or line.startswith("!"):
            continue
        node_ids.append(line)
    return node_ids


def collect_suite(root: Path, *, timeout_s: int = DISCOVER_TIMEOUT_S) -> DiscoverResult:
    """在 root（必须是固定副本）上执行 pytest --collect-only -q，返回用例清单或失败分类。"""
    if not root.exists():
        return DiscoverResult(ok=False, error=DiscoverErrorKind.ROOT_MISSING)
    if not root.is_dir():
        return DiscoverResult(ok=False, error=DiscoverErrorKind.ROOT_NOT_DIR)

    # -p no:cacheprovider：发现过程不在固定副本里写 .pytest_cache，避免摘要漂移。
    command = [
        _python_for_discover(),
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
        str(root),
    ]
    env = dict(os.environ)
    # 子进程里别再继承测试库连接串，避免被测套件的 conftest 顺手连上我们的库
    env.pop("TESTDOCK_TEST_DATABASE_URL", None)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    try:
        completed = subprocess.run(  # noqa: S603 - 参数是 list，不经 shell
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return DiscoverResult(
            ok=False,
            error=DiscoverErrorKind.TIMEOUT,
            command=command,
            stderr_tail=_tail([ln for ln in stderr.splitlines()]),
        )
    except OSError as exc:
        return DiscoverResult(ok=False, error=DiscoverErrorKind.FAILED, command=command,
                              stderr_tail=[f"{type(exc).__name__}: {exc}"])

    stderr_lines = (completed.stderr or "").splitlines()
    if completed.returncode != 0:
        kind = DiscoverErrorKind.FAILED
        stderr_text = completed.stderr or ""
        if not (completed.stdout or "").strip() and "No module named pytest" in stderr_text:
            kind = DiscoverErrorKind.PYTEST_MISSING
        return DiscoverResult(
            ok=False,
            error=kind,
            command=command,
            returncode=completed.returncode,
            stderr_tail=_tail(stderr_lines),
        )

    node_ids = parse_collected_node_ids(completed.stdout or "")
    if not node_ids:
        return DiscoverResult(
            ok=False,
            error=DiscoverErrorKind.NO_TESTS,
            command=command,
            returncode=completed.returncode,
            stderr_tail=_tail(stderr_lines),
        )
    return DiscoverResult(
        ok=True,
        node_ids=node_ids,
        command=command,
        returncode=completed.returncode,
    )


__all__ = [
    "CODE_COPY_SCHEMA_VERSION",
    "CodeCopyError",
    "DISCOVER_TIMEOUT_S",
    "DiscoverErrorKind",
    "DiscoverResult",
    "EMPTY_SUITE_SOURCES_HINT",
    "ResolvedSource",
    "SourceBoundaryError",
    "collect_suite",
    "configured_code_copies_root",
    "configured_trusted_roots",
    "copy_source",
    "list_suite_sources",
    "load_code_copy_sidecar",
    "parse_collected_node_ids",
    "resolve_source",
    "resolve_suite_root",
    "suite_sources_hint",
    "tree_digest",
    "verify_code_copy",
]
