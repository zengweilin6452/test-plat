"""把 spawn.spawn_runner 包成一个"测试可替换"的接缝。

为什么需要这一层：
  dispatcher 需要在**集成测试里**验证"派发"这件事本身（领租约 + dispatching +
  写事件），而不是每次都真的起一个子进程。测试用 `use_spawner()` 换掉真实 spawn，
  生产路径永远是 spawn_runner。这是依赖注入，不是 monkey patch。
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import Any, Protocol

from . import spawn as spawn_mod


class Spawner(Protocol):
    def __call__(
        self,
        *,
        run_id: str,
        config: Mapping[str, Any],
        lease: Mapping[str, Any],
        control_url: str | None = None,
        control_token: str | None = None,
        start_tail: bool = True,
    ) -> Awaitable[int]: ...


_spawner: Spawner = spawn_mod.spawn_runner


def use_spawner(spawner: Spawner | None) -> None:
    """替换/恢复 spawner（测试用；传 None 恢复真实实现）。"""
    global _spawner
    _spawner = spawner or spawn_mod.spawn_runner


def current_spawner() -> Spawner:
    return _spawner


async def spawn(
    *,
    run_id: str,
    config: Mapping[str, Any],
    lease: Mapping[str, Any],
    control_url: str | None = None,
    control_token: str | None = None,
) -> int:
    if control_url is None or control_token is None:
        # 调度路径没显式传控制面信息时回落到本进程 API 的 internal 面。
        # 缺 token 会让 runner control_disabled、不再心跳，60s 后被
        # reconciler 判 lease_expired——真跑链路必然失败，所以必须补齐。
        from ..routers.debug_runtime import get_control_url_and_token

        resolved_url, resolved_token = get_control_url_and_token()
        control_url = control_url if control_url is not None else resolved_url
        control_token = control_token if control_token is not None else resolved_token
    return await _spawner(
        run_id=run_id,
        config=config,
        lease=lease,
        control_url=control_url,
        control_token=control_token,
    )


__all__ = ["Spawner", "current_spawner", "spawn", "use_spawner"]
