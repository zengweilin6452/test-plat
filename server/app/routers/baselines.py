"""基线：GET /baselines 与 POST /baselines（request_key 幂等）。

基线可比性的口径
----------------
baselines.profile_id 指向 resource_profiles，档案的可比性用**规范化字符串**
比较（app/domain/profiles.py），不是 uuid 相等：同一台设备在不同批次可能
注册成不同 profile 行，uuid 不等不代表设备不同。

表结构真源（server/alembic/versions/0001_initial.py:478-500）：
  baselines 有 environment_id / suite_version_id / source_component_id /
  name / version / metrics_snapshot，**没有 request_key 列**。
所以幂等靠「同 (project, application, name, version) 已存在则直接返回」实现，
request_key 由调用方传入、用于表达「同一个用户请求」，响应里带回。
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..dependencies import require_client_header
from ..domain.gates import snapshot_from_rows
from ..domain.metrics_view import missing_fields
from ..domain.profiles import ProfileNormalizationError, normalize_profile

router = APIRouter(tags=["baselines"])

_BASELINE_SELECT = """
    SELECT b.id, b.project_id, b.application_id, b.environment_id, b.suite_version_id,
           b.profile_id, b.source_component_id, b.name, b.version, b.metrics_snapshot,
           b.created_at,
           rp.name AS profile_name, rp.spec AS profile_spec,
           rc.run_id AS source_run_id
      FROM baselines b
      LEFT JOIN resource_profiles rp ON rp.id = b.profile_id
      LEFT JOIN run_components rc ON rc.id = b.source_component_id
"""

_RUN_SQL = """
    SELECT r.id, r.project_id, r.application_id, r.application_id AS app_id,
           r.revision_id, r.profile_id, rp.spec AS profile_spec,
           tr.environment_id, tr.suite_version_id
      FROM test_runs r
      LEFT JOIN task_revisions tr ON tr.id = r.revision_id
      LEFT JOIN resource_profiles rp ON rp.id = r.profile_id
     WHERE r.id::text = :run_id
"""

_METRIC_SQL = """
    SELECT m.metric_key, m.statistic, m.unit, m.scope, m.window_key, m.sample_count,
           m.value, m.missing_reason, m.missing_reason_text, m.component_id,
           m.metric_version
      FROM metric_summaries m
     WHERE m.component_id = ANY(:component_ids)
"""


def _profile_of(spec: Any) -> tuple[str | None, str | None, str | None]:
    """spec（dict 或档案串）-> (规范化档案, 原始片段, 错误)。"""
    if not spec:
        return None, None, "资源档案为空"
    try:
        if isinstance(spec, dict):
            raw = "|".join(
                str(spec.get(key) or "")
                for key in ("os_name", "os_version", "screen_resolution")
            ) or None
        else:
            raw = str(spec)
        return normalize_profile(spec), raw, None
    except ProfileNormalizationError as exc:
        return None, None, str(exc)


def _snapshot_preview(snapshot: Any) -> list[dict[str, Any]]:
    """metrics_snapshot -> API 视图：缺失指标保留 missing_reason，值恒为 null。

    DB CHECK ck_baselines_metrics_snapshot_object 要求 metrics_snapshot 是
    **jsonb 对象**（真源 server/alembic/versions/0001_initial.py 的 baselines），
    因此格式为 `{"metrics": [...行...], "meta": {...}}`。
    """
    rows = _snapshot_rows(snapshot)
    preview = []
    for row in rows:
        if row.get("statistic") != "median":
            continue
        preview.append(
            {
                "key": row.get("metric_key"),
                "median": row.get("value"),
                "unit": row.get("unit"),
                "sample_count": row.get("sample_count"),
                **missing_fields(row),
            }
        )
    return preview


def _snapshot_rows(snapshot: Any) -> list[dict[str, Any]]:
    """兼容两种历史形态：新写入是 {"metrics": [...]} 对象，早期是行数组。"""
    if isinstance(snapshot, dict):
        rows = snapshot.get("metrics")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if isinstance(snapshot, list):
        return [row for row in snapshot if isinstance(row, dict)]
    return []


def _baseline_view(row: dict[str, Any]) -> dict[str, Any]:
    profile, raw, error = _profile_of(row["profile_spec"])
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "application_id": row["application_id"],
        "environment_id": row["environment_id"],
        "suite_version_id": row["suite_version_id"],
        "profile_id": row["profile_id"],
        "profile": profile,
        "profile_raw": raw,
        "profile_error": error,
        "source_component_id": row["source_component_id"],
        "source_run_id": row["source_run_id"],
        "name": row["name"],
        "baseline_name": row["name"],
        "version": row["version"],
        "baseline_version": row["version"],
        "run_id": row["source_run_id"],
        "created_at": row["created_at"],
        "metrics": _snapshot_preview(row["metrics_snapshot"]),
    }


@router.get("/baselines")
async def list_baselines(
    application_id: Annotated[str | None, Query()] = None,
    resource_profile_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """基线列表。resource_profile_id 过滤按「规范化档案」比较，不是 uuid 相等。"""
    sql = _BASELINE_SELECT
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if application_id:
        where.append("b.application_id::text = :application_id")
        params["application_id"] = application_id
    if project_id:
        where.append("b.project_id::text = :project_id")
        params["project_id"] = project_id
    if resource_profile_id:
        # 参数既可以是 resource_profiles.id（uuid），也可以是规范化档案串
        # 本身（如 "android-13|1080x2400|pixel-7-pro"）—— 后者不查表，直接比对。
        target = None
        try:
            uuid.UUID(resource_profile_id)
        except (ValueError, AttributeError, TypeError):
            target = resource_profile_id
        if target is None:
            profile_row = (
                await session.execute(
                    text("SELECT spec FROM resource_profiles WHERE id::text = :pid"),
                    {"pid": resource_profile_id},
                )
            ).mappings().first()
            if profile_row is None:
                raise HTTPException(status_code=404, detail="resource profile not found")
            target, _raw, error = _profile_of(profile_row["spec"])
            if target is None:
                raise HTTPException(
                    status_code=422, detail=f"资源档案无法规范化，无法按档案过滤: {error}"
                )
        # 规范化在应用层做：先取出候选，再按规范化字符串过滤
        params["target_profile"] = target
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY b.created_at DESC, b.version DESC LIMIT :limit"

    rows = (await session.execute(text(sql), params)).mappings().all()
    items = [_baseline_view(dict(row)) for row in rows]
    if resource_profile_id:
        wanted, _, wanted_error = _profile_of(params["target_profile"])
        if wanted is None:
            # 传入的是 UUID 时 target 已是规范化串；传入的是脏档案串则在这里规范化
            try:
                wanted = normalize_profile(params["target_profile"])
            except ProfileNormalizationError:
                raise HTTPException(
                    status_code=422,
                    detail=f"资源档案无法规范化，无法按档案过滤: {wanted_error}",
                ) from None
        items = [item for item in items if item["profile"] == wanted]
    return {"items": items, "total": len(items)}


@router.get("/baselines/{baseline_id}")
async def get_baseline(
    baseline_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(_BASELINE_SELECT + " WHERE b.id::text = :id"), {"id": baseline_id}
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="baseline not found")
    return _baseline_view(dict(row))


@router.post("/baselines", status_code=201)
async def create_baseline(
    payload: dict[str, Any],
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """从一次已完成运行创建基线（request_key 幂等）。

    请求体：`{"request_key": "...", "run_id": "..."}`，可选 `name`。
    - 运行必须 completed：否则 409（半截数据不能当基线）；
    - 幂等键 = (project, application, name, version)，同键重复提交返回已有行；
    - metrics_snapshot 存**完整行**（含缺失指标），下游仍能区分
      「测得 0」与「没测到」。
    """
    request_key = payload.get("request_key")
    if not request_key or not isinstance(request_key, str):
        raise HTTPException(status_code=422, detail="request_key 必填")
    run_id = payload.get("run_id")
    if not run_id:
        raise HTTPException(status_code=422, detail="run_id 必填")
    name = payload.get("name")

    run = (
        await session.execute(text(_RUN_SQL), {"run_id": str(run_id)})
    ).mappings().first()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run["app_id"] is None:
        raise HTTPException(status_code=409, detail="运行没有关联应用")
    from ..domain import identity as identity_mod

    # 归档守卫（工单 04）：归档范围禁止登记新基线
    await identity_mod.assert_scope_active(
        session, project_id=str(run["project_id"]), application_id=str(run["app_id"])
    )
    if run["environment_id"] is None:
        raise HTTPException(status_code=409, detail="运行 revision 没有环境，无法创建基线")

    state = (
        await session.execute(text("SELECT state FROM test_runs WHERE id = :id"), {"id": run["id"]})
    ).scalar()
    if state != "completed":
        raise HTTPException(
            status_code=409, detail=f"运行 state={state} 未完成，不能作为基线来源"
        )

    profile, _raw, profile_error = _profile_of(run["profile_spec"])
    if profile is None:
        raise HTTPException(
            status_code=409, detail=f"运行资源档案无法规范化，不能创建基线: {profile_error}"
        )

    components = (
        (
            await session.execute(
                text(
                    "SELECT id, kind FROM run_components WHERE run_id = :run_id "
                    "ORDER BY CASE kind WHEN 'performance' THEN 0 ELSE 1 END, id"
                ),
                {"run_id": run["id"]},
            )
        )
        .mappings()
        .all()
    )
    if not components:
        raise HTTPException(status_code=409, detail="运行没有组件记录，不能创建基线")
    component = components[0]

    rows = (
        (
            await session.execute(
                text(_METRIC_SQL), {"component_ids": [component["id"]]}
            )
        )
        .mappings()
        .all()
    )
    snapshot = []
    for row in rows:
        item = dict(row)
        # 工单审查修复：快照行带上来源运行 ID——分析侧 `_snapshot_run_ids`
        # 靠它反查默认基线的来源运行；没有它，已有基线会被判 baseline_missing。
        item["source_run_id"] = str(run["id"])
        snapshot.append(item)
    if not snapshot:
        raise HTTPException(status_code=409, detail="运行没有任何指标行，不能创建基线")

    baseline_name = name or f"run:{run['id']}"
    existing = (
        await session.execute(
            text(
                _BASELINE_SELECT
                + " WHERE b.application_id = :app_id AND b.name = :name "
                "ORDER BY b.version DESC LIMIT 1"
            ),
            {"app_id": run["app_id"], "name": baseline_name},
        )
    ).mappings().first()
    if existing is not None:
        view = _baseline_view(dict(existing))
        view["created"] = False
        view["request_key"] = request_key
        return view

    next_version = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM baselines "
                "WHERE application_id = :app_id AND name = :name"
            ),
            {"app_id": run["app_id"], "name": baseline_name},
        )
    ).scalar()

    new_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO baselines
                (id, project_id, application_id, environment_id, suite_version_id,
                 profile_id, source_component_id, name, version, metrics_snapshot)
            VALUES
                (:id, :project_id, :application_id, :environment_id, :suite_version_id,
                 :profile_id, :source_component_id, :name, :version,
                 CAST(:metrics_snapshot AS jsonb))
            """
        ),
        {
            "id": new_id,
            "project_id": run["project_id"],
            "application_id": run["app_id"],
            "environment_id": run["environment_id"],
            "suite_version_id": run["suite_version_id"],
            "profile_id": run["profile_id"],
            "source_component_id": component["id"],
            "name": baseline_name,
            "version": next_version,
            "metrics_snapshot": json.dumps(
                {"metrics": snapshot, "schema": 1}, ensure_ascii=False, default=str
            ),
        },
    )
    created = (
        await session.execute(
            text(_BASELINE_SELECT + " WHERE b.id = :id"), {"id": new_id}
        )
    ).mappings().first()
    view = _baseline_view(dict(created))
    view["created"] = True
    view["request_key"] = request_key
    view["metrics_snapshot_rows"] = len(snapshot)
    return view


@router.get("/baselines/{baseline_id}/snapshot")
async def get_baseline_snapshot(
    baseline_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """基线快照的判定视图：`{metric: {value, sourceRunId, ...}}`（vendor baseline_data 口径）。"""
    row = (
        await session.execute(
            text(_BASELINE_SELECT + " WHERE b.id::text = :id"), {"id": baseline_id}
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="baseline not found")
    snapshot = row["metrics_snapshot"]
    data = snapshot_from_rows(_snapshot_rows(snapshot))
    return {"baseline_id": row["id"], "name": row["name"], "version": row["version"], "data": data}
