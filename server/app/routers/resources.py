"""执行资源（设备池）：GET /resources。

表结构真源 = server/alembic/versions/0001_initial.py（对齐
docs/platform-prototype/schema.sql）。注意几个容易写错的真实列名：
  - execution_resources.profile_id（不是 resource_profile_id）
  - execution_resources.resource_key（不是 serial；存 adb serial / 节点侧标识）
  - execution_resources.kind（device / emulator / ...）
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["resources"])

_STATUSES = {"ready", "offline", "unauthorized", "draining"}


@router.get("/resources")
async def list_resources(
    status: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """设备列表。status 过滤取值 ready/offline/unauthorized/draining。

    busy 不落库，由「存在未释放租约」实时推导 —— 资源表本身没有 busy 列，
    这是 docs/plan/data-model.md 的明确约定（避免两处状态互相矛盾）。
    """
    if status is not None and status not in _STATUSES:
        raise HTTPException(status_code=422, detail=f"未知 status: {status}")

    sql = """
        SELECT r.id, r.resource_key, r.status, r.kind, r.platform, r.profile_id,
               l.run_id AS lease_run_id, l.debug_session_id AS lease_debug_id,
               p.name AS profile_name, p.spec
          FROM execution_resources r
          LEFT JOIN resource_leases l
                 ON l.resource_id = r.id AND l.released_at IS NULL
          LEFT JOIN resource_profiles p
                 ON p.id = r.profile_id
    """
    params: dict[str, object] = {}
    if status is not None:
        sql += " WHERE r.status = :status"
        params["status"] = status
    sql += " ORDER BY r.resource_key"

    rows = (await session.execute(text(sql), params)).mappings().all()

    items = []
    for row in rows:
        spec = row["spec"] or {}
        items.append(
            {
                "id": row["id"],
                "name": row["resource_key"],
                "resource_key": row["resource_key"],
                "status": row["status"],
                "kind": row["kind"] or "device",
                "platform": row["platform"] or "android",
                "profile_id": row["profile_id"],
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
