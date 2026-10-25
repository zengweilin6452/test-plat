"""P2 集成测试的公共夹具（任务 / 套件两组测试共用）。

隔离策略
--------
**不碰 127.0.0.1:55432 那个共享库**：它正被 API server 与 Lead 的其它测试使用。
conftest.py 的 pg_instance 起一个独立临时实例（55433），migrated_dsn 在上面跑
alembic upgrade head；本模块再把 app.db 的引擎重绑到那个 DSN 上。

几个必须知道的坑（都已实测）
---------------------------
1. Windows 默认 ProactorEventLoop，psycopg 异步连接直接不可用；pytest-asyncio 会
   为每个用例新建事件循环，所以这里在每个用例开始前显式装 SelectorEventLoop 策略。
2. app.db 的引擎是懒建的模块级单例，绑到旧 DSN 后再改 settings 无效，必须
   reset_engine() 清掉缓存。
3. 每个用例自建 project / environment / application / suite（uuid 后缀），
   结束时按 project 级联删除，互不干扰。
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

# --------------------------------------------------------------------------- #
# 环境变量必须在 import app.* 之前设好
# --------------------------------------------------------------------------- #
TEST_DB = os.environ.get("TESTDOCK_TEST_DATABASE_URL", "").strip()
if TEST_DB:
    os.environ.setdefault("TESTDOCK_DATABASE_URL", TEST_DB)

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

CLIENT_HEADERS = {"X-TestDock-Client": "web"}


def install_selector_policy() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def dsn() -> str:
    """本次测试实际连的库：优先用 api_client 绑定的 moved DSN。"""
    return _BOUND_DSN or TEST_DB or os.environ.get("TESTDOCK_DATABASE_URL", "") or ""


#: api_client 绑定的 DSN。并发跑多份 pytest 时，各进程的 conftest 可能拿到**不同**的
#: 临时实例，所以夹具写入必须跟着 api_client 走，不能回头读 settings。
_BOUND_DSN = ""


def _exec_sync(sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    """同步执行一条 SQL（用 asyncio.run 包一层），返回 mappings 行列表。

    显式传 dsn：app.config.settings.database_url 可能被同机并发的另一份 pytest
    改过，直接读它会写进别人的库。这里只认本进程的 TEST_DB / api_client 绑定的值。
    """
    install_selector_policy()
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    target = dsn()
    if not target:  # pragma: no cover - 用例依赖 TEST_DB 才能收集
        raise RuntimeError("没有可用的测试库 DSN")

    async def _inner() -> list[Any]:
        engine = create_async_engine(target)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params or {})
                try:
                    return list(result.mappings().all())
                except Exception:  # noqa: BLE001 - 非 SELECT 没有行集
                    return []
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


@pytest.fixture(scope="module")
def api_client(migrated_dsn: str):
    """把 app 绑到临时实例上，返回 TestClient。

    绑定的方式是改 settings.database_url + reset_engine()，不动 app 的其它实现。
    """
    global _BOUND_DSN

    os.environ["TESTDOCK_DATABASE_URL"] = migrated_dsn
    os.environ.setdefault("TESTDOCK_TEST_DATABASE_URL", migrated_dsn)
    _BOUND_DSN = migrated_dsn
    install_selector_policy()

    from app.config import settings

    settings.database_url = migrated_dsn

    from app import db as db_mod

    if hasattr(db_mod, "reset_engine"):
        db_mod.reset_engine()
    for attr in ("_engine", "_sessionmaker"):
        if hasattr(db_mod, attr):
            setattr(db_mod, attr, None)

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    install_selector_policy()
    with TestClient(fastapi_app) as client:
        yield client

    if hasattr(db_mod, "reset_engine"):
        db_mod.reset_engine()
    _BOUND_DSN = ""


@pytest.fixture()
def seed(api_client):
    """建一套最小数据：project / environment / application / suite。

    返回 dict，包含各 id 与一个 cleanup()。
    """
    suffix = uuid.uuid4().hex[:10]
    ids = {
        "project_id": str(uuid.uuid4()),
        "environment_id": str(uuid.uuid4()),
        "application_id": str(uuid.uuid4()),
        "other_application_id": str(uuid.uuid4()),
        "suite_id": str(uuid.uuid4()),
        "other_suite_id": str(uuid.uuid4()),
    }

    _exec_sync(
        "INSERT INTO projects (id, code, name) VALUES (CAST(:id AS uuid), :code, :name)",
        {"id": ids["project_id"], "code": f"p2-{suffix}", "name": f"P2 Test {suffix}"},
    )
    _exec_sync(
        """
        INSERT INTO applications (id, project_id, platform, name, identifier)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'android', :name, :identifier)
        """,
        {
            "id": ids["application_id"],
            "pid": ids["project_id"],
            "name": f"Android {suffix}",
            "identifier": f"com.example.p2{suffix}",
        },
    )
    _exec_sync(
        """
        INSERT INTO applications (id, project_id, platform, name, identifier)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'ios', :name, :identifier)
        """,
        {
            "id": ids["other_application_id"],
            "pid": ids["project_id"],
            "name": f"iOS {suffix}",
            "identifier": f"com.example.p2{suffix}.ios",
        },
    )
    _exec_sync(
        """
        INSERT INTO environments (id, project_id, name, config)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :name, '{}'::jsonb)
        """,
        {"id": ids["environment_id"], "pid": ids["project_id"], "name": f"env-{suffix}"},
    )
    _exec_sync(
        """
        INSERT INTO test_suites (id, project_id, application_id, name, test_type)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), :name, 'performance')
        """,
        {
            "id": ids["suite_id"],
            "pid": ids["project_id"],
            "aid": ids["application_id"],
            "name": f"perf-{suffix}",
        },
    )
    _exec_sync(
        """
        INSERT INTO test_suites (id, project_id, application_id, name, test_type)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), :name, 'ui')
        """,
        {
            "id": ids["other_suite_id"],
            "pid": ids["project_id"],
            "aid": ids["other_application_id"],
            "name": f"ui-{suffix}",
        },
    )

    def cleanup() -> None:
        try:
            _exec_sync(
                "DELETE FROM projects WHERE id = CAST(:pid AS uuid)",
                {"pid": ids["project_id"]},
            )
        except Exception:  # noqa: BLE001 - 清理失败不该遮盖真正的失败
            pass

    ids["suffix"] = suffix
    ids["cleanup"] = cleanup
    try:
        yield ids
    finally:
        cleanup()


@asynccontextmanager
async def _noop() -> AsyncIterator[None]:  # pragma: no cover - 占位
    yield
