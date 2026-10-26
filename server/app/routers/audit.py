"""审计事件只读查询（P6，api-design.md §2.8 GET /api/v1/audit-events）。

audit_events 是纯追加的追溯表：平台只读，不提供任何写入端点（写入发生在
业务事务里，见 data-model.md）。分页用 limit/offset，固定 created_at DESC
（并列时以 id DESC 兜底，与 audits_project_time 索引的游标方向一致）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["audit"])


@router.get("/audit-events")
async def list_audit_events(
    project_id: str | None = Query(default=None, description="按项目过滤"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """分页返回审计事件（created_at DESC, id DESC）。只读，不落任何变更。"""
    conditions = ""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if project_id is not None:
        conditions = "WHERE project_id = CAST(:project_id AS uuid)"
        params["project_id"] = project_id

    total_row = await session.execute(
        text(f"SELECT count(*) FROM audit_events {conditions}"), params
    )
    total = int(total_row.scalar() or 0)

    rows = await session.execute(
        text(
            f"""
            SELECT id, project_id, actor_ref, action, entity_type, entity_id,
                   request_id, changes, created_at
            FROM audit_events {conditions}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    items = [
        {
            "id": str(r.id),
            "project_id": str(r.project_id),
            "actor_ref": r.actor_ref,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id),
            "request_id": r.request_id,
            "changes": r.changes,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}
