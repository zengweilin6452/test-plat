"""工作空间与平台元信息端点（正式化改造工单 01/06/07）。

- GET /workspace：唯一工作空间的显示名称（单行设置，缺行补建默认值）。
- PATCH /workspace：改名；去空白、1-60 字符，保存失败不伪造成功。
- GET /capabilities：平台能力摘要 + 版本信息。前端能力标签、关于页
  与环境标识统一从这里读取，不在前端写死「已有组件基础」一类能力描述。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..dependencies import require_client_header
from ..domain import workspace as workspace_mod

router = APIRouter(tags=["workspace"])

#: 平台当前真实支持执行能力的目标端（工单 06）。服务端是唯一事实来源，
#: 前端从这里读，不再维护自己的能力常量。
SUPPORTED_PLATFORMS: tuple[str, ...] = ("android",)
ALL_PLATFORMS: tuple[str, ...] = ("android", "ios", "web")


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    name: str
    customized_at: Any = None
    updated_at: Any = None
    #: 显式演示环境标识（TESTDOCK_DEMO_MODE=1）；不暴露数据库连接串等敏感配置
    demo_mode: bool = False


class WorkspacePatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class PlatformCapabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    platform: str
    #: 平台是否具备执行能力；与设备就绪状态分开表达
    supported: bool


class CapabilitiesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    version: str
    #: 构建能提供提交标识时才有值；否则为 null，前端如实说明「不可用」
    commit: str | None = None
    demo_mode: bool = False
    fake_runner_enabled: bool = False
    platforms: list[PlatformCapabilityOut]


@router.get("/workspace", response_model=WorkspaceOut)
async def get_workspace(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    from ..config import settings

    data = await workspace_mod.get_workspace(session)
    return {**data, "demo_mode": settings.demo_mode}


@router.patch("/workspace", response_model=WorkspaceOut)
async def patch_workspace(
    body: WorkspacePatchIn,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """改名。服务端再次去空白并校验长度；成功返回新值，失败保持原值。"""
    from ..config import settings

    data = await workspace_mod.rename_workspace(session, name=body.name)
    return {**data, "demo_mode": settings.demo_mode}


@router.get("/capabilities", response_model=CapabilitiesOut)
async def get_capabilities() -> dict[str, Any]:
    from ..config import build_commit, fake_runner_enabled, settings
    from ..main import app as fastapi_app

    return {
        "version": fastapi_app.version,
        "commit": build_commit(),
        "demo_mode": settings.demo_mode,
        "fake_runner_enabled": fake_runner_enabled(),
        "platforms": [
            {"platform": platform, "supported": platform in SUPPORTED_PLATFORMS}
            for platform in ALL_PLATFORMS
        ],
    }
