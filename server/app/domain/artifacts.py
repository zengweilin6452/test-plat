"""产物登记：finalize 时把磁盘上的文件变成 artifacts 行（development-plan.md §8.4）。

三条硬规则
----------
1. **每一行都能自证**：sha256 与 byte_size 都是对磁盘字节现算的，不是 runner
   上报的数字。数据库里有 CHECK (sha256 ~ '^[0-9a-f]{64}$')，这里绝不填占位值。
2. **storage_key 存相对路径**：产物目录在 API 侧可能被移动/挂载到别处，绝对路径
   一旦入库就锁死了部署形态。落库前把 artifacts_root 前缀剥掉，读取时再拼回去；
   下载端点还要再校验一次"拼回来的路径没跑出 artifacts_root"（防目录穿越）。
3. **幂等**：同一 run 重复 finalize（重跑 finalize、import 通道、崩溃后恢复）不能
   插入重复行。UNIQUE(project_id, run_id, logical_key) 是老文件的天然主键，走
   ON CONFLICT DO UPDATE 只刷新可变字段（availability / 大小 / 哈希），避免主键抖动。

表结构真源（0001_initial.py:artifacts）：
  id, project_id, run_id, component_id, logical_key, kind, storage_key, mime_type,
  byte_size, sha256, schema_version, availability, expires_at, created_at
  注意真实列名是 storage_key / byte_size（不是 storage_uri / size_bytes）。
  kind 的 CHECK: screenshot|ui_tree|video|log|trace|metric_series|report_json|
                  report_html|other
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: artifacts.kind 的合法取值（与 0001_initial.py 的 CHECK 完全一致）
ARTIFACT_KINDS: tuple[str, ...] = (
    "screenshot",
    "ui_tree",
    "video",
    "log",
    "trace",
    "metric_series",
    "report_json",
    "report_html",
    "other",
)

#: 扫描时跳过的目录/文件（缓存、临时文件、被移动过的产物）
_SKIP_DIRS = {".pytest_cache", "__pycache__", ".git", ".cache", ".ipynb_checkpoints"}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".tmp", ".part", ".swp"}

#: 单文件哈希上限（超过就不登记，避免把视频整段读进内存）
MAX_HASH_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class ScannedFile:
    """扫描到的一个待登记文件。"""

    absolute_path: Path
    relative_key: str
    kind: str
    mime_type: str
    byte_size: int
    sha256: str


def sha256_file(path: Path) -> str:
    """流式算 sha256（64 位小写十六进制，满足 DB CHECK）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify(path: Path, relative_key: str) -> str:
    """按文件名/后缀判定 artifacts.kind。

    证据目录约定来自 vendor mobile_auto/evidence/collector.py：
      evidence/<16hex>/failure-frame.png -> screenshot
      evidence/<16hex>/ui-tree.xml        -> ui_tree
      evidence/<16hex>/meta.json          -> report_json（证据元数据）
      evidence/<16hex>/trace.zip          -> trace
    """
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        return "screenshot"
    if suffix in (".mp4", ".webm", ".avi", ".mov"):
        return "video"
    if suffix in (".xml",) and "tree" in name:
        return "ui_tree"
    if suffix in (".xml", ".uia", ".json") and "ui" in name and "tree" in name:
        return "ui_tree"
    if suffix in (".log", ".txt") or name.endswith(".log"):
        return "log"
    if suffix in (".zip", ".trace", ".perfetto", ".jsonl.gz"):
        return "trace"
    if suffix in (".csv", ".parquet") and ("metric" in name or "perf" in name):
        return "metric_series"
    if suffix == ".html":
        return "report_html"
    if suffix == ".json":
        if "metric" in name or "summary" in name:
            return "metric_series"
        return "report_json"
    if suffix == ".jsonl" or name == "run-manifest.jsonl":
        return "report_json"
    return "other"


def mime_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    # mimetypes 对 .jsonl / .uia 等不认识的类型会返回 None，DB 里 mime_type NOT NULL
    return "application/octet-stream"


def scan_artifacts(
    root: Path,
    *,
    max_files: int = 2000,
) -> list[ScannedFile]:
    """递归扫描产物目录，返回可登记文件列表（sha256 现算）。

    logical_key 用相对路径（POSIX 分隔符），这样同一份产物在不同机器上得到的
    逻辑键完全一致，跨库比对/report 引用都不会因路径风格漂移。
    """
    root = Path(root)
    if not root.is_dir():
        return []
    found: list[ScannedFile] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if path.suffix.lower() in _SKIP_SUFFIXES or filename.startswith("."):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if not path.is_file() or stat.st_size > MAX_HASH_BYTES:
                continue
            relative = path.relative_to(root).as_posix()
            found.append(
                ScannedFile(
                    absolute_path=path,
                    relative_key=relative,
                    kind=classify(path, relative),
                    mime_type=mime_for(path),
                    byte_size=int(stat.st_size),
                    sha256=sha256_file(path),
                )
            )
            if len(found) >= max_files:
                return found
    return found


def storage_key_for(absolute: Path | str, artifacts_root: Path | str) -> str:
    """把绝对路径改写成相对 storage_key（POSIX 分隔符）。

    不在 artifacts_root 之下的路径（例如 runner 用了外部 tmp）退化为文件名，
    宁可丢目录信息也不要往库里塞绝对路径。
    """
    absolute_path = Path(absolute)
    root = Path(artifacts_root)
    try:
        return absolute_path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return absolute_path.name


def resolve_storage_path(
    storage_key: str, artifacts_root: Path | str | None = None
) -> Path | None:
    """storage_key -> 绝对路径，并确保没有跑出 artifacts_root。

    artifacts_root 省略时取 settings.artifacts_dir（下载端点/报告读源码都走这个默认）。
    """
    if artifacts_root is None:
        from ..config import settings

        artifacts_root = settings.artifacts_dir
    root = Path(artifacts_root).resolve()
    candidate = (root / storage_key).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


_INSERT_SQL = text(
    """
    INSERT INTO artifacts (
        id, project_id, run_id, component_id, logical_key, kind, storage_key,
        mime_type, byte_size, sha256, schema_version, availability, expires_at
    ) VALUES (
        :id, :project_id, :run_id, :component_id, :logical_key, :kind, :storage_key,
        :mime_type, :byte_size, :sha256, :schema_version, :availability, :expires_at
    )
    ON CONFLICT (project_id, storage_key) DO UPDATE
       SET run_id = EXCLUDED.run_id,
           component_id = EXCLUDED.component_id,
           logical_key = EXCLUDED.logical_key,
           kind = EXCLUDED.kind,
           mime_type = EXCLUDED.mime_type,
           byte_size = EXCLUDED.byte_size,
           sha256 = EXCLUDED.sha256,
           availability = EXCLUDED.availability
    RETURNING id, logical_key, kind, storage_key, sha256, byte_size, availability,
              expires_at, created_at
    """
)


def retention_days_from_settings() -> int:
    """产物保留天数（<=0 表示未配置保留策略，不写 expires_at）。"""
    from ..config import settings

    try:
        value = int(getattr(settings, "artifact_retention_days", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


async def register_files(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    run_id: str | uuid.UUID,
    files: Iterable[ScannedFile],
    artifacts_root: Path | str,
    component_id: str | uuid.UUID | None = None,
    schema_version: str = "1",
    retention_days: int | None = None,
) -> list[dict[str, Any]]:
    """把扫描结果写成 artifacts 行（幂等）。返回落库后的行。

    必须在调用方事务内执行：finalize 要求"产物行 + state=completed"原子可见，
    否则前端会看到"已完成但没有产物"。

    配置了保留期（retention_days 或 TESTDOCK_ARTIFACT_RETENTION_DAYS）时同时写
    expires_at：证据的 expired 状态由此真实可达，而不是只有 DB 手工行才能出现。
    """
    days = retention_days if retention_days is not None else retention_days_from_settings()
    expires_at = (
        datetime.now(UTC) + timedelta(days=days) if days and days > 0 else None
    )
    rows: list[dict[str, Any]] = []
    for item in files:
        storage_key = storage_key_for(item.absolute_path, artifacts_root)
        row = (
            await session.execute(
                _INSERT_SQL,
                {
                    "id": str(uuid.uuid4()),
                    "project_id": str(project_id),
                    "run_id": str(run_id),
                    "component_id": str(component_id) if component_id else None,
                    "logical_key": item.relative_key,
                    "kind": item.kind if item.kind in ARTIFACT_KINDS else "other",
                    "storage_key": storage_key,
                    "mime_type": item.mime_type,
                    "byte_size": item.byte_size,
                    "sha256": item.sha256,
                    "schema_version": schema_version,
                    "availability": "available",
                    "expires_at": expires_at,
                },
            )
        ).mappings().first()
        rows.append(dict(row))
    return rows


async def finalize_artifacts(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    run_id: str | uuid.UUID,
    artifacts_dir: Path | str,
    artifacts_root: Path | str,
    component_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    """扫描 run 的产物目录并登记全部文件。返回 {files, rows, sha256s}。

    这是 finalize 的第一段：**先写产物，再改状态**。顺序反过来的话，崩溃窗口里
    会出现 state=completed 但产物表为空，前端"报告"页会永远显示无产物。
    """
    scanned = scan_artifacts(Path(artifacts_dir))
    rows = await register_files(
        session,
        project_id=project_id,
        run_id=run_id,
        files=scanned,
        artifacts_root=artifacts_root,
        component_id=component_id,
    )
    return {
        "files": len(scanned),
        "rows": rows,
        "sha256s": {item.relative_key: item.sha256 for item in scanned},
    }


def effective_availability(
    row: dict[str, Any],
    *,
    artifacts_root: Path | str | None = None,
) -> tuple[str, str | None]:
    """计算证据的**当前**可用性（三态）与不可用原因。

    数据库里的 availability 是登记时的声明；文件被清理、保留期到期都不改行，
    所以读的时候要按磁盘与 expires_at 复核，否则报告永远显示 available、
    下载门控形同虚设（工单 05）：

    - 已声明 missing/expired 的行保持声明值（清扫/人工标记的可信来源）；
    - expires_at 已过 -> expired（retention_expired）；
    - storage_key 解析不到（含目录穿越）-> missing（storage_unresolvable）；
    - 磁盘上没有文件 -> missing（file_missing）；
    - 其余 -> available。

    返回 (availability, unavailable_reason)。只读判定，不回写数据库。
    """
    stored = str(row.get("availability") or "available")
    if stored == "expired":
        return "expired", "retention_expired"
    if stored == "missing":
        return "missing", "file_missing"

    expires_at = row.get("expires_at")
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires_at:
            return "expired", "retention_expired"

    storage_key = str(row.get("storage_key") or "")
    if not storage_key:
        return "missing", "storage_unresolvable"
    path = resolve_storage_path(storage_key, artifacts_root)
    if path is None:
        return "missing", "storage_unresolvable"
    if not path.is_file():
        return "missing", "file_missing"
    return "available", None


def with_effective_availability(
    row: dict[str, Any], *, artifacts_root: Path | str | None = None
) -> dict[str, Any]:
    """在产物行上追加派生字段（availability / unavailable_reason），不改原行。"""
    availability, reason = effective_availability(row, artifacts_root=artifacts_root)
    decorated = dict(row)
    decorated["availability"] = availability
    decorated["unavailable_reason"] = reason
    return decorated


async def list_artifacts(
    session: AsyncSession,
    run_id: str | uuid.UUID,
    *,
    project_id: str | uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """GET /runs/{id}/artifacts 的数据源（按 logical_key 排序，结果稳定）。

    availability / unavailable_reason 是按磁盘与 expires_at 复核后的**当前**状态。
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT id, project_id, run_id, component_id, logical_key, kind,
                       storage_key, mime_type, byte_size, sha256, schema_version,
                       availability, expires_at, created_at
                  FROM artifacts
                 WHERE run_id = :run_id
                   AND (CAST(:project_id AS uuid) IS NULL
                        OR project_id = CAST(:project_id AS uuid))
                 ORDER BY logical_key
                """
            ),
            {"run_id": str(run_id), "project_id": str(project_id) if project_id else None},
        )
    ).mappings().all()
    return [with_effective_availability(dict(r)) for r in rows]


async def get_artifact(
    session: AsyncSession,
    run_id: str | uuid.UUID,
    artifact_id: str | uuid.UUID,
    *,
    project_id: str | uuid.UUID | None = None,
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id, project_id, run_id, component_id, logical_key, kind,
                       storage_key, mime_type, byte_size, sha256, schema_version,
                       availability, expires_at, created_at
                  FROM artifacts
                 WHERE run_id = :run_id AND id = :artifact_id
                   AND (CAST(:project_id AS uuid) IS NULL
                        OR project_id = CAST(:project_id AS uuid))
                """
            ),
            {
                "run_id": str(run_id),
                "artifact_id": str(artifact_id),
                "project_id": str(project_id) if project_id else None,
            },
        )
    ).mappings().first()
    return with_effective_availability(dict(row)) if row else None


async def find_by_suffix(
    session: AsyncSession, run_id: str | uuid.UUID, suffixes: tuple[str, ...]
) -> list[dict[str, Any]]:
    """按 logical_key 后缀挑产物（report.json / junit.xml 等）。"""
    rows = await list_artifacts(session, run_id)
    return [r for r in rows if any(str(r["logical_key"]).endswith(s) for s in suffixes)]


_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def is_valid_sha256(value: str | None) -> bool:
    return bool(value) and bool(_HEX_RE.match(value))


__all__ = [
    "ARTIFACT_KINDS",
    "MAX_HASH_BYTES",
    "ScannedFile",
    "classify",
    "effective_availability",
    "finalize_artifacts",
    "find_by_suffix",
    "get_artifact",
    "is_valid_sha256",
    "list_artifacts",
    "mime_for",
    "register_files",
    "resolve_storage_path",
    "retention_days_from_settings",
    "scan_artifacts",
    "sha256_file",
    "storage_key_for",
    "with_effective_availability",
]
