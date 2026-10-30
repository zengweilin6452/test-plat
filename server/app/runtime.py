"""运行收敛：把"跑完了/跑挂了"落成 (产物 + 事件 + 状态 + 租约) 四件事。

为什么抽出来
------------
有 4 条路径会把 run 推到终态：
  1. runner 正常上报 /internal/runs/{id}/complete|fail
  2. runner 进程退出但没上报（崩溃、被 kill）
  3. reconciler 判定心跳超时
  4. POST /runs/import 降级通道

如果每条各自写一遍"登记产物 + 写事件 + transition + 释放租约"，它们一定会
慢慢长歪（比如某条忘了释放租约，设备就永久卡住）。这里只保留一份实现。

顺序（唯一正确顺序）
--------------------
  先登记产物 -> 再写事件 -> 再 transition 到终态 -> 最后释放租约

为什么产物必须在 state 变更之前：前端看到 completed 就会去请求 /artifacts，
若产物还没入库，页面就是"已完成但零产物"，且没有任何自愈机会。反过来，产物
先入库但状态没改（进程在中间崩），重跑一次 finalize 靠 logical_key 幂等即可。

为什么释放租约必须在最后：租约释放代表"设备空闲可被别的 run 领取"。如果先释放，
下一个 run 可能在旧 run 还在写产物时抢到同一台设备，证据目录就会互相污染。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text

from .config import settings
from .db import get_sessionmaker
from .domain import artifacts as artifacts_mod
from .domain import events as events_mod
from .domain import leases as leases_mod
from .domain import runs as runs_mod
from .integrations import leases as local_leases

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinalizeResult:
    """一次 finalize 的结果（测试断言用）。"""

    run_id: str
    state: str
    outcome: str | None
    artifact_count: int
    sha256s: dict[str, str]
    already_terminal: bool = False


async def _run_row(session, run_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT tr.id, tr.project_id, tr.state, tr.outcome, tr.resource_id,
                       tr.revision_id, tr.application_id, tr.started_at,
                       COALESCE(rev.test_type, 'ui') AS test_type
                  FROM test_runs tr
                  LEFT JOIN task_revisions rev ON rev.id = tr.revision_id
                 WHERE tr.id = :id
                """
            ),
            {"id": str(run_id)},
        )
    ).mappings().first()
    return dict(row) if row else None


def read_junit_summary(path: Path) -> dict[str, Any]:
    """从 junit.xml 取用例计数（不依赖第三方 XML 绑定）。"""
    if not path.exists():
        return {"present": False}
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return {"present": True, "parse_error": str(exc)}
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            try:
                totals[key] += int(suite.get(key) or 0)
            except ValueError:
                pass
    totals["present"] = True
    totals["failed"] = totals["failures"] + totals["errors"]
    return totals


async def _advance_to(session, run_id: str, current: str, target: str, *, reason: str | None,
                      actor: str) -> str:
    """沿状态机的正向边把运行推到 target 的前驱，返回推进后的状态。

    为什么不能直接写终态：check_transition 只认 FORWARD_EDGES 的单步边
    （queued -> dispatching -> running -> finalizing -> completed），
    dispatching -> completed 是非法迁移。runner 正常跑完时确实会先 ack 进
    running，但进程崩溃、导入通道、以及 runner 从未 ack 的情况都没有中间态，
    所以收敛时必须自己补齐这几步，而不是绕过状态机。

    errored / cancelled 可以从任意非终态直达，不需要推进。
    """
    if target != runs_mod.STATE_COMPLETED:
        return current
    while True:
        forward = runs_mod.FORWARD_EDGES.get(current)
        if forward is None or forward == target:
            return current
        if forward in (runs_mod.STATE_RUNNING, runs_mod.STATE_FINALIZING):
            bound = (
                await session.execute(
                    text("SELECT resource_id FROM test_runs WHERE id = :id"), {"id": run_id}
                )
            ).scalar_one_or_none()
            if bound is None:
                # 没有绑定设备就进不了执行态（DB CHECK 会拒绝）。这是调用方的
                # 前置条件缺失，给出可读的 409，而不是把 IntegrityError 抛成 500。
                from .errors import conflict

                raise conflict(
                    "run_without_resource",
                    f"运行 {run_id} 尚未绑定执行资源，无法收敛到 completed",
                    {"run_id": run_id, "state": current},
                )
            # ck_test_runs_state_executing_needs_resource：进入执行态必须有
            # resource_id + started_at。用 DB 的 now() 与 created_at 取大，
            # 避免 Python 时钟略早于插入时间而撞 started_at_not_before_created。
            await session.execute(
                text(
                    "UPDATE test_runs SET started_at = GREATEST(now(), created_at) "
                    " WHERE id = :id AND started_at IS NULL"
                ),
                {"id": run_id},
            )
        await runs_mod.transition(
            session, run_id, current, forward, reason=reason, actor=actor
        )
        current = forward


def derive_outcome(
    *,
    state: str,
    explicit_outcome: str | None,
    junit: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> str | None:
    """收敛出最终 outcome。

    只在 state=completed 时给值（DB CHECK 兜底，绝不绕过）：
      - 显式给了 outcome 就用它
      - 否则看 junit：有失败 -> failed，有测试且全绿 -> passed
      - 既没 outcome 也没 junit 有用例 -> not_tested（并写 not_tested_reason）
    """
    if state != runs_mod.STATE_COMPLETED:
        return None
    if explicit_outcome in runs_mod.ALL_OUTCOMES:
        return explicit_outcome
    if junit and junit.get("present"):
        if int(junit.get("failed") or 0) > 0:
            return runs_mod.OUTCOME_FAILED
        if int(junit.get("tests") or 0) > 0:
            return runs_mod.OUTCOME_PASSED
        return runs_mod.OUTCOME_NOT_TESTED
    return runs_mod.OUTCOME_NOT_TESTED


def read_report_payload(artifacts_dir: Path | str | None) -> dict[str, Any] | None:
    """读取 report.json；损坏/缺失按"没有性能报告"处理，不让 finalize 崩掉。"""
    if artifacts_dir is None:
        return None
    path = Path(artifacts_dir) / "report.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and "metricsSummary" in payload else None


def _component_state(component: Mapping[str, Any], overall_state: str) -> str:
    """组件状态：优先采用 runner 上报值，缺省按整体终态映射。

    非 completed 组件不得携带 outcome（DB CHECK），调用方据此清空结论，
    但 state / reason_code / summary 仍如实保留（取消/错误不丢组件事实）。
    """
    reported = str(component.get("state") or "").strip()
    if reported in ("pending", "running", "completed", "errored", "cancelled"):
        return reported
    return "completed" if overall_state == runs_mod.STATE_COMPLETED else "errored"


async def _record_results(
    session,
    row: dict,
    *,
    components: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    report: dict[str, Any] | None,
    overall_state: str,
) -> bool:
    """登记组件、用例及性能摘要；返回是否存在 performance 组件。

    所有终态都登记组件事实；不再把组件 state 硬编码成 completed，也不只在
    completed 时登记。返回的布尔值表示是否存在性能组件（而非是否有报告）。
    """
    items = [dict(c) for c in components if isinstance(c, Mapping)]
    if (
        report is not None
        and overall_state == runs_mod.STATE_COMPLETED
        and not any(c.get("kind") == "performance" for c in items)
    ):
        # 有 report.json 却没上报 performance 组件：按性能组件登记，避免指标丢失。
        items.append(
            {
                "kind": "performance",
                "state": "completed",
                "outcome": "not_tested",
                "reason_code": "gate_policy_missing",
            }
        )

    has_perf = False
    for component in items:
        kind = component.get("kind")
        if kind not in ("ui", "performance"):
            continue
        state = _component_state(component, overall_state)
        outcome = component.get("outcome")
        if state == runs_mod.STATE_COMPLETED:
            outcome = outcome if outcome in runs_mod.ALL_OUTCOMES else "not_tested"
        else:
            outcome = None
        reason = component.get("reason_code")
        if state == runs_mod.STATE_COMPLETED:
            if outcome == runs_mod.OUTCOME_NOT_TESTED:
                reason = reason or (
                    "gate_policy_missing" if kind == "performance" else "no_tests"
                )
            else:
                reason = None
        else:
            reason = reason or None
        cid = (await session.execute(text(
            "INSERT INTO run_components (id, project_id, run_id, kind, adapter_key, adapter_version, state, outcome, reason_code, summary) "
            "VALUES (gen_random_uuid(), :pid, :rid, :kind, :adapter, '1', :state, :outcome, :reason, CAST(:summary AS jsonb)) "
            "ON CONFLICT (project_id, run_id, kind) DO UPDATE SET state = EXCLUDED.state, "
            "outcome = EXCLUDED.outcome, reason_code = EXCLUDED.reason_code, summary = EXCLUDED.summary "
            "RETURNING id"
        ), {"pid": row["project_id"], "rid": row["id"], "kind": kind,
            "adapter": "mobile_perf" if kind == "performance" else "mobile_auto",
            "state": state, "outcome": outcome,
            "reason": reason,
            "summary": json.dumps(report if kind == "performance" and report is not None else component.get("summary") or {}, ensure_ascii=False)})).scalar_one()
        if kind == "ui":
            for case in cases:
                if not isinstance(case, Mapping) or not case.get("case_key"):
                    continue
                await session.execute(text(
                    "INSERT INTO case_results (id, project_id, component_id, case_key, outcome, duration_ms, error_summary) "
                    "VALUES (gen_random_uuid(), :pid, :cid, :key, :outcome, :duration, :error) "
                    "ON CONFLICT (project_id, component_id, case_key, attempt) DO NOTHING"
                ), {"pid": row["project_id"], "cid": cid, "key": case["case_key"],
                    "outcome": case.get("outcome") or "errored",
                    "duration": case.get("duration_ms"), "error": case.get("error_summary")})
        else:
            has_perf = True
            if report is not None:
                from .integrations.mobile_perf import summaries_from_report
                mapped = summaries_from_report(report)
                for metric in mapped.rows:
                    await session.execute(text(
                        "INSERT INTO metric_summaries (id, project_id, component_id, metric_key, metric_version, unit, scope, window_key, "
                        "statistic, sample_count, value, missing_reason, missing_reason_text) "
                        "VALUES (gen_random_uuid(), :pid, :cid, :metric_key, :version, :unit, :scope, :window_key, "
                        ":statistic, :sample_count, :value, :missing_reason, :missing_reason_text) ON CONFLICT DO NOTHING"
                    ), {"pid": row["project_id"], "cid": cid, "version": mapped.metric_version, **metric.as_dict()})
    return has_perf


async def _aggregate_component_outcome(session, run_id: str) -> tuple[str | None, str | None]:
    """组件结论 -> 整体结论（failed > not_tested > passed），并给出 not_tested 原因。"""
    rows = (
        await session.execute(
            text(
                "SELECT state, outcome, reason_code FROM run_components "
                "WHERE run_id = :rid ORDER BY kind"
            ),
            {"rid": run_id},
        )
    ).mappings().all()
    if not rows:
        return None, None
    # 组件没正常完成（errored/cancelled/pending）时，整体不能伪装成 passed。
    incomplete = [row for row in rows if row["state"] != runs_mod.STATE_COMPLETED]
    if incomplete:
        reason = next(
            (row["reason_code"] for row in incomplete if row["reason_code"]),
            "component_not_completed",
        )
        return runs_mod.OUTCOME_NOT_TESTED, reason
    outcomes = [str(row["outcome"]) for row in rows if row["outcome"]]
    if not outcomes:
        return None, None
    if runs_mod.OUTCOME_FAILED in outcomes:
        return runs_mod.OUTCOME_FAILED, None
    if runs_mod.OUTCOME_NOT_TESTED in outcomes:
        reason = next(
            (
                row["reason_code"]
                for row in rows
                if row["outcome"] == runs_mod.OUTCOME_NOT_TESTED and row["reason_code"]
            ),
            None,
        )
        return runs_mod.OUTCOME_NOT_TESTED, reason
    return runs_mod.OUTCOME_PASSED, None


async def _apply_original_gate(session, run_id: str) -> dict[str, Any]:
    """在 finalizing 事务内计算原始判定，并同步 performance 组件结论。

    必须在 transition 到 completed 之前调用：门禁显式接收 run_complete=True，
    不再依赖"先把 run 写成 completed 再直接 UPDATE outcome"的路径。
    """
    from .routers.analyses import evaluate_run_original

    evaluation = await evaluate_run_original(
        session,
        run_id,
        request_key="original:" + run_id,
        run_complete=True,
    )
    await session.execute(
        text(
            "UPDATE run_components SET outcome = :outcome, reason_code = :reason "
            "WHERE run_id = :rid AND kind = 'performance'"
        ),
        {
            "rid": run_id,
            "outcome": evaluation["verdict"],
            "reason": evaluation["reason_code"]
            if evaluation["verdict"] == runs_mod.OUTCOME_NOT_TESTED
            else None,
        },
    )
    return evaluation


async def finalize_run(
    *,
    run_id: str | uuid.UUID,
    state: str,
    outcome: str | None = None,
    reason: str | None = None,
    project_id: str | uuid.UUID | None = None,
    artifacts_dir: Path | str | None = None,
    release_lease_reason: str | None = None,
    extra_event: Mapping[str, Any] | None = None,
    actor: str = "runtime",
) -> FinalizeResult:
    """把 run 收敛到终态。幂等：已是同一终态时直接返回 already_terminal。

    返回 FinalizeResult；state 不是终态时抛 409（由 domain.transition 给出）。
    """
    rid = str(run_id)
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        row = await _run_row(session, rid)
    if row is None:
        from .errors import not_found

        raise not_found("run", rid)
    pid = str(project_id or row["project_id"])

    if row["state"] in runs_mod.TERMINAL_STATES:
        return FinalizeResult(
            run_id=rid,
            state=row["state"],
            outcome=row["outcome"],
            artifact_count=0,
            sha256s={},
            already_terminal=True,
        )

    # 磁盘侧（扫描 / 哈希 / junit / report 读取）放在事务外，避免长事务读大文件；
    # 对应的数据库行在下面的事务里登记，保证"产物 + 结论 + 终态 + 事件"原子可见。
    scanned = (
        artifacts_mod.scan_artifacts(Path(artifacts_dir))
        if artifacts_dir is not None and Path(artifacts_dir).is_dir()
        else []
    )
    artifact_count = len(scanned)
    sha_map: dict[str, str] = {item.relative_key: item.sha256 for item in scanned}
    junit: dict[str, Any] = {"present": False}
    report: dict[str, Any] | None = None
    if artifacts_dir is not None and Path(artifacts_dir).is_dir():
        junit = read_junit_summary(Path(artifacts_dir) / "junit.xml")
        report = read_report_payload(artifacts_dir)

    components = list((extra_event or {}).get("components") or [])
    cases = list((extra_event or {}).get("cases") or [])
    target_state = state
    final_outcome: str | None = None
    not_tested_reason: str | None = None

    # 事件 + 组件/用例/指标 + 原始判定 + 终态 + 租约释放：同一个事务。
    async with sessionmaker() as session:
        async with session.begin():
            locked_row = (
                await session.execute(
                    text(
                        "SELECT state, outcome FROM test_runs WHERE id = :id FOR UPDATE"
                    ),
                    {"id": rid},
                )
            ).mappings().one()
            locked_state = str(locked_row["state"])
            if locked_state in runs_mod.TERMINAL_STATES:
                return FinalizeResult(
                    rid,
                    locked_state,
                    locked_row["outcome"],
                    artifact_count,
                    sha_map,
                    already_terminal=True,
                )

            if scanned:
                await artifacts_mod.register_files(
                    session,
                    project_id=pid,
                    run_id=rid,
                    files=scanned,
                    artifacts_root=settings.artifacts_dir,
                )

            has_perf = await _record_results(
                session,
                row,
                components=components,
                cases=cases,
                report=report,
                overall_state=target_state,
            )

            # 按测试类型强制：performance/joint 的 completed 必须有性能组件；
            # 否则降级为 errored，绝不产生"completed 缺 original"的新性能运行。
            perf_count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM run_components "
                        "WHERE run_id = :rid AND kind = 'performance'"
                    ),
                    {"rid": rid},
                )
            ).scalar_one()
            if target_state == runs_mod.STATE_COMPLETED:
                # 数据库里已有性能组件也算（例如重试时组件先于判定写入过）。
                has_perf = has_perf or int(perf_count) > 0
                if str(row["test_type"]) in ("performance", "joint") and int(perf_count) == 0:
                    target_state = runs_mod.STATE_ERRORED
                    final_outcome = None
                    not_tested_reason = None
                    reason = "missing_performance_component"
                    has_perf = False

            if target_state == runs_mod.STATE_COMPLETED:
                if has_perf:
                    # finalizing 内完成原始判定（显式 run_complete=True），
                    # 再把组件结论与整体聚合一起收敛；失败会回滚整个事务。
                    evaluation = await _apply_original_gate(session, rid)
                    original_count = (
                        await session.execute(
                            text(
                                "SELECT count(*) FROM gate_evaluations e "
                                "JOIN run_components rc ON rc.id = e.component_id "
                                "WHERE rc.run_id = :rid AND e.mode = 'original'"
                            ),
                            {"rid": rid},
                        )
                    ).scalar_one()
                    if int(original_count) == 0:
                        # 理论上不可达；宁可 errored 也不能 completed 缺 original。
                        target_state = runs_mod.STATE_ERRORED
                        final_outcome = None
                        reason = "original_missing"
                        not_tested_reason = None
                    else:
                        final_outcome, component_reason = await _aggregate_component_outcome(
                            session, rid
                        )
                        if final_outcome is None:
                            final_outcome = evaluation["verdict"]
                        if final_outcome == runs_mod.OUTCOME_NOT_TESTED:
                            not_tested_reason = (
                                component_reason
                                or evaluation.get("reason_code")
                                or reason
                                or "not_tested"
                            )
                            reason = not_tested_reason
                        else:
                            not_tested_reason = None
                else:
                    # UI-only（或没有性能组件）：优先用组件聚合，其次 junit/显式结论。
                    final_outcome, component_reason = await _aggregate_component_outcome(
                        session, rid
                    )
                    if final_outcome is None:
                        final_outcome = derive_outcome(
                            state=target_state,
                            explicit_outcome=outcome,
                            junit=junit,
                            reason=reason,
                        )
                        component_reason = None
                    if final_outcome == runs_mod.OUTCOME_NOT_TESTED:
                        not_tested_reason = component_reason or reason or "not_tested"
                        reason = not_tested_reason
                    else:
                        not_tested_reason = None

            payload: dict[str, Any] = {}
            if extra_event:
                payload.update({str(k): v for k, v in extra_event.items()})
            # 收敛事实最后写入：extra_event 不能覆盖 state/outcome/证据计数。
            payload.update(
                {
                    "stage": "finish",
                    "state": target_state,
                    "outcome": final_outcome,
                    "reason": reason,
                    "artifact_count": artifact_count,
                    "junit": junit,
                }
            )

            # 收敛目标可能是多步之外的终态（runner 崩溃时停留在 dispatching），
            # 先沿正向边推到前驱，再由 transition 做最后一步，绝不跳过状态机。
            current = await _advance_to(
                session, rid, locked_state, target_state, reason=reason, actor=actor
            )
            await runs_mod.transition(
                session,
                rid,
                current,
                target_state,
                outcome=final_outcome if target_state == runs_mod.STATE_COMPLETED else None,
                reason=not_tested_reason or reason,
                actor=actor,
            )
            await events_mod.append_event(
                session, project_id=pid, run_id=rid,
                source_key=events_mod.SOURCE_RECONCILER if actor == "reconciler" else "runtime",
                source_event_id=events_mod.event_id_for("finish", rid, target_state, reason),
                event_type="error" if target_state == runs_mod.STATE_ERRORED else "finish",
                payload=payload,
            )
            if release_lease_reason:
                await leases_mod.release_lease(
                    session, run_id=rid, reason=release_lease_reason
                )

    # 设备本机锁收尾（DB 租约已释放，本地锁也要清，否则下次派发会被误判 busy）
    await release_local_lock_for_run(rid)

    return FinalizeResult(
        run_id=rid,
        state=target_state,
        outcome=final_outcome,
        artifact_count=artifact_count,
        sha256s=sha_map,
    )


async def release_local_lock_for_run(run_id: str) -> bool:
    """清理该 run 占用设备的本机兜底锁。"""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        serial = (
            await session.execute(
                text(
                    """
                    SELECT er.resource_key
                      FROM test_runs tr
                      JOIN execution_resources er ON er.id = tr.resource_id
                     WHERE tr.id = :id
                    """
                ),
                {"id": str(run_id)},
            )
        ).scalar_one_or_none()
    if not serial:
        return False
    return local_leases.release(str(serial), settings.runtime_dir)


async def read_report_source(run_id: str | uuid.UUID) -> dict[str, Any] | None:
    """report 所需的 run + 应用 + 资源 + 组件快照（GET /runs/{id}/report 用）。"""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT tr.id, tr.project_id, tr.application_id, tr.platform,
                           tr.resource_id, tr.state, tr.outcome, tr.reason_code,
                           tr.not_tested_reason, tr.started_at, tr.ended_at,
                           tr.created_at, tr.revision_id, tr.config_snapshot,
                           a.name AS application_name, a.identifier AS app_identifier,
                           er.resource_key AS resource_name,
                           rp.name AS profile_name, rp.fingerprint AS profile_fingerprint,
                           trv.test_type
                      FROM test_runs tr
                      LEFT JOIN applications a ON a.id = tr.application_id
                      LEFT JOIN execution_resources er ON er.id = tr.resource_id
                      LEFT JOIN resource_profiles rp ON rp.id = tr.profile_id
                      LEFT JOIN task_revisions trv ON trv.id = tr.revision_id
                     WHERE tr.id = :id
                    """
                ),
                {"id": str(run_id)},
            )
        ).mappings().first()
    if not row:
        return None
    data = dict(row)
    # vendor 侧 report.json（业务指标 / 阈值快照）若已登记成产物，就把内容并进来，
    # 让 GET /report 的 metricsSummary / thresholdsAtRun 有真实来源，而不是空对象。
    data.update(_report_json_payload(str(run_id)))
    return data


def _report_json_payload(run_id: str) -> dict[str, Any]:
    """读取该 run 已登记的 report.json 产物内容（缺失时返回空字典）。

    这里用同步引擎：read_report_source 既被异步请求调用，也可能被同步 TestClient
    路径调用，同步引擎不挑事件循环策略（Windows Proactor 下 psycopg async 不可用）。
    """
    from sqlalchemy import create_engine

    picked: dict[str, Any] = {}
    try:
        engine = create_engine(str(settings.database_url))
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT kind, storage_key FROM artifacts "
                        " WHERE run_id = :run_id "
                        "   AND (kind = :report_kind OR logical_key LIKE :pattern) "
                        " ORDER BY logical_key"
                    ),
                    {
                        "run_id": run_id,
                        "report_kind": "report_json",
                        "pattern": "%junit.xml",
                    },
                ).mappings().all()
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001 - 报告是只读视图，取不到就降级为空
        return {}

    report_path = None
    junit_path = None
    for row in rows:
        key = str(row["storage_key"])
        if junit_path is None and key.endswith("junit.xml"):
            junit_path = artifacts_mod.resolve_storage_path(key, settings.artifacts_dir)
        elif report_path is None and key.endswith("report.json"):
            report_path = artifacts_mod.resolve_storage_path(key, settings.artifacts_dir)

    payload: dict[str, Any] = {}
    if report_path is not None and report_path.is_file():
        try:
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        if isinstance(loaded, dict):
            payload = loaded
            if isinstance(loaded.get("metricsSummary"), dict):
                picked["metricsSummary"] = loaded["metricsSummary"]
            elif isinstance(loaded.get("metrics"), dict):
                picked["metricsSummary"] = loaded["metrics"]
            if isinstance(loaded.get("thresholdsAtRun"), dict):
                picked["thresholdsAtRun"] = loaded["thresholdsAtRun"]
            elif isinstance(loaded.get("thresholds"), dict):
                picked["thresholdsAtRun"] = loaded["thresholds"]
            if isinstance(loaded.get("junit"), dict):
                picked["junit"] = loaded["junit"]
            if loaded.get("mode"):
                picked["mode"] = str(loaded["mode"])

    # junit.xml 是证据里的权威用例计数，report.json 未必带；缺的时候从这里补，
    # 报告页才能显示"跑了几个用例 / 几个失败"。
    if "junit" not in picked and junit_path is not None:
        summary = read_junit_summary(junit_path)
        if summary.get("present"):
            picked["junit"] = summary
    return picked


__all__ = [
    "FinalizeResult",
    "derive_outcome",
    "finalize_run",
    "read_junit_summary",
    "read_report_source",
    "release_local_lock_for_run",
]
