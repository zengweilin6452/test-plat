"""P1-01：Runner 写端点的 fencing token 强制校验（真实 PostgreSQL）。

验收对应（任务书 P1-01）：
- 缺少 token / 错误 token / 垃圾 token：一律 409 fence_mismatch，且不产生
  任何副作用（不续租、不落心跳事件、不改 run 状态、不落运行事件）；
- 当前有效 token：允许；
- 无 token 的 fence 查询不得泄露当前 token（错误响应里没有 expected）；
- 旧 Runner（A，token 已过期）在 Runner B 重新领取租约后，所有写操作被拒，
  且 B 的租约不被 A 的心跳续命；B 用自己的 token 正常操作；
- 终态 Run 保留幂等重试语义（already=true），但不接受状态改写。

原缺陷：verify_fence 默认 require_token=False，缺 token 的请求按"不校验"
放行（ok=True, checked=False）；fail 只在 token 非空时校验；extend_lease 在
token 为 NULL 时按 run_id 续租当前活动租约——三者叠加等于"不带 token 就能
绕过 fencing"。另外 fence_mismatch 的 details 曾回显 expected（当前租约的
token），旧 Runner 拿旧 token 被拒时能从 409 里学到新 token 再冒用。
"""

from __future__ import annotations

import os
import uuid

import pytest
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests._p3_common import (
    CLIENT_HEADERS,
    TEST_DB,
    async_session,
    requires_db,
    reset_db_engine,
)
from tests._p3_common import make_run as make_run
from tests._p3_common import p3_project as project  # noqa: F401 - fixture 复用
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - fixture 复用

pytestmark = requires_db


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    reset_db_engine(TEST_DB)


@pytest.fixture
def control_token(client) -> str:
    token = getattr(client.app.state, "control_token", None)
    assert token, "lifespan 应该生成 control token"
    return token


def _headers(control_token: str) -> dict[str, str]:
    return {"X-Control-Token": control_token}


def _to_running_with_lease(sync_engine, project: dict, run_id: str, token: int) -> None:
    """把 run 推到 running 并插入一条持有 token 的活动租约。

    复合外键要求 resource_leases.(project_id, run_id, resource_id) 与
    test_runs 的绑定一致，所以先绑定 resource 再插租约。fence_counter 同步
    到 token：acquire_lease 的真实序列是"bump 计数器 -> 用新值插租约"，
    不同步的话后续重新领取会从小计数器重新开始（旧 token 反而大于新 token）。
    """
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET state = 'running',"
                " resource_id = CAST(:rid AS uuid), profile_id = CAST(:pid AS uuid),"
                " started_at = now()"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"rid": project["resource_id"], "pid": project["profile_id"], "id": run_id},
        )
        conn.execute(
            text(
                "UPDATE execution_resources SET fence_counter = :token"
                " WHERE id = CAST(:rid AS uuid)"
            ),
            {"rid": project["resource_id"], "token": token},
        )
        conn.execute(
            text(
                "INSERT INTO resource_leases (id, project_id, resource_id, run_id,"
                "                             fencing_token, holder_id, expires_at)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run AS uuid), :token, 'runner-a',"
                "         now() + interval '120 seconds')"
            ),
            {
                "pid": project["project_id"],
                "rid": project["resource_id"],
                "run": run_id,
                "token": token,
            },
        )


def _lease_remaining(sync_engine, run_id: str) -> float:
    with sync_engine.connect() as conn:
        return float(
            conn.execute(
                text(
                    "SELECT extract(epoch FROM expires_at - now())"
                    " FROM resource_leases WHERE run_id = CAST(:run AS uuid)"
                    " AND released_at IS NULL"
                ),
                {"run": run_id},
            ).scalar_one()
        )


def _event_count(sync_engine, run_id: str, event_type: str) -> int:
    with sync_engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM run_events"
                    " WHERE run_id = CAST(:run AS uuid) AND event_type = :kind"
                ),
                {"run": run_id, "kind": event_type},
            ).scalar_one()
        )


def _run_state(sync_engine, run_id: str) -> str:
    with sync_engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT state FROM test_runs WHERE id = CAST(:id AS uuid)"),
                {"id": run_id},
            ).scalar_one()
        )


# --------------------------------------------------------------------------- #
# 心跳：缺 token / 错 token / 垃圾 token 一律拒绝，无副作用
# --------------------------------------------------------------------------- #
def test_heartbeat_without_token_is_rejected_without_side_effects(
    client, project, sync_engine, control_token, make_run
):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 7)

    before = _lease_remaining(sync_engine, run_id)
    response = client.post(
        f"/internal/runs/{run_id}/heartbeat",
        json={"pid": 1},
        headers=_headers(control_token),
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "fence_mismatch"
    assert "expected" not in (response.json().get("details") or {}), (
        "错误响应不得回显当前租约的 token"
    )
    after = _lease_remaining(sync_engine, run_id)
    assert after <= before + 2, "无效心跳不得给租约续期"
    assert _event_count(sync_engine, run_id, "heartbeat") == 0, (
        "无效心跳不得产生新的运行事件"
    )


def test_heartbeat_with_wrong_or_garbage_token_is_rejected(
    client, project, sync_engine, control_token, make_run
):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 7)

    for bad in (999, "not-a-number", 7.9, True, None):
        response = client.post(
            f"/internal/runs/{run_id}/heartbeat",
            json={"pid": 1, "fencing_token": bad},
            headers=_headers(control_token),
        )
        assert response.status_code == 409, (bad, response.text)
    assert _event_count(sync_engine, run_id, "heartbeat") == 0
    assert _run_state(sync_engine, run_id) == "running"


def test_heartbeat_with_current_token_extends_and_reports_cancel(
    client, project, sync_engine, control_token, make_run
):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 7)

    response = client.post(
        f"/internal/runs/{run_id}/heartbeat",
        json={"pid": 1, "progress": 40, "stage": 2, "fencing_token": 7},
        headers=_headers(control_token),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "cancel": False, "fence_ok": True}
    assert _lease_remaining(sync_engine, run_id) > 60, "有效心跳必须真的续租"
    assert _event_count(sync_engine, run_id, "heartbeat") == 1

    cancelled = client.post(
        f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS
    )
    assert cancelled.status_code == 202, cancelled.text
    # 取消已把 run 收敛成终态并释放租约：此后旧 runner 的心跳是 409
    # fence_mismatch —— runner 侧把它当 fence_lost 立即退出，停止信号比
    # cancel 标志更强（无论租约是被取消收敛还是已转手，都必须停）。
    response = client.post(
        f"/internal/runs/{run_id}/heartbeat",
        json={"pid": 1, "fencing_token": 7},
        headers=_headers(control_token),
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "fence_mismatch"


# --------------------------------------------------------------------------- #
# complete / fail：缺 token 与错 token 都不能收敛别人的 run
# --------------------------------------------------------------------------- #
def test_complete_requires_current_token(client, project, sync_engine, control_token, make_run):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 7)

    for payload in (
        {"outcome": "passed"},
        {"outcome": "passed", "fencing_token": 999},
    ):
        response = client.post(
            f"/internal/runs/{run_id}/complete",
            json=payload,
            headers=_headers(control_token),
        )
        assert response.status_code == 409, (payload, response.text)
        assert response.json()["code"] == "fence_mismatch"
        assert "expected" not in (response.json().get("details") or {})
    assert _run_state(sync_engine, run_id) == "running", (
        "无效 complete 不得改变 run 状态"
    )

    ok = client.post(
        f"/internal/runs/{run_id}/complete",
        json={"outcome": "passed", "fencing_token": 7},
        headers=_headers(control_token),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "completed"


def test_fail_requires_current_token(client, project, sync_engine, control_token, make_run):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 7)

    for payload in (
        {"error_code": "runner_failed", "message": "boom"},
        {"error_code": "runner_failed", "fencing_token": 999},
    ):
        response = client.post(
            f"/internal/runs/{run_id}/fail",
            json=payload,
            headers=_headers(control_token),
        )
        assert response.status_code == 409, (payload, response.text)
    assert _run_state(sync_engine, run_id) == "running", (
        "无 token 的 fail 曾能直接把 run 打成 errored，必须拒绝"
    )

    ok = client.post(
        f"/internal/runs/{run_id}/fail",
        json={"error_code": "runner_failed", "fencing_token": 7},
        headers=_headers(control_token),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "errored"


# --------------------------------------------------------------------------- #
# fence 查询：缺 token 不泄露当前 token
# --------------------------------------------------------------------------- #
def test_fence_query_without_token_does_not_leak(
    client, project, sync_engine, control_token, make_run
):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 777)

    missing = client.get(
        f"/internal/runs/{run_id}/fence", headers=_headers(control_token)
    )
    assert missing.status_code == 409, missing.text
    assert "777" not in missing.text, "无 token 的 fence 查询不得泄露当前 token"

    wrong = client.get(
        f"/internal/runs/{run_id}/fence",
        params={"token": "666"},
        headers=_headers(control_token),
    )
    assert wrong.status_code == 409, wrong.text
    assert "777" not in wrong.text, "错 token 的 fence 查询同样不得泄露当前 token"

    ok = client.get(
        f"/internal/runs/{run_id}/fence",
        params={"token": "777"},
        headers=_headers(control_token),
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True and body["token"] == 777


# --------------------------------------------------------------------------- #
# events / ack：与其他写端点同一 fence 纪律
# --------------------------------------------------------------------------- #
def test_events_without_valid_token_are_rejected(
    client, project, sync_engine, control_token, make_run
):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 7)
    batch = {
        "events": [
            {"source_key": "runner", "source_event_id": "evt-1", "kind": "stage",
             "payload": {"stage": "pytest"}}
        ]
    }

    for token in (None, 999):
        payload = dict(batch)
        if token is not None:
            payload["fencing_token"] = token
        response = client.post(
            f"/internal/runs/{run_id}/events",
            json=payload,
            headers=_headers(control_token),
        )
        assert response.status_code == 409, (token, response.text)
    assert _event_count(sync_engine, run_id, "stage") == 0, (
        "无效 runner 的事件不得落库"
    )

    payload = dict(batch, fencing_token=7)
    ok = client.post(
        f"/internal/runs/{run_id}/events",
        json=payload,
        headers=_headers(control_token),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["accepted"] == 1


def test_ack_without_valid_token_is_rejected(
    client, project, sync_engine, control_token, make_run
):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 7)

    response = client.post(
        f"/internal/runs/{run_id}/ack",
        json={"pid": 4242},
        headers=_headers(control_token),
    )
    assert response.status_code == 409, response.text
    assert _event_count(sync_engine, run_id, "ack") == 0

    ok = client.post(
        f"/internal/runs/{run_id}/ack",
        json={"pid": 4242, "fencing_token": 7},
        headers=_headers(control_token),
    )
    assert ok.status_code == 200, ok.text


# --------------------------------------------------------------------------- #
# A/B 接管：旧 Runner 在租约转手后的一切写操作都被拒
# --------------------------------------------------------------------------- #
def test_stale_runner_cannot_touch_reacquired_lease(
    client, project, sync_engine, control_token, make_run
):
    """A 持 token=100 -> 租约过期被回收 -> B 重新领取（token 递增）。

    A 用 token=100 或不带 token 继续发请求必须全部被拒，且 B 的租约不被 A
    的心跳续命；B 用自己的 token 正常心跳并收敛。
    """
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)
    _to_running_with_lease(sync_engine, project, run_id, 100)

    from app.domain import leases as leases_mod

    async def _reacquire():
        async with async_session() as session:
            # 模拟 reconciler：把 A 的租约判过期并回收（CHECK 要求
            # expires_at > created_at，所以 created_at 一起前移）
            await session.execute(
                text(
                    "UPDATE resource_leases"
                    " SET created_at = now() - interval '200 seconds',"
                    "     expires_at = now() - interval '1 second'"
                    " WHERE run_id = CAST(:run AS uuid) AND released_at IS NULL"
                ),
                {"run": run_id},
            )
            reaped = await leases_mod.release_stale_leases(
                session, stale_seconds=0
            )
            assert [row["fencing_token"] for row in reaped] == [100]
            await session.commit()
            lease = await leases_mod.acquire_lease(
                session,
                project_id=project["project_id"],
                run_id=run_id,
                resource_id=project["resource_id"],
                holder_id="runner-b",
            )
            assert lease is not None
            await session.commit()
            return lease

    lease_b = None
    from tests._p3_common import install_selector_policy

    install_selector_policy()
    import asyncio

    lease_b = asyncio.run(_reacquire())
    assert lease_b.fencing_token > 100, "重新领取必须递增 fencing token"
    token_b = lease_b.fencing_token

    # A 的写操作全部被拒
    stale_payloads = [
        ("heartbeat", {"pid": 1, "fencing_token": 100}),
        ("heartbeat", {"pid": 1}),
        ("complete", {"outcome": "passed", "fencing_token": 100}),
        ("complete", {"outcome": "passed"}),
        ("fail", {"error_code": "runner_failed", "fencing_token": 100}),
        ("fail", {"error_code": "runner_failed"}),
        ("events", {"fencing_token": 100, "events": []}),
        ("ack", {"pid": 1, "fencing_token": 100}),
    ]
    remaining_before = _lease_remaining(sync_engine, run_id)
    for action, payload in stale_payloads:
        response = client.post(
            f"/internal/runs/{run_id}/{action}",
            json=payload,
            headers=_headers(control_token),
        )
        assert response.status_code == 409, (action, payload, response.text)
        assert "expected" not in (response.json().get("details") or {})
    fence = client.get(
        f"/internal/runs/{run_id}/fence",
        params={"token": "100"},
        headers=_headers(control_token),
    )
    assert fence.status_code == 409
    remaining_after = _lease_remaining(sync_engine, run_id)
    assert remaining_after <= remaining_before + 2, (
        "旧 Runner 的心跳不得给新 Runner 的租约续期"
    )
    assert _run_state(sync_engine, run_id) == "running"

    # B 的操作全部正常
    ok_hb = client.post(
        f"/internal/runs/{run_id}/heartbeat",
        json={"pid": 2, "fencing_token": token_b},
        headers=_headers(control_token),
    )
    assert ok_hb.status_code == 200, ok_hb.text
    assert ok_hb.json()["fence_ok"] is True
    ok_complete = client.post(
        f"/internal/runs/{run_id}/complete",
        json={"outcome": "passed", "fencing_token": token_b},
        headers=_headers(control_token),
    )
    assert ok_complete.status_code == 200, ok_complete.text
    assert ok_complete.json()["state"] == "completed"


def test_extend_lease_rejects_mismatched_token(project, sync_engine, make_run):
    """domain 层：extend_lease 只续 token 精确匹配的租约（旧 token 续不动新租约）。"""
    import asyncio

    from app.domain import leases as leases_mod

    from tests._p3_common import install_selector_policy

    install_selector_policy()
    run_id = make_run(state="running", request_key=str(uuid.uuid4()), project=project)

    async def _scenario():
        async with async_session() as session:
            first = await leases_mod.acquire_lease(
                session,
                project_id=project["project_id"],
                run_id=run_id,
                resource_id=project["resource_id"],
                holder_id="runner-a",
            )
            assert first is not None
            await session.commit()
            await leases_mod.release_lease(session, run_id=run_id, reason="expired")
            await session.commit()
            second = await leases_mod.acquire_lease(
                session,
                project_id=project["project_id"],
                run_id=run_id,
                resource_id=project["resource_id"],
                holder_id="runner-b",
            )
            assert second is not None
            await session.commit()
            assert second.fencing_token > first.fencing_token

            with sync_engine.connect() as conn:
                before = conn.execute(
                    text(
                        "SELECT extract(epoch FROM expires_at - now())"
                        " FROM resource_leases WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": second.id},
                ).scalar_one()

            assert await leases_mod.extend_lease(
                session, run_id=run_id, token=first.fencing_token
            ) is False, "旧 token 不得续新租约"
            await session.commit()

            with sync_engine.connect() as conn:
                after_stale = conn.execute(
                    text(
                        "SELECT extract(epoch FROM expires_at - now())"
                        " FROM resource_leases WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": second.id},
                ).scalar_one()

            assert await leases_mod.extend_lease(
                session, run_id=run_id, token=second.fencing_token
            ) is True
            await session.commit()

            with sync_engine.connect() as conn:
                after_renew = conn.execute(
                    text(
                        "SELECT extract(epoch FROM expires_at - now())"
                        " FROM resource_leases WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": second.id},
                ).scalar_one()
            await session.rollback()
            return before, after_stale, after_renew

    before, after_stale, after_renew = asyncio.run(_scenario())
    assert after_stale <= before + 2, "旧 token 的续租请求不得改变新租约"
    assert after_renew > 100, "当前 token 的续租必须生效"


# --------------------------------------------------------------------------- #
# 终态幂等重试：不要求 token（不能改状态），但不拒绝
# --------------------------------------------------------------------------- #
def test_terminal_run_keeps_idempotent_retry_semantics(
    client, project, control_token, make_run
):
    run_id = make_run(
        state="completed", request_key=str(uuid.uuid4()), project=project
    )
    response = client.post(
        f"/internal/runs/{run_id}/complete",
        json={"outcome": "failed", "reason": "late_retry"},
        headers=_headers(control_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["already"] is True
    assert body["state"] == "completed"
    assert body["outcome"] == "passed", "终态重试不得改写既有结论"
