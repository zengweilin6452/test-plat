"""项目与应用：GET /applications（项目与应用页）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["applications"])


@router.get("/applications")
async def list_applications(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    sql = """
        SELECT a.id, a.project_id, a.name, a.platform, a.identifier,
               (SELECT count(*) FROM test_tasks t WHERE t.application_id = a.id) AS task_count
          FROM applications a
         ORDER BY a.platform, a.name
    """
    rows = (await session.execute(text(sql))).mappings().all()
    items = [dict(r) for r in rows]
    by_platform: dict[str, int] = {}
    for item in items:
        by_platform[item["platform"]] = by_platform.get(item["platform"], 0) + 1
    return {"items": items, "total": len(items), "by_platform": by_platform}
