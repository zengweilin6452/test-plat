"""工作台聚合端点（api-design.md：GET /overview）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas import OverviewOut

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewOut)
async def get_overview(
    scope: str | None = None,
    project_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> OverviewOut:
    """工作台聚合。scope（android/ios/web）与 project_id 同时约束统计与"需要关注"。

    project_id 缺省 = 跨项目汇总（显式「全部项目」）；传入时必须存在，
    不存在返回 404，而不是把空列表伪装成「这个项目没有数据」（工单 05）。
    """
    from typing import Any

    from fastapi import HTTPException
    from sqlalchemy import text

    if scope is not None and scope not in ("android", "ios", "web"):
        raise HTTPException(status_code=422, detail=f"scope 只支持 android / ios / web，收到 {scope!r}")

    async def scalar(sql: str, params: dict[str, Any] | None = None) -> int:
        result = await session.execute(text(sql), params or {})
        value = result.scalar()
        return int(value or 0)

    params: dict[str, Any] = {"scope": scope} if scope else {}
    if project_id:
        exists = (
            await session.execute(
                text("SELECT 1 FROM projects WHERE id::text = :pid"), {"pid": project_id}
            )
        ).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="project not found")
        params["pid"] = project_id

    # 所有统计共用同一范围谓词；project_id 为空时明确是跨项目汇总
    run_project = "AND tr.project_id::text = :pid" if project_id else ""
    app_project = "AND project_id::text = :pid" if project_id else ""
    res_project = "AND project_id::text = :pid" if project_id else ""
    platform_clause = "AND platform = :scope" if scope else ""
    run_platform = "AND tr.platform = :scope" if scope else ""

    app_total = await scalar(
        f"SELECT count(*) FROM applications WHERE platform = 'android' {app_project} {platform_clause}", params
    )
    res_total = await scalar(
        f"SELECT count(*) FROM execution_resources WHERE 1=1 {res_project} {platform_clause}",
        params,
    )
    res_ready = await scalar(
        f"SELECT count(*) FROM execution_resources WHERE status = 'ready' {res_project} {platform_clause}", params
    )
    run_total = await scalar(f"SELECT count(*) FROM test_runs tr WHERE 1=1 {run_project} {run_platform}", params)
    run_running = await scalar(
        "SELECT count(*) FROM test_runs tr WHERE tr.state IN"
        f" ('queued','dispatching','running','finalizing') {run_project} {run_platform}",
        params,
    )
    passed = await scalar(
        f"SELECT count(*) FROM test_runs tr WHERE tr.outcome = 'passed' {run_project} {run_platform}",
        params,
    )
    failed = await scalar(
        f"SELECT count(*) FROM test_runs tr WHERE tr.outcome = 'failed' {run_project} {run_platform}",
        params,
    )
    not_tested = await scalar(
        f"SELECT count(*) FROM test_runs tr WHERE tr.outcome = 'not_tested' {run_project} {run_platform}",
        params,
    )

    denominator = passed + failed
    pass_rate = round(passed / denominator * 100, 1) if denominator else None
    return OverviewOut(
        application_total=app_total,
        resource_total=res_total,
        resource_ready=res_ready,
        run_total=run_total,
        run_running=run_running,
        passed=passed,
        failed=failed,
        not_tested=not_tested,
        pass_rate=pass_rate,
        needs_attention=failed + not_tested,
    )
