"""运行创建与调度的真实 PostgreSQL 回归（不启动设备 runner）。"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.main import app
from app.runner import dispatch_runner
from app.scheduler import dispatcher
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests._p3_common import (
    CLIENT_HEADERS,
    TEST_DB,
    make_project,
    requires_db,
    reset_db_engine,
)
from tests._p3_common import make_run as make_run
from tests._p3_common import p3_project as project  # noqa: F401 - fixture 复用
from tests._p3_common import sync_engine as sync_engine

pytestmark = requires_db


@pytest.fixture
def client():
    # 与 _p3_common.api_client 同款：关掉 lifespan 的后台调度循环，否则它会
    # 抢在用例手动 dispatch_one 之前消费 queued run（import 排除回归曾因此
    # 偶发 no_queued_run——后台循环把对照运行领走了）。
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    reset_db_engine(TEST_DB)


@pytest.fixture
def spawns(monkeypatch):
    # 直连 dispatcher 的用例不经过 client，引擎必须显式绑到测试库：模块导入期
    # app.config 先于 _p3_common 实例化 settings，默认 DSN 指向业务库（同
    # test_import_and_finalize._finalize 的先例）。
    reset_db_engine(TEST_DB)
    calls = []

    async def spawn(**kwargs):
        calls.append(kwargs)
        return 123456

    monkeypatch.setattr(dispatch_runner, "_spawner", spawn)
    return calls


def _body(project, **overrides):
    body = {
        "application_id": project["application_id"],
        "task_id": project["task_id"],
        "request_key": str(uuid.uuid4()),
        "platform": "android",
        "module": "ui",
        "device": {"resource_id": project["resource_id"]},
    }
    body.update(overrides)
    return body


def _row(engine, run_id):
    with engine.connect() as conn:
        return dict(conn.execute(
            text("SELECT * FROM test_runs WHERE id = CAST(:id AS uuid)"), {"id": run_id}
        ).mappings().one())


def test_create_run_generates_id_event_and_returns_same_run_on_retry(client, project, sync_engine):
    body = _body(project)
    first = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS)
    assert first.status_code == 201, first.text
    run_id = first.json()["id"]
    assert str(uuid.UUID(run_id)) == run_id
    assert first.json()["state"] == "queued"
    second = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == run_id
    assert second.json()["duplicate"] is True
    events = client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    assert [event["event_type"] for event in events] == ["queued"]
    assert _row(sync_engine, run_id)["outcome"] is None


def test_event_failure_rolls_back_created_run(client, project, sync_engine, monkeypatch):
    from app.routers import runs

    async def fail(*args, **kwargs):
        raise RuntimeError("pytest event write failure")

    monkeypatch.setattr(runs.events_mod, "append_event", fail)
    body = _body(project)
    response = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS)
    assert response.status_code == 500
    with sync_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM test_runs WHERE request_key = :key"),
                             {"key": body["request_key"]}).scalar_one()
    assert count == 0


def test_concurrent_submission_is_idempotent(client, project, sync_engine):
    body = _body(project)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda _: client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS), range(2)
        ))
    assert sorted(r.status_code for r in responses) == [200, 201], [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1


def test_create_run_without_revision_is_rejected_without_orphan_run(client, project):
    body = _body(project)
    body.pop("task_id")
    response = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "readiness_incomplete"


def test_revision_must_belong_to_selected_application(client, project, sync_engine):
    """跨应用的任务+修订组合：task_id 属于另一个应用，必须按不存在拒绝。"""
    other = make_project(sync_engine)
    response = client.post("/api/v1/runs", json=_body(
        project, task_id=other["task_id"], revision_id=other["revision_id"]
    ), headers=CLIENT_HEADERS)
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"


def test_create_then_dispatch_binds_requested_resource_before_lease(
    client, project, sync_engine, spawns
):
    requested = max(project["resources"], key=lambda resource: resource["id"])
    response = client.post("/api/v1/runs", json=_body(
        project, device={"resource_id": requested["id"]}
    ), headers=CLIENT_HEADERS)
    assert response.status_code == 201, response.text
    result = asyncio.run(dispatcher.dispatch_one(response.json()["id"]))
    assert result.ok, result.reason
    row = _row(sync_engine, result.run_id)
    assert row["state"] == "dispatching"
    assert str(row["resource_id"]) == requested["id"]
    assert str(row["profile_id"]) == requested["profile_id"]
    assert len(spawns) == 1
    assert spawns[0]["lease"]["resource_id"] == requested["id"]
    with sync_engine.connect() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM resource_leases WHERE run_id = CAST(:id AS uuid) "
            "AND released_at IS NULL"
        ), {"id": result.run_id}).scalar_one() == 1


def test_dispatch_existing_queued_run_does_not_violate_lease_foreign_key(
    project, make_run, sync_engine, spawns
):
    run_id = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)
    result = asyncio.run(dispatcher.dispatch_one(run_id))
    assert result.ok, result.reason
    assert _row(sync_engine, run_id)["state"] == "dispatching"
    assert len(spawns) == 1


def test_busy_requested_device_stays_queued_and_dispatches_after_release(
    project, make_run, sync_engine, spawns
):
    requested = max(project["resources"], key=lambda resource: resource["id"])
    run_ids = [make_run(state="queued", request_key=str(uuid.uuid4()), project=project)
               for _ in range(2)]
    with sync_engine.begin() as conn:
        for run_id in run_ids:
            conn.execute(text(
                "UPDATE test_runs SET config_snapshot = CAST(:config AS jsonb) "
                "WHERE id = CAST(:id AS uuid)"
            ), {"id": run_id, "config": json.dumps({"requested_resource_id": requested["id"]})})
    assert asyncio.run(dispatcher.dispatch_one(run_ids[0])).ok
    second = asyncio.run(dispatcher.dispatch_one(run_ids[1]))
    assert second.reason == "resource_busy"
    assert _row(sync_engine, run_ids[1])["state"] == "queued"
    assert len(spawns) == 1
    with sync_engine.begin() as conn:
        conn.execute(text(
            "UPDATE resource_leases SET released_at = now(), release_reason = 'pytest' "
            "WHERE run_id = CAST(:id AS uuid)"
        ), {"id": run_ids[0]})
    assert asyncio.run(dispatcher.dispatch_one(run_ids[1])).ok
    assert len(spawns) == 2


def test_two_dispatchers_cannot_spawn_same_run_twice(project, make_run, sync_engine, spawns):
    run_id = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)

    async def dispatch_twice():
        return await asyncio.gather(dispatcher.dispatch_one(run_id), dispatcher.dispatch_one(run_id))

    results = asyncio.run(dispatch_twice())
    assert sum(result.ok for result in results) == 1
    assert len(spawns) == 1


def test_two_runs_contending_for_one_device_do_not_steal_or_double_lease(
    project, make_run, sync_engine, spawns
):
    run_ids = [make_run(state="queued", request_key=str(uuid.uuid4()), project=project)
               for _ in range(2)]
    with sync_engine.begin() as conn:
        for run_id in run_ids:
            conn.execute(text("UPDATE test_runs SET config_snapshot = CAST(:config AS jsonb) "
                              "WHERE id = :id"),
                         {"id": run_id, "config": json.dumps({
                             "requested_resource_id": project["resource_id"]})})

    async def concurrent():
        return await asyncio.gather(*(dispatcher.dispatch_one(run_id) for run_id in run_ids))

    results = asyncio.run(concurrent())
    assert sum(result.ok for result in results) == 1
    assert len(spawns) == 1
    assert sorted(_row(sync_engine, run_id)["state"] for run_id in run_ids) == ["dispatching", "queued"]


def test_revision_config_and_device_are_frozen_into_run(client, project, sync_engine, spawns):
    config = {"device": {"resource_id": project["resource_id"], "allow_busy_queue": True},
              "perf": {"duration_s": 120, "items": ["CPU", "Memory", "FPS"]}}
    with sync_engine.begin() as conn:
        conn.execute(text(
            "UPDATE task_revisions SET config = CAST(:config AS jsonb), test_type = 'performance' "
            "WHERE id = CAST(:id AS uuid)"
        ), {"id": project["revision_id"], "config": json.dumps(config)})
    body = _body(project)
    body.pop("device")
    response = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS)
    assert response.status_code == 201, response.text
    snapshot = _row(sync_engine, response.json()["id"])["config_snapshot"]
    assert snapshot["requested_resource_id"] == project["resource_id"]
    assert snapshot["perf"] == config["perf"]
    assert snapshot["module"] == "perf"
    assert asyncio.run(dispatcher.dispatch_one(response.json()["id"])).ok
    assert spawns[0]["config"]["perf"] == config["perf"]


@pytest.mark.parametrize("status", ["offline", "unauthorized", "draining"])
def test_unready_requested_device_is_rejected(client, project, sync_engine, status):
    with sync_engine.begin() as conn:
        conn.execute(text("UPDATE execution_resources SET status = :status WHERE id = :id"),
                     {"status": status, "id": project["resource_id"]})
    response = client.post("/api/v1/runs", json=_body(project), headers=CLIENT_HEADERS)
    assert response.status_code == 424, response.text
    assert response.json()["code"] == "device_not_ready"


def test_device_from_another_project_is_rejected(client, project, sync_engine):
    other = make_project(sync_engine)
    response = client.post("/api/v1/runs", json=_body(
        project, device={"resource_id": other["resource_id"]}
    ), headers=CLIENT_HEADERS)
    assert response.status_code == 404, response.text


def test_events_are_serialized_for_concurrent_writers(project, make_run, sync_engine):
    from app.db import get_sessionmaker
    from app.domain.events import append_event

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)

    async def append(index):
        async with get_sessionmaker()() as session:
            async with session.begin():
                await append_event(session, project_id=project["project_id"], run_id=run_id,
                                   source_key="api", source_event_id=str(index),
                                   event_type="stage", payload={"stage": "pytest"})

    async def concurrent():
        await asyncio.gather(*(append(index) for index in range(5)))

    asyncio.run(concurrent())
    with sync_engine.connect() as conn:
        sequences = conn.execute(text(
            "SELECT sequence FROM run_events WHERE run_id = :id ORDER BY sequence"
        ), {"id": run_id}).scalars().all()
    assert sequences == [1, 2, 3, 4, 5]


def test_import_source_queued_run_is_never_dispatched(project, make_run, sync_engine, spawns):
    """导入运行（POST /runs/import）先以 queued 提交、稍后才 finalize。

    这个提交窗口若被 dispatcher 领走，外部产物会被当成真跑派给 runner——
    曾是独立审查发现的 MEDIUM。轮询 SQL 与显式指派路径都要挡住它。
    """
    import_run = make_run(
        state="queued",
        request_key="import-" + uuid.uuid4().hex[:8],
        project=project,
        config_snapshot={"source": "import"},
    )
    result = asyncio.run(dispatcher.dispatch_one(import_run))
    assert result.ok is False
    assert result.reason == "import_not_dispatchable"
    assert _row(sync_engine, import_run)["state"] == "queued"
    assert spawns == []

    from app.scheduler.dispatcher import _QUEUED_SQL

    with sync_engine.connect() as conn:
        candidates = [str(r[0]) for r in conn.execute(text(str(_QUEUED_SQL)), {"limit": 100})]
    assert import_run not in candidates, "轮询候选集不得包含导入运行"


def test_import_source_run_does_not_block_normal_dispatch(project, make_run, sync_engine, spawns):
    import_run = make_run(
        state="queued",
        request_key="import-" + uuid.uuid4().hex[:8],
        project=project,
        config_snapshot={"source": "import"},
    )
    make_run(state="queued", request_key=str(uuid.uuid4()), project=project)
    # 导入运行 created_at 更早（先插），轮询必须跳过它选中真跑
    result = asyncio.run(dispatcher.dispatch_one())
    assert result.ok, result.reason
    assert result.run_id != import_run
    assert _row(sync_engine, import_run)["state"] == "queued"


def test_internal_events_rejects_non_array_with_intact_message(
    client, project, sync_engine
):
    """validation_error 只收列表：传字符串曾被 ''.join 拆成单字消息。"""
    response = client.post("/api/v1/runs", json=_body(project), headers=CLIENT_HEADERS)
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    # P1-01：events 先过 fence，载荷形状校验在其后 —— 补齐合法租约与 token，
    # 让本用例继续专测 validation_error 分支。
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET state = 'running', resource_id = CAST(:rid AS uuid),"
                " profile_id = CAST(:pid AS uuid), started_at = now()"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"rid": project["resource_id"], "pid": project["profile_id"], "id": run_id},
        )
        conn.execute(
            text(
                "INSERT INTO resource_leases (id, project_id, resource_id, run_id,"
                "                             fencing_token, holder_id, expires_at)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run AS uuid), 11, 'pytest', now() + interval '120 seconds')"
            ),
            {"pid": project["project_id"], "rid": project["resource_id"], "run": run_id},
        )
    token = getattr(app.state, "control_token", "")
    rejected = client.post(
        f"/internal/runs/{run_id}/events",
        json={"fencing_token": 11, "events": "not-a-list"},
        headers={"X-Control-Token": token},
    )
    assert rejected.status_code == 400, rejected.text
    body = rejected.json()
    assert body["code"] == "validation_error"
    assert body["message"] == "events 必须是数组"


def test_requested_device_with_other_platform_fails_with_precise_reason(
    project, make_run, sync_engine
):
    """显式指定的设备与运行平台不符时，错误码要能说明"这台设备不对"。

    曾经的 available 查询带着 `platform = :platform`，跨平台设备同样查不到，
    于是与"设备全部掉线"共用 device_unavailable —— 排查时分不清是设备没了
    还是指错了设备。跨项目/设备不存在也必须保持可区分的错误码。
    """
    with sync_engine.connect() as conn:
        project_platform = conn.execute(
            text("SELECT platform FROM applications WHERE id = CAST(:id AS uuid)"),
            {"id": project["application_id"]},
        ).scalar_one()
    other_platform = "ios" if project_platform == "android" else "android"

    foreign_id = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        profile_id = conn.execute(
            text(
                "INSERT INTO resource_profiles (id, project_id, platform, name, fingerprint, spec)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :platform, :name, :fp,"
                "         '{}'::jsonb)"
                " RETURNING id"
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": project["project_id"],
                "platform": other_platform,
                "name": "profile-" + foreign_id[:8],
                "fp": uuid.uuid4().hex + uuid.uuid4().hex,
            },
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO execution_resources (id, project_id, node_id, profile_id, platform,"
                "                                resource_key, kind, status)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:nid AS uuid),"
                "         CAST(:fid AS uuid), :platform, :key, 'device', 'ready')"
            ),
            {
                "id": foreign_id,
                "pid": project["project_id"],
                "nid": project["node_id"],
                "fid": profile_id,
                "platform": other_platform,
                "key": "P3OTHER" + foreign_id[:8].upper(),
            },
        )

    # 1) 同项目、别的平台：设备确实存在，只是平台对不上
    cross_platform = make_run(
        state="queued",
        request_key="xp-" + uuid.uuid4().hex[:8],
        project=project,
        config_snapshot={"requested_resource_id": foreign_id},
    )
    result = asyncio.run(dispatcher.dispatch_one(cross_platform))
    assert result.reason == "requested_device_platform_mismatch", result.reason
    row = _row(sync_engine, cross_platform)
    assert row["state"] == "errored"
    assert row["reason_code"] == "requested_device_platform_mismatch"
    assert row["resource_id"] is None, "失败的运行不该被绑定设备"

    # 2) 根本不存在的设备：与"设备忙"和"平台不符"都要可区分
    missing = make_run(
        state="queued",
        request_key="nx-" + uuid.uuid4().hex[:8],
        project=project,
        config_snapshot={"requested_resource_id": str(uuid.uuid4())},
    )
    result = asyncio.run(dispatcher.dispatch_one(missing))
    assert result.reason == "requested_device_not_found", result.reason
    assert _row(sync_engine, missing)["state"] == "errored"

    # 3) 设备确实被别的运行占着：必须留在 queued 等下一轮，不能判死
    busy = make_run(
        state="queued",
        request_key="bs-" + uuid.uuid4().hex[:8],
        project=project,
        config_snapshot={"requested_resource_id": project["resource_id"]},
    )
    # 租约的复合外键要求 run 已绑定同一资源，所以先把占位运行绑上去。
    holder = make_run(
        state="queued",
        request_key="hd-" + uuid.uuid4().hex[:8],
        project=project,
        config_snapshot={"requested_resource_id": project["resource_id"]},
    )
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET resource_id = CAST(:rid AS uuid),"
                "       profile_id = CAST(:fid AS uuid) WHERE id = CAST(:run AS uuid)"
            ),
            {"rid": project["resource_id"], "fid": project["profile_id"], "run": holder},
        )
        conn.execute(
            text(
                "INSERT INTO resource_leases (id, project_id, resource_id, run_id, fencing_token,"
                "                            holder_id, expires_at)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run AS uuid), 1, 'pytest-holder', now() + interval '120 seconds')"
            ),
            {"pid": project["project_id"], "rid": project["resource_id"], "run": holder},
        )
    result = asyncio.run(dispatcher.dispatch_one(busy))
    assert result.reason == "resource_busy", result.reason
    assert _row(sync_engine, busy)["state"] == "queued"


def test_spawn_failure_releases_lease(project, make_run, sync_engine, monkeypatch):
    async def fail(**kwargs):
        raise OSError("pytest spawn failure")

    monkeypatch.setattr(dispatch_runner, "_spawner", fail)
    run_id = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)
    result = asyncio.run(dispatcher.dispatch_one(run_id))
    assert result.reason == "runner_spawn_failed"
    row = _row(sync_engine, run_id)
    assert row["state"] == "errored"
    assert row["outcome"] is None
    with sync_engine.connect() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM resource_leases WHERE run_id = CAST(:id AS uuid) "
            "AND released_at IS NULL"
        ), {"id": run_id}).scalar_one() == 0


def test_get_run_detail_returns_components_without_fake_columns(client, project, sync_engine):
    """GET /runs/{id} 曾查询 run_components 不存在的 started_at/ended_at 而 500（P3 遗留）。"""
    body = _body(project)
    run_id = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS).json()["id"]
    detail = client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["id"] == run_id
    assert payload["state"] == "queued"
    assert payload["components"] == []


def test_dispatch_passes_control_url_and_token(client, project, sync_engine, spawns):
    """调度 spawn 缺控制面 token 曾让 runner control_disabled、60s 判 lease_expired。"""
    response = client.post("/api/v1/runs", json=_body(project), headers=CLIENT_HEADERS)
    assert response.status_code == 201, response.text
    result = asyncio.run(dispatcher.dispatch_one(response.json()["id"]))
    assert result.ok, result.reason
    assert len(spawns) == 1
    assert spawns[0]["control_url"], spawns[0]
    assert spawns[0]["control_token"], "control_token 必须传给 runner，否则不会心跳"
