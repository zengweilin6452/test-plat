"""P1 只读 API 回归测试（需要真实 PostgreSQL）。

这类测试不打桩数据库：schema 的 CHECK / 部分唯一索引 / jsonb 语义只有真库能验证，
用 SQLite 或 mock 等于没测。没有 TESTDOCK_TEST_DATABASE_URL 时整体 skip，
CI 里由 postgres service 提供，本机由 scripts/pg_portable_setup.ps1 提供。

运行：
    TESTDOCK_TEST_DATABASE_URL=postgresql+psycopg://testdock@127.0.0.1:55432/testdock \
        python -m pytest server/tests/test_api_readonly.py -v
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

TEST_DB = os.environ.get("TESTDOCK_TEST_DATABASE_URL", "").strip()

if not TEST_DB:
    pytest.skip(
        "需要 TESTDOCK_TEST_DATABASE_URL 指向已升级到 head 的 PostgreSQL 才能跑集成测试",
        allow_module_level=True,
    )

os.environ.setdefault("TESTDOCK_DATABASE_URL", TEST_DB)


@pytest.fixture(scope="module")
def app_client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client


def test_health_reports_db_state_without_target(app_client):
    resp = app_client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    # 不输出数据库主机（凭据 / 拓扑都不泄露）
    assert "database_target" not in body


def test_overview_shape(app_client):
    resp = app_client.get("/api/v1/overview")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "application_total",
        "resource_total",
        "resource_ready",
        "run_total",
        "run_running",
        "passed",
        "failed",
        "not_tested",
        "pass_rate",
    ):
        assert key in body, f"overview 缺少字段 {key}"
    # pass_rate 在没有任何判定结果时必须是 None（不是 0）
    if body["passed"] + body["failed"] == 0:
        assert body["pass_rate"] is None


def test_resources_status_filter(app_client):
    resp = app_client.get("/api/v1/resources")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == len(body["items"])
    assert body["ready"] == sum(1 for i in body["items"] if i["status"] == "ready")

    for status in ("ready", "offline", "unauthorized", "draining"):
        sub = app_client.get("/api/v1/resources", params={"status": status}).json()
        assert all(i["status"] == status for i in sub["items"]), status


def test_resources_rejects_unknown_status(app_client):
    resp = app_client.get("/api/v1/resources", params={"status": "bogus"})
    assert resp.status_code == 422


def test_busy_is_derived_not_stored(app_client):
    """busy 必须由未释放租约推导，资源表里没有 busy 列。"""
    from sqlalchemy import text

    from app.db import get_engine

    import asyncio

    async def _columns():
        engine = get_engine()
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='execution_resources'"
                )
            )
            return {r[0] for r in rows}

    columns = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_columns())
    assert "busy" not in columns


def test_tasks_shape(app_client):
    resp = app_client.get("/api/v1/tasks")
    assert resp.status_code == 200
    body = resp.json()
    for item in body["items"]:
        # state 与 outcome 是两个字段，不合并
        assert "lifecycle" in item
        if item["run"] is not None:
            assert "state" in item["run"]
            assert "outcome" in item["run"]
