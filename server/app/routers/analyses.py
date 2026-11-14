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

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..dependencies import require_client_header
from ..domain.gates import snapshot_from_rows
from ..domain.metrics_view import median_metric_view
from ..domain.metrics_view import metric_row_view as _metric_view
from ..services.analysis import (
    evaluate_run_original,
)
from ..services.analysis import (
    load_components as _load_components,
)
from ..services.analysis import (
    load_metrics as _load_metrics,
)
from ..services.analysis import (
    load_run as _load_run,
)
from ..services.analysis import (
    profile_of as _profile_of,
)
from ..services.analysis import (
    reason_text_from_checks as _reason_text_from_checks,
)

router = APIRouter(tags=["analyses"])

# 读 run/组件/指标的 SQL 与加载器已随判定核心迁到 services/analysis.py（P2-02），
# 本文件经顶部别名导入继续使用（_load_run / _load_components / _load_metrics /
# _profile_of），路由层不再自带业务闭包。

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

#: 泄漏趋势的指标固定为 PSS 中位数（vendor mobile_perf leak 模块同口径）
LEAK_METRIC_KEY = "mem_pss_mb"
LEAK_MIN_RUNS = 3


def _ols_slope_mb_per_day(points: list[tuple[float, float]]) -> float | None:
    """普通最小二乘斜率（x=小时，y=MB）→ MB/天；x 全相等时返回 None。"""
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator <= 0:
        return None
    slope_per_hour = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    return slope_per_hour * 24.0


async def _leak_trend(
    session: AsyncSession, run: dict[str, Any], device_profile: str | None
) -> dict[str, Any] | None:
    """内存泄漏趋势（vendor mobile_perf leak 模块的平台侧等价实现）。

    vendor 的 `PerfKit.leak_trend` 读自己的 SQLite store，而平台每次运行的
    store 都落在各自产物目录里（互相看不到），跨 run 序列只能从
    metric_summaries 取：同应用 + 同设备档案的历史 mem_pss_mb median 做 OLS。
    置信度三态与 vendor 一致：<3 次 insufficient、跨度 0 insufficient、
    <24h low、其余 ok。斜率只做参考展示，门禁结论仍由 gate_evaluations 给。
    """
    if not device_profile:
        return None
    rows = (
        await session.execute(
            text(
                "SELECT tr.started_at, ms.value, rp.spec AS profile_spec"
                "  FROM metric_summaries ms"
                "  JOIN run_components rc ON rc.project_id = ms.project_id"
                "    AND rc.id = ms.component_id"
                "  JOIN test_runs tr ON tr.project_id = rc.project_id AND tr.id = rc.run_id"
                "  JOIN resource_profiles rp ON rp.id = tr.profile_id"
                " WHERE ms.metric_key = :key AND ms.statistic = 'median'"
                "   AND ms.value IS NOT NULL AND ms.missing_reason IS NULL"
                "   AND tr.application_id = :app AND rc.kind = 'performance'"
                "   AND tr.state = 'completed'"
                " ORDER BY tr.started_at, tr.id"
            ),
            {"key": LEAK_METRIC_KEY, "app": str(run["application_id"])},
        )
    ).mappings().all()

    points: list[tuple[float, float]] = []
    profile_mismatch = 0
    first_ts: datetime | None = None
    for row in rows:
        started_at = row["started_at"]
        if not started_at:
            continue
        # 档案不可比的历史点不参与（vendor 同口径：跨档默认 ProfileMismatch）
        row_profile, _ = _profile_of(row["profile_spec"] if isinstance(row["profile_spec"], dict) else None)
        if row_profile is not None and row_profile != device_profile:
            profile_mismatch += 1
            continue
        if first_ts is None:
            first_ts = started_at
        hours = (started_at - first_ts).total_seconds() / 3600.0
        points.append((hours, float(row["value"])))

    run_count = len(points)
    if run_count < LEAK_MIN_RUNS:
        return {
            "metric": "mem_pss_slope_mb_per_day",
            "slopeMbPerDay": None,
            "confidence": "insufficient",
            "confidenceReason": f"同档案历史运行不足 {LEAK_MIN_RUNS} 次（当前 {run_count} 次），无法估计趋势",
            "runCount": run_count,
            "spanHours": 0.0,
            "profileMismatchRuns": profile_mismatch or None,
        }
    span_hours = points[-1][0]
    slope = _ols_slope_mb_per_day(points)
    if slope is None:
        return {
            "metric": "mem_pss_slope_mb_per_day",
            "slopeMbPerDay": None,
            "confidence": "insufficient",
            "confidenceReason": "历史运行时间跨度为 0，无法估计趋势",
            "runCount": run_count,
            "spanHours": span_hours,
            "profileMismatchRuns": profile_mismatch or None,
        }
    confidence = "low" if span_hours < 24 else "ok"
    reason = (
        "时间跨度不足 24 小时，斜率仅供参考"
        if confidence == "low"
        else "同档案历史运行 ≥3 次且跨度 ≥24 小时"
    )
    return {
        "metric": "mem_pss_slope_mb_per_day",
        "slopeMbPerDay": round(slope, 4),
        "confidence": confidence,
        "confidenceReason": reason,
        "runCount": run_count,
        "spanHours": round(span_hours, 2),
        "firstMedian": points[0][1],
        "lastMedian": points[-1][1],
        "profileMismatchRuns": profile_mismatch or None,
    }


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
            metric_views.append(median_metric_view(row))

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
        # 泄漏趋势（vendor leak 同口径的平台侧实现）：性能/联动运行才有关注点
        "leakTrend": (
            await _leak_trend(session, run, device_profile)
            if run["test_type"] in ("performance", "joint")
            else None
        ),
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


@router.post("/runs/{run_id}/gate-evaluations", status_code=201)
async def create_gate_evaluation(
    run_id: str,
    payload: dict[str, Any],
    _client: str = Depends(require_client_header),
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
    # 判定核心在 services/analysis.py（P2-02）；payload["created"] 区分新建（201）
    # 与幂等重放（200），HTTP 状态语义留在路由层。
    result = await evaluate_run_original(
        session,
        run_id,
        request_key=request_key,
        policy_id=payload.get("policy_id"),
        baseline_run_id=payload.get("baseline_run_id"),
    )
    if result.get("created"):
        return result
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=200, content=jsonable_encoder(result))


