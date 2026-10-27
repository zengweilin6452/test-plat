#!/usr/bin/env python3
"""vendor 同步与只读校验。

用法:
  python scripts/vendor_sync.py sync [mobile_perf|mobile_auto]  # 按源更新快照与锁文件，不删除目标文件
  python scripts/vendor_sync.py check    # 校验 vendor/ 与锁文件逐字节一致（CI 与提交前必跑）
  python scripts/vendor_sync.py list     # 打印锁文件摘要

只读纪律（docs/plan/vendor-integration.md 5.2）:
  - vendor/** 永不被平台写入；只由本脚本从源仓库复制。
  - 校验通过 = 锁文件里每条 sha256 与磁盘一致 + 无未登记文件。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "vendor"
LOCK_PATH = VENDOR_DIR / "VENDOR.lock.json"
LOCK_SCHEMA_VERSION = 1

# 源仓库绝对路径（只读）。可在 CI 用环境变量覆盖。
SOURCES = {
    "mobile_auto": {
        "root": Path(r"D:\\workspace\\claudecode-test\\moblie-auto"),
        "target": "mobile_auto",
        "include": [
            "src/mobile_auto",
            "tools/adb",
            "tests/unit",
            "tests/contract",
            "tests/integration",
            "tests/fixtures",
            "docs/integration.md",
            "docs/validation.md",
            "pyproject.toml",
            "requirements-lock.txt",
            "GLOSSARY.md",
            "README.md",
        ],
        "exclude_dirs": {"__pycache__", ".pytest_cache", ".ruff_cache"},
        "exclude_globs": {"*.pyc", "*.pyo"},
    },
    "mobile_perf": {
        "root": Path(r"D:\\workspace\\claudecode-test\\moblie-xn"),
        "target": "mobile_perf",
        "include": [
            "src/mobile_perf",
            "dist/solopi",
            # mobile_perf/adb.py: BUNDLED_ADB_REL_PATH = SoloPi/platform-tools/adb.exe
            "SoloPi/platform-tools",
            # mobile_perf/solo.py: HARNESS_ENTRY_REL_PATH = SoloPi/solopi-skill/scripts/harness/src/solopi_harness/solopi_ai.py
            "SoloPi/solopi-skill/scripts/harness",
            "tests/unit",
            "tests/contract",
            "tests/fixtures",
            "tests/conftest.py",
            "pyproject.toml",
            "README.md",
        ],
        "exclude_dirs": {"__pycache__", ".pytest_cache", ".ruff_cache"},
        "exclude_globs": {"*.pyc", "*.pyo"},
    },
}

# 面向库/记录：目录递归包含嵌套 .pytest_cache、__pycache__ 这类"缓存目录里的文件"，
# 单纯比对 parts 与 exclude_dirs 会漏（例如 tools/adb/.pytest_cache/...）。
_EXCLUDE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", "__MACOSX"}


def _prune_cache_dirs(target: str) -> int:
    """删除复制进 vendor 的缓存目录，返回删除的目录数。

    必须在生成 lock 之前调用，否则缓存文件名随机（pytest-cache-files-xxxx），
    lock 无法稳定，check 必然失败。
    """
    removed = 0
    for path in sorted((VENDOR_DIR / target).rglob("*"), reverse=True):
        if path.is_dir() and path.name in _EXCLUDE_DIR_NAMES:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head(root: Path) -> str | None:
    """直接读 .git/HEAD，避免依赖 git 可执行文件（CI 与沙箱一致）。"""
    head = root / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    if text.startswith("ref: "):
        ref = root / ".git" / text[5:].strip()
        try:
            return ref.read_text(encoding="utf-8").strip() or None
        except OSError:
            packed = root / ".git" / "packed-refs"
            try:
                want = text[5:].strip()
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(want) and not line.startswith("#"):
                        return line.split()[0]
            except OSError:
                return None
            return None
    return text


def _iter_source_files(root: Path, include: list[str], exclude_dirs: set[str], exclude_globs: set[str]):
    """逐个 include 项展开成文件；目录递归，文件直接产出。"""
    for rel in include:
        src = root / rel
        if not src.exists():
            raise SystemExit(f"源路径不存在: {src}")
        if src.is_file():
            yield rel, src
            continue
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            parts = set(path.relative_to(root).parts)
            if parts & exclude_dirs:
                continue
            if any(path.match(g) for g in exclude_globs):
                continue
            yield path.relative_to(root).as_posix(), path


def cmd_sync(names: list[str] | None = None) -> int:
    """按源同步，不删除目标目录；源移除文件时拒绝隐式清理。"""
    selected = names or list(SOURCES)
    previous = json.loads(LOCK_PATH.read_text(encoding="utf-8")) if LOCK_PATH.is_file() else {}
    files: dict[str, dict[str, object]] = dict(previous.get("files", {}))
    sources_meta: dict[str, dict[str, object]] = dict(previous.get("sources", {}))
    plans = {}
    for name in selected:
        cfg = SOURCES[name]
        source_files = list(_iter_source_files(cfg["root"], cfg["include"], cfg["exclude_dirs"], cfg["exclude_globs"]))
        incoming = {f"{cfg['target']}/{rel}" for rel, _ in source_files}
        removed = {rel for rel in files if rel.startswith(cfg["target"] + "/")} - incoming
        if removed:
            raise SystemExit("源文件已移除，需显式批准清理后同步：" + ", ".join(sorted(removed)))
        plans[name] = source_files

    for name in selected:
        cfg = SOURCES[name]
        root: Path = cfg["root"]
        target: str = cfg["target"]
        if not root.is_dir():
            raise SystemExit(f"源仓库不存在: {root}")
        dst_root = VENDOR_DIR / target
        count = 0
        total_bytes = 0
        for rel, src in plans[name]:
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            digest = _sha256(dst)
            key = f"{target}/{rel}"
            files[key] = {"sha256": digest, "size": dst.stat().st_size}
            count += 1
            total_bytes += dst.stat().st_size
        sources_meta[name] = {
            "root": str(root),
            "target": target,
            "git_head": _git_head(root),
            "files": count,
            "bytes": total_bytes,
            "include": cfg["include"],
        }
        print(f"[sync] {name}: {count} 文件 / {total_bytes / 1048576:.1f} MiB")

    lock = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "note": "由 scripts/vendor_sync.py sync 生成；vendor/** 只读，禁止手工编辑",
        "sources": sources_meta,
        "files": dict(sorted(files.items())),
    }
    LOCK_PATH.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[sync] 锁定 {len(files)} 个文件 -> {LOCK_PATH.relative_to(REPO_ROOT)}")
    return 0


def cmd_check() -> int:
    if not LOCK_PATH.is_file():
        print("[check] 缺少 VENDOR.lock.json，先运行 sync", file=sys.stderr)
        return 2
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("schema_version") != LOCK_SCHEMA_VERSION:
        print(f"[check] 锁文件 schema_version 不匹配: {lock.get('schema_version')}", file=sys.stderr)
        return 2
    expected: dict[str, dict[str, object]] = lock["files"]

    problems: list[str] = []
    # 1) 逐条校验
    for rel, meta in expected.items():
        path = VENDOR_DIR / rel
        if not path.is_file():
            problems.append(f"缺失: {rel}")
            continue
        if path.stat().st_size != meta["size"]:
            problems.append(f"大小不符: {rel} ({path.stat().st_size} != {meta['size']})")
            continue
        actual = _sha256(path)
        if actual != meta["sha256"]:
            problems.append(f"内容被改动: {rel}")

    # 2) 找未登记文件（只读纪律的反向证明）
    for target in ("mobile_auto", "mobile_perf"):
        root = VENDOR_DIR / target
        if not root.is_dir():
            problems.append(f"缺失目录: {target}/")
            continue
        for path in root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(VENDOR_DIR).as_posix()
                if rel not in expected:
                    problems.append(f"未登记文件: {rel}")

    if problems:
        print(f"[check] 失败，{len(problems)} 处问题：", file=sys.stderr)
        for p in problems[:50]:
            print(f"  - {p}", file=sys.stderr)
        if len(problems) > 50:
            print(f"  ... 其余 {len(problems) - 50} 条省略", file=sys.stderr)
        return 1

    total_bytes = sum(m["size"] for m in expected.values())
    print(f"[check] OK: {len(expected)} 文件 / {total_bytes / 1048576:.1f} MiB 与锁文件逐字节一致")
    for name, meta in lock["sources"].items():
        print(f"  {name}: git {meta['git_head']} <- {meta['root']}")
    return 0


def cmd_list() -> int:
    if not LOCK_PATH.is_file():
        print("缺少 VENDOR.lock.json", file=sys.stderr)
        return 2
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    print(f"schema_version={lock['schema_version']} 文件数={len(lock['files'])}")
    for name, meta in lock["sources"].items():
        print(
            f"  {name}: {meta['files']} 文件 / {meta['bytes'] / 1048576:.1f} MiB "
            f"git={meta['git_head']}"
        )
        for inc in meta["include"]:
            print(f"    - {inc}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"sync", "check", "list"}:
        print(__doc__)
        return 2
    if argv[1] == "sync":
        if any(name not in SOURCES for name in argv[2:]):
            print("同步源仅支持：" + ", ".join(SOURCES), file=sys.stderr)
            return 2
        return cmd_sync(argv[2:] or None)
    if len(argv) != 2:
        return 2
    return {"check": cmd_check, "list": cmd_list}[argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
