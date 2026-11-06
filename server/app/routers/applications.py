"""项目与应用：列表与全生命周期管理（正式化改造工单 02/04）。

- GET /applications：列表，支持 project_id / platform / 归档筛选；
  `application_id` 供统一上下文解析单个应用（03）。
- POST /applications：仅开放 Android；标识沿用包名校验，同项目同目标端唯一
  （含归档记录），冲突 409 identity_conflict。
- PATCH /applications/{id}：仅改显示名称。
- GET /applications/{id}：单应用详情（上下文解析与深链接校验用）。
- GET /applications/{id}/archive-preview、POST archive | restore：
  与项目同一套守卫；父项目仍归档时拒绝恢复子应用。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..domain import identity as identity_mod
from ..errors import client_header_required, not_found, validation_error
from ..schemas import ApplicationsOut

router = APIRouter(tags=["applications"])

_APP_SELECT = """
    SELECT a.id, a.project_id, a.platform, a.name, a.identifier, a.archived_at, a.created_at,
           (SELECT count(*) FROM test_tasks t WHERE t.application_id = a.id) AS task_count
      FROM applications a
"""


def _valid_uuid_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        uuid.UUID(value)
    except ValueError:
        raise validation_error([f"application id 必须是 uuid，收到 {value!r}"]) from None
    return value


@router.get("/applications", response_model=ApplicationsOut)
async def list_applications(
    project_id: Annotated[str | None, Query()] = None,
    platform: Annotated[str | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    archived_only: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    sql = _APP_SELECT
    where: list[str] = []
    params: dict[str, object] = {}
    if project_id is not None:
        where.append("a.project_id::text = :pid")
        params["pid"] = project_id
    if platform is not None:
        where.append("a.platform = :platform")
        params["platform"] = platform
    if archived_only:
        where.append("a.archived_at IS NOT NULL")
    elif not include_archived:
        where.append("a.archived_at IS NULL")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY a.platform, a.name"
    rows = (await session.execute(text(sql), params)).mappings().all()
    items = [dict(r) for r in rows]
    by_platform: dict[str, int] = {}
    for item in items:
        by_platform[item["platform"]] = by_platform.get(item["platform"], 0) + 1
    return {"items": items, "total": len(items), "by_platform": by_platform}


@router.get("/applications/{application_id}")
async def get_application(
    application_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """单应用详情（含归档状态）：统一上下文与深链接的服务端校验入口。"""
    row = (
        await session.execute(
            text(_APP_SELECT + " WHERE a.id::text = :id"),
            {"id": application_id},
        )
    ).mappings().first()
    if row is None:
        raise not_found("application", application_id)
    return dict(row)


@router.post("/applications", status_code=201)
async def create_application(
    body: dict[str, Any],
    client: str = Depends(client_header_required),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await identity_mod.create_application(
        session,
        project_id=body.get("project_id"),
        platform=body.get("platform"),
        name=body.get("name"),
        identifier=body.get("identifier"),
    )


@router.patch("/applications/{application_id}")
async def rename_application(
    application_id: str,
    body: dict[str, Any],
    client: str = Depends(client_header_required),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """改名只影响显示名称；所属项目、目标端与标识不可修改（ADR-0001）。"""
    return await identity_mod.rename_application(session, application_id, name=body.get("name"))


@router.get("/applications/{application_id}/archive-preview")
async def application_archive_preview(
    application_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await identity_mod.archive_impact(
        session, entity="application", entity_id=_valid_uuid_or_none(application_id) or application_id
    )


@router.post("/applications/{application_id}/archive")
async def archive_application(
    application_id: str,
    client: str = Depends(client_header_required),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await identity_mod.archive_entity(
        session, entity="application", entity_id=_valid_uuid_or_none(application_id) or application_id
    )


@router.post("/applications/{application_id}/restore")
async def restore_application(
    application_id: str,
    client: str = Depends(client_header_required),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await identity_mod.restore_entity(
        session, entity="application", entity_id=_valid_uuid_or_none(application_id) or application_id
    )
