"""正式化改造服务端行为测试（工单 01/02/04/05/06/07/09）。

全部在 pytest 自动建立的独立临时 PostgreSQL 上运行（conftest.py），
不接触正式库或用户已有服务。覆盖：
- 工作空间默认 / 改名 / 非法输入 / 持久化（AC-02）
- 项目与应用创建、改名、身份唯一性、归档记录占用唯一键（AC-03）
- 归档占用保护、父子恢复、归档后业务写入拒绝（AC-04/05/06/09）
- 能力摘要、首用状态、正式启动假执行拒绝（AC-01/11/12）
- 旧演示数据预览只按固定身份识别、逐项执行受控（AC-10）
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import formal_start_blocker
from app.main import app
from tests._p3_common import (
    CLIENT_HEADERS,
    TEST_DB,
    drop_project,
    make_project,
    reset_db_engine,
    requires_db,
    sync_engine,
)

pytestmark = requires_db


def _sql_conn():
    """直接 SQL 造占用数据（不经过 API）；绑定到进程私有的隔离库。"""
    from sqlalchemy import create_engine

    return create_engine(TEST_DB, future=True).begin()


@pytest.fixture(scope="module")
def client():
    import os

    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as api:
        yield api
    reset_db_engine(TEST_DB)


def _new_project(client: TestClient, prefix: str = "formal") -> dict:
    code = f"{prefix}-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/projects",
        json={"code": f"  {code.upper()}  ", "name": "  真实项目  "},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == code
    assert body["name"] == "真实项目"
    return body


def _new_app(client: TestClient, project_id: str, name: str = "真实应用") -> dict:
    ident = f"com.example.app{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/applications",
        json={"project_id": project_id, "platform": "android", "name": name, "identifier": ident},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# 01 / 06 / 07
# --------------------------------------------------------------------------- #
def test_workspace_default_rename_validation_and_persistence(client: TestClient) -> None:
    first = client.get("/api/v1/workspace")
    assert first.status_code == 200, first.text
    assert first.json()["name"] == "默认工作空间"
    assert first.json()["demo_mode"] is False

    for bad in ("", "   ", "x" * 61):
        resp = client.patch("/api/v1/workspace", json={"name": bad}, headers=CLIENT_HEADERS)
        assert resp.status_code in (400, 422), resp.text
    # 失败不改原值
    assert client.get("/api/v1/workspace").json()["name"] == "默认工作空间"

    renamed = client.patch(
        "/api/v1/workspace", json={"name": "  长中文工作空间名称验收用  "}, headers=CLIENT_HEADERS
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "长中文工作空间名称验收用"
    assert renamed.json()["customized_at"] is not None
    # 重新读取（模拟刷新）仍是新值
    assert client.get("/api/v1/workspace").json()["name"] == "长中文工作空间名称验收用"
    # 复原，避免污染其它用例
    client.patch("/api/v1/workspace", json={"name": "默认工作空间"}, headers=CLIENT_HEADERS)


def test_capabilities_and_onboarding_are_real(client: TestClient) -> None:
    caps = client.get("/api/v1/capabilities")
    assert caps.status_code == 200, caps.text
    body = caps.json()
    assert body["version"]
    assert {p["platform"] for p in body["platforms"]} == {"android", "ios", "web"}
    supports = {p["platform"]: p["supported"] for p in body["platforms"]}
    assert supports == {"android": True, "ios": False, "web": False}
    assert "database_url" not in caps.text.lower()

    onboarding = client.get("/api/v1/onboarding/status")
    assert onboarding.status_code == 200, onboarding.text
    steps = {step["key"]: step for step in onboarding.json()["steps"]}
    assert set(steps) == {"workspace", "project", "application", "device", "run"}
    assert onboarding.json()["complete"] in (True, False)
    # 不靠引导端点写入任何业务对象
    with _sql_conn() as conn:
        assert conn.execute(text("SELECT count(*) FROM projects WHERE code LIKE 'onboarding-demo%'")).scalar() == 0


def test_formal_start_rejects_fake_runner(monkeypatch) -> None:
    # 不 reload app.config：其它模块按 `from .config import settings` 持有旧对象，
    # reload 会让运行中读取 settings 的代码与测试 monkeypatch 的对象不一致。
    monkeypatch.setenv("TESTDOCK_FAKE_RUNNER", "1")
    monkeypatch.delenv("TESTDOCK_DEMO_MODE", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    blocker = formal_start_blocker()
    assert blocker and "TESTDOCK_FAKE_RUNNER" in blocker
    # 显式演示环境允许；pytest 测试通道允许
    monkeypatch.setenv("TESTDOCK_DEMO_MODE", "1")
    monkeypatch.setenv("PYTEST_VERSION", "9")
    assert formal_start_blocker() is None


def test_seed_demo_refuses_formal_default_database(monkeypatch) -> None:
    import importlib.util
    from pathlib import Path

    seed_path = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo_under_test", seed_path)
    assert spec and spec.loader
    seed_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_mod)

    monkeypatch.delenv("TESTDOCK_DEMO_MODE", raising=False)
    assert seed_mod.main(["seed_demo.py", "--dry-run"]) == 2
    assert seed_mod.main(["seed_demo.py", "--demo", "--dry-run", "--database-url", "postgresql+psycopg://testdock@127.0.0.1:55432/testdock"]) == 2
    # 独立演示库的 dry-run 不写库
    assert seed_mod.main([
        "seed_demo.py", "--demo", "--dry-run",
        "--database-url", "postgresql+psycopg://testdock@127.0.0.1:55433/testdock_demo",
    ]) == 0


# --------------------------------------------------------------------------- #
# 02 / 04 / 05 / 06
# --------------------------------------------------------------------------- #
def test_new_project_can_create_performance_task_without_environment_id(client: TestClient) -> None:
    project = _new_project(client)
    application = _new_app(client, project["id"])

    response = client.post(
        "/api/v1/tasks",
        json={
            "name": "默认环境性能任务",
            "test_type": "performance",
            "platform": "android",
            "application_id": application["id"],
            "config": {},
        },
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["test_type"] == "performance"
    assert body["readiness"] == "draft"
    assert body["revision"]["environment_id"]


def test_default_environment_backfill_preserves_existing_environments(client: TestClient) -> None:
    project_with_environment = _new_project(client)
    project_without_environment = _new_project(client)
    application = _new_app(client, project_without_environment["id"])
    with _sql_conn() as conn:
        existing_id = conn.execute(
            text("SELECT id FROM environments WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": project_with_environment["id"]},
        ).scalar_one()
        conn.execute(
            text("DELETE FROM environments WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": project_without_environment["id"]},
        )

    migration_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0010_default_environments.py"
    spec = importlib.util.spec_from_file_location("migration_0010", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with _sql_conn() as conn:
        conn.execute(text(migration.BACKFILL_SQL))
        conn.execute(text(migration.BACKFILL_SQL))

    response = client.post(
        "/api/v1/tasks",
        json={
            "name": "存量项目性能任务",
            "test_type": "performance",
            "platform": "android",
            "application_id": application["id"],
            "config": {},
        },
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 201, response.text
    with _sql_conn() as conn:
        environments = conn.execute(
            text(
                "SELECT project_id, id, name FROM environments "
                "WHERE project_id IN (CAST(:first AS uuid), CAST(:second AS uuid)) "
                "ORDER BY project_id, name"
            ),
            {"first": project_with_environment["id"], "second": project_without_environment["id"]},
        ).all()
    assert len(environments) == 2
    by_project = {str(row.project_id): row for row in environments}
    assert str(by_project[project_with_environment["id"]].id) == str(existing_id)
    assert by_project[project_without_environment["id"]].name == "default"


def test_project_application_identity_and_rename(client: TestClient) -> None:
    project = _new_project(client)
    # 同身份重复创建：可理解的冲突 + existing_id 指向原对象
    duplicate = client.post(
        "/api/v1/projects",
        json={"code": project["code"], "name": "另一个项目"},
        headers=CLIENT_HEADERS,
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["code"] == "identity_conflict"
    assert duplicate.json()["details"]["existing_id"] == project["id"]

    for bad in ("", "-abc", "a" * 61, "bad code", "bad_code", "a.b"):
        resp = client.post(
            "/api/v1/projects", json={"code": bad, "name": "非法"}, headers=CLIENT_HEADERS
        )
        assert resp.status_code in (400, 422), (bad, resp.text)

    # 应用：仅 Android；非法包名 / iOS / Web 均拒绝
    for body in (
        {"platform": "ios", "identifier": "com.example.ios"},
        {"platform": "web", "identifier": "com.example.web"},
        {"platform": "android", "identifier": "not-a-package"},
    ):
        resp = client.post(
            "/api/v1/applications",
            json={"project_id": project["id"], "name": "不支持的应用", **body},
            headers=CLIENT_HEADERS,
        )
        assert resp.status_code in (400, 422), resp.text

    app = _new_app(client, project["id"])
    duplicate_app = client.post(
        "/api/v1/applications",
        json={
            "project_id": project["id"], "platform": "android",
            "name": "同名另一个", "identifier": app["identifier"],
        },
        headers=CLIENT_HEADERS,
    )
    assert duplicate_app.status_code == 409
    assert duplicate_app.json()["details"]["existing_id"] == app["id"]

    # 改名只影响显示名，身份与 ID 不变
    renamed = client.patch(
        "/api/v1/applications/" + app["id"], json={"name": "  改名后的应用  "}, headers=CLIENT_HEADERS
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["id"] == app["id"]
    assert renamed.json()["identifier"] == app["identifier"]
    assert renamed.json()["project_id"] == project["id"]
    assert renamed.json()["name"] == "改名后的应用"

    project_renamed = client.patch(
        "/api/v1/projects/" + project["id"], json={"name": "改名后的项目"}, headers=CLIENT_HEADERS
    )
    assert project_renamed.json()["code"] == project["code"]
    assert project_renamed.json()["id"] == project["id"]

    # 项目列表默认排除归档；带 include_archived 能拿到管理视图
    listed = client.get("/api/v1/projects").json()
    assert any(item["id"] == project["id"] for item in listed["items"])


def test_archive_blocks_active_runs_and_rejects_business_writes(client: TestClient, sync_engine) -> None:
    # 用 P3 夹具建立合法的项目 / 应用 / 修订 / 资源链，再插一条 queued 运行
    project = make_project(sync_engine)
    project_id = project["project_id"]
    app_id = project["application_id"]
    run_id = None
    try:
        from sqlalchemy import text as sql_text

        with sync_engine.begin() as conn:
            row = conn.execute(
                sql_text(
                    "INSERT INTO test_runs (id, project_id, application_id, platform, revision_id,"
                    " request_key, state, config_snapshot, created_by)"
                    " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:aid AS uuid), 'android',"
                    " CAST(:rev AS uuid), :rk, 'queued', '{}'::jsonb, 'pytest') RETURNING id"
                ),
                {"pid": project_id, "aid": app_id, "rev": project["revision_id"], "rk": "archive-block-" + uuid.uuid4().hex},
            ).first()
        run_id = str(row.id)

        preview = client.get("/api/v1/projects/" + project_id + "/archive-preview")
        assert preview.status_code == 200, preview.text
        assert preview.json()["blockers"]["active_runs"], "预览应列出具体阻塞运行"

        blocked = client.post("/api/v1/projects/" + project_id + "/archive", headers=CLIENT_HEADERS)
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["code"] == "archive_blocked"
        assert blocked.json()["details"]["blockers"]["active_runs"][0]["id"] == run_id
        with sync_engine.begin() as conn:
            state = conn.execute(sql_text("SELECT state FROM test_runs WHERE id::text = :id"), {"id": run_id}).scalar()
        assert state == "queued", "归档不能自动取消现有活动"

        # 让运行终态后归档；重复归档幂等
        with sync_engine.begin() as conn:
            conn.execute(
                sql_text("UPDATE test_runs SET state = 'cancelled', ended_at = now() WHERE id::text = :id"),
                {"id": run_id},
            )
        archived = client.post("/api/v1/projects/" + project_id + "/archive", headers=CLIENT_HEADERS)
        assert archived.status_code == 200, archived.text
        again = client.post("/api/v1/projects/" + project_id + "/archive", headers=CLIENT_HEADERS)
        assert again.status_code == 200 and again.json()["already"] is True

        # 归档后：任务、构建、套件、基线、门禁、运行等直接接口提交都被服务端拒绝
        write_attempts = [
            ("post", "/api/v1/tasks", {"name": "归档后任务", "test_type": "ui", "platform": "android", "application_id": app_id, "project_id": project_id, "config": {}}),
            ("post", "/api/v1/builds", {"application_id": app_id, "version": "1.0", "build_key": "key-" + uuid.uuid4().hex}),
            ("post", "/api/v1/runs", {"application_id": app_id, "platform": "android", "request_key": "run-" + uuid.uuid4().hex}),
            ("post", "/api/v1/suites", {"application_id": app_id, "name": "归档后套件", "test_type": "ui"}),
            ("post", "/api/v1/baselines", {"request_key": "b-" + uuid.uuid4().hex, "run_id": run_id}),
            ("post", "/api/v1/gate-policies", {"application_id": app_id, "rules": {}}),
        ]
        for method, path, body in write_attempts:
            resp = getattr(client, method)(path, json=body, headers=CLIENT_HEADERS)
            assert resp.status_code == 409, (path, resp.status_code, resp.text)
            assert resp.json()["code"] == "object_archived", (path, resp.text)

        # 父项目归档时不能单独恢复子应用；项目恢复不复活单独归档的应用
        assert client.post("/api/v1/applications/" + app_id + "/archive", headers=CLIENT_HEADERS).status_code == 200
        restore_child = client.post("/api/v1/applications/" + app_id + "/restore", headers=CLIENT_HEADERS)
        assert restore_child.status_code == 409, restore_child.text
        assert client.post("/api/v1/projects/" + project_id + "/restore", headers=CLIENT_HEADERS).status_code == 200
        assert client.get("/api/v1/applications/" + app_id).json()["archived_at"] is not None
        assert client.post("/api/v1/applications/" + app_id + "/restore", headers=CLIENT_HEADERS).status_code == 200
    finally:
        drop_project(project_id)


@pytest.mark.parametrize("entity", ["project", "application"])
def test_restore_reports_previous_archive_state_and_preserves_identity(client, entity):
    project = _new_project(client, "restore")
    application = _new_app(client, project["id"])
    original = project if entity == "project" else application
    path = "projects" if entity == "project" else "applications"
    url = f"/api/v1/{path}/{original['id']}"
    try:
        archived = client.post(url + "/archive", headers=CLIENT_HEADERS)
        assert archived.status_code == 200, archived.text
        assert archived.json()["archived_at"] is not None
        for already in (False, True):
            restored = client.post(url + "/restore", headers=CLIENT_HEADERS)
            assert restored.status_code == 200, restored.text
            assert restored.json() == {
                "id": original["id"], "name": original["name"],
                "archived_at": None, "already": already,
            }
        if entity == "application":
            current = client.get(url).json()
        else:
            current = next(item for item in client.get("/api/v1/projects").json()["items"]
                           if item["id"] == original["id"])
        for field in ("id", "name", "code") if entity == "project" else (
            "id", "name", "project_id", "platform", "identifier"
        ):
            assert current[field] == original[field]
        assert current["archived_at"] is None
    finally:
        drop_project(project["id"])


def test_project_scope_filters_are_served_by_api(client: TestClient) -> None:
    first = _new_project(client, "scope-a")
    second = _new_project(client, "scope-b")
    _new_app(client, first["id"], "同名应用")
    _new_app(client, second["id"], "同名应用")
    for project in (first, second):
        resp = client.get("/api/v1/overview", params={"project_id": project["id"]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["application_total"] == 1, resp.text
        assert client.get("/api/v1/tasks", params={"project_id": project["id"]}).status_code == 200
        assert client.get("/api/v1/runs", params={"project_id": project["id"]}).status_code == 200
        assert client.get("/api/v1/suites", params={"project_id": project["id"]}).status_code == 200
    # 不存在的项目不伪装成空列表
    missing = str(uuid.uuid4())
    assert client.get("/api/v1/overview", params={"project_id": missing}).status_code == 404
    assert client.get("/api/v1/runs", params={"project_id": missing}).status_code == 404


# --------------------------------------------------------------------------- #
# 09
# --------------------------------------------------------------------------- #
def test_legacy_review_preview_is_safe_and_name_independent(client: TestClient) -> None:
    preview = client.get("/api/v1/legacy-review")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["preview_token"]
    for item in body["items"]:
        assert item["id"] and item["match_basis"]
        # 预览不含删除动作，也不按名称自动清理
        assert "delete" not in item["allowed_actions"]
    # 真实同名对象不会凭名称成为候选
    same_name = _new_project(client, "real")
    client.patch("/api/v1/projects/" + same_name["id"], json={"name": "星河 Demo"}, headers=CLIENT_HEADERS)
    after = client.get("/api/v1/legacy-review").json()
    assert all(item["id"] != same_name["id"] for item in after["items"])

    # 过期预览 token 不执行
    stale = client.post(
        "/api/v1/legacy-review/apply",
        json={"preview_token": "stale-token", "actions": []},
        headers=CLIENT_HEADERS,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "state_conflict"

    # 空操作列表是稳定的重复执行（不改写历史）
    current = client.get("/api/v1/legacy-review").json()
    result = client.post(
        "/api/v1/legacy-review/apply",
        json={"preview_token": current["preview_token"], "actions": []},
        headers=CLIENT_HEADERS,
    )
    assert result.status_code == 200, result.text
    assert result.json()["applied"] == []


def test_legacy_review_distinguishes_original_renamed_and_real_seedlike_records(client: TestClient) -> None:
    """AC-10：隔离库副本造三种对象；只按固定身份/原字段识别，真实同名不入选。"""
    from sqlalchemy import text as sql_text

    from app.routers.legacy_review import SEED_PROJECT_ID

    engine_url = TEST_DB
    from sqlalchemy import create_engine

    engine = create_engine(engine_url, future=True)
    real_id = str(uuid.uuid4())
    renamed_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            # 原始 seed 项目（固定 ID + 原始名称）
            conn.execute(
                sql_text(
                    "INSERT INTO projects (id, code, name) VALUES (CAST(:id AS uuid), 'testdock-demo', '星河 Demo')"
                    " ON CONFLICT (id) DO UPDATE SET code = EXCLUDED.code, name = EXCLUDED.name"
                ),
                {"id": SEED_PROJECT_ID},
            )
            # 固定 ID 但已被用户改名：候选仍可识别，但改名/归档需人工判断？
            # 规格允许「已承载真实数据时直接保留并改名」，这里保留 confirmed 但标注当前名。
            conn.execute(
                sql_text(
                    "INSERT INTO projects (id, code, name) VALUES (CAST(:id AS uuid), :code, :name)"
                ),
                {"id": renamed_id, "code": "renamed-seed-" + renamed_id[:8], "name": "真实业务改名后项目"},
            )
            # 真实同名项目：仅名称命中，不入选候选
            conn.execute(
                sql_text("INSERT INTO projects (id, code, name) VALUES (CAST(:id AS uuid), :code, '星河 Demo')"),
                {"id": real_id, "code": "real-same-name-" + real_id[:8]},
            )
        body = client.get("/api/v1/legacy-review").json()
        ids = {item["id"] for item in body["items"]}
        assert SEED_PROJECT_ID in ids
        assert real_id not in ids, "真实同名项目不能按名称判定为演示数据"
        project_candidate = next(item for item in body["items"] if item["id"] == SEED_PROJECT_ID)
        assert project_candidate["confidence"] == "confirmed"
        assert project_candidate["current_name"] == "星河 Demo"
        assert any("固定 ID" in basis for basis in project_candidate["match_basis"])

        # 改名：保留 ID / 编码，历史身份不变
        result = client.post(
            "/api/v1/legacy-review/apply",
            json={
                "preview_token": body["preview_token"],
                "actions": [{"id": SEED_PROJECT_ID, "entity": "project", "action": "rename", "name": "保留的真实测试项目"}],
            },
            headers=CLIENT_HEADERS,
        )
        assert result.status_code == 200, result.text
        assert result.json()["applied"][0]["result"] == "保留的真实测试项目"
        after = client.get("/api/v1/projects?include_archived=true").json()
        project = next(item for item in after["items"] if item["id"] == SEED_PROJECT_ID)
        assert project["code"] == "testdock-demo", "改名不改身份"
        assert project["name"] == "保留的真实测试项目"

        # 重复执行同一改名（重新预览后）稳定，不改写其它历史
        second = client.get("/api/v1/legacy-review").json()
        second_result = client.post(
            "/api/v1/legacy-review/apply",
            json={
                "preview_token": second["preview_token"],
                "actions": [{"id": SEED_PROJECT_ID, "entity": "project", "action": "rename", "name": "保留的真实测试项目"}],
            },
            headers=CLIENT_HEADERS,
        )
        assert second_result.status_code == 200, second_result.text
        assert client.get("/api/v1/projects?include_archived=true").json()["items"]
    finally:
        with engine.begin() as conn:
            for pid in (SEED_PROJECT_ID, renamed_id, real_id):
                conn.execute(sql_text("DELETE FROM projects WHERE id::text = :id"), {"id": pid})
        engine.dispose()


def test_archive_and_new_run_share_row_level_lock(client: TestClient, sync_engine) -> None:
    """AC-06 普通并发：归档提交后，新的运行提交不能再插入该范围。"""
    import asyncio
    from sqlalchemy import text as sql_text

    from app.domain import identity as identity_mod
    from app.errors import ApiError

    project = make_project(sync_engine)
    project_id = project["project_id"]
    try:
        # 归档项目（无活动占用）
        from app.db import get_sessionmaker as _maker

        async def do_archive() -> None:
            async with _maker()() as session:
                async with session.begin():
                    await identity_mod.archive_entity(session, entity="project", entity_id=project_id)

        asyncio.run(do_archive())

        async def try_guard() -> str:
            async with _maker()() as session:
                async with session.begin():
                    try:
                        await identity_mod.assert_scope_active(
                            session, project_id=project_id, application_id=project["application_id"]
                        )
                    except ApiError as exc:
                        return exc.code
                    return "allowed"

        assert asyncio.run(try_guard()) == "object_archived"
        # 归档后的项目仍可通过只读详情访问；历史运行没有被改写
        assert client.get("/api/v1/projects?include_archived=true").status_code == 200
        with sync_engine.begin() as conn:
            assert conn.execute(
                sql_text("SELECT count(*) FROM test_runs WHERE project_id::text = :pid"), {"pid": project_id}
            ).scalar() == 0
    finally:
        drop_project(project_id)


def test_migration_is_append_only_and_can_be_reapplied() -> None:
    """AC-16：0009 只追加；在已迁移的隔离库再次 upgrade head 不新增业务数据。"""
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import text as sql_text

    repo_root = Path(__file__).resolve().parents[2]
    versions = repo_root / "server" / "alembic" / "versions"
    chain = {}
    for path in sorted(versions.glob("[0-9]*.py")):
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {
            node.targets[0].id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and node.targets
            and isinstance(node.targets[0], ast.Name)
        }
        chain[values["revision"]] = values["down_revision"]
    assert chain["0009"] == "0008"
    assert "0001" in chain and chain["0001"] is None

    baseline = json.loads(
        (repo_root / "docs" / "contracts" / "migration-baseline.json").read_text(encoding="utf-8")
    )
    original = versions / "0001_initial.py"
    normalized = original.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized).hexdigest() == baseline["0001_initial.py"]["sha256"], (
        "历史迁移 0001 被改写"
    )

    env = dict(os.environ)
    env["TESTDOCK_DATABASE_URL"] = TEST_DB
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(repo_root / "server"),
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    from sqlalchemy import create_engine

    engine = create_engine(TEST_DB, future=True)
    with engine.begin() as conn:
        # 重复迁移不灌 seed，不改写既有身份；工作空间仍只有一行
        assert conn.execute(sql_text("SELECT count(*) FROM workspace_settings")).scalar() == 1
        assert conn.execute(sql_text(
            "SELECT count(*) FROM projects WHERE code = 'testdock-demo'"
        )).scalar() == 0
    engine.dispose()


@pytest.mark.parametrize("entity", ["project", "application"])
def test_archive_transaction_blocks_concurrent_submission(client, sync_engine, entity):
    """A real request waits on the archive transaction, then sees its commit."""
    import asyncio
    from app.db import get_sessionmaker
    from app.domain.identity import archive_entity

    project = make_project(sync_engine)
    target = project["project_id" if entity == "project" else "application_id"]

    async def exercise():
        async with get_sessionmaker()() as session:
            async with session.begin():
                pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                await archive_entity(session, entity=entity, entity_id=target)
                submission = asyncio.create_task(asyncio.to_thread(
                    client.post, "/api/v1/runs", headers=CLIENT_HEADERS,
                    json={"application_id": project["application_id"], "platform": "android",
                          "request_key": "concurrent-" + uuid.uuid4().hex},
                ))
                try:
                    # Observe a database wait, rather than trusting thread timing.
                    for _ in range(500):
                        with sync_engine.connect() as observer:
                            waiting = observer.execute(text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                                "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                            ), {"pid": pid}).scalar_one()
                        if waiting:
                            break
                        await asyncio.sleep(0.01)
                    assert waiting, "submission never waited for the archive row lock"
                    assert not submission.done()
                finally:
                    await session.commit()
            response = await asyncio.wait_for(submission, 10)
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "object_archived"
    try:
        asyncio.run(exercise())
        with sync_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM test_runs WHERE project_id::text=:id"),
                                {"id": project["project_id"]}).scalar_one() == 0
    finally:
        drop_project(project["project_id"])


@pytest.mark.parametrize("entity", ["project", "application"])
def test_archived_build_identity_rejected_before_device_access(client, sync_engine, monkeypatch, entity):
    from app.services import builds

    def forbidden(*args, **kwargs):
        pytest.fail("archived identity check accessed a real device")
    monkeypatch.setattr(builds.adb_integration, "resolve_adb_path", forbidden)
    project = make_project(sync_engine)
    try:
        path = "projects" if entity == "project" else "applications"
        target = project["project_id" if entity == "project" else "application_id"]
        assert client.post(f"/api/v1/{path}/{target}/archive", headers=CLIENT_HEADERS).status_code == 200
        with sync_engine.connect() as conn:
            before = conn.execute(text("SELECT metadata FROM app_builds WHERE id::text=:id"),
                                  {"id": project["build_id"]}).scalar_one()
        for suffix, payload in (
            ("identity-checks", {"resource_id": project["resource_id"], "purpose": "manual", "test_type": "ui"}),
            ("confirm-identity", {"check_id": str(uuid.uuid4())}),
        ):
            response = client.post(f"/api/v1/builds/{project['build_id']}/{suffix}",
                                   json=payload, headers=CLIENT_HEADERS)
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "object_archived"
        with sync_engine.connect() as conn:
            assert conn.execute(text("SELECT metadata FROM app_builds WHERE id::text=:id"),
                                {"id": project["build_id"]}).scalar_one() == before
    finally:
        drop_project(project["project_id"])


@pytest.mark.parametrize("archived_path", ["projects", "applications"])
def test_completed_history_preserved_and_onboarding_uses_active_completed_runs(client, sync_engine, archived_path):
    project = make_project(sync_engine)
    pid = project["project_id"]
    rid = str(uuid.uuid4())
    def run_step():
        return next(s for s in client.get("/api/v1/onboarding/status").json()["steps"] if s["key"] == "run")
    baseline = run_step()["count"]
    try:
        with sync_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO test_runs (id,project_id,application_id,platform,revision_id,request_key,"
                "state,config_snapshot,created_by) VALUES (:id,:pid,:aid,'android',:rev,:key,"
                "'queued',CAST(:snapshot AS jsonb),'pytest')"
            ), {"id": rid, "pid": pid, "aid": project["application_id"], "rev": project["revision_id"],
                "key": rid, "snapshot": json.dumps({"project_name": "original", "inputs": [1, 2]})})
        assert run_step()["count"] == baseline
        with sync_engine.begin() as conn:
            conn.execute(text("UPDATE test_runs SET state='completed',outcome='passed',"
                              "started_at=now(),ended_at=now(),resource_id=:resource,profile_id=:profile WHERE id=:id"),
                         {"id": rid, "resource": project["resource_id"], "profile": project["profile_id"]})
            conn.execute(text(
                "INSERT INTO artifacts (id,project_id,run_id,logical_key,kind,storage_key,mime_type,byte_size,sha256) "
                "VALUES (:id,:pid,:rid,'history','log','history/log','text/plain',0,:sha)"
            ), {"id": str(uuid.uuid4()), "pid": pid, "rid": rid, "sha": "0" * 64})
        assert run_step()["count"] == baseline + 1
        def history():
            with sync_engine.connect() as conn:
                return [conn.execute(text(f"SELECT to_jsonb(t) FROM {table} t WHERE {column}::text=:id"),
                                     {"id": rid}).scalars().all()
                        for table, column in (("test_runs", "id"), ("artifacts", "run_id"))]
        before = history()
        for path, target in (("projects", pid), ("applications", project["application_id"])):
            response = client.patch(f"/api/v1/{path}/{target}", json={"name": "renamed"}, headers=CLIENT_HEADERS)
            assert response.status_code == 200, response.text
            assert history() == before
        target = pid if archived_path == "projects" else project["application_id"]
        response = client.post(f"/api/v1/{archived_path}/{target}/archive", headers=CLIENT_HEADERS)
        assert response.status_code == 200, response.text
        assert history() == before
        assert run_step()["count"] == baseline
    finally:
        drop_project(pid)
