"""模板库与执行锁定（工单 25）。

存储事实：所有调试会话的 vendor TemplateStore 都落在同一个资产根
（runner 的 cwd 是 server/，MobileConfig 不覆盖 assets_dir → 默认 "assets"
相对 cwd，即 server/assets）。所以"跨会话共享"由共享根保证——新会话
list_templates 读到的就是其他会话登记过的模板。

执行锁定：任务修订的 config.image_templates 声明
    [{"logical": "...", "version_id": "...", "sha256": "..."}]
派发前对共享根的 manifest.json 逐条核对当前版本；缺失 / 版本不符 / 摘要不符
一律阻断（errored template_pin_mismatch），绝不静默改用别的版本。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

TEMPLATE_ASSETS_ENV = "TESTDOCK_TEMPLATE_ASSETS_DIR"


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
