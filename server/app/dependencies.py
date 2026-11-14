"""共享的请求前置条件依赖（development-plan.md §8.1）。

require_client_header 从 routers/tasks.py 上移到这里：写操作守卫是全 API 的
横切约束，不该住在第一个用到它的业务路由里。

注意：X-TestDock-Client 是"请求前置条件 + 防跨站表单措施"（浏览器通道的
表单/简单请求带不了自定义头），不是身份认证 —— 不能用它替代用户认证，
也不适用于内部 Runner 协议（ Runner 面的鉴权是 X-Control-Token，
见 routers/internal.py，两者不许混用）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from .errors import CLIENT_HEADER, CLIENT_HEADER_VALUE, client_header_required


def require_client_header(
    x_testdock_client: Annotated[str | None, Header(alias=CLIENT_HEADER)] = None,
) -> str:
    """写操作必须带 X-TestDock-Client: web（development-plan.md §8.1 防跨站表单）。

    缺失时 428 Precondition Required 而不是 403：这是"缺少前置条件"，
    不是"认证失败"，语义上更准确，也避免前端把它当成登录问题去跳登录页。
    """
    if x_testdock_client is None:
        raise client_header_required()
    if x_testdock_client.strip().lower() != CLIENT_HEADER_VALUE:
        raise client_header_required()
    return x_testdock_client.strip()


__all__ = ["require_client_header"]
