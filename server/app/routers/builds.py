"""构建登记与设备身份核对端点（工单 04，§9.2）。

    GET  /builds                       按 application_id 列出构建
    POST /builds                       登记固定构建（同 key 同身份复用）
    POST /builds/{id}/identity-checks  在设备互斥下只读安装身份
    POST /builds/{id}/confirm-identity 显式确认并固定基准

设备身份读取与 readiness 共用短检查租约（device_checks.kind='identity'），
因此与 run/debug 天然互斥；busy 时零设备访问。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas import (
    BuildCreateIn,
    BuildRecordOut,
    BuildsOut,
    BuildIdentityCheckOut,
    ConfirmIdentityIn,
    IdentityCheckIn,
)
from ..services import builds as build_service
from .tasks import require_client_header

router = APIRouter(tags=["builds"])


@router.get("/builds", response_model=BuildsOut)
async def list_builds(
    application_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """按应用（可选项目）列出构建，含声明身份、核对状态与固定基准。"""
    return await build_service.list_builds(
        session, application_id=application_id, project_id=project_id
    )


@router.post(
    "/builds",
    response_model=BuildRecordOut,
    status_code=201,
    responses={200: {"model": BuildRecordOut, "description": "同 key 同身份复用原记录"}},
)
async def create_build(
    payload: BuildCreateIn,
    response: Response,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """登记构建；同 key 同身份返回原记录，不同身份 409 且不改原记录。"""
    from ..domain import identity as identity_mod

    # 归档守卫（工单 04）：归档范围禁止登记新构建
    await identity_mod.assert_scope_active(session, application_id=payload.application_id)
    record, created = await build_service.register_build(
        session,
        application_id=payload.application_id,
        version=payload.version,
        build_key=payload.build_key,
        source_commit=payload.source_commit,
        sha256=payload.sha256,
    )
    response.status_code = 201 if created else 200
    return record


@router.post("/builds/{build_id}/identity-checks", response_model=BuildIdentityCheckOut)
async def check_build_identity(
    build_id: str,
    payload: IdentityCheckIn,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """只读核对设备上已安装包的身份；busy 返回 409 且不访问设备。"""
    return await build_service.run_identity_check(
        session,
        build_id=build_id,
        resource_id=payload.resource_id,
        purpose=payload.purpose,
        test_type=payload.test_type,
        holder_id=client,
    )


@router.post("/builds/{build_id}/confirm-identity", response_model=BuildRecordOut)
async def confirm_build_identity(
    build_id: str,
    payload: ConfirmIdentityIn,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """显式确认核对结果并原子固定基准；重复相同确认幂等。"""
    return await build_service.confirm_identity(
        session, build_id=build_id, check_id=payload.check_id
    )
