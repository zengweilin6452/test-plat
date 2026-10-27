"""项目清单：GET /projects（device-registration.md D5 配套）。

设备页按项目过滤需要一个可枚举的项目列表；本端点只读、不分页（项目数量级
是个位数），字段集合冻结为 {id, code, name, archived_at}。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["projects"])


@router.get("/projects")
async def list_projects(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = (
        await session.execute(
            text("SELECT id, code, name, archived_at FROM projects ORDER BY created_at, code")
        )
    ).mappings().all()
    items = [
        {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "archived_at": row["archived_at"],
        }
        for row in rows
    ]
    return {"items": items, "total": len(items)}
