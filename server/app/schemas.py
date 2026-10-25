"""API 响应模型（P1 只读部分）。字段与 docs/plan/api-design.md 对齐。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

RunState = Literal[
    "queued", "dispatching", "running", "finalizing", "completed", "errored", "cancelled"
]
Outcome = Literal["passed", "failed", "not_tested"]


class ErrorEnvelope(BaseModel):
    """统一错误信封（api-design.md 8.1）。"""

    code: str
    message: str
    request_id: str


class ResourceProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    os_name: str | None = None
    os_version: str | None = None
    screen_resolution: str | None = None


class ExecutionResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    serial: str
    status: Literal["ready", "offline", "unauthorized", "draining"]
    resource_profile_id: str | None = None
    platform: str = "android"


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    name: str
    platform: str
    identifier: str


class TaskSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    module: str
    lifecycle: str
    updated_at: datetime | None = None


class RunSummaryOut(BaseModel):
    """列表用：state 与 outcome 分开返回，前端自己拼展示态（原型单 status 字段要拆）。"""

    model_config = ConfigDict(from_attributes=True)
    id: str
    task_id: str
    state: RunState
    outcome: Outcome | None = None
    resource_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class OverviewOut(BaseModel):
    application_total: int
    resource_total: int
    resource_ready: int
    run_total: int
    run_running: int
    passed: int
    failed: int
    not_tested: int
    pass_rate: float | None = None
    needs_attention: int


class GenericObject(BaseModel):
    model_config = ConfigDict(extra="allow")
