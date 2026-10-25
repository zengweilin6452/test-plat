"""工作台聚合端点（api-design.md：GET /overview）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas import OverviewOut

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewOut)
async def get_overview(session: AsyncSession = Depends(get_session)) -> OverviewOut:
    """首期只统计 Android；iOS/Web 无适配器（与原型 targetScope 一致）。"""
    from sqlalchemy import text

    async def scalar(sql: str) -> int:
        result = await session.execute(text(sql))
        value = result.scalar()
        return int(value or 0)

    app_total = await scalar("SELECT count(*) FROM applications WHERE platform = 'android'")
    res_total = await scalar("SELECT count(*) FROM execution_resources")
    res_ready = await scalar("SELECT count(*) FROM execution_resources WHERE status = 'ready'")
    run_total = await scalar("SELECT count(*) FROM test_runs")
    run_running = await scalar(
        "SELECT count(*) FROM test_runs WHERE state IN ('queued','dispatching','running','finalizing')"
    )
    passed = await scalar("SELECT count(*) FROM test_runs WHERE outcome = 'passed'")
    failed = await scalar("SELECT count(*) FROM test_runs WHERE outcome = 'failed'")
    not_tested = await scalar("SELECT count(*) FROM test_runs WHERE outcome = 'not_tested'")

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
