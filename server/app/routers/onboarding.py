"""首次使用引导状态（正式化改造工单 08）。

完成状态完全由真实数据与检查结果计算：不存「引导进度」这种可伪造的状态，
也绝不自动生成示例项目 / 伪设备来推进步骤。跳过与否由前端本地保存，
随时可从设置页返回。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["onboarding"])


class OnboardingStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    key: str
    title: str
    description: str
    done: bool
    #: 下一步该去哪（前端路由路径）；完成后为 null
    target: str | None = None
    #: 完成该步骤时已具备的真实数量，供页面展示
    count: int = 0


class OnboardingStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    complete: bool
    steps: list[OnboardingStepOut]


@router.get("/onboarding/status", response_model=OnboardingStatusOut)
async def get_onboarding_status(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    async def scalar(sql: str) -> int:
        value = (await session.execute(text(sql))).scalar()
        return int(value or 0)

    workspace_named = int(
        (
            await session.execute(
                text("SELECT count(*) FROM workspace_settings WHERE id = 1 AND customized_at IS NOT NULL")
            )
        ).scalar()
        or 0
    )
    project_count = await scalar("SELECT count(*) FROM projects WHERE archived_at IS NULL")
    application_count = await scalar(
        "SELECT count(*) FROM applications a JOIN projects p ON p.id = a.project_id"
        " WHERE a.platform = 'android' AND a.archived_at IS NULL AND p.archived_at IS NULL"
    )
    device_count = await scalar(
        "SELECT count(*) FROM execution_resources r JOIN projects p ON p.id = r.project_id"
        " WHERE p.archived_at IS NULL"
    )
    run_count = await scalar(
        "SELECT count(*) FROM test_runs r JOIN projects p ON p.id = r.project_id"
        " JOIN applications a ON a.id = r.application_id AND a.project_id = r.project_id"
        " WHERE p.archived_at IS NULL AND a.archived_at IS NULL"
        " AND r.state = 'completed' AND r.ended_at IS NOT NULL"
    )

    steps = [
        OnboardingStepOut(
            key="workspace",
            title="设置工作空间名称",
            description="在设置页给本机工作空间起一个名字",
            done=workspace_named > 0,
            target="/settings",
            count=workspace_named,
        ),
        OnboardingStepOut(
            key="project",
            title="建立项目",
            description="在项目与应用页创建第一个项目",
            done=project_count > 0,
            target="/apps",
            count=project_count,
        ),
        OnboardingStepOut(
            key="application",
            title="登记 Android 应用",
            description="在项目下登记被测应用的包名标识",
            done=application_count > 0,
            target="/apps",
            count=application_count,
        ),
        OnboardingStepOut(
            key="device",
            title="同步执行设备",
            description="连接 Android 设备后，在执行资源页同步真实设备",
            done=device_count > 0,
            target="/devices",
            count=device_count,
        ),
        OnboardingStepOut(
            key="run",
            title="完成第一次运行",
            description="登记构建与套件输入，创建任务并发起运行",
            done=run_count > 0,
            target="/ui",
            count=run_count,
        ),
    ]
    return {"complete": all(step.done for step in steps), "steps": [step.model_dump() for step in steps]}
