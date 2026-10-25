"""TestDock API 入口。

P0 只提供健康检查；P1 起按 docs/plan/api-design.md 逐步补齐端点。
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .routers import applications, overview, resources, runs, tasks


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
    # P1: 在这里执行 reconciler 启停
    yield


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
app.include_router(resources.router, prefix=API_PREFIX)
app.include_router(tasks.router, prefix=API_PREFIX)
app.include_router(runs.router, prefix=API_PREFIX)


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