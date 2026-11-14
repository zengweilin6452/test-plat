"""性能门禁判定核心（自 routers/analyses.py 迁入，P2-02 分层）。

为什么抽出来
------------
runtime.finalize_run 的 finalizing 事务要调用「原始判定」，此前在函数内
import routers.analyses.evaluate_run_original —— Runtime → Router 是反向
依赖。判定核心（读 run/组件/指标 → 选策略/基线 → judge → 落判定行）放在
services 层，两侧调用方向全部变成正向：

    routers/analyses.py（HTTP 解析 / 响应映射） -> services/analysis.py
    runtime.py（finalizing 事务）              -> services/analysis.py

错误约定：本模块抛 app.errors.ApiError，status/code/message 与迁移前
HTTPException 经 main._STATUS_CODES 映射后的信封逐字段一致
（422 -> validation_error、404 -> not_found、409 -> state_conflict、
details={}），路由层无需翻译。

响应约定：evaluate_run_original 返回判定载荷 dict（含 "created" 布尔），
不再返回 JSONResponse —— 200/201 的区分是 HTTP 语义，由路由层据
"created" 决定（幂等重放 200，新建 201）。

数据口径（与迁移前完全一致，勿改）：
- 缺失指标 value IS NULL 时按 missing_reason 呈现，绝不返回 0；
- 同一组件 original 只有一条（gate_one_original 部分唯一索引兜底）；
- 判定只 INSERT，绝不 UPDATE 既有行（三态不可逆，证据只能追加）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.gates import (
    REASON_BASELINE_MISSING,
    REASON_GATE_POLICY_MISSING,
    REASON_PROFILE_MISMATCH,
    evaluation_fingerprint,
    gate_outcome,
    judge_spec,
    snapshot_from_rows,
)
from ..domain.gates import build_report_view as _build_report_view
from ..errors import ApiError

# test_runs 没有 device_profile 列：档案来自被租用资源的 resource_profiles.spec
RUN_SQL = """
    SELECT r.id, r.project_id, r.application_id, r.platform, r.revision_id,
           r.state, r.outcome, r.reason_code, r.not_tested_reason,
           r.started_at, r.ended_at, r.created_at, r.profile_id, r.config_snapshot,
           a.name AS application_name,
           tr.task_id, tr.test_type,
           t.name AS task_name,
           rp.name AS profile_name, rp.spec AS profile_spec
      FROM test_runs r
      JOIN applications a ON a.id = r.application_id
      LEFT JOIN task_revisions tr ON tr.id = r.revision_id
      LEFT JOIN test_tasks t ON t.id = tr.task_id
      LEFT JOIN resource_profiles rp ON rp.id = r.profile_id
     WHERE r.id::text = :run_id
"""

COMPONENT_SQL = """
    SELECT rc.id, rc.kind, rc.adapter_key, rc.adapter_version, rc.state,
           rc.outcome, rc.reason_code, rc.summary, rc.created_at
      FROM run_components rc
     WHERE rc.run_id = :run_id
     ORDER BY rc.kind, rc.id
"""

METRIC_SQL = """
    SELECT m.id, m.component_id, m.metric_key, m.metric_version, m.unit, m.scope,
           m.window_key, m.statistic, m.sample_count, m.value, m.missing_reason,
           m.missing_reason_text, m.created_at
      FROM metric_summaries m
     WHERE m.component_id = ANY(:component_ids)
     ORDER BY m.metric_key, m.statistic
"""


def profile_of(spec: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """resource_profiles.spec -> (规范化档案, 错误说明)。"""
    from ..domain.profiles import ProfileNormalizationError, normalize_profile

    if not spec:
        return None, "资源档案为空"
    try:
        return normalize_profile(spec), None
    except ProfileNormalizationError as exc:
        return None, str(exc)


def reason_text_from_checks(checks: Any) -> str | None:
    if not isinstance(checks, list):
        return None
    for item in checks:
        if isinstance(item, dict) and "reason_text" in item:
            value = item["reason_text"]
            return str(value) if value is not None else None
    return None


async def load_run(session: AsyncSession, run_id: str) -> dict[str, Any]:
    row = (await session.execute(text(RUN_SQL), {"run_id": run_id})).mappings().first()
    if row is None:
        raise ApiError(404, "not_found", "run not found", {})
    return dict(row)


async def load_components(session: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    rows = (await session.execute(text(COMPONENT_SQL), {"run_id": run_id})).mappings().all()
    return [dict(row) for row in rows]


async def load_metrics(
    session: AsyncSession, component_ids: list[Any]
) -> dict[Any, list[dict[str, Any]]]:
    if not component_ids:
        return {}
    rows = (
        (await session.execute(text(METRIC_SQL), {"component_ids": component_ids}))
        .mappings()
        .all()
    )
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["component_id"], []).append(dict(row))
    return grouped


def _is_complete(run: dict[str, Any]) -> bool:
    return run["state"] == "completed"


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _text_id(value: Any) -> Any:
    """UUID -> str：checks / 响应体里不能留非 JSON 类型。"""
    return str(value) if value is not None else None


async def _latest_policy_id(session: AsyncSession, application_id: Any) -> Any:
    """该应用最新版本的策略 id（没有则 None）。"""
    return (
        await session.execute(
            text(
                "SELECT id FROM gate_policies WHERE application_id = :app_id "
                "ORDER BY version DESC, created_at DESC, id DESC LIMIT 1"
            ),
            {"app_id": application_id},
        )
    ).scalar()


async def _default_baseline_run_id(
    session: AsyncSession, project_id: Any, application_id: Any, run_profile_spec: Any
) -> Any:
    """缺省基线：优先同档案的最新基线，其次该应用最新基线（跨档案由判定给 profile_mismatch）。"""
    run_profile, _ = profile_of(run_profile_spec)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT b.profile_id, b.metrics_snapshot, p.spec AS profile_spec "
                    "FROM baselines b "
                    "LEFT JOIN resource_profiles p ON p.id = b.profile_id "
                    "WHERE b.project_id = :project_id AND b.application_id = :app_id "
                    "ORDER BY b.created_at DESC"
                ),
                {"project_id": project_id, "app_id": application_id},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return None
    chosen = None
    for row in rows:
        profile, _ = profile_of(row["profile_spec"])
        if run_profile and profile and profile == run_profile:
            chosen = row
            break
    # 工单 13：没有同档案基线就记录缺失，不回退跨档案——跨档案比较没有可比性，
    # 交给判定流程报 baseline_missing / profile_mismatch，而不是悄悄比一个错误档案。
    if chosen is None:
        return None
    snapshot = chosen["metrics_snapshot"]
    run_ids = _snapshot_run_ids(snapshot)
    if not run_ids:
        return None
    # 只解析合法 UUID：快照是历史 JSON，脏值不应把整个判定打成 500
    import uuid as _uuid_mod

    def _is_uuid(value: Any) -> bool:
        try:
            _uuid_mod.UUID(str(value))
        except (TypeError, ValueError):
            return False
        return True

    run_ids = [value for value in run_ids if _is_uuid(value)]
    if not run_ids:
        return None
    # 工单审查修复：旧基线的快照行可能只带 component_id（历史写入缺
    # source_run_id）——把它兜底解析回所属运行，而不是当成不存在的运行。
    params = {f"id{i}": str(value) for i, value in enumerate(run_ids)}
    resolved = (
        await session.execute(
            text(
                "SELECT x.id::text AS candidate, r.id::text AS run_id "
                "FROM (SELECT "
                + " UNION ALL ".join(
                    f"CAST(:id{i} AS uuid) AS id" for i in range(len(run_ids))
                )
                + ") x "
                "LEFT JOIN run_components rc ON rc.id = x.id "
                "LEFT JOIN test_runs r ON r.id = COALESCE(rc.run_id, x.id)"
            ),
            params,
        )
    ).mappings().all()
    by_candidate = {row["candidate"]: row["run_id"] for row in resolved}
    for candidate in run_ids:
        run_id = by_candidate.get(str(candidate))
        if run_id:
            return run_id
    return None


def _snapshot_run_ids(snapshot: Any) -> list[Any]:
    import json as _json_mod

    data = snapshot
    if isinstance(data, str):
        data = _json_mod.loads(data)
    if isinstance(data, dict) and isinstance(data.get("metrics"), (list, dict)):
        data = data["metrics"]
    found: list[Any] = []
    values = data.values() if isinstance(data, dict) else (data if isinstance(data, list) else [])
    for entry in values:
        if not isinstance(entry, dict):
            continue
        run_id = entry.get("source_run_id") or entry.get("sourceRunId")
        if run_id and run_id not in found:
            found.append(run_id)
    return found


async def _missing_policy_placeholder(session: AsyncSession, application_id: Any) -> Any:
    """「没有策略」占位策略行。

    gate_evaluations.policy_id 是 NOT NULL，而「缺策略」本身就是要记录的事实。
    这里落一条 version=1 的 __missing_policy__ 策略（rules={}），让 not_tested 判定
    有归属；它不会和被判定应用的真实策略混在一起（同应用下 name 唯一 + version 唯一），
    也绝不 UPDATE 任何既有策略行。
    """
    existing = (
        await session.execute(
            text(
                "SELECT id FROM gate_policies "
                "WHERE project_id = (SELECT project_id FROM applications WHERE id = :app_id) "
                "AND application_id = :app_id AND name = '__missing_policy__'"
            ),
            {"app_id": application_id},
        )
    ).scalar()
    if existing is not None:
        return existing
    return (
        await session.execute(
            text(
                """
                INSERT INTO gate_policies
                    (id, project_id, application_id, name, version, rules)
                SELECT gen_random_uuid(), a.project_id, a.id,
                       '__missing_policy__', 1, '{}'::jsonb
                  FROM applications a WHERE a.id = :app_id
                RETURNING id
                """
            ),
            {"app_id": application_id},
        )
    ).scalar()


async def _not_tested_evaluation(
    session: AsyncSession,
    *,
    run: dict[str, Any],
    component: dict[str, Any],
    mode: str,
    request_key: str,
    policy_id: Any,
    reason_code: str,
    reason_text: str,
) -> dict[str, Any]:
    """建一条 not_tested 判定（缺策略/缺基线）：三态门禁不压二态，绝不返回 passed。

    gate_evaluations.policy_id 是 NOT NULL，而「缺策略」恰恰就是要记录的事实，
    所以这里落一条**占位策略**（version=0，不参与 GET /gate-policies 的版本序列），
    判定依据记在 checks.reason_text 里，绝不改写任何既有策略行。
    """
    if policy_id is None:
        policy_id = await _missing_policy_placeholder(session, run["application_id"])
    checks = [{"reason_code": reason_code, "reason_text": reason_text}]
    row = (
        await session.execute(
            text(
                """
                INSERT INTO gate_evaluations
                    (id, project_id, component_id, policy_id, baseline_id, mode,
                     request_key, verdict, reason_code, checks)
                VALUES
                    (gen_random_uuid(), :project_id, :component_id, :policy_id, NULL,
                     :mode, :request_key, 'not_tested', :reason_code,
                     CAST(:checks AS jsonb))
                RETURNING id
                """
            ),
            {
                "project_id": run["project_id"],
                "component_id": component["id"],
                "policy_id": policy_id,
                "mode": mode,
                "request_key": request_key,
                "reason_code": reason_code,
                "checks": _json(checks),
            },
        )
    ).scalar()
    return await _evaluation_payload(session, row, created=True)


async def _evaluation_payload(session: AsyncSession, evaluation_id: Any, *, created: bool) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT e.id, e.component_id, e.policy_id, e.baseline_id, e.mode, e.verdict, "
                "e.reason_code, e.checks, e.request_key, e.created_at, "
                "p.name AS policy_name, p.version AS policy_version "
                "FROM gate_evaluations e LEFT JOIN gate_policies p ON p.id = e.policy_id "
                "WHERE e.id = :id"
            ),
            {"id": evaluation_id},
        )
    ).mappings().first()
    checks = row["checks"] if isinstance(row["checks"], list) else []
    return {
        "id": _text_id(row["id"]),
        "evaluation_id": _text_id(row["id"]),
        "mode": row["mode"],
        "verdict": row["verdict"],
        "reason": row["reason_code"],
        "reason_code": row["reason_code"],
        "reason_text": reason_text_from_checks(checks),
        "checks": checks,
        "policy_id": _text_id(row["policy_id"]),
        "policy_version": row["policy_version"],
        "baseline_id": _text_id(row["baseline_id"]),
        "request_key": row["request_key"],
        "created_at": row["created_at"],
        "created": created,
        # 试算不改写历史报告：original 行一字未动
        "note": "试算不改写历史报告",
        "profile_mismatch_reason": REASON_PROFILE_MISMATCH,
    }


async def evaluate_run_original(
    session: AsyncSession,
    run_id: str,
    *,
    request_key: str,
    policy_id: Any = None,
    baseline_run_id: Any = None,
    run_complete: bool | None = None,
) -> dict[str, Any]:
    """原始判定核心（路由与 finalizing 事务共用）。

    `run_complete=None` 时按库内 state 判断（外部试算路径）；finalizing 内调用
    必须显式传 `run_complete=True`，因为此时 run 还没有 transition 到 completed。
    只 INSERT 判定行，绝不 UPDATE 既有 original。
    返回判定载荷 dict（"created" 区分新建/幂等重放，HTTP 状态由路由层定）。
    """
    if not request_key or not isinstance(request_key, str):
        raise ApiError(422, "validation_error", "request_key 必填", {})

    run = await load_run(session, run_id)
    existing = (
        await session.execute(
            text(
                "SELECT id FROM gate_evaluations "
                "WHERE project_id = :project_id AND request_key = :request_key"
            ),
            {"project_id": run["project_id"], "request_key": request_key},
        )
    ).mappings().first()
    if existing is not None:
        return await _evaluation_payload(session, existing["id"], created=False)

    components = await load_components(session, run["id"])
    perf_components = [c for c in components if c["kind"] == "performance"] or components
    if not perf_components:
        raise ApiError(409, "state_conflict", "本次运行没有运行组件，无法判定", {})
    component = perf_components[0]
    # 同一组件上 original 只有一条（部分唯一索引 gate_one_original 兜底），
    # 所以「还没有 original」= 这是该组件的首次判定。
    # 「首次判定」= 还没有任何判定 + 请求也没指定要重算。
    # 显式带了 policy_id（试算/改阈值重算）一律落 reanalysis：改阈值绝不能覆盖
    # 原始判定，哪怕该组件还没有 original 行（三态不可逆，证据只能追加）。
    # 反过来，该组件还没有 original 时，无论请求是否点名策略，本次都落 original
    # （部分唯一索引 gate_one_original 要求每组件恰好一条基线判定）。
    original_exists = (
        await session.execute(
            text(
                "SELECT 1 FROM gate_evaluations "
                "WHERE project_id = :project_id AND component_id = :component_id "
                "AND mode = 'original' LIMIT 1"
            ),
            {"project_id": run["project_id"], "component_id": component["id"]},
        )
    ).first() is not None
    # 工单 14：已终态的历史运行即使缺 original，补判定也只能是 reanalysis——
    # "原始判定"意味着执行时点的首轮结论，事后补造等于伪造。finalizing 内的
    # 首轮判定（runtime._apply_original_gate）不受影响：那时 run 还没终态。
    mode = (
        "reanalysis"
        if original_exists or run["state"] in ("completed", "errored", "cancelled")
        else "original"
    )
    if run_complete is None and run["state"] not in ("completed", "errored", "cancelled"):
        # 外部试算打到未完成的运行：没有可判定的输入，拒绝并说明缺项，不预写判定。
        # （finalizing 内的首轮判定显式传 run_complete=True，不走这条拒绝。）
        raise ApiError(
            409,
            "state_conflict",
            f"运行尚未完成（当前状态 {run['state']}），无法判定；完成后再试算或等待 finalizing 内的原始判定",
            {},
        )

    explicit_policy = bool(policy_id)
    if not policy_id:
        # AC-GATE-01：排队时固定在 config_snapshot.gate_policy 的策略版本，
        # 排队期间新版本不影响这次执行的判定依据；旧运行没有快照才回退"最新"。
        snapshot_policy = run.get("config_snapshot")
        snapshot_policy = (
            snapshot_policy.get("gate_policy")
            if isinstance(snapshot_policy, dict)
            else None
        )
        if isinstance(snapshot_policy, dict) and snapshot_policy.get("id"):
            policy_id = snapshot_policy["id"]
        else:
            policy_id = await _latest_policy_id(session, run["application_id"])
    # 缺策略/缺基线不是「通过」，而是 not_tested（三态门禁不压二态）。
    # 两者原因分开报告（工单 12）；策略先核验再谈基线：not_tested 行的 policy_id
    # 必须是真实存在的行，显式给来的失效 id 不能被引用进判定记录。
    policy = (
        await session.execute(
            text(
                "SELECT id, project_id, application_id, name, version, rules "
                "FROM gate_policies WHERE id::text = :policy_id"
            ),
            {"policy_id": str(policy_id)},
        )
    ).mappings().first()
    if policy is None:
        if explicit_policy:
            # 显式指定的策略版本失效：按不存在拒绝，绝不偷偷替换成最新版本
            raise ApiError(404, "not_found", "gate policy not found", {})
        return await _not_tested_evaluation(
            session,
            run=run,
            component=component,
            mode=mode,
            request_key=request_key,
            policy_id=None,
            reason_code=REASON_GATE_POLICY_MISSING,
            reason_text="缺少门禁策略，无法判定",
        )
    if not baseline_run_id:
        baseline_run_id = await _default_baseline_run_id(
            session, run["project_id"], run["application_id"], run["profile_spec"]
        )
    if not baseline_run_id:
        return await _not_tested_evaluation(
            session,
            run=run,
            component=component,
            mode=mode,
            request_key=request_key,
            policy_id=policy["id"],
            reason_code=REASON_BASELINE_MISSING,
            reason_text="缺少可比基线，无法判定",
        )
    baseline_run = await load_run(session, str(baseline_run_id))

    baseline_component = next(
        (
            c
            for c in await load_components(session, baseline_run["id"])
            if c["kind"] == "performance"
        ),
        None,
    )
    baseline_rows = (
        await load_metrics(session, [baseline_component["id"]]) if baseline_component else {}
    )
    baseline_metrics = snapshot_from_rows(baseline_rows.get(baseline_component["id"], []) if baseline_component else [])

    baseline_id = None
    if baseline_component is not None:
        baseline_id = (
            await session.execute(
                text(
                    "SELECT id FROM baselines WHERE source_component_id = :component_id "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"component_id": baseline_component["id"]},
            )
        ).scalar()
    if baseline_id is None:
        # 基线运行本身没有建过 baselines 行（只按 run 比）：挂该应用最新基线，
        # 解析不出就留 NULL —— 判定依据仍来自 baseline_run 的指标快照。
        baseline_id = (
            await session.execute(
                text(
                    "SELECT id FROM baselines WHERE project_id = :project_id "
                    "AND application_id = :app_id ORDER BY created_at DESC LIMIT 1"
                ),
                {"project_id": run["project_id"], "app_id": run["application_id"]},
            )
        ).scalar()

    run_profile, _ = profile_of(run["profile_spec"])
    baseline_profile, _ = profile_of(baseline_run["profile_spec"])
    summary_rows = (await load_metrics(session, [component["id"]])).get(component["id"], [])

    report = _build_report_view(
        run_id=str(run["id"]),
        device_profile=(run["profile_spec"] or run_profile),
        started_at=run["started_at"],
        stopped_at=run["ended_at"],
        summary_rows=summary_rows,
    )
    spec = judge_spec(
        baseline_name=f"run:{baseline_run['id']}",
        policy_rules=policy["rules"],
        baseline_profile=baseline_profile,
        baseline_metrics=baseline_metrics,
    )
    outcome = gate_outcome(
        report=report,
        spec=spec,
        run_complete=_is_complete(run) if run_complete is None else bool(run_complete),
        policy_rules=policy["rules"],
        run_profile=(run["profile_spec"] or run_profile),
        baseline_profile=baseline_profile,
        baseline_data=baseline_metrics,
    )

    checks = outcome.as_checks_payload()
    fingerprint = evaluation_fingerprint(
        mode=mode,
        policy_id=policy["id"],
        policy_version=policy["version"],
        rules=policy["rules"],
        baseline_id=baseline_id,
        baseline_name=f"run:{baseline_run['id']}",
        baseline_version=None,
        baseline_profile=baseline_profile,
        verdict=outcome.verdict,
        reason_code=outcome.reason_code,
        checks=checks,
    )
    checks = checks + [{"evaluation_sha256": fingerprint}]

    row = (
        await session.execute(
            text(
                """
                INSERT INTO gate_evaluations
                    (id, project_id, component_id, policy_id, baseline_id, mode,
                     request_key, verdict, reason_code, checks)
                VALUES
                    (gen_random_uuid(), :project_id, :component_id, :policy_id,
                     :baseline_id, :mode,
                     :request_key, :verdict, :reason_code, CAST(:checks AS jsonb))
                RETURNING id
                """
            ),
            {
                "project_id": run["project_id"],
                "component_id": component["id"],
                "policy_id": policy["id"],
                "baseline_id": baseline_id,
                "mode": mode,
                "request_key": request_key,
                "verdict": outcome.verdict,
                "reason_code": outcome.reason_code,
                "checks": _json(checks),
            },
        )
    ).scalar()
    return await _evaluation_payload(session, row, created=True)


__all__ = [
    "COMPONENT_SQL",
    "METRIC_SQL",
    "RUN_SQL",
    "evaluate_run_original",
    "load_components",
    "load_metrics",
    "load_run",
    "profile_of",
    "reason_text_from_checks",
]
