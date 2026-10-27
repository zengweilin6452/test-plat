"""P3 测试夹具：连 pytest_configure 备好的独立测试库（tests/conftest.py）。

库的来源由 conftest.py 决定：默认是进程私有的临时 PG 实例；显式设置
TESTDOCK_TEST_DATABASE_URL 时才复用外部库。本模块在**导入期**读取该环境变量
算 HAVE_DB，因此实例必须在收集开始前就绪（conftest.py 的 pytest_configure）。

命名：文件名以 _ 开头，pytest 不会当测试收集；测试模块里 `from _p3_common import ...`
（tests/ 有 __init__.py，pytest 以 tests.xxx 收集，所以用 tests._p3_common 也行）。

Windows 注意：psycopg 3 的异步连接不支持 ProactorEventLoop，这里显式装
WindowsSelectorEventLoopPolicy（与 app/main.py 一致）。
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

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

# pytest-asyncio >=1.0 移除了 event_loop_policy 夹具：policy 必须在模块导入期
# （也就是 asyncio 还没创建任何 loop 之前）就装好，否则默认 Proactor 会让
# psycopg 异步连接在 Windows 上直接 InterfaceError。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DSN_ENV = "TESTDOCK_TEST_DATABASE_URL"
TEST_DB = os.environ.get(DSN_ENV, "").strip()
if TEST_DB:
    os.environ.setdefault("TESTDOCK_DATABASE_URL", TEST_DB)

CLIENT_HEADERS = {"X-TestDock-Client": "web"}


def install_selector_policy() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def libpq_dsn() -> str:
    return TEST_DB.replace("postgresql+psycopg://", "postgresql://")


def database_available() -> bool:
    if not TEST_DB:
        return False
    try:
        import psycopg

        with psycopg.connect(libpq_dsn(), connect_timeout=3) as conn:
            row = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'test_runs'"
            ).fetchone()
        return row is not None
    except Exception:  # noqa: BLE001
        return False


HAVE_DB = database_available()

requires_db = pytest.mark.skipif(
    not HAVE_DB,
    reason=f"{DSN_ENV} 未设置或库不可用（P3 集成测试需要真实 PostgreSQL）",
)

#: P3 的测试项目统一用这个 code 前缀，便于清理
P3_PROJECT_PREFIX = "p3test-"

#: 当前用例的 P3 项目（由 p3_project 夹具写入，make_run 无参时用它）
_DEFAULT_PROJECT: list[dict] = []


def reset_db_engine(dsn: str | None = None) -> None:
    """把 app.db 的引擎重绑到指定 DSN（懒建单例，必须清缓存）。"""
    install_selector_policy()
    if dsn:
        os.environ["TESTDOCK_DATABASE_URL"] = dsn
    from app.config import settings

    settings.database_url = dsn or TEST_DB
    from app import db as db_mod

    if hasattr(db_mod, "reset_engine"):
        db_mod.reset_engine()
    for attr in ("_engine", "_sessionmaker"):
        if hasattr(db_mod, attr):
            setattr(db_mod, attr, None)


def _exec_sync(sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    """同步执行一条 SQL（内部 asyncio.run 包一层），返回 mappings 行列表。"""
    install_selector_policy()
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    dsn = os.environ.get("TESTDOCK_DATABASE_URL") or TEST_DB

    async def _inner() -> list[Any]:
        engine = create_async_engine(dsn)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params or {})
                try:
                    rows = list(result.mappings().all())
                except Exception:  # noqa: BLE001 - 非 SELECT 没有行集
                    rows = []
                if not result.returns_rows:
                    rows = []
                return rows
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


@pytest.fixture(scope="session", autouse=True)
def _p3_environment():
    """指向测试库 + 关掉 lifespan 里的后台调度（用例手动驱动 dispatcher）。"""
    if not HAVE_DB:
        yield
        return
    os.environ.setdefault("TESTDOCK_SCHEDULER", "0")
    reset_db_engine(TEST_DB)
    yield


@pytest.fixture(scope="session")
def sync_engine():
    from sqlalchemy import create_engine

    engine = create_engine(TEST_DB, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def demo(sync_engine) -> dict:
    """demo 种子（scripts/seed_demo.py）：取一个 android application 与 ready 资源。"""
    from sqlalchemy import text

    with sync_engine.connect() as conn:
        project = conn.execute(
            text("SELECT id, code FROM projects ORDER BY created_at LIMIT 1")
        ).first()
        if project is None:
            pytest.skip("库里没有 demo project，先跑 scripts/seed_demo.py")
        app_row = conn.execute(
            text(
                "SELECT id, platform FROM applications"
                " WHERE project_id = :p AND platform = 'android' ORDER BY created_at LIMIT 1"
            ),
            {"p": project.id},
        ).first()
        node = conn.execute(
            text("SELECT id FROM execution_nodes WHERE project_id = :p LIMIT 1"),
            {"p": project.id},
        ).first()
        if app_row is None or node is None:
            pytest.skip("demo 种子缺少 android application / execution node")
    return {
        "project_id": str(project.id),
        "project_code": project.code,
        "application_id": str(app_row.id),
        "platform": app_row.platform,
        "node_id": str(node.id),
    }


def make_project(sync_engine, *, resources: int = 2, platform: str = "android") -> dict:
    """建一个干净的 P3 测试项目（含 application / node / 若干 ready 资源）。

    用独立项目而不用 demo 项目：P3 的 dispatcher 会挑"任意 ready 资源"，
    共用 demo 项目会跟 API server / Lead 的测试抢设备。
    """
    suffix = uuid.uuid4().hex[:10]
    project_id = str(uuid.uuid4())
    application_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    _exec_sync(
        "INSERT INTO projects (id, code, name) VALUES (CAST(:id AS uuid), :code, :name)",
        {"id": project_id, "code": P3_PROJECT_PREFIX + suffix, "name": f"P3 {suffix}"},
    )
    _exec_sync(
        "INSERT INTO applications (id, project_id, platform, name, identifier)"
        " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :platform, :name, :identifier)",
        {
            "id": application_id,
            "pid": project_id,
            "platform": platform,
            "name": f"App {suffix}",
            "identifier": f"com.example.p3{suffix}",
        },
    )
    _exec_sync(
        "INSERT INTO execution_nodes (id, project_id, name, agent_version, status)"
        " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :name, 'pytest', 'online')",
        {"id": node_id, "pid": project_id, "name": f"node-{suffix}"},
    )
    _exec_sync(
        "INSERT INTO resource_profiles (id, project_id, platform, name, fingerprint, spec)"
        " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'android', :name, :fp, '{}'::jsonb)",
        {
            "id": profile_id,
            "pid": project_id,
            "name": f"profile-{suffix}",
            # ck_resource_profiles_fingerprint_hex64 要求 64 位十六进制
            "fp": uuid.uuid4().hex + uuid.uuid4().hex,
        },
    )
    # test_runs.revision_id 有复合外键 (project_id, application_id, revision_id) ->
    # task_revisions，所以必须先造 environment -> task -> revision 这条链。
    environment_id = str(uuid.uuid4())
    _exec_sync(
        "INSERT INTO environments (id, project_id, name, config)"
        " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :name, '{}'::jsonb)",
        {"id": environment_id, "pid": project_id, "name": f"env-{suffix}"},
    )
    task_id = str(uuid.uuid4())
    _exec_sync(
        "INSERT INTO test_tasks (id, project_id, application_id, name, lifecycle, created_by)"
        " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), :name,"
        "         'ready', 'pytest')",
        {"id": task_id, "pid": project_id, "aid": application_id, "name": f"task-{suffix}"},
    )
    revision_id = str(uuid.uuid4())
    _exec_sync(
        "INSERT INTO task_revisions (id, project_id, application_id, task_id,"
        "                           revision, environment_id, test_type, readiness, config, created_by)"
        " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), CAST(:tid AS uuid),"
        "         1, CAST(:eid AS uuid), 'ui', 'draft', '{}'::jsonb, 'pytest')",
        {
            "id": revision_id,
            "pid": project_id,
            "aid": application_id,
            "tid": task_id,
            "eid": environment_id,
        },
    )

    resource_ids = []
    for index in range(resources):

        resource_id = str(uuid.uuid4())
        serial = f"P3{suffix.upper()}{index}"
        _exec_sync(
            "INSERT INTO execution_resources"
            " (id, project_id, node_id, profile_id, platform, resource_key, kind, status)"
            " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:nid AS uuid),"
            "         CAST(:fid AS uuid), 'android', :key, 'device', 'ready')",
            {
                "id": resource_id,
                "pid": project_id,
                "nid": node_id,
                "fid": profile_id,
                "key": serial,
            },
        )
        resource_ids.append({"id": resource_id, "serial": serial, "profile_id": profile_id})
    return {
        "project_id": project_id,
        "application_id": application_id,
        "node_id": node_id,
        "environment_id": environment_id,
        "task_id": task_id,
        "revision_id": revision_id,
        "profile_id": profile_id,
        "resources": resource_ids,
        "resource_id": resource_ids[0]["id"] if resource_ids else None,
        "suffix": suffix,
    }


#: 删项目要按外键依赖叶子优先的顺序（全部外键都是 NO ACTION，先删 projects 必然
#: ForeignKeyViolation）。顺序来自 .runtime/cleanup_test_projects.py——已在真实库
#: 上验证过 11619 行删除成功的那份（device-registration.md D6 改动三）。
PROJECT_TABLE_DROP_ORDER: tuple[str, ...] = (
    "resource_leases",
    "artifacts",
    "case_results",
    "metric_summaries",
    "gate_evaluations",
    "baselines",
    "run_events",
    "run_components",
    "debug_sessions",
    "test_runs",
    "task_revisions",
    "execution_resources",
    "suite_versions",
    "test_tasks",
    "test_suites",
    "gate_policies",
    "app_builds",
    "environments",
    "execution_nodes",
    "resource_profiles",
    "applications",
    "audit_events",
    "project_members",
    "projects",
)


def drop_project(project_id: str) -> None:
    """按外键叶子优先的顺序删项目及其全部从属数据。

    失败直接抛，不吞异常：清理失败要立刻暴露，而不是攒成 949 台孤儿设备
    （device-registration.md §1.4 就是这么来的）。
    """
    for table in PROJECT_TABLE_DROP_ORDER[:-1]:
        _exec_sync(
            f"DELETE FROM {table} WHERE project_id = CAST(:pid AS uuid)",  # noqa: S608 - 表名来自本模块常量
            {"pid": project_id},
        )
    # projects 自身没有 project_id 列，按 id 删（cleanup_test_projects.py 同款）
    _exec_sync(
        "DELETE FROM projects WHERE id = CAST(:pid AS uuid)",
        {"pid": project_id},
    )


@pytest.fixture
def p3_project(sync_engine):
    """一个干净的 P3 项目（2 个 ready 设备），用例结束删除。"""
    project = make_project(sync_engine)
    _DEFAULT_PROJECT.append(project)
    try:
        yield project
    finally:
        if _DEFAULT_PROJECT:
            _DEFAULT_PROJECT.pop()
        drop_project(project["project_id"])


@pytest.fixture(scope="module")
def api_client():
    """把 app 绑到测试库，返回 TestClient（lifespan 会生成 control token）。"""
    if not HAVE_DB:
        pytest.skip("需要 TESTDOCK_TEST_DATABASE_URL")
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as client:
        yield client
    reset_db_engine(TEST_DB)


@pytest.fixture
def control_token(api_client) -> str:
    token = getattr(api_client.app.state, "control_token", None)
    assert token, "lifespan 应该生成 control token"
    return token


@pytest.fixture
def make_run(sync_engine):
    """插一条指定状态的 run（直接 SQL，不经路由层）。"""
    from sqlalchemy import text as _text

    def _factory(*, state: str = "queued", request_key: str, project: dict | None = None,
                 config_snapshot: dict | None = None) -> str:
        from app.domain import runs as _runs

        import json as _json

        proj = project or _DEFAULT_PROJECT[0]
        project_id = proj.get("project_id")
        application_id = proj.get("application_id") or proj.get("id")
        resource_id = proj.get("resource_id")
        # running/finalizing 受 ck_test_runs_state_executing_needs_resource 约束：
        # 这两个状态必须有 resource_id + started_at；其余状态两者必须为 NULL。
        needs_resource = state in ("running", "finalizing")
        terminal = state in _runs.TERMINAL_STATES
        # completed 还受 ck_test_runs_state_executing_needs_resource 约束：
        # 必须 resource_id + started_at 齐全才能以 completed 落库。
        if terminal:
            needs_resource = True
        with sync_engine.begin() as conn:
            row = conn.execute(
                _text(
                    "INSERT INTO test_runs (id, project_id, application_id, platform, revision_id,"
                    "                      request_key, state, config_snapshot, created_by,"
                    "                      resource_id, profile_id, started_at, ended_at,"
                    "                      outcome)"
                    " VALUES (CAST(:id AS uuid), CAST(:project_id AS uuid), CAST(:application_id AS uuid),"
                    "         :platform, CAST(:revision_id AS uuid),"
                    "         :request_key, :state, CAST(:config AS jsonb), 'pytest',"
                    "         CAST(:resource_id AS uuid), CAST(:profile_id AS uuid),"
                    "         CASE WHEN :needs_start THEN now() ELSE NULL END,"
                    "         CASE WHEN :terminal THEN now() ELSE NULL END,"
                    # ck_test_runs_state_outcome_pair: completed 行必须自带 outcome，
                    # 否则 INSERT 本身就违反 CHECK（测试稍后自会 UPDATE 覆盖）。
                    "         CASE WHEN :terminal THEN 'passed' ELSE NULL END)"
                    " RETURNING id"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "project_id": project_id,
                    "application_id": application_id,
                    "request_key": request_key,
                    "state": state,
                    "config": _json.dumps(config_snapshot or {}, ensure_ascii=False),
                    "platform": proj.get("platform") or "android",
                    "revision_id": proj.get("revision_id"),
                    "resource_id": resource_id if needs_resource else None,
                    "profile_id": (proj.get("profile_id") if needs_resource else None),
                    "needs_start": needs_resource,
                    "terminal": terminal,
                },
            ).first()
        return str(row.id)

    return _factory





def _windows_selector_loop() -> Any:
    import selectors

    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()


@pytest.fixture
def event_loop_policy():
    """pytest-asyncio 会用它造 loop；Windows 必须用 Selector（psycopg async 不支持 Proactor）。"""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


@pytest.fixture
async def session():
    """一个异步会话（P3 的 domain 层用例直接用；结束时回滚未提交的写）。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.set_event_loop(asyncio.get_running_loop())
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ.get("TESTDOCK_DATABASE_URL") or TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as sess:
            yield sess
            await sess.rollback()
    finally:
        await engine.dispose()


@asynccontextmanager
async def async_session() -> AsyncIterator[Any]:
    install_selector_policy()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(os.environ.get("TESTDOCK_DATABASE_URL") or TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


__all__ = [
    "CLIENT_HEADERS",
    "HAVE_DB",
    "PROJECT_TABLE_DROP_ORDER",
    "REPO_ROOT",
    "SERVER_ROOT",
    "TEST_DB",
    "async_session",
    "database_available",
    "drop_project",
    "install_selector_policy",
    "libpq_dsn",
    "make_project",
    "make_run",
    "requires_db",
    "reset_db_engine",
    "session",
]
