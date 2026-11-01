"""工单 04：运行生命周期、资源独占与取消（真实 PG，无真机）。

覆盖的验收点（spec §6.2 / §9.1 / §9.3，用户故事 12–15）：

- 任务修订不可变：编辑追加新修订，旧修订内容不被改写；同名不同配置 409；
  幂等键同内容复用、不同内容拒绝；readiness=validated 只能由显式验证产生；
- 草稿修订不能发起运行，已验证修订正常入队，且运行固定在被验证的那个修订上；
- 设备被占时不并发执行；指定设备不存在/平台不符/不可用分别收敛，不误判为掉线；
- 取消执行中的运行会**终止 runner 进程树**：终态、事件、租约释放都可观察，
  无残留活动租约，设备可立刻被下一次运行领取；取消幂等且终态后不 500；
- 事件按 sequence 可补投，重复投递不产生重复行。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.runner import dispatch_runner, spawn
from app.scheduler import dispatcher
from tests._p3_common import (
    CLIENT_HEADERS,
    TEST_DB,
    reset_db_engine,
    requires_db,
)
from tests._p3_common import make_run as make_run
from tests._p3_common import p3_project as project
from tests._p3_common import sync_engine as sync_engine

pytestmark = requires_db


@pytest.fixture
def client():
    # 关掉 lifespan 的后台调度，用例手动驱动 dispatcher（与 test_run_submission 同款）。
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


@pytest.fixture
def spawns(monkeypatch):
    """替换 dispatcher 的 spawn 接缝（不启动真实 runner）。"""
    reset_db_engine(TEST_DB)
    calls = []

    async def spawner(**kwargs):
        calls.append(kwargs)
        return 123456

    monkeypatch.setattr(dispatch_runner, "_spawner", spawner)
    return calls


def _body(project: dict, **overrides) -> dict:
    body = {
        "application_id": project["application_id"],
        "task_id": project["task_id"],
        "revision_id": project["revision_id"],
        "request_key": str(uuid.uuid4()),
        "platform": "android",
        "device": {"resource_id": project["resource_id"]},
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


def _active_leases(engine, run_id: str) -> list[dict]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT * FROM resource_leases WHERE run_id = CAST(:id AS uuid)"
                    " AND released_at IS NULL"
                ),
                {"id": run_id},
            ).mappings()
        ]


def _insert_lease(engine, project: dict, run_id: str, *, token: int = 7) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO resource_leases (id, project_id, resource_id, run_id,"
                "                             fencing_token, holder_id, expires_at)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run AS uuid), :token, 'pytest', now() + interval '300 seconds')"
            ),
            {
                "pid": project["project_id"],
                "rid": project["resource_id"],
                "run": run_id,
                "token": token,
            },
        )


# --------------------------------------------------------------------------- #
# 任务修订：不可变、同名冲突、幂等键、显式验证
# --------------------------------------------------------------------------- #
def _task_payload(project: dict, name: str, **overrides) -> dict:
    payload = {
        "name": name,
        "test_type": "ui",
        "platform": "android",
        "application_id": project["application_id"],
        "build_id": project["build_id"],
        "suite_version_id": project["suite_version_id"],
        "config": {"package_name": "com.example.p3", "app_version": "1.0.0"},
    }
    payload.update(overrides)
    return payload


def _task_name() -> str:
    return "冒烟-" + uuid.uuid4().hex[:8]


def test_task_edit_appends_immutable_revision_and_validation_is_explicit(
    client, project
):
    """编辑只追加新修订；readiness=validated 只能由 POST /tasks/{id}/validate 产生。"""
    name = _task_name()
    created = client.post(
        "/api/v1/tasks", json=_task_payload(project, name), headers=CLIENT_HEADERS
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["revision"]["readiness"] == "draft"
    draft_revision_id = task["revision"]["id"]

    patched = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={
            "lock_version": task["lock_version"],
            "config": {"package_name": "com.example.p3", "app_version": "2.0.0"},
        },
        headers=CLIENT_HEADERS,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["revision"]["revision"] == 2
    assert patched.json()["revision"]["readiness"] == "draft", "编辑不会顺带验证"

    revisions = client.get(
        f"/api/v1/tasks/{task['id']}/revisions", headers=CLIENT_HEADERS
    ).json()["items"]
    by_id = {item["id"]: item for item in revisions}
    assert [item["revision"] for item in revisions] == [2, 1]
    assert by_id[draft_revision_id]["config"]["app_version"] == "1.0.0", (
        "旧修订内容不得被编辑改写"
    )
    assert by_id[draft_revision_id]["readiness"] == "draft"

    validated = client.post(
        f"/api/v1/tasks/{task['id']}/validate", headers=CLIENT_HEADERS
    )
    assert validated.status_code == 200, validated.text
    body = validated.json()
    assert body["revision"]["readiness"] == "validated"
    assert body["revision"]["id"] != draft_revision_id
    history = client.get(
        f"/api/v1/tasks/{task['id']}/revisions", headers=CLIENT_HEADERS
    ).json()["items"]
    assert {item["readiness"] for item in history if item["readiness"] == "validated"} == {
        "validated"
    }
    assert [item["readiness"] for item in history if item["revision"] == 1] == ["draft"], (
        "原修订不得被回写成 validated"
    )


def test_task_name_conflict_and_idempotency_key_semantics(client, project):
    """同名不同配置 409；同键同内容复用、同键不同内容拒绝且无副作用。"""
    name = _task_name()
    key = "idem-" + uuid.uuid4().hex[:8]
    first = client.post(
        "/api/v1/tasks",
        json=_task_payload(project, name),
        params={"request_key": key},
        headers=CLIENT_HEADERS,
    )
    assert first.status_code == 201, first.text
    task_id = first.json()["id"]

    # 同名同内容：复用原任务（200），不再多一条修订
    reused = client.post("/api/v1/tasks", json=_task_payload(project, name), headers=CLIENT_HEADERS)
    assert reused.status_code == 200, reused.text
    assert reused.json()["id"] == task_id
    assert reused.json()["revision_count"] == 1

    # 同名不同配置：冲突，且不悄悄返回旧配置
    conflict = client.post(
        "/api/v1/tasks",
        json=_task_payload(
            project, name, config={"package_name": "com.example.p3", "app_version": "9.9.9"}
        ),
        headers=CLIENT_HEADERS,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "task_configuration_conflict"
    assert conflict.json()["details"]["fields"] == ["config"]

    # 同键同内容：复用首次任务
    same_key = client.post(
        "/api/v1/tasks",
        json=_task_payload(project, name),
        params={"request_key": key},
        headers=CLIENT_HEADERS,
    )
    assert same_key.status_code == 200, same_key.text
    assert same_key.json()["id"] == task_id

    # 同键不同内容：拒绝（幂等键先于业务判重），不产生新任务/修订
    different = client.post(
        "/api/v1/tasks",
        json=_task_payload(
            project, name, config={"package_name": "com.example.p3", "app_version": "3.0.0"}
        ),
        params={"request_key": key},
        headers=CLIENT_HEADERS,
    )
    assert different.status_code == 409, different.text
    assert different.json()["code"] == "idempotency_conflict"
    assert different.json()["details"]["existing_task_id"] == task_id


def test_draft_revision_cannot_start_run_and_validated_revision_enqueues(
    client, project, sync_engine
):
    """未验证修订发起运行被拒；显式验证后正常运行入队，并固定在验证过的修订上。"""
    name = _task_name()
    created = client.post(
        "/api/v1/tasks", json=_task_payload(project, name), headers=CLIENT_HEADERS
    )
    assert created.status_code == 201, created.text
    task = created.json()
    draft_revision_id = task["revision"]["id"]

    rejected = client.post(
        "/api/v1/runs",
        json={
            "application_id": project["application_id"],
            "task_id": task["id"],
            "revision_id": draft_revision_id,
            "request_key": str(uuid.uuid4()),
            "platform": "android",
            "device": {"resource_id": project["resource_id"]},
        },
        headers=CLIENT_HEADERS,
    )
    assert rejected.status_code in (409, 422), rejected.text
    assert rejected.json()["code"] != "internal_error"
    with sync_engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM test_runs WHERE revision_id = CAST(:rid AS uuid)"),
            {"rid": draft_revision_id},
        ).scalar_one() == 0, "被拒的草稿修订不得留下运行"

    validated = client.post(
        f"/api/v1/tasks/{task['id']}/validate", headers=CLIENT_HEADERS
    )
    assert validated.status_code == 200, validated.text
    validated_revision_id = validated.json()["revision"]["id"]

    accepted = client.post(
        "/api/v1/runs",
        json={
            "application_id": project["application_id"],
            "task_id": task["id"],
            "request_key": str(uuid.uuid4()),
            "platform": "android",
            "device": {"resource_id": project["resource_id"]},
        },
        headers=CLIENT_HEADERS,
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["state"] == "queued"
    assert accepted.json()["revision_id"] == validated_revision_id, (
        "省略 revision_id 时必须固定最新 validated 修订"
    )
    row = _row(sync_engine, accepted.json()["id"])
    assert str(row["revision_id"]) == validated_revision_id
    assert row["outcome"] is None


# --------------------------------------------------------------------------- #
# 状态机：终态不可改写、非 completed 的 outcome 必须为 NULL
# --------------------------------------------------------------------------- #
@pytest.fixture
def control_token(client) -> str:
    token = getattr(client.app.state, "control_token", None)
    assert token, "lifespan 应该生成 control token"
    return token


def test_terminal_run_is_immutable_and_outcome_only_on_completed(
    client, project, make_run, sync_engine, control_token
):
    """取消/出错的终态不会被 control 面改写成 completed，也不会顺手补上结论。"""
    cancelled = make_run(state="cancelled", request_key=str(uuid.uuid4()), project=project)
    headers = {"X-Control-Token": control_token}

    late_complete = client.post(
        f"/internal/runs/{cancelled}/complete",
        json={"outcome": "passed", "reason": "late_report"},
        headers=headers,
    )
    assert late_complete.status_code == 200, late_complete.text
    assert late_complete.json()["already"] is True
    assert late_complete.json()["state"] == "cancelled"
    assert late_complete.json()["outcome"] is None
    row = _row(sync_engine, cancelled)
    assert row["state"] == "cancelled"
    assert row["outcome"] is None, "非 completed 的 outcome 必须为 NULL（DB CHECK 兜底）"

    # dispatcher 只认 queued：终态/运行中都不会被"再派发"改写状态
    result = asyncio.run(dispatcher.dispatch_one(cancelled))
    assert result.ok is False
    assert result.reason == "not_queued:cancelled"
    assert _row(sync_engine, cancelled)["state"] == "cancelled"


# --------------------------------------------------------------------------- #
# 设备独占：被占时排队、不可用按原因收敛
# --------------------------------------------------------------------------- #
def test_busy_requested_device_never_runs_two_runs_concurrently(
    project, make_run, sync_engine, spawns
):
    """同一台指定设备上有活动租约时，第二个 run 必须留在 queued（不是并发跑）。"""
    run_ids = [
        make_run(
            state="queued",
            request_key=str(uuid.uuid4()),
            project=project,
            config_snapshot={"requested_resource_id": project["resource_id"]},
        )
        for _ in range(2)
    ]
    first = asyncio.run(dispatcher.dispatch_one(run_ids[0]))
    assert first.ok, first.reason

    second = asyncio.run(dispatcher.dispatch_one(run_ids[1]))
    assert second.ok is False
    assert second.reason == "resource_busy", "被占是可重试的忙，不是掉线"
    assert len(spawns) == 1, "设备被占时不得启动第二个 runner"
    row = _row(sync_engine, run_ids[1])
    assert row["state"] == "queued"
    assert row["outcome"] is None
    assert row["reason_code"] is None, "忙不得被写成终态原因"
    assert _active_leases(sync_engine, run_ids[0]) != []
    assert _active_leases(sync_engine, run_ids[1]) == []


def test_requested_device_unavailable_converges_with_its_own_reason(
    project, make_run, sync_engine, spawns
):
    """提交后设备掉线/未授权：收敛为 device_unavailable，不与 resource_busy 混用。"""
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE execution_resources SET status = 'unauthorized'"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"id": project["resource_id"]},
        )
    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        project=project,
        config_snapshot={"requested_resource_id": project["resource_id"]},
    )
    result = asyncio.run(dispatcher.dispatch_one(run_id))
    assert result.ok is False
    assert result.reason == "device_unavailable"
    row = _row(sync_engine, run_id)
    assert row["state"] == "errored"
    assert row["reason_code"] == "device_unavailable"
    assert row["outcome"] is None
    assert spawns == []


# --------------------------------------------------------------------------- #
# 事件恢复：按 sequence 补投、重复投递不产生重复行
# --------------------------------------------------------------------------- #
def test_events_replay_by_sequence_and_duplicate_delivery_adds_no_rows(
    client, project, sync_engine, control_token
):
    run_id = client.post(
        "/api/v1/runs", json=_body(project), headers=CLIENT_HEADERS
    ).json()["id"]
    headers = {"X-Control-Token": control_token}
    batch = {
        "events": [
            {
                "source_key": "runner",
                "source_event_id": f"evt-{index}",
                "kind": "stage",
                "payload": {"stage": "pytest", "progress": 40 + index},
            }
            for index in range(1, 4)
        ]
    }
    first = client.post(f"/internal/runs/{run_id}/events", json=batch, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 3

    # 网络重试：同一批事件再次投递，幂等键命中，一行都不多
    replay = client.post(f"/internal/runs/{run_id}/events", json=batch, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["accepted"] == 0
    with sync_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT count(*) AS total, count(DISTINCT sequence) AS uniq"
                "  FROM run_events WHERE run_id = CAST(:id AS uuid)"
            ),
            {"id": run_id},
        ).mappings().one()
    assert rows["total"] == rows["uniq"] == 4, "重复投递不得产生重复行"

    # 断线补投：按 sequence 分页取全量（前端 RunDrawer 的循环口径）
    page1 = client.get(
        f"/api/v1/runs/{run_id}/events", params={"after": 0, "limit": 2}
    ).json()
    assert [item["sequence"] for item in page1["items"]] == [1, 2]
    assert page1["next_after"] == 2
    assert page1["has_more"] is True
    page2 = client.get(
        f"/api/v1/runs/{run_id}/events",
        params={"after": page1["next_after"], "limit": 2},
    ).json()
    assert [item["sequence"] for item in page2["items"]] == [3, 4]
    assert page2["has_more"] is False
    assert page2["next_after"] == 4

    # WS 快照给出 last_sequence；断线重连后从这里补投应当已追平
    with client.websocket_connect(f"/api/v1/ws/runs/{run_id}") as socket:
        snapshot = socket.receive_json()
    assert snapshot["type"] == "snapshot"
    last_sequence = snapshot["run"]["last_sequence"]
    assert last_sequence == 4
    caught_up = client.get(
        f"/api/v1/runs/{run_id}/events", params={"after": last_sequence}
    ).json()
    assert caught_up["items"] == []
    assert caught_up["has_more"] is False


def test_runner_exit_after_accepted_cancel_converges_to_cancelled_not_errored(
    client, project, make_run, sync_engine, monkeypatch, tmp_path
):
    """取消已受理后 runner 自行退出：兜底收敛必须是 cancelled，不是 errored。

    正常路径里取消路由自己会 finalize；但 runner 也可能先从 heartbeat 看到取消、
    自己退出（或 API 重启过、只能靠进程退出兜底）。退出码 1 在"没有取消事实"时
    应该映射成 errored(runner_exit_1)；有取消事实时必须写成 cancelled + outcome NULL，
    否则用户点过的取消会被显示成"运行出错"。
    """
    run_id = make_run(
        state="running",
        request_key=str(uuid.uuid4()),
        project=project,
        config_snapshot={"requested_resource_id": project["resource_id"]},
    )
    _insert_lease(sync_engine, project, run_id)
    with sync_engine.begin() as conn:
        conn.execute(
            text("UPDATE test_runs SET cancel_requested_at = now() WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        )

    script = tmp_path / "exiting_runner.py"
    script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    log_path = tmp_path / "exiting.log"
    monkeypatch.setattr(
        spawn,
        "build_spec",
        lambda **kwargs: spawn.SpawnSpec(
            argv=[sys.executable, str(script)],
            env=dict(os.environ),
            cwd=str(tmp_path),
            log_path=log_path,
            stdout_path=log_path,
        ),
    )

    async def run_until_terminal() -> tuple[str | None, str | None]:
        from app.db import get_sessionmaker

        await spawn.spawn_runner(
            run_id=run_id,
            config={},
            lease={"serial": "P3STANDIN", "fencing_token": 7},
            start_tail=True,
        )
        sessionmaker = get_sessionmaker()
        for _ in range(200):
            async with sessionmaker() as session:
                row = (
                    await session.execute(
                        text("SELECT state, outcome FROM test_runs WHERE id = CAST(:id AS uuid)"),
                        {"id": run_id},
                    )
                ).mappings().one()
            if row["state"] in ("completed", "errored", "cancelled"):
                return str(row["state"]), row["outcome"]
            await asyncio.sleep(0.05)
        return None, None

    state, outcome = asyncio.run(run_until_terminal())
    assert state == "cancelled", "已受理的取消不能被退出兜底写成 errored"
    assert outcome is None
    assert _active_leases(sync_engine, run_id) == []


# --------------------------------------------------------------------------- #
# 取消：真的停下来
# --------------------------------------------------------------------------- #
_STAND_IN_RUNNER = """
import os
import subprocess
import sys
import time

# 一个「假 runner」进程树：父进程代表 runner，子进程代表它拉起的 pytest/adb。
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(f"{os.getpid()} {child.pid}")
time.sleep(600)
"""


def _wait_until(predicate, *, timeout: float = 15.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        return str(pid) in (completed.stdout or "")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_cancel_running_run_kills_process_tree_releases_lease_and_frees_device(
    client, project, make_run, sync_engine, monkeypatch, spawns, tmp_path
):
    """取消 running 的 run：进程树终止 + 终态/事件/租约/设备再领取全部可观察。

    这里用真实子进程树当 runner 替身（不走 adb / pytest），取消必须 taskkill /T
    才能同时带走子进程；只杀父进程会留下孤儿继续占设备。
    """
    run_id = make_run(
        state="running",
        request_key=str(uuid.uuid4()),
        project=project,
        config_snapshot={"requested_resource_id": project["resource_id"]},
    )
    _insert_lease(sync_engine, project, run_id)

    script = tmp_path / "stand_in_runner.py"
    script.write_text(_STAND_IN_RUNNER, encoding="utf-8")
    pid_file = tmp_path / "runner.pids"
    log_path = tmp_path / "runner.log"
    monkeypatch.setattr(
        spawn,
        "build_spec",
        lambda **kwargs: spawn.SpawnSpec(
            argv=[sys.executable, str(script), str(pid_file)],
            env=dict(os.environ),
            cwd=str(tmp_path),
            log_path=log_path,
            stdout_path=log_path,
        ),
    )
    asyncio.run(
        spawn.spawn_runner(
            run_id=run_id,
            config={},
            lease={"serial": "P3STANDIN", "fencing_token": 7},
            start_tail=False,
        )
    )
    assert _wait_until(pid_file.exists), "runner 替身没能启动"
    runner_pid, child_pid = (int(part) for part in pid_file.read_text().split())
    assert _pid_alive(runner_pid) and _pid_alive(child_pid)

    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "cancelled"

    # 1) 进程树真的消失了（父进程 + 它拉起的子进程）
    assert _wait_until(
        lambda: not _pid_alive(runner_pid) and not _pid_alive(child_pid)
    ), "取消必须终止 runner 进程树，不能留下孤儿占设备"

    # 2) 终态可观察：cancelled，outcome 必须为 NULL（取消不是测试结论）
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["state"] == "cancelled"
    assert detail["outcome"] is None
    assert detail["cancel_requested"] is True
    row = _row(sync_engine, run_id)
    assert row["ended_at"] is not None
    assert row["reason_code"] == "cancel_requested"

    # 3) 事件可观察：受理事实 + 收敛事实
    events = client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    kinds = [event["event_type"] for event in events]
    assert "cancel_requested" in kinds
    finish = [event for event in events if event["event_type"] == "finish"][-1]
    assert finish["payload"]["state"] == "cancelled"
    assert finish["payload"]["outcome"] is None

    # 4) 无残留活动租约
    assert _active_leases(sync_engine, run_id) == []
    with sync_engine.connect() as conn:
        reason = conn.execute(
            text(
                "SELECT release_reason FROM resource_leases WHERE run_id = CAST(:id AS uuid)"
            ),
            {"id": run_id},
        ).scalar_one()
    assert reason == "cancel_requested"

    # 5) 取消幂等：重复取消是 409（不是 500），不写第二条事实
    again = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "state_conflict"

    # 6) 设备立即可以被下一次运行领取（不用等 reconciler 的 60s 陈旧判定）
    next_run = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        project=project,
        config_snapshot={"requested_resource_id": project["resource_id"]},
    )
    result = asyncio.run(dispatcher.dispatch_one(next_run))
    assert result.ok, result.reason
    assert len(spawns) == 1
    assert _row(sync_engine, next_run)["state"] == "dispatching"
    assert str(_row(sync_engine, next_run)["resource_id"]) == project["resource_id"]
    assert len(_active_leases(sync_engine, next_run)) == 1


def test_cancel_running_run_registers_artifacts_already_on_disk(
    client, project, make_run, sync_engine, monkeypatch, tmp_path
):
    """取消也要登记已落盘的产物：joint 被取消时 report.json/采集窗口已经写出了。

    取消路径曾漏传 artifacts_dir，导致"采集窗口确实发生过"这件事在报告页整块
    丢失（与 spawn._finalize_after_exit 的口径不一致）。
    """
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    artifacts_root = settings.artifacts_dir
    run_id = make_run(
        state="running",
        request_key=str(uuid.uuid4()),
        project=project,
        config_snapshot={"requested_resource_id": project["resource_id"]},
    )
    _insert_lease(sync_engine, project, run_id)
    run_dir = artifacts_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "collectWindow": {
                    "collect_started_at": "2026-10-25T12:00:00+00:00",
                    "collect_stopped_at": "2026-10-25T12:01:00+00:00",
                    "ui": {
                        "started_at": "2026-10-25T12:00:05+00:00",
                        "ended_at": "2026-10-25T12:00:55+00:00",
                        "timeout_s": 600,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "cancelled"

    keys = [item["logical_key"] for item in client.get(
        f"/api/v1/runs/{run_id}/artifacts"
    ).json()["items"]]
    assert "report.json" in keys, "取消也必须登记取消前已写出的产物"

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["collectWindow"]["ui"]["timeout_s"] == 600
    assert report["collectWindow"]["collect_started_at"].startswith("2026-10-25T12:00:00")


def test_terminate_run_process_reports_whether_a_process_was_really_killed(monkeypatch):
    """`runner_terminated` 不能撒谎：taskkill 失败/没有 pid 都不是"杀掉了"。

    Windows 分支按 taskkill 退出码判定；随后观测到进程退出也算杀掉。
    """
    spawn_mod = spawn

    class _Completed:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    async def _pid(run_id: str) -> int:
        return 4321

    # 1) 进程表与 ack 事件里都没有 pid：没有可杀的东西
    async def _no_pid(run_id: str) -> None:
        return None

    monkeypatch.setattr(spawn_mod, "_pid_from_events", _no_pid)
    spawn_mod._PROCESSES.pop("no-such-run", None)
    assert asyncio.run(spawn_mod.terminate_run_process("no-such-run")) is False

    # 2) taskkill 返回非 0（进程已消失/无权限）：不能报告成已终止
    monkeypatch.setattr(spawn_mod, "_pid_from_events", _pid)
    monkeypatch.setattr(
        spawn_mod.subprocess, "run", lambda *a, **k: _Completed(returncode=128)
    )
    if os.name == "nt":
        assert asyncio.run(spawn_mod.terminate_run_process("taskkill-failed")) is False

    # 3) taskkill 返回 0：真的杀了
    monkeypatch.setattr(
        spawn_mod.subprocess, "run", lambda *a, **k: _Completed(returncode=0)
    )
    if os.name == "nt":
        assert asyncio.run(spawn_mod.terminate_run_process("taskkill-ok")) is True

    # 4) taskkill 说失败，但随后观测到进程退出：仍算杀掉（退出是更硬的证据）
    class _FakeProcess:
        pid = 4321
        returncode = None

        async def wait(self) -> int:
            self.returncode = 1
            return 1

        def kill(self) -> None:  # pragma: no cover - Windows 分支不走
            self.returncode = 1

    fake = _FakeProcess()
    spawn_mod._PROCESSES["observed-exit"] = fake
    monkeypatch.setattr(
        spawn_mod.subprocess, "run", lambda *a, **k: _Completed(returncode=128)
    )
    assert asyncio.run(spawn_mod.terminate_run_process("observed-exit")) is True
    assert "observed-exit" not in spawn_mod._PROCESSES
