"""门禁策略：GET /gate-policies 与 PUT /gate-policies/{id}。

不可变语义
----------
改阈值**不 UPDATE 历史行**：gate_policies 按 (project, application, name, version)
唯一，PUT 一律插入 version+1 的新行，并返回新行。历史 gate_evaluations 仍指向
旧 policy_id，因此既有 original 判定与它的阈值证据永不漂移。

响应里的 `id` 一律是新版本行的 id；`superseded_id` 是本次被替代的旧版本。
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
from ..domain.gates import GateError, policy_rules_to_thresholds, rules_fingerprint

router = APIRouter(tags=["gate-policies"])

_SELECT = """
    SELECT p.id, p.project_id, p.application_id, p.name, p.version, p.rules, p.created_at,
           a.name AS application_name
      FROM gate_policies p
      LEFT JOIN applications a ON a.id = p.application_id
"""

# 首期单条全局策略的默认值（docs/plan/development-plan.md §7.3）
DEFAULT_RULES: dict[str, Any] = {
    "min_samples": 10,
    "thresholds": [
        {"metric_key": "mem_pss_mb", "op": "lt", "threshold": 240, "level": "fail"},
        {"metric_key": "cpu_process_pct", "op": "lt", "threshold": 35, "level": "warn"},
        {"metric_key": "fps_frame", "op": "ge", "threshold": 50, "level": "fail"},
    ],
}


def _policy_view(row: dict[str, Any]) -> dict[str, Any]:
    rules = row["rules"] or {}
    try:
        thresholds = {
            key: list(value) for key, value in policy_rules_to_thresholds(rules).items()
        }
        error = None
    except GateError as exc:
        thresholds, error = {}, str(exc)
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "application_id": row["application_id"],
        "application_name": row["application_name"],
        "name": row["name"],
        "version": row["version"],
        "rules": rules,
        # 归一后的 vendor 口径阈值，前端直接展示，不必自己解析 rules
        "thresholds": thresholds,
        "min_samples": (rules or {}).get("min_samples", (rules or {}).get("minSamples")),
        "rules_sha256": rules_fingerprint(rules),
        "rules_error": error,
        "created_at": row["created_at"],
    }


@router.get("/gate-policies")
async def list_gate_policies(
    application_id: Annotated[str | None, Query()] = None,
    latest_only: Annotated[bool, Query()] = True,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """门禁策略列表。默认只返回每个应用的最新版本（历史版本仍在库里可查）。"""
    sql = _SELECT
    params: dict[str, Any] = {}
    if application_id:
        sql += " WHERE p.application_id::text = :application_id"
        params["application_id"] = application_id
    sql += " ORDER BY p.created_at DESC, p.version DESC"

    rows = (await session.execute(text(sql), params)).mappings().all()
    items = [_policy_view(dict(row)) for row in rows]
    if latest_only:
        seen: set[tuple[Any, str]] = set()
        kept = []
        for item in items:
            key = (item["application_id"], item["name"])
            if key in seen:
                continue
            seen.add(key)
            kept.append(item)
        items = kept
    return {"items": items, "total": len(items)}


@router.get("/gate-policies/{policy_id}")
async def get_gate_policy(
    policy_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    row = (
        await session.execute(text(_SELECT + " WHERE p.id::text = :id"), {"id": policy_id})
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="gate policy not found")
    return _policy_view(dict(row))


@router.put("/gate-policies/{policy_id}", status_code=200)
async def update_gate_policy(
    policy_id: str,
    payload: dict[str, Any],
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """改阈值 = 插入新版本行，**绝不 UPDATE 同 id 的历史行**。

    请求体：`{"rules": {...}}` 或 `{"thresholds": [...], "min_samples": 10}`。
    返回体的 `id` 是新版本行 id，`version` 递增，`superseded_id` 为旧行 id。
    """
    current = (
        await session.execute(text(_SELECT + " WHERE p.id::text = :id"), {"id": policy_id})
    ).mappings().first()
    if current is None:
        raise HTTPException(status_code=404, detail="gate policy not found")
    current = dict(current)
    from ..domain import identity as identity_mod

    # 归档守卫（工单 04）：归档范围禁止修改门禁策略等业务配置
    await identity_mod.assert_scope_active(
        session,
        project_id=str(current["project_id"]),
        application_id=str(current["application_id"]),
    )

    rules = payload.get("rules")
    if rules is None:
        if "thresholds" not in payload and "min_samples" not in payload:
            raise HTTPException(status_code=422, detail="必须提供 rules 或 thresholds")
        rules = {}
        if "min_samples" in payload:
            rules["min_samples"] = payload["min_samples"]
        if "thresholds" in payload:
            rules["thresholds"] = payload["thresholds"]
    try:
        normalized = policy_rules_to_thresholds(rules)
    except GateError as exc:
        raise HTTPException(status_code=422, detail=f"策略规则非法: {exc}") from exc
    if not normalized:
        raise HTTPException(status_code=422, detail="策略至少要有一条阈值规则")

    name = payload.get("name") or current["name"]
    next_version = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM gate_policies "
                "WHERE application_id = :app_id AND name = :name"
            ),
            {"app_id": current["application_id"], "name": name},
        )
    ).scalar()

    new_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO gate_policies
                (id, project_id, application_id, name, version, rules)
            VALUES
                (:id, :project_id, :application_id, :name, :version, CAST(:rules AS jsonb))
            """
        ),
        {
            "id": new_id,
            "project_id": current["project_id"],
            "application_id": current["application_id"],
            "name": name,
            "version": next_version,
            "rules": json.dumps(rules, ensure_ascii=False, default=str),
        },
    )

    created = (
        await session.execute(text(_SELECT + " WHERE p.id = :id"), {"id": new_id})
    ).mappings().first()
    view = _policy_view(dict(created))
    view["superseded_id"] = current["id"]
    view["superseded_version"] = current["version"]
    view["created"] = True
    return view


@router.post("/gate-policies", status_code=201)
async def create_gate_policy(
    payload: dict[str, Any],
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """新建策略（首期单条全局策略用默认阈值）。同一应用下重名则 version+1。"""
    from ..domain import identity as identity_mod

    application_id = payload.get("application_id")
    if not application_id:
        raise HTTPException(status_code=422, detail="application_id 必填")
    await identity_mod.assert_scope_active(session, application_id=str(application_id))
    app = (
        await session.execute(
            text("SELECT id, project_id FROM applications WHERE id::text = :id"),
            {"id": str(application_id)},
        )
    ).mappings().first()
    if app is None:
        raise HTTPException(status_code=404, detail="application not found")

    rules = payload.get("rules") or DEFAULT_RULES
    try:
        normalized = policy_rules_to_thresholds(rules)
    except GateError as exc:
        raise HTTPException(status_code=422, detail=f"策略规则非法: {exc}") from exc
    if not normalized:
        raise HTTPException(status_code=422, detail="策略至少要有一条阈值规则")

    name = payload.get("name") or "default"
    next_version = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM gate_policies "
                "WHERE application_id = :app_id AND name = :name"
            ),
            {"app_id": app["id"], "name": name},
        )
    ).scalar()
    new_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO gate_policies
                (id, project_id, application_id, name, version, rules)
            VALUES
                (:id, :project_id, :application_id, :name, :version, CAST(:rules AS jsonb))
            """
        ),
        {
            "id": new_id,
            "project_id": app["project_id"],
            "application_id": app["id"],
            "name": name,
            "version": next_version,
            "rules": json.dumps(rules, ensure_ascii=False, default=str),
        },
    )
    created = (
        await session.execute(text(_SELECT + " WHERE p.id = :id"), {"id": new_id})
    ).mappings().first()
    view = _policy_view(dict(created))
    view["created"] = True
    return view
