"""性能分析：GET /runs/{run_id}/metrics 与 GET /analyses。

为什么单独放在这个 router 里
----------------------------
P3 同事正在改 server/app/routers/runs.py 与 server/app/domain/runs.py。
P4 的性能端点全部集中在本文件，路径仍按 docs/plan/api-design.md
（/runs/{run_id}/metrics、/analyses），靠 router 注册顺序与 runs router 共存：

- `/runs/{run_id}/gate-evaluations` 只在 `APIRouter` 路径表里出现一次
  （main.py 先 include analyses，再 include runs），不会重复注册；
- `/runs/{run_id}/metrics` 在 runs router 里不存在，不会冲突。

数据来源
--------
全部走裸 SQL 直读表（metric_summaries / run_components / test_runs /
baselines / gate_evaluations），不依赖 P3 的 domain/runs.py 是否就绪。

三态语义
--------
- 缺失指标（metric_summaries.value IS NULL）在 API 里返回 `value: null` +
  `missing_reason`，前端据此显示「—」。**绝不返回 0**。
- 没有 component / 没有指标行时返回空数组，不伪造成 0 或空对象。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..domain.gates import (
    REASON_CODES,
    REASON_PROFILE_MISMATCH,
    evaluation_fingerprint,
    gate_outcome,
    judge_spec,
    snapshot_from_rows,
)
from ..domain.gates import build_report_view as _build_report_view
from ..domain.gates import (
    REASON_BASELINE_MISSING,
    REASON_DEVICE_DEGRADED,
    REASON_GATE_POLICY_MISSING,
    REASON_METRIC_MISSING,
    REASON_RUN_INCOMPLETE,
    REASON_SAMPLE_BELOW_MIN,
)
from ..domain.profiles import ProfileNormalizationError, normalize_profile

router = APIRouter(tags=["analyses"])

# test_runs 没有 device_profile 列：档案来自被租用资源的 resource_profiles.spec
_RUN_SQL = """
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

_COMPONENT_SQL = """
    SELECT rc.id, rc.kind, rc.adapter_key, rc.adapter_version, rc.state,
           rc.outcome, rc.reason_code, rc.summary, rc.created_at
      FROM run_components rc
     WHERE rc.run_id = :run_id
     ORDER BY rc.kind, rc.id
"""

_METRIC_SQL = """
    SELECT m.id, m.component_id, m.metric_key, m.metric_version, m.unit, m.scope,
           m.window_key, m.statistic, m.sample_count, m.value, m.missing_reason,
           m.missing_reason_text, m.created_at
      FROM metric_summaries m
     WHERE m.component_id = ANY(:component_ids)
     ORDER BY m.metric_key, m.statistic
"""

_TASK_RUNS_SQL = """
    SELECT r.id
      FROM test_runs r
      JOIN task_revisions tr ON tr.id = r.revision_id
     WHERE tr.task_id::text = :task_id
     ORDER BY r.created_at DESC, r.id DESC
     LIMIT :limit
"""

_EVALUATION_SQL = """
    SELECT e.id, e.component_id, e.policy_id, e.baseline_id, e.mode, e.verdict,
           e.reason_code, e.checks, e.created_at,
           p.name AS policy_name, p.version AS policy_version, p.rules AS policy_rules,
           b.name AS baseline_name, b.version AS baseline_version, b.profile_id,
           b.metrics_snapshot
      FROM gate_evaluations e
      LEFT JOIN gate_policies p ON p.id = e.policy_id
      LEFT JOIN baselines b ON b.id = e.baseline_id
     WHERE e.component_id = ANY(:component_ids)
     ORDER BY e.created_at DESC, e.id DESC
"""

_BASELINE_SQL = """
    SELECT b.id, b.name, b.version, b.profile_id, b.environment_id, b.suite_version_id,
           b.source_component_id, b.metrics_snapshot, b.created_at,
           rp.name AS profile_name, rp.spec AS profile_spec, rc.run_id AS source_run_id
      FROM baselines b
      LEFT JOIN resource_profiles rp ON rp.id = b.profile_id
      LEFT JOIN run_components rc ON rc.id = b.source_component_id
"""


def _profile_of(spec: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """resource_profiles.spec -> (规范化档案, 错误说明)。"""
    if not spec:
        return None, "资源档案为空"
    try:
        return normalize_profile(spec), None
    except ProfileNormalizationError as exc:
        return None, str(exc)


def _reason_text_from_checks(checks: Any) -> str | None:
    if not isinstance(checks, list):
        return None
    for item in checks:
        if isinstance(item, dict) and "reason_text" in item:
            value = item["reason_text"]
            return str(value) if value is not None else None
    return None


async def _load_run(session: AsyncSession, run_id: str) -> dict[str, Any]:
    row = (await session.execute(text(_RUN_SQL), {"run_id": run_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return dict(row)


async def _load_components(session: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    rows = (await session.execute(text(_COMPONENT_SQL), {"run_id": run_id})).mappings().all()
    return [dict(row) for row in rows]


async def _load_metrics(
    session: AsyncSession, component_ids: list[Any]
) -> dict[Any, list[dict[str, Any]]]:
    if not component_ids:
        return {}
    rows = (
        (await session.execute(text(_METRIC_SQL), {"component_ids": component_ids}))
        .mappings()
        .all()
    )
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["component_id"], []).append(dict(row))
    return grouped


def _metric_view(row: dict[str, Any]) -> dict[str, Any]:
    """一行 metric_summaries -> API 视图：缺失指标带 missing_reason，值恒为 null。"""
    return {
        "id": row["id"],
        "component_id": row["component_id"],
        "key": row["metric_key"],
        "metric_key": row["metric_key"],
        "metric_version": row["metric_version"],
        "unit": row["unit"],
        "scope": row["scope"],
        "window_key": row["window_key"],
        "statistic": row["statistic"],
        "sample_count": row["sample_count"],
        # 缺失指标这里是 None，前端显示「—」而不是 0
        "value": row["value"],
        "supported": row["missing_reason"] != "device_unsupported",
        "missing_reason": row["missing_reason"],
        "missing_reason_text": row["missing_reason_text"],
    }


def _is_complete(run: dict[str, Any]) -> bool:
    return run["state"] == "completed"


@router.get("/runs/{run_id}/metrics")
async def get_run_metrics(
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """运行级指标汇总：按组件/指标分组返回 metric_summaries 原始行。

    缺失指标（value IS NULL）返回 `value: null` + `missing_reason`，
    设备不支持的指标（device_unsupported）额外带 `supported: false`。
    """
    run = await _load_run(session, run_id)
    components = await _load_components(session, run["id"])
    by_component = await _load_metrics(session, [c["id"] for c in components])

    component_views = []
    for component in components:
        rows = by_component.get(component["id"], [])
        metrics = [_metric_view(row) for row in rows]
        component_views.append(
            {
                "id": component["id"],
                "kind": component["kind"],
                "adapter_key": component["adapter_key"],
                "adapter_version": component["adapter_version"],
                "state": component["state"],
                "outcome": component["outcome"],
                "reason_code": component["reason_code"],
                "summary": component["summary"] or {},
                "metrics": metrics,
                "metric_count": len(metrics),
                # 显式给出「有值 / 缺失」两个计数，前端不用自己过滤 null
                "measured_count": sum(1 for m in metrics if m["value"] is not None),
                "missing_count": sum(1 for m in metrics if m["value"] is None),
            }
        )

    device_profile, profile_error = _profile_of(run["profile_spec"])
    # 顶层 metrics 是「所有组件」的扁平列表（前端指标表直接用），
    # components[].metrics 是同一批行按组件分组（前端按组件展开时用）。
    flat_metrics = [metric for view in component_views for metric in view["metrics"]]
    return {
        "run_id": run["id"],
        "state": run["state"],
        "outcome": run["outcome"],
        "reason_code": run["reason_code"],
        "device_profile": device_profile,
        "device_profile_raw": (run["profile_spec"] or None),
        "device_profile_error": profile_error,
        "metrics": flat_metrics,
        "components": component_views,
        "metric_total": sum(c["metric_count"] for c in component_views),
        "measured_total": sum(c["measured_count"] for c in component_views),
        "missing_total": sum(c["missing_count"] for c in component_views),
    }


async def _analysis_for_run(
    session: AsyncSession, run: dict[str, Any], *, evaluation_id: str | None = None
) -> dict[str, Any]:
    components = await _load_components(session, run["id"])
    component_ids = [c["id"] for c in components]
    by_component = await _load_metrics(session, component_ids)

    evaluations = (
        (await session.execute(text(_EVALUATION_SQL), {"component_ids": component_ids}))
        .mappings()
        .all()
        if component_ids
        else []
    )
    original = None
    for row in evaluations:
        if row["mode"] == "original":
            original = row
            break
    # AC-CONTRACT-04：默认展示**原始判定**；最新试算不会悄悄顶掉它。
    # 只有调用方显式给 evaluation_id 才切换到那条判定（通常是一次 reanalysis）。
    chosen = original
    if evaluation_id:
        chosen = next(
            (row for row in evaluations if str(row["id"]) == str(evaluation_id)), None
        )
        if chosen is None:
            raise HTTPException(status_code=404, detail="evaluation not found for this run")

    device_profile, profile_error = _profile_of(run["profile_spec"])
    perf_component = next(
        (c for c in components if c["kind"] == "performance"),
        components[0] if components else None,
    )

    metric_views: list[dict[str, Any]] = []
    if perf_component is not None:
        for row in by_component.get(perf_component["id"], []):
            if row["statistic"] != "median":
                continue
            metric_views.append(
                {
                    "key": row["metric_key"],
                    "metric_key": row["metric_key"],
                    "statistic": row["statistic"],
                    "scope": row["scope"],
                    "window_key": row["window_key"],
                    "metric_version": row["metric_version"],
                    "median": row["value"],
                    "value": row["value"],
                    "unit": row["unit"],
                    "sample_count": row["sample_count"],
                    "supported": row["missing_reason"] != "device_unsupported",
                    "missing_reason": row["missing_reason"],
                    "missing_reason_text": row["missing_reason_text"],
                }
            )

    return {
        "run": {
            "id": run["id"],
            "application_id": run["application_id"],
            "application_name": run["application_name"],
            "task_id": run["task_id"],
            "task_name": run["task_name"],
            "test_type": run["test_type"],
            "platform": run["platform"],
            "state": run["state"],
            "outcome": run["outcome"],
            "reason_code": run["reason_code"],
            "not_tested_reason": run["not_tested_reason"],
            "started_at": run["started_at"],
            "ended_at": run["ended_at"],
            "created_at": run["created_at"],
        },
        "verdict": chosen["verdict"] if chosen else None,
        "mode": chosen["mode"] if chosen else None,
        # 缺 original 时不兜底 reanalysis：明确告诉前端"还没有原始判定"
        "original_missing": original is None,
        "selected_evaluation_id": str(chosen["id"]) if chosen else None,
        "reason": chosen["reason_code"] if chosen else None,
        "reason_text": _reason_text_from_checks(chosen["checks"]) if chosen else None,
        "checks": (chosen["checks"] if chosen and isinstance(chosen["checks"], list) else []),
        "metrics": metric_views,
        "thresholds": (chosen["policy_rules"] if chosen else None),
        "context": {
            "device_profile": device_profile,
            "device_profile_error": profile_error,
            "window": (
                f"{run['started_at']}/{run['ended_at']}"
                if run["started_at"] and run["ended_at"]
                else None
            ),
            "statistic": "median",
            "platform": run["platform"],
        },
        "components": [
            {
                "id": c["id"],
                "kind": c["kind"],
                "state": c["state"],
                "outcome": c["outcome"],
                "reason_code": c["reason_code"],
            }
            for c in components
        ],
        "evaluations": [
            {
                "id": row["id"],
                "component_id": row["component_id"],
                "mode": row["mode"],
                "verdict": row["verdict"],
                "reason_code": row["reason_code"],
                "reason_text": _reason_text_from_checks(row["checks"]),
                "policy_id": row["policy_id"],
                "policy_version": row["policy_version"],
                "baseline_id": row["baseline_id"],
                "baseline_name": row["baseline_name"],
                "baseline_version": row["baseline_version"],
                "created_at": row["created_at"],
            }
            for row in evaluations
        ],
        "baseline_options": await _baseline_options(session, run, device_profile),
        "trial": None,
    }


async def _baseline_options(
    session: AsyncSession, run: dict[str, Any], device_profile: str | None
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(_BASELINE_SQL + " WHERE b.application_id = :app_id ORDER BY b.created_at DESC"),
                {"app_id": run["application_id"]},
            )
        )
        .mappings()
        .all()
    )
    options = []
    for row in rows:
        profile, error = _profile_of(row["profile_spec"])
        same = bool(profile and device_profile and profile == device_profile)
        options.append(
            {
                "id": row["id"],
                "baseline_name": row["name"],
                "version": row["version"],
                "source_run_id": row["source_run_id"],
                "profile": profile,
                "profile_error": error,
                "same_profile": same,
            }
        )
    return options


@router.get("/analyses")
async def list_analyses(
    run_id: Annotated[str | None, Query()] = None,
    task_id: Annotated[str | None, Query()] = None,
    evaluation_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """分析页数据：`?run_id=` 单次运行，`?task_id=` 该任务最近若干次运行的趋势。

    默认展示原始判定；`?evaluation_id=` 显式选择某条判定（通常是一次试算）。
    """
    if evaluation_id and task_id and not run_id:
        raise HTTPException(status_code=422, detail="evaluation_id 只能与 run_id 搭配使用")
    if not run_id and not task_id:
        raise HTTPException(status_code=422, detail="必须提供 run_id 或 task_id")
    if run_id and task_id:
        raise HTTPException(status_code=422, detail="run_id 与 task_id 只能二选一")

    if run_id:
        run = await _load_run(session, run_id)
        # run_id 是「单次运行分析页」，直接返回该分析本身（docs/plan/api-design.md:195）；
        # task_id 是「趋势列表」，返回 {items, total}。
        return await _analysis_for_run(session, run, evaluation_id=evaluation_id)

    ids = [
        row["id"]
        for row in (
            await session.execute(text(_TASK_RUNS_SQL), {"task_id": task_id, "limit": limit})
        ).mappings()
    ]
    items = []
    for single in ids:
        run = await _load_run(session, str(single))
        items.append(await _analysis_for_run(session, run))
    # 顶层也带上最新一次运行的分析（run 字段），列表在 items 里，前端首屏不用再取一次
    latest = items[0] if items else {}
    return {**latest, "items": items, "total": len(items)}


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
    run_profile, _ = _profile_of(run_profile_spec)
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
        profile, _ = _profile_of(row["profile_spec"])
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
    return run_ids[0]


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
    return await _evaluation_response(session, row, created=True)


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


async def _baseline_row(session: AsyncSession, baseline_id: str):
    row = (
        await session.execute(
            text(_BASELINE_SQL + " WHERE b.id::text = :baseline_id"),
            {"baseline_id": baseline_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="baseline not found")
    return dict(row)


def _snapshot_metrics(snapshot: Any) -> dict[str, Any]:
    """baselines.metrics_snapshot -> vendor baseline_data。

    快照既可能是 {metric: {value, sourceRunId}} 形态，也可能是
    metric_summaries 行数组（落库前用 snapshot_from_rows 生成）。两种都接受。
    """
    if isinstance(snapshot, list):
        return snapshot_from_rows([row for row in snapshot if isinstance(row, dict)])
    if isinstance(snapshot, dict):
        data: dict[str, Any] = {}
        for key, raw in snapshot.items():
            if isinstance(raw, dict) and raw.get("value") is not None:
                data[str(key)] = {**raw, "value": float(raw["value"])}
            elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
                data[str(key)] = {"value": float(raw), "sourceRunId": None}
        return data
    return {}


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
    """
    if not request_key or not isinstance(request_key, str):
        raise HTTPException(status_code=422, detail="request_key 必填")

    run = await _load_run(session, run_id)
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
        return await _evaluation_response(session, existing["id"], created=False)

    components = await _load_components(session, run["id"])
    perf_components = [c for c in components if c["kind"] == "performance"] or components
    if not perf_components:
        raise HTTPException(status_code=409, detail="本次运行没有运行组件，无法判定")
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
        raise HTTPException(
            status_code=409,
            detail=f"运行尚未完成（当前状态 {run['state']}），无法判定；完成后再试算或等待 finalizing 内的原始判定",
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
            raise HTTPException(status_code=404, detail="gate policy not found")
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
    baseline_run = await _load_run(session, str(baseline_run_id))

    baseline_component = next(
        (
            c
            for c in await _load_components(session, baseline_run["id"])
            if c["kind"] == "performance"
        ),
        None,
    )
    baseline_rows = (
        await _load_metrics(session, [baseline_component["id"]]) if baseline_component else {}
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

    run_profile, _ = _profile_of(run["profile_spec"])
    baseline_profile, _ = _profile_of(baseline_run["profile_spec"])
    summary_rows = (await _load_metrics(session, [component["id"]])).get(component["id"], [])

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
    return await _evaluation_response(session, row, created=True)


@router.post("/runs/{run_id}/gate-evaluations", status_code=201)
async def create_gate_evaluation(
    run_id: str,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """试算 = 新增判定行。**绝不 UPDATE original 行。**

    请求体（docs/plan/api-design.md:201）：`{request_key, policy_id, baseline_run_id}`。
    - request_key 幂等：同 project 下重复 request_key 直接返回已存在的那一行；
    - 该组件还没有 original 行 → 本次落 mode='original'（「首次判定」）；
      已有 original → 本次落 mode='reanalysis'（「改阈值重算」），
      两条路径都只 INSERT，绝不 UPDATE 既有行；
    - policy_id / baseline_run_id 缺省时由平台补：取该应用最新策略版本，
      基线取同档案的最新基线（没有同档案基线则退回最新基线，判定自然给出 profile_mismatch）；
      两者都补不出来 → not_tested + gate_policy_missing（不是「通过」）；
    - 档案不可比不拦截为 422，判定照做（not_tested + profile_mismatch），
      因为「跨档案」本身就是要记录的事实。
    """
    request_key = payload.get("request_key")
    if not request_key or not isinstance(request_key, str):
        raise HTTPException(status_code=422, detail="request_key 必填")
    return await evaluate_run_original(
        session,
        run_id,
        request_key=request_key,
        policy_id=payload.get("policy_id"),
        baseline_run_id=payload.get("baseline_run_id"),
    )


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _text_id(value: Any) -> Any:
    """UUID -> str：checks / 响应体里不能留非 JSON 类型。"""
    return str(value) if value is not None else None


async def _evaluation_response(session: AsyncSession, evaluation_id: Any, *, created: bool):
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
    payload = {
        "id": _text_id(row["id"]),
        "evaluation_id": _text_id(row["id"]),
        "mode": row["mode"],
        "verdict": row["verdict"],
        "reason": row["reason_code"],
        "reason_code": row["reason_code"],
        "reason_text": _reason_text_from_checks(checks),
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
    # 幂等重放用 200 与"真的新建了"的 201 区分（api-design.md §1.3 同一约定）
    if created:
        return payload
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=200, content=jsonable_encoder(payload))
