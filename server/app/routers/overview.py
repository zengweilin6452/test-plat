"""工作台聚合端点（api-design.md：GET /overview）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas import OverviewOut

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewOut)
async def get_overview(
    scope: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> OverviewOut:
    """工作台聚合。scope（android/ios/web）同时约束统计与"需要关注"（AC-OV-01），
    缺省 = 全部平台；未知的 scope 422。"""
    from typing import Any

    from fastapi import HTTPException
    from sqlalchemy import text

    if scope is not None and scope not in ("android", "ios", "web"):
        raise HTTPException(status_code=422, detail=f"scope 只支持 android / ios / web，收到 {scope!r}")

    async def scalar(sql: str, params: dict[str, Any] | None = None) -> int:
        result = await session.execute(text(sql), params or {})
        value = result.scalar()
        return int(value or 0)

    # test_runs 的平台在自身 platform 列；应用/资源按各自表过滤。
    run_platform = "AND tr.platform = :scope" if scope else ""
    params = {"scope": scope} if scope else {}
    app_platform = "AND platform = :scope" if scope else ""
    res_platform = "AND platform = :scope" if scope else ""

    app_total = await scalar(
        f"SELECT count(*) FROM applications WHERE platform = 'android' {app_platform}", params
    )
    res_total = await scalar(f"SELECT count(*) FROM execution_resources WHERE 1=1 {res_platform}", params)
    res_ready = await scalar(
        f"SELECT count(*) FROM execution_resources WHERE status = 'ready' {res_platform}", params
    )
    run_total = await scalar(f"SELECT count(*) FROM test_runs tr WHERE 1=1 {run_platform}", params)
    run_running = await scalar(
        "SELECT count(*) FROM test_runs tr WHERE tr.state IN"
        " ('queued','dispatching','running','finalizing')" + run_platform,
        params,
    )
    passed = await scalar(
        "SELECT count(*) FROM test_runs tr WHERE tr.outcome = 'passed'" + run_platform, params
    )
    failed = await scalar(
        "SELECT count(*) FROM test_runs tr WHERE tr.outcome = 'failed'" + run_platform, params
    )
    not_tested = await scalar(
        "SELECT count(*) FROM test_runs tr WHERE tr.outcome = 'not_tested'" + run_platform,
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
