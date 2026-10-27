"""执行资源（设备池）：GET /resources、POST /resources/sync。

表结构真源 = server/alembic/versions/0001_initial.py（对齐
docs/platform-prototype/schema.sql）。注意几个容易写错的真实列名：
  - execution_resources.profile_id（不是 resource_profile_id）
  - execution_resources.resource_key（不是 serial；存 adb serial / 节点侧标识）
  - execution_resources.kind（device / emulator / ...）
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import CLIENT_HEADER, CLIENT_HEADER_VALUE, client_header_required, not_found
from ..services import resources as resource_service

router = APIRouter(tags=["resources"])

_STATUSES = {"ready", "offline", "unauthorized", "draining"}


class ResourceSyncIn(BaseModel):
    """POST /resources/sync 请求体（§4.1）：两个键都可选，body 可为 {}。"""

    project_id: str | None = None
    node_id: str | None = None


@router.post("/resources/sync")
async def sync_resources(
    payload: ResourceSyncIn,
    x_testdock_client: Annotated[str | None, Header(alias=CLIENT_HEADER)] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """问 adb「现在插着什么设备」，把答案登记进设备池（写操作，web 守卫与 POST /runs 一致）。"""
    if x_testdock_client is None or not x_testdock_client.strip():
        raise client_header_required()
    if x_testdock_client.strip().lower() != CLIENT_HEADER_VALUE:
        raise client_header_required()
    return await resource_service.sync_resources(
        session,
        project_id=payload.project_id,
        node_id=payload.node_id,
    )


@router.get("/resources")
async def list_resources(
    status: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """设备列表。status 过滤取值 ready/offline/unauthorized/draining。

    project_id 可选（D5）：不传 = 全部项目（向后兼容）；传了但项目不存在
    返回 404——空列表会被误读成「这个项目没设备」。
    busy 不落库，由「存在未释放租约」实时推导 —— 资源表本身没有 busy 列，
    这是 docs/plan/data-model.md 的明确约定（避免两处状态互相矛盾）。
    """
    if status is not None and status not in _STATUSES:
        raise HTTPException(status_code=422, detail=f"未知 status: {status}")

    params: dict[str, object] = {}
    if project_id is not None:
        exists = (
            await session.execute(
                text("SELECT 1 FROM projects WHERE id = CAST(:pid AS uuid)"),
                {"pid": project_id},
            )
        ).first()
        if exists is None:
            raise not_found("project", project_id)

    sql = """
        SELECT r.id, r.project_id, r.node_id, r.resource_key, r.status, r.kind, r.platform,
               r.profile_id, r.last_seen_at,
               l.run_id AS lease_run_id, l.debug_session_id AS lease_debug_id,
               p.name AS profile_name, p.spec
          FROM execution_resources r
          LEFT JOIN resource_leases l
                 ON l.resource_id = r.id AND l.released_at IS NULL
          LEFT JOIN resource_profiles p
                 ON p.id = r.profile_id AND p.project_id = r.project_id
    """
    conditions = []
    if status is not None:
        conditions.append("r.status = :status")
        params["status"] = status
    if project_id is not None:
        conditions.append("r.project_id = CAST(:pid AS uuid)")
        params["pid"] = project_id
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY r.resource_key"

    rows = (await session.execute(text(sql), params)).mappings().all()

    items = []
    for row in rows:
        spec = row["spec"] or {}
        items.append(
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "node_id": row["node_id"],
                "name": row["resource_key"],
                "resource_key": row["resource_key"],
                "status": row["status"],
                "kind": row["kind"] or "device",
                "platform": row["platform"] or "android",
                "profile_id": row["profile_id"],
                "last_seen_at": row["last_seen_at"],
                "profile": {
                    "name": row["profile_name"],
                    "os_name": spec.get("os_name"),
                    "os_version": spec.get("os_version"),
                    "screen_resolution": spec.get("screen_resolution"),
                }
                if row["profile_name"]
                else None,
                "busy": row["lease_run_id"] is not None or row["lease_debug_id"] is not None,
                "lease": {
                    "run_id": row["lease_run_id"],
                    "debug_session_id": row["lease_debug_id"],
                }
                if (row["lease_run_id"] or row["lease_debug_id"])
                else None,
            }
        )

    ready = sum(1 for i in items if i["status"] == "ready")
    return {
        "items": items,
        "total": len(items),
        "ready": ready,
        "summary": f"{ready} 台已授权在线 / {len(items)} 台设备",
    }
