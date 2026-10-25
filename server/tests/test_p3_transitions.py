"""P3：状态机单入口 transition() 的行为约束（development-plan.md §7.2）。

这些用例只碰 domain 层（不经过路由），确保"唯一状态转换入口"的语义不依赖 HTTP。
"""

from __future__ import annotations

from tests._p3_common import make_run as make_run  # noqa: PLW0127 - 夹具复用
from tests._p3_common import p3_project as seed  # noqa: PLW0127 - 夹具别名
from tests._p3_common import requires_db
from tests._p3_common import session as session  # noqa: PLW0127
from tests._p3_common import sync_engine as sync_engine  # noqa: PLW0127

pytestmark = requires_db


import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.domain import runs as runs_mod  # noqa: E402
from app.errors import ApiError  # noqa: E402


async def test_forward_transition_advances_state(session, seed, make_run):
    run_id = make_run(state="queued", request_key="p3-fwd-" + _suffix())
    result = await runs_mod.transition(
        session, run_id, runs_mod.STATE_QUEUED, runs_mod.STATE_DISPATCHING, actor="pytest"
    )
    assert result.source == "queued"
    assert result.target == "dispatching"
    await session.commit()
    state = await _state(session, run_id)
    assert state == "dispatching"


async def test_illegal_transition_raises_409(session, seed, make_run):
    """queued -> completed 不是合法边，必须 409（而不是默默改成 completed）。"""
    run_id = make_run(state="queued", request_key="p3-illegal-" + _suffix())
    with pytest.raises(ApiError) as excinfo:
        await runs_mod.transition(
            session, run_id, runs_mod.STATE_QUEUED, runs_mod.STATE_COMPLETED, outcome="passed"
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "illegal_transition"


async def test_expect_state_mismatch_raises_409_and_leaves_row(session, seed, make_run):
    """expect_state 不匹配时 0 行受影响 -> 409，且行状态不变（乐观并发的基础）。"""
    run_id = make_run(state="running", request_key="p3-expect-" + _suffix())
    with pytest.raises(ApiError) as excinfo:
        await runs_mod.transition(
            session, run_id, runs_mod.STATE_QUEUED, runs_mod.STATE_CANCELLED
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.code in ("state_conflict", "illegal_transition")
    assert await _state(session, run_id) == "running"


async def test_terminal_state_is_immutable(session, seed, make_run):
    run_id = make_run(state="completed", request_key="p3-terminal-" + _suffix())
    # 先补 outcome，让 completed 行满足 ck_test_runs_state_outcome_pair
    await session.execute(
        text("UPDATE test_runs SET outcome = 'passed' WHERE id = :id"), {"id": run_id}
    )
    await session.commit()
    for target in (
        runs_mod.STATE_RUNNING,
        runs_mod.STATE_ERRORED,
        runs_mod.STATE_CANCELLED,
        runs_mod.STATE_FINALIZING,
    ):
        with pytest.raises(ApiError) as excinfo:
            await runs_mod.transition(session, run_id, runs_mod.STATE_COMPLETED, target)
        assert excinfo.value.status_code == 409
        assert excinfo.value.code == "illegal_transition"
    assert await _state(session, run_id) == "completed"


async def test_outcome_only_on_completed(session, seed, make_run):
    """errored / cancelled 带 outcome 会被 domain 层直接清掉（DB CHECK 兜底）。"""
    run_id = make_run(state="running", request_key="p3-outcome-" + _suffix())
    result = await runs_mod.transition(
        session,
        run_id,
        runs_mod.STATE_RUNNING,
        runs_mod.STATE_ERRORED,
        outcome="passed",
        reason="boom",
    )
    assert result.outcome is None
    await session.commit()
    row = (
        await session.execute(
            text("SELECT state, outcome FROM test_runs WHERE id = :id"), {"id": run_id}
        )
    ).mappings().first()
    assert row["state"] == "errored"
    assert row["outcome"] is None


async def test_cancel_from_every_executing_state(session, seed, make_run):
    for state in ("queued", "dispatching", "running", "finalizing"):
        run_id = make_run(state=state, request_key=f"p3-cancel-{state}-" + _suffix())
        await runs_mod.transition(
            session, run_id, state, runs_mod.STATE_CANCELLED, reason="user_cancelled"
        )
        await session.commit()
        assert await _state(session, run_id) == "cancelled"


async def test_not_tested_requires_reason(session, seed, make_run):
    run_id = make_run(state="finalizing", request_key="p3-nt-" + _suffix())
    await runs_mod.transition(
        session,
        run_id,
        runs_mod.STATE_FINALIZING,
        runs_mod.STATE_COMPLETED,
        outcome="not_tested",
        reason="no_matching_cases",
    )
    await session.commit()
    row = (
        await session.execute(
            text("SELECT state, outcome, not_tested_reason FROM test_runs WHERE id = :id"),
            {"id": run_id},
        )
    ).mappings().first()
    assert row["outcome"] == "not_tested"
    assert row["not_tested_reason"] == "no_matching_cases"


async def _state(session, run_id: str) -> str:
    await session.commit()
    return (
        await session.execute(
            text("SELECT state FROM test_runs WHERE id = :id"), {"id": run_id}
        )
    ).scalar_one()


def _suffix() -> str:
    import uuid

    return uuid.uuid4().hex
