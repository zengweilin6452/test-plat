"""工单 08：运行生命周期（真实 PG）。

覆盖的验收点（spec §6.2 / §9.1 / §9.3、AC-LIVE-01、AC-CONTRACT-03）：

- 提交必须显式给出应用、任务、幂等键；省略 revision_id 时由服务端解析**一次**
  并固定，响应回传实际 revision_id；
- 跨应用/跨项目的任务、修订、父运行一律拒绝；非 validated 修订不能发起运行；
- overrides / source_dir / test_paths / fake_outcome / source 不能改写固定输入；
- 取消先受理（202）后收敛：queued 直接落 cancelled；dispatching/running/finalizing
  由工单 04 起主动终止 runner 进程树并当场收敛（终态/事件/租约释放可见），
  与 runner 真实完成竞争时不伪造 cancelled；
- 取消事实持久化在列上（0006），不因事件分页/断线补拉而丢失；
- 事件分页给出 next_after / has_more，超过 500 条仍能补拉；
- 列表、详情、WS 快照共用同一进度投影；WS 断线重连能重放终态。
"""

from __future__ import annotations

import os
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.domain import events as events_mod
from app.main import app
from app.routers import runs as runs_router
from tests._p3_common import (
    CLIENT_HEADERS,
    TEST_DB,
    make_project,
    reset_db_engine,
    requires_db,
)
from tests._p3_common import make_run as make_run
from tests._p3_common import p3_project as project
from tests._p3_common import sync_engine as sync_engine

pytestmark = requires_db


@pytest.fixture
def client():
    # 与 test_run_submission 同款：关掉 lifespan 的后台调度，否则它会领走
    # 用例刚建的 queued run，取消/分页断言就失去确定性。
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


@pytest.fixture
def control_token(client) -> str:
    token = getattr(client.app.state, "control_token", None)
    assert token, "lifespan 应该生成 control token"
    return token


def _body(project: dict, **overrides) -> dict:
    body = {
        "application_id": project["application_id"],
        "task_id": project["task_id"],
        "request_key": str(uuid.uuid4()),
        "platform": "android",
    }
    body.update(overrides)
    return body


def _row(engine, run_id: str) -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("SELECT * FROM test_runs WHERE id = CAST(:id AS uuid)"), {"id": run_id}
            )
            .mappings()
            .one()
        )


def _run_count(engine, project_id: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM test_runs WHERE project_id = CAST(:pid AS uuid)"),
                {"pid": project_id},
            ).scalar_one()
        )


def _add_draft_revision(engine, project: dict) -> str:
    revision_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO task_revisions (id, project_id, application_id, task_id,"
                "                           revision, environment_id, test_type,"
                "                           readiness, config, created_by)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         CAST(:tid AS uuid), 2, CAST(:eid AS uuid), 'ui', 'draft',"
                "         '{}'::jsonb, 'pytest')"
            ),
            {
                "id": revision_id,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "tid": project["task_id"],
                "eid": project["environment_id"],
            },
        )
    return revision_id


# --------------------------------------------------------------------------- #
# 提交：显式身份 + 固定修订 + 固定输入
# --------------------------------------------------------------------------- #


def test_submission_requires_application_task_and_request_key(client, project):
    missing_application = _body(project)
    missing_application.pop("application_id")
    response = client.post("/api/v1/runs", json=missing_application, headers=CLIENT_HEADERS)
    # 请求形状/策略拒绝沿用 api-design.md 的 400 validation_error；
    # 422 留给"修订未就绪"这类语义问题（readiness_incomplete）
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "validation_error"

    missing_task = _body(project)
    missing_task.pop("task_id")
    response = client.post("/api/v1/runs", json=missing_task, headers=CLIENT_HEADERS)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "readiness_incomplete"

    missing_key = _body(project)
    missing_key.pop("request_key")
    response = client.post("/api/v1/runs", json=missing_key, headers=CLIENT_HEADERS)
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "validation_error"


def test_omitted_revision_is_resolved_once_and_returned(client, project, sync_engine):
    body = _body(project)
    response = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS)
    assert response.status_code == 201, response.text
    created = response.json()
    # 省略 revision_id 时由服务端解析并固定，响应必须回传实际值
    assert created["revision_id"] == project["revision_id"]
    assert created["task_id"] == project["task_id"]
    assert _row(sync_engine, created["id"])["revision_id"] == uuid.UUID(project["revision_id"])

    # 重放同一 request_key：返回既有运行的 revision，不重新解析
    replay = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS)
    assert replay.status_code == 200, replay.text
    assert replay.json()["duplicate"] is True
    assert replay.json()["revision_id"] == project["revision_id"]


def test_draft_revision_cannot_start_a_run(client, project, sync_engine):
    draft_id = _add_draft_revision(sync_engine, project)
    response = client.post(
        "/api/v1/runs",
        json=_body(project, revision_id=draft_id),
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "readiness_incomplete"
    assert _run_count(sync_engine, project["project_id"]) == 0

    # 只给 task_id 时跳过草稿，固定到已验证修订
    resolved = client.post("/api/v1/runs", json=_body(project), headers=CLIENT_HEADERS)
    assert resolved.status_code == 201, resolved.text
    assert resolved.json()["revision_id"] == project["revision_id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("overrides", {"timeout_s": 1}),
        ("source_dir", "C:/tmp/suite"),
        ("test_paths", ["tests/test_other.py"]),
        ("fake_outcome", "passed"),
        ("source", "import"),
    ],
)
def test_fixed_inputs_cannot_be_overridden(client, project, sync_engine, field, value):
    body = _body(project, **{field: value})
    response = client.post("/api/v1/runs", json=body, headers=CLIENT_HEADERS)
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "validation_error"
    assert field in response.text
    assert _run_count(sync_engine, project["project_id"]) == 0


def test_parent_run_must_belong_to_same_application(client, project, make_run, sync_engine):
    other = make_project(sync_engine)
    other_run = make_run(state="completed", request_key=str(uuid.uuid4()), project=other)
    response = client.post(
        "/api/v1/runs",
        json=_body(project, parent_run_id=other_run),
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------- #
# 取消：先受理后收敛
# --------------------------------------------------------------------------- #


def test_cancel_queued_run_converges_to_cancelled(client, project, sync_engine):
    created = client.post("/api/v1/runs", json=_body(project), headers=CLIENT_HEADERS)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "cancelled"
    assert body["cancel_requested"] is True
    assert body["cancel_requested_at"]

    row = _row(sync_engine, run_id)
    assert row["state"] == "cancelled"
    assert row["cancel_requested_at"] is not None
    assert row["ended_at"] is not None
    assert row["outcome"] is None, "cancelled 不得伪造通过/失败结论"

    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "cancelled"
    assert detail["cancel_requested"] is True
    assert detail["stage"] == 4

    events = client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    assert [event["event_type"] for event in events] == ["queued", "cancel_requested"]

    # 终态不受理：重复取消是 409，而不是再写一条事实
    again = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "state_conflict"


def test_cancel_running_run_converges_to_cancelled_without_faking_outcome(
    client, project, make_run, sync_engine
):
    """运行中取消必须真的收敛，但绝不把取消写成测试结论。

    工单 04 起升级：取消 running 会主动终止 runner 进程树并立即收敛，
    不再只写 `cancel_requested_at` 等心跳/60s 陈旧判定（否则 vendor 卡死时
    设备会被长期占用）。进程树终止与设备再领取的端到端证据见
    `test_issue04_run_lifecycle.py`。
    """
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))

    first = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert first.status_code == 202, first.text
    assert first.json()["state"] == "cancelled", "取消必须收敛，不能只留下事实"
    assert first.json()["outcome"] is None, "取消不是测试结论"
    assert first.json()["cancel_requested"] is True
    first_at = first.json()["cancel_requested_at"]
    assert first_at

    row = _row(sync_engine, run_id)
    assert row["state"] == "cancelled"
    assert row["outcome"] is None
    assert row["cancel_requested_at"] is not None

    # 重复取消是 409 conflict（幂等语义），不是 500，也不再写第二条事实
    second = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "state_conflict"
    assert _row(sync_engine, run_id)["cancel_requested_at"] == row["cancel_requested_at"]

    # 取消事实已受理后 runner 恰好上报完成：终态保持真实完成态，不伪造 cancelled
    raced = make_run(state="running", request_key=str(uuid.uuid4()))
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET cancel_requested_at = now()"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"id": raced},
        )
        conn.execute(
            text(
                "UPDATE test_runs SET state = 'completed', outcome = 'passed',"
                " ended_at = now() WHERE id = CAST(:id AS uuid)"
            ),
            {"id": raced},
        )
    detail = client.get(f"/api/v1/runs/{raced}").json()
    assert detail["state"] == "completed"
    assert detail["outcome"] == "passed"
    assert detail["cancel_requested"] is True

    after_terminal = client.post(f"/api/v1/runs/{raced}/cancel", headers=CLIENT_HEADERS)
    assert after_terminal.status_code == 409, after_terminal.text


def test_cancel_after_terminal_is_conflict(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "state_conflict"
    row = _row(sync_engine, run_id)
    assert row["cancel_requested_at"] is None, "终态运行不得被写入取消事实"


def test_heartbeat_reports_cancel_from_column(
    client, project, control_token, make_run, sync_engine
):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))
    headers = {"X-Control-Token": control_token}
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO resource_leases (id, project_id, resource_id, run_id,"
                "                             fencing_token, holder_id, expires_at)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run AS uuid), 7, 'pytest', now() + interval '5 seconds')"
            ),
            {"pid": project["project_id"], "rid": project["resource_id"], "run": run_id},
        )

    before = client.post(
        f"/internal/runs/{run_id}/heartbeat",
        json={"fencing_token": 7, "pid": 1},
        headers=headers,
    )
    assert before.status_code == 200, before.text
    assert before.json() == {"ok": True, "cancel": False, "fence_ok": True}
    # 心跳必须真的续租：否则执行中的运行会被 reconciler 当成失联回收
    with sync_engine.connect() as conn:
        remaining = conn.execute(
            text(
                "SELECT extract(epoch FROM expires_at - now()) FROM resource_leases"
                " WHERE run_id = CAST(:run AS uuid) AND released_at IS NULL"
            ),
            {"run": run_id},
        ).scalar_one()
    assert remaining > 60, remaining

    client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    after = client.post(
        f"/internal/runs/{run_id}/heartbeat",
        json={"fencing_token": 7, "pid": 1},
        headers=headers,
    )
    assert after.status_code == 200, after.text
    assert after.json()["cancel"] is True, "runner 必须能从心跳感知取消受理"


def test_repeated_heartbeats_with_static_progress_stay_distinct(
    client, project, control_token, make_run, sync_engine, monkeypatch
):
    """回归：采集窗口内 progress/stage 不变时，周期性心跳不得被幂等键塌缩成一条。

    reconciler 用「最近一条 heartbeat 事件」判心跳超时（reconciler.py _STALE_SQL）。
    若幂等键只含 (pid, progress, stage)，性能采集窗口里这三个值长时间不变，8 次
    心跳只会落 1 条事件，60s 后仍在心跳的健康运行被误回收成 lease_expired
    （真机 RUN-0517/0518）。
    """
    from app.routers import internal as internal_router

    run_id = make_run(state="running", request_key=str(uuid.uuid4()))
    headers = {"X-Control-Token": control_token}
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO resource_leases (id, project_id, resource_id, run_id,"
                "                             fencing_token, holder_id, expires_at)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run AS uuid), 9, 'pytest', now() + interval '120 seconds')"
            ),
            {"pid": project["project_id"], "rid": project["resource_id"], "run": run_id},
        )
    payload = {"fencing_token": 9, "pid": 4242, "progress": 40, "stage": 2}

    def _beat_count() -> int:
        with sync_engine.connect() as conn:
            return conn.execute(
                text(
                    "SELECT count(*) FROM run_events"
                    " WHERE run_id = CAST(:run AS uuid) AND event_type = 'heartbeat'"
                ),
                {"run": run_id},
            ).scalar_one()

    monkeypatch.setattr(internal_router, "_heartbeat_bucket", lambda: 100)
    assert (
        client.post(
            f"/internal/runs/{run_id}/heartbeat", json=payload, headers=headers
        ).status_code
        == 200
    )
    monkeypatch.setattr(internal_router, "_heartbeat_bucket", lambda: 101)
    assert (
        client.post(
            f"/internal/runs/{run_id}/heartbeat", json=payload, headers=headers
        ).status_code
        == 200
    )
    assert _beat_count() == 2, "静态 progress/stage 的周期性心跳必须各记一条事件"

    # 同一时间桶内的网络重试仍应幂等，不制造重复事件
    assert (
        client.post(
            f"/internal/runs/{run_id}/heartbeat", json=payload, headers=headers
        ).status_code
        == 200
    )
    assert _beat_count() == 2, "同一时间桶内的心跳重试必须幂等去重"


# --------------------------------------------------------------------------- #
# 事件分页与投影一致性（AC-CONTRACT-03 / AC-LIVE-01）
# --------------------------------------------------------------------------- #


def _bulk_events(engine, project_id: str, run_id: str, *, first: int, last: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO run_events (id, project_id, run_id, sequence, source_key,"
                "                        source_event_id, event_type, payload, occurred_at)"
                " SELECT gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid), g,"
                "        'runner', 'bulk-' || g, 'stage',"
                "        '{\"stage\": \"pytest\"}'::jsonb, now()"
                "   FROM generate_series(CAST(:first AS integer), CAST(:last AS integer)) AS g"
            ),
            {"pid": project_id, "rid": run_id, "first": first, "last": last},
        )


def test_events_pagination_after_500_keeps_cancel_fact(client, project, sync_engine):
    created = client.post("/api/v1/runs", json=_body(project), headers=CLIENT_HEADERS)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    # 1 = queued，2..621 = 620 条 runner 阶段事件，622 = cancel_requested
    _bulk_events(sync_engine, project["project_id"], run_id, first=2, last=621)

    cancelled = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert cancelled.status_code == 202, cancelled.text

    first_page = client.get(f"/api/v1/runs/{run_id}/events", params={"limit": 500}).json()
    assert first_page["total"] == 500
    assert first_page["after"] == 0
    assert first_page["next_after"] == 500
    assert first_page["has_more"] is True
    assert all(event["event_type"] != "cancel_requested" for event in first_page["items"])

    second_page = client.get(
        f"/api/v1/runs/{run_id}/events",
        params={"after": first_page["next_after"], "limit": 500},
    ).json()
    assert second_page["has_more"] is False
    assert second_page["next_after"] == 622
    assert second_page["items"][-1]["event_type"] == "cancel_requested"

    # 重复补拉同一段不产生重复：起点固定、按 sequence 去重
    replay = client.get(f"/api/v1/runs/{run_id}/events", params={"limit": 500}).json()
    assert [event["sequence"] for event in replay["items"]] == [
        event["sequence"] for event in first_page["items"]
    ]

    # 取消事实不依赖事件分页：详情与列表都读列
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["cancel_requested"] is True
    assert detail["state"] == "cancelled"
    assert detail["last_sequence"] == 622
    assert detail["progress"] == 80


def test_list_detail_and_ws_share_progress_projection(client, project, make_run, sync_engine):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))
    _bulk_events(sync_engine, project["project_id"], run_id, first=1, last=1)

    detail = client.get(f"/api/v1/runs/{run_id}").json()
    listed = next(
        item
        for item in client.get("/api/v1/runs", params={"limit": 200}).json()["items"]
        if item["id"] == run_id
    )
    assert detail["progress"] == 80
    assert listed["progress"] == detail["progress"]
    assert detail["stage"] == 2

    with client.websocket_connect(f"/api/v1/ws/runs/{run_id}") as socket:
        snapshot = socket.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["run"]["progress"] == detail["progress"]
        assert snapshot["run"]["stage"] == detail["stage"]
        assert snapshot["run"]["last_sequence"] == detail["last_sequence"]
        assert snapshot["run"]["cancel_requested"] is False


def test_ws_live_finish_and_reconnect_replays_terminal(client, project, make_run, sync_engine):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))

    with client.websocket_connect(f"/api/v1/ws/runs/{run_id}") as socket:
        snapshot = socket.receive_json()
        assert snapshot["run"]["state"] == "running"
        # 执行侧收敛（真实完成），WS 轮询必须在 2s 内推出终态
        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE test_runs SET state = 'completed', outcome = 'passed',"
                    " ended_at = now() WHERE id = CAST(:id AS uuid)"
                ),
                {"id": run_id},
            )
        frames = []
        while True:
            frame = socket.receive_json()
            frames.append(frame)
            if frame["type"] == "finished":
                break
        assert {"type": "state", "state": "completed"} in [
            {"type": f["type"], "state": f.get("state")} for f in frames
        ]
        assert frames[-1] == {"type": "finished", "state": "completed", "outcome": "passed"}

    # 断线重连：终态从快照重放，事件序列不从头再推一遍
    with client.websocket_connect(f"/api/v1/ws/runs/{run_id}") as socket:
        snapshot = socket.receive_json()
        assert snapshot["run"]["state"] == "completed"
        assert snapshot["run"]["outcome"] == "passed"
        assert snapshot["run"]["last_sequence"] >= 0
        finished = socket.receive_json()
        assert finished == {"type": "finished", "state": "completed", "outcome": "passed"}
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()


def test_stage_weights_match_sql_projection():
    """SQL 投影与 domain/events.STAGE_WEIGHTS 是同一份口径，改一处必须改两处。"""
    sql_weights = {
        name: int(weight)
        for name, weight in re.findall(
            r"WHEN '(\w+)' THEN (\d+)", runs_router._EVENT_PROGRESS_SQL
        )
    }
    assert sql_weights == dict(events_mod.STAGE_WEIGHTS)
