"""TestDock API 入口。

P0 只提供健康检查；P1 起按 docs/plan/api-design.md 逐步补齐端点。
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import scheduler_enabled, settings
from .errors import ApiError
from .ws import hub as _hub
from .routers import applications, debug as debug_router, overview, projects, resources, runs, suites, tasks
from .routers import analyses, baselines, gate_policies


def _install_windows_event_loop_policy() -> None:
    """Windows 上必须使用 SelectorEventLoop。

    psycopg 3 的异步连接不支持 ProactorEventLoop，会在第一次连接时抛
    InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode。
    Python 3.8+ 在 Windows 上默认就是 ProactorEventLoop，因此这里显式切回 Selector。
    必须在创建事件循环之前调用（uvicorn 启动前 / asyncio.run 之前）。
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """API 生命周期：生成控制 token，启停 dispatcher / reconciler。

    TESTDOCK_SCHEDULER=0 时只生成 token 不起后台任务 —— 单元测试直接用 domain
    层，不需要一个偷偷跑的后台循环去抢库里的 queued run。
    """
    token = control_mod.ensure_token(settings.control_token_path)
    app.state.control_token = token

    stop = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []
    if scheduler_enabled():
        from .scheduler import dispatcher as dispatcher_mod
        from .scheduler import reconciler as reconciler_mod

        loop = asyncio.get_running_loop()
        _hub.bind_loop(loop)
        tasks = [
            loop.create_task(dispatcher_mod.run_forever(stop=stop), name="testdock-dispatcher"),
            loop.create_task(reconciler_mod.run_forever(stop=stop), name="testdock-reconciler"),
        ]
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


# 模块导入期就切策略：即使通过 "uvicorn app.main:app" 启动（不经过 main()），
# 导入本模块时也会先把策略装好。
_install_windows_event_loop_policy()

app = FastAPI(
    title="TestDock API",
    version="0.1.0",
    description="移动端 UI 自动化与性能测试平台",
    lifespan=lifespan,
)


API_PREFIX = "/api/v1"
app.include_router(overview.router, prefix=API_PREFIX)
app.include_router(applications.router, prefix=API_PREFIX)
app.include_router(projects.router, prefix=API_PREFIX)
app.include_router(resources.router, prefix=API_PREFIX)
app.include_router(tasks.router, prefix=API_PREFIX)
app.include_router(runs.router, prefix=API_PREFIX)
app.include_router(suites.router, prefix=API_PREFIX)


# --------------------------------------------------------------------------- #
# P2 追加：统一错误信封（api-design.md §1.2）
# --------------------------------------------------------------------------- #
# 契约要求任何错误都是 {code, message, request_id, details}。FastAPI 默认渲染
# {"detail": ...}，所以这里注册两个处理器：
#   - ApiError：业务异常，自带 code / details
#   - HTTPException：框架或旧路由抛的，按 status 映射到错误码表，避免出现裸 detail
# request_id 目前取请求头 X-Request-Id，没有就临时生成；接入 trace 后换成中间件注入。
def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id") or uuid.uuid4().hex


def _envelope(request: Request, *, code: str, message: str, details: Any) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
        "details": details,
    }


#: 框架级 HTTPException 的 status -> 错误码（api-design.md §1.2 表里已有的那些）
_STATUS_CODES: dict[int, str] = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "state_conflict",
    422: "validation_error",
    428: "client_header_required",
    500: "internal_error",
    503: "service_unavailable",
}


@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        # details 里可能带 domain 对象里的 datetime（stale_version 会回填最新任务），
        # 直接塞进 JSONResponse 会在 json.dumps 处抛 TypeError -> 500，这里统一编码。
        content=jsonable_encoder(
            _envelope(request, code=exc.code, message=exc.message, details=exc.extra_details)
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_CODES.get(exc.status_code, f"http_{exc.status_code}")
    message = exc.detail if isinstance(exc.detail, str) else "请求失败"
    details: Any = {} if isinstance(exc.detail, str) else {"detail": exc.detail}
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(request, code=code, message=message, details=details),
    )


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求体校验失败也要走信封：把 pydantic 的 errors 原样放进 details。"""
    errors = exc.errors()
    summary = "; ".join(
        f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}" for err in errors
    )
    return JSONResponse(
        status_code=422,
        content=_envelope(
            request,
            code="validation_error",
            message=f"请求校验失败：{summary}",
            details={"errors": jsonable_encoder(errors)},
        ),
    )
# P4：性能分析 / 基线 / 门禁策略。必须在 runs 之后注册，
# 因为 /runs/{run_id}/gate-evaluations 定义在 analyses router 里，
# 先注册它能确保该路径只被注册一次（runs router 不提供该路径）。
app.include_router(analyses.router, prefix=API_PREFIX)
app.include_router(baselines.router, prefix=API_PREFIX)
app.include_router(gate_policies.router, prefix=API_PREFIX)
app.include_router(debug_router.router, prefix=API_PREFIX)


# --------------------------------------------------------------------------- #
# P6 追加：数据设计页静态 schema 文档 + 审计事件只读查询
# --------------------------------------------------------------------------- #
from .routers import audit as audit_router  # noqa: E402
from .routers import schema as schema_router  # noqa: E402

app.include_router(schema_router.router, prefix=API_PREFIX)
app.include_router(audit_router.router, prefix=API_PREFIX)


# --------------------------------------------------------------------------- #
# P3 追加：运行生命周期（internal 协议 + WebSocket + 调度器启停）
# --------------------------------------------------------------------------- #
from .domain import control as control_mod  # noqa: E402
from .routers import internal as internal_router  # noqa: E402
from .routers import ws as ws_router  # noqa: E402

# /internal/* 是 runner 专用协议面（X-Control-Token 鉴权），不挂在 /api/v1 下：
# 它不是对外契约，路径也不应该出现在公开 OpenAPI 里。
app.include_router(internal_router.router)
# WS 契约在 api-design.md 里写作 /api/v1/ws/runs/{id}，而任务书写 /ws/runs/{id}。
# 两个都挂（同一个 router 实例，行为完全一致），避免前端和验收各按一份文档。
app.include_router(ws_router.router, prefix=API_PREFIX)
app.include_router(ws_router.router)

__all__ = ["app", "main", "lifespan"]


@app.get("/api/v1/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": app.version,
        "database_target": settings.database_url.split("@")[-1],
    }


def main() -> None:
    """启动 API 服务。

    不用 uvicorn.run("app.main:app")：那样 uvicorn 会自己新建事件循环，
    Windows 上拿到的是 ProactorEventLoop，psycopg 3 异步连接直接报
    InterfaceError: Psycopg cannot use the 'ProactorEventLoop'。
    这里先在当前线程设置 SelectorEventLoop 策略，再让 uvicorn 在本线程的
    循环上跑，保证策略生效。
    """
    _install_windows_event_loop_policy()
    import asyncio

    import uvicorn

    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info")
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.close()


if __name__ == "__main__":
    main()