"""TestDock API 入口。

P0 只提供健康检查；P1 起按 docs/plan/api-design.md 逐步补齐端点。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # P1: 在这里执行 reconciler 启停
    yield


app = FastAPI(
    title="TestDock API",
    version="0.1.0",
    description="移动端 UI 自动化与性能测试平台",
    lifespan=lifespan,
)


@app.get("/api/v1/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": app.version,
        "database_target": settings.database_url.split("@")[-1],
    }


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
