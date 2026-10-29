"""工单 02：短检查租约、fence 严格性与未确认停机隔离（真实 PostgreSQL）。

验收对应：
- 短检查与运行共用 resource_leases 权威，同一设备并发只能有一个持有者；
- 旧 fencing token 拒绝写入；token 缺失在严格模式下拒绝；
- 未确认停机时保留租约并把资源置 draining，资源不可再分配。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.domain import leases
from tests._p3_common import async_session, make_run, requires_db
from tests._p3_common import p3_project as project  # noqa: F401 - fixture 复用
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - fixture 复用

pytestmark = requires_db


@pytest.fixture
def clean_checks(project, sync_engine):
    """测试结束先清租约再清 device_checks，避免项目删除撞外键。"""
    yield project
    with sync_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM resource_leases WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": project["project_id"]},
        )
        conn.execute(
            text("DELETE FROM device_checks WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": project["project_id"]},
        )


def _insert_check(sync_engine, project, *, resource_id: str | None = None,
                  test_type: str = "ui") -> str:
    check_id = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO device_checks"
                " (id, project_id, resource_id, kind, test_type, holder_id, state, expires_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         'readiness', :tt, 'pytest', 'opening', now() + interval '60 seconds')"
            ),
            {
                "id": check_id,
                "pid": project["project_id"],
                "rid": resource_id or project["resource_id"],
                "tt": test_type,
            },
        )
    return check_id


def _live_lease_count(sync_engine, project_id: str) -> int:
    with sync_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM resource_leases"
                " WHERE project_id = CAST(:pid AS uuid) AND released_at IS NULL"
            ),
            {"pid": project_id},
        ).scalar_one()


def _resource_status(sync_engine, resource_id: str) -> str:
    with sync_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM execution_resources WHERE id = CAST(:rid AS uuid)"),
            {"rid": resource_id},
        ).scalar_one()


def test_check_and_run_lease_are_mutually_exclusive(clean_checks, make_run, sync_engine):
    project = clean_checks
    resource_id = project["resource_id"]
    check_id = _insert_check(sync_engine, project, resource_id=resource_id)
    run_id = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)

    async def check_side():
        async with async_session() as session:
            lease = await leases.acquire_lease_for_check(
                session,
                project_id=project["project_id"],
                check_id=check_id,
                resource_id=resource_id,
                holder_id="readiness",
            )
            if lease is not None:
                await session.commit()
            return lease

    async def run_side():
        async with async_session() as session:
            lease = await leases.acquire_lease(
                session,
                project_id=project["project_id"],
                run_id=run_id,
                resource_id=resource_id,
                holder_id="runner",
            )
            if lease is not None:
                await session.commit()
            return lease

    async def race():
        return await asyncio.gather(check_side(), run_side())

    check_lease, run_lease = asyncio.run(race())
    winners = [lease for lease in (check_lease, run_lease) if lease is not None]
    assert len(winners) == 1, "check 与 run 不能同时持有同一设备"
    assert _live_lease_count(sync_engine, project["project_id"]) == 1


def test_stale_fence_token_cannot_write_or_release(clean_checks, make_run):
    project = clean_checks
    resource_id = project["resource_id"]
    run_id = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)

    async def scenario():
        async with async_session() as session:
            first = await leases.acquire_lease(
                session,
                project_id=project["project_id"],
                run_id=run_id,
                resource_id=resource_id,
                holder_id="runner",
            )
            assert first is not None
            await session.commit()
            await leases.release_lease(session, run_id=run_id, reason="test_restart")
            await session.commit()

            second = await leases.acquire_lease(
                session,
                project_id=project["project_id"],
                run_id=run_id,
                resource_id=resource_id,
                holder_id="runner",
            )
            assert second is not None
            await session.commit()
            assert second.fencing_token > first.fencing_token

            stale = await leases.verify_fence(
                session, run_id=run_id, token=first.fencing_token
            )
            assert stale["ok"] is False and stale["checked"] is True

            strict_missing = await leases.verify_fence(
                session, run_id=run_id, token=None, require_token=True
            )
            assert strict_missing["ok"] is False and strict_missing["checked"] is True

            current = await leases.verify_fence(
                session, run_id=run_id, token=second.fencing_token
            )
            assert current["ok"] is True

            await leases.release_lease(
                session, run_id=run_id, reason="stale", token=first.fencing_token
            )
            await session.commit()
            assert await leases.live_lease_for_run(session, run_id) is not None
            await session.rollback()

    asyncio.run(scenario())


def test_check_result_write_requires_live_fence(clean_checks, sync_engine):
    project = clean_checks
    resource_id = project["resource_id"]
    check_id = _insert_check(sync_engine, project, resource_id=resource_id)

    async def scenario():
        async with async_session() as session:
            lease = await leases.acquire_lease_for_check(
                session,
                project_id=project["project_id"],
                check_id=check_id,
                resource_id=resource_id,
                holder_id="readiness",
            )
            assert lease is not None
            await session.commit()

            written = await leases.record_check_result(
                session,
                check_id=check_id,
                token=lease.fencing_token,
                state="finished",
                result={"ready": True},
            )
            assert written is True
            await session.commit()

            rejected = await leases.record_check_result(
                session,
                check_id=check_id,
                token=lease.fencing_token + 999,
                state="failed",
                result={"ready": False},
            )
            assert rejected is False
            await session.commit()
            await leases.release_lease_for_check(
                session, check_id=check_id, reason="done", token=lease.fencing_token
            )
            await session.commit()

            # 租约已释放 = fence 失效：旧拥有者不能再写结果。
            late = await leases.record_check_result(
                session,
                check_id=check_id,
                token=lease.fencing_token,
                state="failed",
                result={"ready": False},
            )
            assert late is False
            await session.commit()

    asyncio.run(scenario())

    with sync_engine.connect() as conn:
        state, result = conn.execute(
            text("SELECT state, result FROM device_checks WHERE id = CAST(:cid AS uuid)"),
            {"cid": check_id},
        ).one()
    assert state == "finished"
    assert result == {"ready": True}


def test_unconfirmed_stop_keeps_resource_unallocatable(clean_checks, make_run, sync_engine):
    project = clean_checks
    resource_id = project["resource_id"]
    first_run = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)
    second_run = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)

    async def scenario():
        async with async_session() as session:
            lease = await leases.acquire_lease(
                session,
                project_id=project["project_id"],
                run_id=first_run,
                resource_id=resource_id,
                holder_id="runner",
            )
            assert lease is not None
            await session.commit()

            released = await leases.release_lease_if_stopped(
                session,
                run_id=first_run,
                reason="cancel_timeout",
                token=lease.fencing_token,
                stopped_confirmed=False,
            )
            assert released is None
            await session.commit()
            assert await leases.live_lease_for_run(session, first_run) is not None
            assert _resource_status(sync_engine, resource_id) == "draining"

            blocked = await leases.acquire_lease(
                session,
                project_id=project["project_id"],
                run_id=second_run,
                resource_id=resource_id,
                holder_id="runner-2",
            )
            assert blocked is None
            await session.commit()

            released = await leases.release_lease_if_stopped(
                session,
                run_id=first_run,
                reason="stop_confirmed",
                token=lease.fencing_token,
                stopped_confirmed=True,
            )
            assert released is not None
            await session.commit()
            assert _resource_status(sync_engine, resource_id) == "ready"

    asyncio.run(scenario())
