"""joint 执行窗参数（D11）：ui_timeout_s 默认 600、允许 10-3600，由任务修订固定。

runner 与 spawn 侧共用同一个 clamp：平台拒绝/夹紧的口径必须和 runner 兜底一致，
否则"平台认为 3600 合法、runner 又夹回 600"这类两边各说各话的错位会出现。
"""

from __future__ import annotations

from typing import Any

DEFAULT_UI_TIMEOUT_S = 600
MIN_UI_TIMEOUT_S = 10
MAX_UI_TIMEOUT_S = 3600


def clamp_ui_timeout(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_UI_TIMEOUT_S
    return max(MIN_UI_TIMEOUT_S, min(MAX_UI_TIMEOUT_S, seconds))


__all__ = [
    "DEFAULT_UI_TIMEOUT_S",
    "MAX_UI_TIMEOUT_S",
    "MIN_UI_TIMEOUT_S",
    "clamp_ui_timeout",
]
