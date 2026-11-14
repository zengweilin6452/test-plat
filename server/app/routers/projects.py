"""项目清单与管理（正式化改造工单 02/04）。

- GET /projects：项目列表。默认排除归档对象；`include_archived` / `archived_only`
  供管理列表与历史查询做归档筛选。
- POST /projects：创建项目（编码唯一、去空白转小写、校验规则见 domain/identity）。
- PATCH /projects/{id}：仅改显示名称（身份字段创建后固定，ADR-0001）。
- GET /projects/{id}/archive-preview：归档影响预览（关联数量 + 当前占用）。
- POST /projects/{id}/archive | /restore：归档与恢复；被活动占用 409，
  重复操作幂等返回稳定结果。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..dependencies import require_client_header
from ..domain import identity as identity_mod
from ..errors import validation_error
from ..schemas import ProjectsOut

router = APIRouter(tags=["projects"])


def _valid_uuid_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        uuid.UUID(value)
    except ValueError:
        raise validation_error([f"project id 必须是 uuid，收到 {value!r}"]) from None
    return value


@router.get("/projects", response_model=ProjectsOut)
async def list_projects(
    include_archived: Annotated[bool, Query()] = False,
    archived_only: Annotated[bool, Query()] = False,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sql = "SELECT id, code, name, archived_at, created_at FROM projects"
    if archived_only:
        sql += " WHERE archived_at IS NOT NULL"
    elif not include_archived:
        sql += " WHERE archived_at IS NULL"
    sql += " ORDER BY created_at, code"
    rows = (await session.execute(text(sql))).mappings().all()
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


@router.post("/projects", status_code=201)
async def create_project(
    body: dict[str, Any],
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """创建项目。编码冲突 409 identity_conflict，details.existing_id 指向原对象。"""
    return await identity_mod.create_project(session, code=body.get("code"), name=body.get("name"))


@router.patch("/projects/{project_id}")
async def rename_project(
    project_id: str,
    body: dict[str, Any],
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """改名只影响显示名称；ID、编码、历史引用与运行快照均不变。"""
    return await identity_mod.rename_project(session, project_id, name=body.get("name"))


@router.get("/projects/{project_id}/archive-preview")
async def project_archive_preview(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await identity_mod.archive_impact(
        session,
        entity="project",
        entity_id=_valid_uuid_or_none(project_id) or project_id,
    )


@router.post("/projects/{project_id}/archive")
async def archive_project(
    project_id: str,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """归档项目。存在非终态运行 / 未关闭调试 / 未释放租约时 409 并给出具体对象。"""
    return await identity_mod.archive_entity(
        session, entity="project", entity_id=_valid_uuid_or_none(project_id) or project_id
    )


@router.post("/projects/{project_id}/restore")
async def restore_project(
    project_id: str,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """恢复项目。不复活此前单独归档的子应用。"""
    return await identity_mod.restore_entity(
        session, entity="project", entity_id=_valid_uuid_or_none(project_id) or project_id
    )
