"""调试会话运行时辅助：控制面 URL/token 的获取（P5）。

为什么单独一个模块：debug 路由需要在请求处理器里拿到当前 API 的控制面地址与
token 去 spawn runner；直接 import app.main 会循环导入（main -> routers.debug ->
main）。放在独立小模块里，main 与 debug 都只依赖它。
"""

from __future__ import annotations

from ..config import settings


def get_control_url_and_token() -> tuple[str, str]:
    """返回 (control_url, control_token)。

    URL 指向本 API 的 internal 面（settings.host:settings.port）；
    token 走 domain 层的唯一解析入口（进程内值 > app.state > 磁盘文件），与
    internal.require_control_token 用的是同一个函数，保证 runner 拿到的令牌
    一定能通过校验。
    """
    import os

    override = os.environ.get("TESTDOCK_CONTROL_URL", "").strip()
    url = override or ("http://%s:%d" % (settings.host, settings.port))
    from ..domain import control as control_mod

    token = control_mod.resolve_token(
        getattr(_current_app_state(), "control_token", None),
        settings.control_token_path,
    )
    return url, token


def _current_app_state():
    """拿全局 app.state（测试与单进程部署下只有一个 app 实例）。"""
    try:
        from ..main import app

        return app.state
    except Exception:  # noqa: BLE001 - 循环导入/测试环境兜底
        return None


__all__ = ["get_control_url_and_token"]
