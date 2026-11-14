"""导入通道的文件系统机制（自 routers/runs.py 迁入，P2-03 分层）。

职责边界
--------
只负责「把外部 vendor 产物目录安全地搬进受管证据目录」这一件事：
内容指纹、边界与 symlink 校验、体积护栏、暂存 + 原子改名、已登记证据回读。
请求编排（幂等判定 / 409 / finalize 调用 / 响应形状）留在
routers/runs.py 的 import_run —— 那是 Run 生命周期与 HTTP 语义。

三条不变式（P1-02 / P2-01，勿改）：
1. 指纹口径与登记口径一致（scan_artifacts：跳过缓存/临时/隐藏文件），
   噪音文件变化不构成内容冲突；
2. 目标目录要么不存在、要么是完整的上一批 —— 暂存失败必须清理，
   绝无"半批产物"被 finalize 登记成完整证据的路径；
3. 边界校验在任何写操作之前：symlink / 逃逸 / 体积超限直接拒绝。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from sqlalchemy import text

from ..config import settings
from ..domain import artifacts as artifacts_mod
from ..errors import validation_error

#: 导入体积护栏（P2-01）：单次导入的文件数与总字节上限。导入是补录通道，
#: 不是任意目录镜像；上限之内覆盖 vendor 产物目录的真实规模。
IMPORT_MAX_FILES = 5000
IMPORT_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


def import_fingerprint(source: Path) -> str:
    """导入内容的确定性指纹（P1-02）：相对路径 + sha256 + 字节大小。

    扫描口径与登记口径一致（scan_artifacts：跳过缓存/临时/隐藏文件），未登记
    的噪音文件变化不构成内容冲突；指纹只覆盖真正会被登记成证据的内容。
    """
    scanned = artifacts_mod.scan_artifacts(source)
    digest = hashlib.sha256()
    for item in sorted(scanned, key=lambda s: s.relative_key):
        digest.update(f"{item.relative_key}\n{item.sha256}\n{item.byte_size}\n".encode())
    return digest.hexdigest()


async def stored_import_fingerprint(run_id: str) -> str | None:
    """Run 行上随导入原子写入的内容指纹（无则不是本实现导入的运行）。"""
    from ..db import get_sessionmaker

    async with get_sessionmaker()() as session:
        value = (
            await session.execute(
                text(
                    "SELECT config_snapshot->>'import_fingerprint'"
                    " FROM test_runs WHERE id::text = :id"
                ),
                {"id": run_id},
            )
        ).scalar_one_or_none()
    return str(value) if value else None


async def registered_evidence(run_id: str) -> tuple[int, dict[str, str]]:
    """已登记产物数量与 logical_key -> sha256 映射（响应里回显既有证据）。"""
    from ..db import get_sessionmaker

    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT logical_key, sha256 FROM artifacts"
                    " WHERE run_id = CAST(:id AS uuid) ORDER BY logical_key"
                ),
                {"id": run_id},
            )
        ).mappings().all()
    return len(rows), {str(r["logical_key"]): str(r["sha256"]) for r in rows}


def collect_import_files(source: Path) -> list[tuple[Path, Path]]:
    """枚举允许复制的 (源文件, 相对路径)，同时执行边界与 symlink 校验（P2-01）。

    - canonical path：以 resolve() 后的源目录为根，逐文件确认没有逃逸；
    - symlink：目录与文件符号链接一律拒绝（防止借链接把允许目录外的内容
      带进可下载证据）；
    - 过滤：与 scan_artifacts 同一口径（缓存目录 / 临时后缀 / 隐藏文件），
      源目录里的 .env、.git 之类不会进入受管证据；
    - 体积：文件数与总字节数双上限。
    """
    root = source.resolve()
    collected: list[tuple[Path, Path]] = []
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        # 目录符号链接一律**拒绝**而不是跳过：跳过会让导入静默成功，而调用方
        # （与用例）的契约是"含 symlink 的源目录整单 400"——CI 实测抓过这个
        # 分歧（目录链接被过滤后导入 201）。符号链接检查先于缓存/隐藏过滤。
        for d in dirnames:
            if (base / d).is_symlink():
                raise validation_error([f"source_dir 含符号链接，拒绝导入: {base / d}"])
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in artifacts_mod.SKIP_DIRS and not d.startswith(".")
        )
        for name in sorted(filenames):
            item = base / name
            if name.startswith(".") or item.suffix.lower() in artifacts_mod.SKIP_SUFFIXES:
                continue
            if item.is_symlink():
                raise validation_error([f"source_dir 含符号链接，拒绝导入: {item}"])
            if not item.is_file():
                continue
            try:
                item.resolve().relative_to(root)
            except ValueError:
                raise validation_error([f"source_dir 文件逃逸出允许目录，拒绝导入: {item}"]) from None
            size = item.stat().st_size
            if len(collected) >= IMPORT_MAX_FILES:
                raise validation_error(
                    [f"导入文件数超过上限 {IMPORT_MAX_FILES}，拒绝导入"]
                )
            total_bytes += size
            if total_bytes > IMPORT_MAX_TOTAL_BYTES:
                raise validation_error(
                    [f"导入总字节数超过上限 {IMPORT_MAX_TOTAL_BYTES}，拒绝导入"]
                )
            collected.append((item, item.relative_to(root)))
    return collected


def import_artifacts_dir(run_id: str, source: Path) -> Path:
    """把外部 vendor 产物目录复制到受管产物目录，返回复制后的路径。

    为什么必须复制：artifacts.storage_key 是相对 settings.artifacts_dir 的路径，
    下载端点与 GET /report 都按这个根反查。直接登记外部绝对路径会让 storage_key
    退化成裸文件名（storage_key_for 的兜底），读回来永远是"文件不存在"。
    复制而不是移动：源目录是用户的既有证据，导入是只读补录，不能改它。

    原子提交（P1-02）：先复制到同卷暂存目录，再一次性 rename 到 <run_id>。
    直接往目标目录边拷边写，中途失败会留下"半批产物"——若随后 finalize 登记
    成功，磁盘与数据库就永久不一致。暂存失败时清理暂存目录：目标目录要么
    不存在、要么是完整的上一批，绝无中间态。
    """
    files = collect_import_files(source)
    target = Path(settings.artifacts_dir) / str(run_id)
    if target.exists():
        # 只会出现在旧版本遗留的部分复制上：调用方已做指纹校验，清掉重拷
        # 才能保证"目标目录 == 本次导入内容"。
        shutil.rmtree(target)
    staging = (
        Path(settings.artifacts_dir)
        / f"_staging-import-{run_id}-{uuid.uuid4().hex[:12]}"
    )
    try:
        staging.mkdir(parents=True)
        for item, relative in files:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


__all__ = [
    "IMPORT_MAX_FILES",
    "IMPORT_MAX_TOTAL_BYTES",
    "collect_import_files",
    "import_artifacts_dir",
    "import_fingerprint",
    "registered_evidence",
    "stored_import_fingerprint",
]
