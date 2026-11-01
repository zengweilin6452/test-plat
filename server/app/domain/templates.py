"""模板库与执行锁定（工单 25 / 08）。

存储事实（工单 08 核实）：所有调试会话的 vendor TemplateStore 都落在同一个资产根。
debug runner 的 cwd 固定为 `server/`（`app/runner/spawn.build_spec`），而
`testdock_runner.debug_job._start_viewer` 不覆盖 `MobileConfig.assets_dir`，它的
默认值是相对路径 "assets" → 解析成 `server/assets`，也就是这里的
`template_assets_root()`。所以「模板跨会话可查、不随会话关闭/刷新消失」由共享根
保证，不是按会话隔离的目录；`/templates?session_id=` 的 session_id 只决定把请求
转发到哪个 viewer。登记本身还要求先过一次框选验证（routers/debug.py 的一次性
凭证），模板库读取不需要设备会话。

环境变量 TESTDOCK_TEMPLATE_ASSETS_DIR 只影响平台侧的读取/锁定核对（测试与
排障用）；vendor viewer 不读它，生产环境不要单独设置，否则会出现「界面读 A 根、
调试会话写 B 根」的错位。

执行锁定：任务修订的 config.image_templates 声明
    [{"logical": "...", "version_id": "...", "sha256": "..."}]
派发前对共享根的 manifest.json 逐条核对当前版本；缺失 / 版本不符 / 摘要不符
一律阻断（errored template_pin_mismatch），绝不静默改用别的版本。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

TEMPLATE_ASSETS_ENV = "TESTDOCK_TEMPLATE_ASSETS_DIR"


def list_template_library(*, assets_root: Path | None = None) -> list[dict[str, Any]]:
    """Read the shared library without opening a device or importing vendor code."""
    root = Path(assets_root) if assets_root else template_assets_root()
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("模板清单格式错误")
    entries = manifest["templates"]
    if not isinstance(entries, dict):
        raise ValueError("模板清单格式错误")
    versions = []
    # ponytail: scan local metadata; add an index only if library size warrants it.
    for directory in sorted((root / "versions").glob("*")):
        if not re.fullmatch(r"[0-9a-f]{32}", directory.name):
            continue
        if not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError("模板版本目录越界")
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            raise ValueError("模板版本元数据格式错误")
        logical = meta["logical"]
        current = entries.get(logical, {})
        if not isinstance(current, dict):
            raise ValueError("模板清单项格式错误")
        if current.get("version_id") == directory.name and current.get("image_sha256") != meta["image_sha256"]:
            raise ValueError("模板清单与当前版本摘要不一致")
        versions.append({
            "logical": logical,
            "version_id": directory.name,
            "image_sha256": meta["image_sha256"],
            "width": meta.get("width"), "height": meta.get("height"),
            "source_width": meta.get("source_width"),
            "source_height": meta.get("source_height"),
            "capture_time": meta.get("capture_time"),
            "current": current.get("version_id") == directory.name,
        })
    for logical, entry in entries.items():
        if not any(v["logical"] == logical and v["version_id"] == entry["version_id"] for v in versions):
            raise ValueError("模板当前版本元数据缺失")
    return versions


def template_assets_root() -> Path:
    """共享模板库的资产根（vendor TemplateStore 根目录）。"""
    raw = os.environ.get(TEMPLATE_ASSETS_ENV, "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    from ..config import settings

    return (settings.repo_root / "server" / "assets").resolve()


def pinned_templates(config: Any) -> list[dict[str, Any]]:
    """修订 config 里的 image_templates 声明（缺失/形状不对一律视为未声明）。"""
    if not isinstance(config, dict):
        return []
    pins = config.get("image_templates")
    if not isinstance(pins, list):
        return []
    return [pin for pin in pins if isinstance(pin, dict) and pin.get("logical")]


def verify_template_pins(pins: list[dict[str, Any]], *, assets_root: Path | None = None) -> dict[str, Any]:
    """对共享模板库核对执行锁定；返回 {verdict, detail}。

    verdict: skipped（未声明）/ verified / mismatch（版本或摘要不符）/ missing。
    """
    if not pins:
        return {"verdict": "skipped", "detail": "修订未声明 image_templates"}
    root = Path(assets_root) if assets_root else template_assets_root()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return {"verdict": "missing", "detail": f"模板库清单不存在：{manifest_path}"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"verdict": "missing", "detail": f"模板库清单不可读：{exc}"}
    entries = manifest.get("templates") if isinstance(manifest, dict) else None
    if not isinstance(entries, dict):
        return {"verdict": "missing", "detail": "模板库清单缺少 templates 键"}

    for pin in pins:
        logical = str(pin["logical"])
        entry = entries.get(logical)
        if entry is None:
            return {"verdict": "missing", "detail": f"模板 {logical} 未在共享库登记"}
        if not isinstance(entry, dict):
            return {"verdict": "missing", "detail": f"模板 {logical} 清单项形状非法"}
        pinned_version = str(pin.get("version_id") or "")
        pinned_sha = str(pin.get("sha256") or "")
        current_version = str(entry.get("version_id") or "")
        current_sha = str(entry.get("image_sha256") or "")
        if pinned_version and pinned_version != current_version:
            return {
                "verdict": "mismatch",
                "detail": f"模板 {logical} 版本已变化：锁定 {pinned_version[:8]}，当前 {current_version[:8]}",
            }
        if pinned_sha and pinned_sha != current_sha:
            return {
                "verdict": "mismatch",
                "detail": f"模板 {logical} 摘要不符：锁定 {pinned_sha[:8]}，当前 {current_sha[:8]}",
            }
    return {"verdict": "verified", "detail": f"{len(pins)} 个模板锁定全部命中当前共享库"}


__all__ = [
    "TEMPLATE_ASSETS_ENV",
    "pinned_templates",
    "template_assets_root",
    "verify_template_pins",
]
