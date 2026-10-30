"""运行状态机：transition() 是唯一的状态写入入口（development-plan.md §7.2）。

为什么必须只有这一个入口
------------------------
test_runs 上有一组 CHECK 约束互相咬合（0001_initial.py:test_runs）：

  ck_test_runs_state_outcome_pair
      (state = 'completed' AND outcome IS NOT NULL)
      OR (state <> 'completed' AND outcome IS NULL)
  ck_test_runs_state_terminal_needs_ended_at
      (state IN ('completed','errored','cancelled')) = (ended_at IS NOT NULL)
  ck_test_runs_state_executing_needs_resource
      state NOT IN ('running','finalizing','completed')
      OR (resource_id IS NOT NULL AND started_at IS NOT NULL)

也就是说"状态 / 结论 / 结束时间 / 资源"四件事必须同时改对，任何一处分散在
路由里手写 UPDATE，迟早会写出绕过 CHECK 的补丁。这里把它们合并在一条
UPDATE 里，先由 Python 状态机判定迁移合法性（给出可读的 409 文案），再由
\"UPDATE ... WHERE id = :id AND state = :expect RETURNING ...\" 做乐观并发控制：
0 行说明有人抢先改了状态 —— 这就是 409 state_conflict，绝不覆盖。

终态语义
--------
completed / errored / cancelled 是终态，永不可再改。重跑一律新建 run
（parent_run_id 指回原 run），这样历史结论与产物 sha256 永远可复算。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import (
    illegal_run_transition,
    not_found,
    state_conflict,
    terminal_run_immutable,
)

# --------------------------------------------------------------------------- #
# 状态常量与状态机
# --------------------------------------------------------------------------- #

STATE_QUEUED = "queued"
STATE_DISPATCHING = "dispatching"
STATE_RUNNING = "running"
STATE_FINALIZING = "finalizing"
STATE_COMPLETED = "completed"
STATE_ERRORED = "errored"
STATE_CANCELLED = "cancelled"

ALL_STATES: tuple[str, ...] = (
    STATE_QUEUED,
    STATE_DISPATCHING,
    STATE_RUNNING,
    STATE_FINALIZING,
    STATE_COMPLETED,
    STATE_ERRORED,
    STATE_CANCELLED,
)

#: 终态集合 —— 与 0001_initial.py 的 ck_test_runs_state_terminal_needs_ended_at 同一份取值
TERMINAL_STATES: frozenset[str] = frozenset(
    {STATE_COMPLETED, STATE_ERRORED, STATE_CANCELLED}
)

#: 执行态（已占用设备、正在跑）
EXECUTING_STATES: frozenset[str] = frozenset({STATE_RUNNING, STATE_FINALIZING})

#: 正常前进链：queued -> dispatching -> running -> finalizing -> completed
FORWARD_EDGES: Mapping[str, str] = {
    STATE_QUEUED: STATE_DISPATCHING,
    STATE_DISPATCHING: STATE_RUNNING,
    STATE_RUNNING: STATE_FINALIZING,
    STATE_FINALIZING: STATE_COMPLETED,
}

#: 任意执行态可转 cancelled / errored；queued / dispatching 也可以（如领取设备失败）
CANCELABLE_STATES: frozenset[str] = frozenset(
    {STATE_QUEUED, STATE_DISPATCHING, STATE_RUNNING, STATE_FINALIZING}
)
ERRORABLE_STATES: frozenset[str] = CANCELABLE_STATES

OUTCOME_PASSED = "passed"
OUTCOME_FAILED = "failed"
OUTCOME_NOT_TESTED = "not_tested"
ALL_OUTCOMES: tuple[str, ...] = (OUTCOME_PASSED, OUTCOME_FAILED, OUTCOME_NOT_TESTED)


@dataclass(frozen=True)
class Transition:
    """一条合法迁移的判定结果（纯函数产出，便于单测不连库）。"""

    source: str
    target: str
    outcome: str | None


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


#: 展示编号前缀。编号本身来自 test_runs.display_no（持久分配，工单 09）；
#: 前缀只做格式化，不参与判定，也不作为主键。
DISPLAY_ID_PREFIX = "RUN"


def format_display_id(display_no: int | None) -> str | None:
    """display_no -> `RUN-0001`。

    编号一旦分配就不再变（历史数据变动、过滤、分页都不重编号），
    所以这里只做纯格式化：同一 display_no 在任何页面、报告、导出里都是同一个字符串。
    """
    if display_no is None:
        return None
    return "%s-%04d" % (DISPLAY_ID_PREFIX, int(display_no))


def allowed_targets(state: str) -> tuple[str, ...]:
    """当前状态允许迁移到的目标状态（用于错误文案与前端按钮可用性）。"""
    if is_terminal(state):
        return ()
    targets: list[str] = []
    if state in FORWARD_EDGES:
        targets.append(FORWARD_EDGES[state])
    if state in CANCELABLE_STATES:
        targets.append(STATE_CANCELLED)
    if state in ERRORABLE_STATES:
        targets.append(STATE_ERRORED)
    return tuple(targets)


def check_transition(current: str, target: str, *, run_id: str = "") -> Transition:
    """判定 current -> target 是否合法；不合法直接抛 409（api-design.md §1.2）。"""
    if target not in ALL_STATES:
        raise illegal_run_transition(run_id, current, target, "未知状态 %r" % (target,))
    if current not in ALL_STATES:
        raise illegal_run_transition(
            run_id, current, target, "库内状态 %r 不在状态机内" % (current,)
        )
    if is_terminal(current):
        raise terminal_run_immutable(run_id, current)
    if target == FORWARD_EDGES.get(current):
        return Transition(current, target, None)
    if target in (STATE_CANCELLED, STATE_ERRORED) and current in CANCELABLE_STATES:
        return Transition(current, target, None)
    raise illegal_run_transition(
        run_id,
        current,
        target,
        "允许的目标状态为 %s" % (", ".join(allowed_targets(current)) or "（无，终态不可改）"),
    )


def normalize_outcome(state: str, outcome: str | None) -> str | None:
    """结论只允许出现在 completed 上；errored / cancelled 必须为 NULL。"""
    if state == STATE_COMPLETED:
        if outcome is None:
            raise illegal_run_transition(
                "",
                state,
                state,
                "state='completed' 必须同时给出 outcome（passed/failed/not_tested）",
            )
        if outcome not in ALL_OUTCOMES:
            raise illegal_run_transition("", state, state, "未知结论 %r" % (outcome,))
        return outcome
    if outcome is not None:
        raise illegal_run_transition(
            "",
            state,
            state,
            "state=%r 不得携带 outcome（DB CHECK 会拒绝，不绕过）" % (state,),
        )
    return None


# --------------------------------------------------------------------------- #
# DB 写入
# --------------------------------------------------------------------------- #

_RETURNED_COLUMNS = """
    id, project_id, application_id, platform, revision_id, parent_run_id, request_key,
    state, outcome, reason_code, resource_id, profile_id, config_snapshot,
    lock_version, started_at, ended_at, created_by, created_at, not_tested_reason
"""

# 一条 UPDATE 同时满足 4 条 CHECK：
#   - state 与 outcome 成对（normalize_outcome 已保证）
#   - 终态一定写 ended_at，非终态一定清空 ended_at
#   - running/finalizing/completed 一定有 resource_id 与 started_at（领取阶段已写）
_UPDATE_TEMPLATE_RAW = """
    UPDATE test_runs
       SET state = :to_state,
           outcome = :outcome,
           ended_at = CASE WHEN :to_state IN ('completed','errored','cancelled')
                           -- GREATEST：长事务里 now()（事务时间戳）可能早于 created_at
                           --（行是在本事务开始后才由别的连接插入的，如测试夹具），
                           -- 直接 now() 会撞 ck_test_runs_ended_at_not_before_created。
                           THEN GREATEST(COALESCE(ended_at, now()), created_at)
                           ELSE NULL END,
           reason_code = COALESCE(:reason, reason_code),
           not_tested_reason = CASE WHEN :outcome = 'not_tested'
                                    THEN COALESCE(:reason, not_tested_reason, 'not_tested')
                                    ELSE not_tested_reason END,
           lock_version = lock_version + 1
     WHERE id = :run_id
       AND state %s
    RETURNING """ + _RETURNED_COLUMNS


#: 单状态模板（AND state = :expect_state），多状态时换成 ANY(:expect_state)
_UPDATE_TEMPLATE = _UPDATE_TEMPLATE_RAW
_UPDATE_ONE_SQL = text(_UPDATE_TEMPLATE % "= :expect_state")
_UPDATE_ANY_SQL = text(_UPDATE_TEMPLATE % "= ANY(:expect_state)")


@dataclass(frozen=True)
class TransitionResult:
    """transition() 的返回值：迁移后的整行（路由层直接序列化）。"""

    run_id: str
    source: str
    target: str
    outcome: str | None
    row: dict[str, Any] = field(default_factory=dict)


async def transition(
    session: AsyncSession,
    run_id: str | uuid.UUID,
    expect_state: str | Iterable[str],
    to_state: str,
    *,
    outcome: str | None = None,
    reason: str | None = None,
    actor: str = "system",
    extras: Mapping[str, Any] | None = None,
) -> TransitionResult:
    """唯一的状态转换入口。

    Parameters
    ----------
    expect_state
        单个状态字符串，或状态集合（内部端点 complete/fail 允许从 running 或
        finalizing 到达，因为两者都可能先发生）。集合内每个状态都必须允许迁到
        to_state，否则 409。
    actor
        仅用于审计文案，不落 test_runs（该表无 actor 列；审计走 run_events）。
    extras
        只允许 reason_code 之外的行级补充（当前仅支持 {"resource_id": ...} 之类
        在领取阶段写入的字段），由调用方保证不违反 CHECK。。

    0 行 affected 时先查当前状态给出精确错误：
    非法迁移 409 / 终态不可改 409 / 已被抢先修改 409 state_conflict。
    """
    run_key = str(run_id)
    expects = (expect_state,) if isinstance(expect_state, str) else tuple(expect_state)
    if not expects:
        raise illegal_run_transition(run_key, "", to_state, "expect_state 不能为空")

    for exp in expects:
        check_transition(exp, to_state, run_id=run_key)
    # 语义：errored / cancelled 上携带的 outcome 被**静默清掉**（与 DB CHECK
    # ck_test_runs_state_outcome_pair 一致：非 completed 行 outcome 必为 NULL），
    # 而不是 409 —— 调用方（runner 上报 fail）不必先猜结论字段是否合法。
    # completed 上缺 outcome 仍然 409（normalize_outcome 内部检查）。
    normalized = (
        normalize_outcome(to_state, outcome)
        if to_state == STATE_COMPLETED
        else None
    )

    sql = _UPDATE_ANY_SQL if len(expects) > 1 else _UPDATE_ONE_SQL
    if extras:
        sql = _with_extras(sql, extras)
    params: dict[str, Any] = {
        **dict(extras or {}),
        "run_id": run_key,
        "to_state": to_state,
        "expect_state": list(expects) if len(expects) > 1 else expects[0],
        "outcome": normalized,
        "reason": reason,
    }

    row = (await session.execute(sql, params)).mappings().first()
    if row is not None:
        data = dict(row)
        return TransitionResult(
            # RETURNING 里的 state 是迁移**后**的值；source 必须报迁移前的
            # expect_state（单个）或 expects 集合（按 "," 拼接），否则
            # test_forward_transition_advances_state 会看到 source==target。
            run_id=run_key,
            source="/".join(expects),
            target=to_state,
            outcome=normalized,
            row=data,
        )

    # 0 行：诊断真实原因
    current = (
        await session.execute(text("SELECT state FROM test_runs WHERE id = :id"), {"id": run_key})
    ).scalar_one_or_none()
    if current is None:
        raise not_found("run", run_key)
    if is_terminal(current):
        raise terminal_run_immutable(run_key, current)
    check_transition(current, to_state, run_id=run_key)
    # 状态机认为合法却 0 行 => 并发抢先修改
    raise state_conflict(run_key, current, "/".join(expects))


_EXTRA_ALLOWED = frozenset({"resource_id", "profile_id", "started_at", "reason_code"})


def _with_extras(sql: Any, extras: Mapping[str, Any]) -> Any:
    """把允许的行级字段塞进 SET（只接受白名单，防止调用方顺手改 state/outcome）。"""
    unknown = set(extras) - _EXTRA_ALLOWED
    if unknown:
        raise ValueError("transition extras 不允许的字段: %s" % ", ".join(sorted(unknown)))
    assignments = ", ".join("%s = :%s" % (name, name) for name in extras)
    patched = _UPDATE_TEMPLATE_RAW.replace(
        "       SET state = :to_state,",
        "       SET state = :to_state,\n           " + assignments + ",",
    )
    condition = "= ANY(:expect_state)" if "ANY(:expect_state)" in str(sql) else "= :expect_state"
    return text(patched % condition)


__all__ = [
    "ALL_OUTCOMES",
    "ALL_STATES",
    "CANCELABLE_STATES",
    "DISPLAY_ID_PREFIX",
    "ERRORABLE_STATES",
    "EXECUTING_STATES",
    "FORWARD_EDGES",
    "OUTCOME_FAILED",
    "OUTCOME_NOT_TESTED",
    "OUTCOME_PASSED",
    "STATE_CANCELLED",
    "STATE_COMPLETED",
    "STATE_DISPATCHING",
    "STATE_ERRORED",
    "STATE_FINALIZING",
    "STATE_QUEUED",
    "STATE_RUNNING",
    "TERMINAL_STATES",
    "Transition",
    "TransitionResult",
    "allowed_targets",
    "check_transition",
    "format_display_id",
    "is_terminal",
    "normalize_outcome",
    "transition",
]
