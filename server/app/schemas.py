"""API 响应模型（P1 只读部分）。字段与 docs/plan/api-design.md 对齐。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

RunState = Literal[
    "queued", "dispatching", "running", "finalizing", "completed", "errored", "cancelled"
]
Outcome = Literal["passed", "failed", "not_tested"]


def _as_text(value: Any) -> Any:
    """把 PG 返回的 UUID 等对象规范成字符串（None 原样保留）。"""
    return str(value) if value is not None else value


#: 数据库 UUID 列在响应模型里的文本表示（OpenAPI 中仍是 string）。
UuidStr = Annotated[str, BeforeValidator(_as_text)]


class ErrorEnvelope(BaseModel):
    """统一错误信封（api-design.md §1.2）。"""

    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class ResourceProfileOut(BaseModel):
    """资源档案视图（嵌套在 ResourceRecordOut.profile）。"""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
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
    #: 显式 allow：响应模型不得沿用 pydantic 默认 extra=ignore 而静默丢字段。
    model_config = ConfigDict(extra="allow")

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

# ---------------------------------------------------------------------------
# P4：性能指标 / 三态门禁 / 基线（追加，不改动上面既有模型）
# ---------------------------------------------------------------------------

GateVerdict = Literal["passed", "failed", "not_tested"]
GateMode = Literal["original", "reanalysis"]
ReasonCode = Literal[
    "profile_mismatch",
    "sample_count_below_minimum",
    "metric_missing",
    "device_degraded",
    "gate_policy_missing",
    "run_incomplete",
]


class MetricOut(BaseModel):
    """单个指标。**缺失指标 value 为 None + missing_reason，绝不写 0.0**。"""

    model_config = ConfigDict(extra="allow")
    id: Any | None = None
    component_id: Any | None = None
    key: str
    metric_version: str | None = None
    unit: str = ""
    scope: str | None = None
    window_key: str | None = None
    statistic: Literal["median", "p95", "p90", "mean", "min", "max"]
    sample_count: int
    value: float | None = None
    supported: bool = True
    missing_reason: str | None = None
    missing_reason_text: str | None = None


class RunMetricsOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_id: Any
    state: str
    outcome: str | None = None
    reason_code: str | None = None
    device_profile: str | None = None
    device_profile_raw: Any | None = None
    device_profile_error: str | None = None
    components: list[dict[str, Any]] = []
    metric_total: int = 0
    measured_total: int = 0
    missing_total: int = 0


class BaselineOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Any
    project_id: Any | None = None
    application_id: Any | None = None
    environment_id: Any | None = None
    suite_version_id: Any | None = None
    profile_id: Any | None = None
    profile: str | None = None
    profile_raw: str | None = None
    profile_error: str | None = None
    source_component_id: Any | None = None
    source_run_id: Any | None = None
    name: str
    version: int
    created_at: datetime | None = None
    metrics: list[dict[str, Any]] = []


class GatePolicyOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Any
    project_id: Any | None = None
    application_id: Any | None = None
    application_name: str | None = None
    name: str
    version: int
    rules: dict[str, Any] = {}
    thresholds: dict[str, Any] = {}
    min_samples: int | None = None
    rules_sha256: str | None = None
    rules_error: str | None = None
    created_at: datetime | None = None


class GateEvaluationOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    evaluation_id: Any
    mode: GateMode
    verdict: GateVerdict
    reason: ReasonCode | None = None
    reason_text: str | None = None
    checks: list[dict[str, Any]] = []
    policy_id: Any | None = None
    policy_version: int | None = None
    baseline_id: Any | None = None
    request_key: str | None = None
    created_at: datetime | None = None



# --------------------------------------------------------------------------- #
# P2 追加：任务 / 修订 / 套件的请求模型
# --------------------------------------------------------------------------- #
# 只在文件尾部追加，不重排既有内容（顺序：P1 只读模型 -> P2 写模型）。
# 校验口径来自 docs/plan/api-design.md：name 1-60；package_name 正则且 <=120；
# app_version <=40；文档用 module 一词，DB 里对应 task_revisions.test_type。
# --------------------------------------------------------------------------- #

TRACK_CLIENT = "web-client"

#: 平台枚举（与 applications.platform 的 CHECK 一致，按字母序方便前端渲染）
Platform = Literal["android", "ios", "web"]
#: DB 里叫 test_type，文档里叫 module，取值一致
TestType = Literal["ui", "performance", "joint"]

_PACKAGE_NAME_RE = r"^[a-zA-Z]\w*(\.[a-zA-Z]\w*)+$"


class TaskCreateIn(BaseModel):
    """POST /tasks 请求体。

    build_id / suite_version_id 都允许为空：先建草稿、后补齐是主要流程
    （readiness='draft' 的 DB CHECK 只要求非 validated 时可以为空）。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    test_type: TestType
    platform: Platform
    application_id: str = Field(min_length=1)
    #: 可选：不传则由服务端按 application_id 反查
    project_id: str | None = None
    build_id: str | None = None
    suite_version_id: str | None = None
    #: task_revisions.environment_id 是 NOT NULL，但不属于业务概念；
    #: 不传时回落到该项目下最早创建的 environment。
    environment_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class TaskPatchIn(BaseModel):
    """PATCH /tasks 请求体。

    lock_version 必填：这是乐观锁的 CAS 条件，缺了就无法区分"读后写"与"盲写"。
    其余字段为 None 表示"不改"（区分不了显式置空，需要清空时用 null 语义的字段除外，
    本阶段没有需要清空的字段，因此刻意不做 undefined 区分）。
    """

    model_config = ConfigDict(extra="forbid")

    lock_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    test_type: TestType | None = None
    platform: Platform | None = None
    build_id: str | None = None
    suite_version_id: str | None = None
    environment_id: str | None = None
    #: None = 沿用旧 config；非 None = 整份替换（修订是快照，不做深合并）
    config: dict[str, Any] | None = None


class TaskValidateIn(BaseModel):
    """POST /tasks/{id}/validate 请求体（当前无需参数，占位以保持接口可扩展）。"""

    model_config = ConfigDict(extra="forbid")


class SuiteSourceOut(BaseModel):
    """GET /suite-sources 的单项：只有 source_id、显示名与适用类型。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    test_types: list[str] = Field(default_factory=list)


class SuiteSourcesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SuiteSourceOut] = Field(default_factory=list)
    total: int
    #: 来源为空时的明确提示（需要宿主配置）；有来源时为 None。
    #: 空数组本身不解释原因，页面不能靠"空列表"猜出下一步该做什么。
    hint: str | None = None


class SuiteCreateIn(BaseModel):
    """POST /suites：从预配置来源登记套件并发布 V1。

    浏览器只提交 source_id；宿主路径由服务端配置决定，不接受任意路径。
    """

    model_config = ConfigDict(extra="forbid")

    application_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    test_type: Literal["ui", "performance", "joint"]
    #: UI 套件必填；performance 是声明式场景、joint 在发布版本时提供来源
    source_id: str | None = Field(default=None, min_length=1)
    source_ref: str | None = None
    source_commit: str | None = None


class NetOverridesIn(BaseModel):
    """vendor net_profile=custom 的整形参数（四项必须齐全、非负）。"""

    model_config = ConfigDict(extra="forbid")

    latency_ms: float = Field(ge=0)
    down_kbps: float = Field(ge=0)
    up_kbps: float = Field(ge=0)
    loss_pct: float = Field(ge=0, le=100)


class PageMarkIn(BaseModel):
    """页面打标：相对采集窗口起点 at_s 秒时对 page 页计一次整页加载起点。"""

    model_config = ConfigDict(extra="forbid")

    page: str = Field(min_length=1, max_length=200)
    at_s: float = Field(ge=0)


class PerformanceScenarioIn(BaseModel):
    """声明式性能场景：固定采集时长 + 实际支持的采集项（不是 pytest 用例）。

    可选能力字段（2026-11 性能能力接入，缺省即不启用）：
    start_mode 启动编排（cold/warm）、capture_har 抓 HAR、net_profile/net_tier/
    net_port/net_mitmdump/net_overrides 网络剖面与代理、frame_poll 逐帧统计、
    page_marks 页面打标（→ page_load_ms）。取值域在 domain.scenario_problems
    与 runner perf_config 两端镜像校验。
    """

    model_config = ConfigDict(extra="forbid")

    duration_s: int = Field(ge=10, le=3600)
    items: list[str] = Field(min_length=1)
    app_package: str | None = None
    start_mode: Literal["cold", "warm"] | None = None
    capture_har: bool | None = None
    net_profile: Literal["none", "4g", "3g", "weak", "custom"] | None = None
    net_tier: Literal["passthrough", "decrypt"] | None = None
    net_port: int | None = Field(default=None, ge=1, le=65535)
    net_mitmdump: str | None = Field(default=None, max_length=500)
    net_overrides: NetOverridesIn | None = None
    frame_poll: bool | None = None
    page_marks: list[PageMarkIn] | None = Field(default=None, max_length=50)


class SuiteVersionPublishIn(BaseModel):
    """POST /suites/{id}/versions：发布 performance 声明式场景或 joint 完整组合。

    UI 版本由 discover 产生；joint 必须同时给 UI 代码来源（source_id）与性能采集项。
    """

    model_config = ConfigDict(extra="forbid")

    scenario: PerformanceScenarioIn
    ui_timeout_s: int | None = Field(default=None, gt=0)
    source_id: str | None = None
    source_ref: str | None = None
    source_commit: str | None = None


class SuiteDiscoverIn(BaseModel):
    """POST /suites/{id}/discover 请求体。

    只接受预配置 source_id（spec §9.2）：浏览器不能传任意宿主路径，
    服务端按配置解析来源、复制固定副本，再在副本上发现。
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    #: 可选覆盖；缺省用 source_id 与 "local"（两列在 DB 里都是 NOT NULL）
    source_ref: str | None = None
    source_commit: str | None = None


class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    revision: int
    test_type: str
    readiness: str
    build_id: str | None = None
    suite_version_id: str | None = None
    environment_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime | None = None


class SuiteVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    suite_id: str
    version: int
    source_ref: str
    source_commit: str
    case_count: int = 0
    case_keys: list[str] = Field(default_factory=list)
    #: 旧版本没有固定代码副本时为 False，界面标“未保留固定代码”。
    has_code_copy: bool = False
    manifest: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


# --------------------------------------------------------------------------- #
# P2 追加：GET /tasks/{id}/revisions 的**冻结**契约
# --------------------------------------------------------------------------- #
# 为什么要单独定义一份"字段全部写死"的模型：前端时间线已经按这组字段渲染路由响应，
# 如果服务端改成可选字段 + 前端破折号兜底，字段名一漂移就会静默变成 "—"。
# 因此这里：
#   1. 字段名、类型、是否必填全部显式写死（不用 from_attributes 的宽松猜测）；
#   2. 多余字段一律 forbid（服务端多给字段 = 契约变了，必须同时改前端）；
#   3. service 层用 model_validate 自检，保证"模型"与"实际返回"永远不会漂移。
# 注意 environment_id / build_id / suite_version_id 是**可空但必填**：
# 键必须出现（NULL 是合法值），这样前端可以无条件读取而不做键存在性判断。


class TaskRevisionRecord(BaseModel):
    """一条任务修订（不可变快照）。GET /tasks/{id}/revisions 的 items 元素。"""

    model_config = ConfigDict(extra="forbid")

    #: 修订 id（UUID 文本）
    id: str
    #: 所属任务 id，前端用它做时间线的归属校验
    task_id: str
    #: 修订序号，从 1 开始单调递增；列表按它倒序
    revision: int
    #: 测试类型：ui / performance / joint
    test_type: TestType
    #: 就绪状态：draft / validated
    readiness: Literal["draft", "validated"]
    #: 关联构建；未绑定为 null（键一定存在）
    build_id: str | None
    #: 关联套件版本；未绑定为 null（键一定存在）
    suite_version_id: str | None
    #: 执行环境；DB 里 NOT NULL，但保留可空以兼容历史数据
    environment_id: str | None
    #: 配置快照（整份替换语义，不做深合并）
    config: dict[str, Any]
    #: 产生该修订的 actor
    created_by: str
    #: 创建时间（ISO8601 字符串）
    created_at: datetime


class TaskRevisionListOut(BaseModel):
    """GET /tasks/{id}/revisions 的响应体：items 按 revision 倒序。"""

    model_config = ConfigDict(extra="forbid")

    items: list[TaskRevisionRecord]
    total: int


# --------------------------------------------------------------------------- #
# 工单 01：现有只读端点的具名响应模型
# --------------------------------------------------------------------------- #
# 约定：
#   - extra="allow"：响应模型只约束已声明字段，额外字段原样透传，不静默丢弃；
#   - 字段集合与 server/app/routers/*.py 实际返回、web/src/types.ts 保持一致；
#   - 前端契约测试（web/tests/contract.test.cjs）会逐字段比对 OpenAPI 与 TS。
# 只在文件尾部追加，不重排既有内容。


class ApplicationRecordOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UuidStr
    project_id: UuidStr
    name: str
    platform: str
    identifier: str
    task_count: int


class ApplicationsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[ApplicationRecordOut]
    total: int
    by_platform: dict[str, int]


class LeaseOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: UuidStr | None = None
    debug_session_id: UuidStr | None = None


class ResourceRecordOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UuidStr
    project_id: UuidStr
    #: 同物理设备按项目各登记一行；项目名供前端区分卡片
    project_name: str | None = None
    node_id: UuidStr | None = None
    name: str
    resource_key: str
    status: Literal["ready", "offline", "unauthorized", "draining"]
    kind: str
    platform: str
    profile_id: UuidStr | None = None
    last_seen_at: datetime | None = None
    profile: ResourceProfileOut | None = None
    busy: bool
    lease: LeaseOut | None = None


class ResourcesOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[ResourceRecordOut]
    total: int
    ready: int
    summary: str


class ProjectRecordOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UuidStr
    code: str
    name: str
    archived_at: datetime | None = None


class ProjectsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[ProjectRecordOut]
    total: int


class ApplicationRefOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UuidStr
    name: str


class RunRecordOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UuidStr
    display_id: str
    name: str
    task_id: UuidStr | None = None
    application: ApplicationRefOut
    platform: str
    test_type: TestType | None = None
    state: RunState
    outcome: Outcome | None = None
    reason_code: str | None = None
    not_tested_reason: str | None = None
    #: 无组件时为 None（不伪造 0%）
    progress: float | None = None
    resource: str | None = None
    #: 在线查看报告入口（GET /runs/{id}/report/view）；仅完成的运行非空
    view_url: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime


class RunsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[RunRecordOut]
    total: int
    #: 下一页游标（封了过滤条件与创建水位）；尽头/空页为 None
    next_cursor: str | None = None
    has_more: bool = False


class TaskRunRefOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UuidStr
    #: 运行的持久展示编号（RUN-0001），与运行页/报告同一字符串
    display_id: str | None = None
    state: RunState
    outcome: Outcome | None = None
    created_at: datetime | None = None
    ended_at: datetime | None = None
    component_total: int | None = None


class TaskRecordOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: UuidStr
    display_id: str
    name: str
    test_type: TestType | None = None
    lifecycle: Literal["draft", "ready", "archived"]
    lock_version: int
    application: ApplicationRefOut
    platform: str
    revision_id: UuidStr | None = None
    readiness: Literal["draft", "validated"] | None = None
    run: TaskRunRefOut | None = None
    revision_count: int


class TasksOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[TaskRecordOut]
    total: int


# --------------------------------------------------------------------------- #
# 工单 04：构建登记与设备身份核对
# --------------------------------------------------------------------------- #
# 构建逻辑身份 = 项目 + 应用 + build_key；version 是业务版本。
# identity_state 在用户显式确认前保持 pending；确认后 baseline 固定，
# 不再从另一台设备静默更新。核对记录存在 app_builds.metadata.identity 下，
# 不新增表（工单约束）。


class BuildCreateIn(BaseModel):
    """POST /builds 请求体（§9.2：version/build_key，可选 source_commit/sha256）。"""

    model_config = ConfigDict(extra="forbid")

    application_id: str
    version: str
    build_key: str
    source_commit: str | None = None
    sha256: str | None = None

    @field_validator("version", "build_key")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("不能为空")
        return text

    @field_validator("source_commit")
    @classmethod
    def _optional_commit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("sha256")
    @classmethod
    def _sha256_hex64(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError("sha256 必须是 64 位小写十六进制")
        return text


class IdentityCheckIn(BaseModel):
    """POST /builds/{id}/identity-checks 请求体。"""

    model_config = ConfigDict(extra="forbid")

    resource_id: str
    purpose: Literal["manual", "pre_run"] = "manual"
    test_type: Literal["ui", "performance", "joint"] = "ui"


class ConfirmIdentityIn(BaseModel):
    """POST /builds/{id}/confirm-identity 请求体：显式提交该构建的核对结果。"""

    model_config = ConfigDict(extra="forbid")

    check_id: str


class BuildIdentityItemOut(BaseModel):
    """单个固定核对项的预期 / 观测 / 结果。"""

    model_config = ConfigDict(extra="allow")

    name: str
    status: Literal["match", "conflict", "unknown", "observed"]
    expected: Any = None
    observed: Any = None
    reason: str | None = None


class BuildIdentityBlockingOut(BaseModel):
    """阻断原因：冲突或不可读。"""

    model_config = ConfigDict(extra="allow")

    check: str
    reason: str
    detail: dict[str, Any] | None = None


class BuildIdentityBaselineOut(BaseModel):
    """已固定的设备安装身份基准。"""

    model_config = ConfigDict(extra="allow")

    package_name: str
    version_name: str
    version_code: int
    resource: dict[str, Any]
    check_id: str
    confirmed_at: str


class BuildIdentityCheckOut(BaseModel):
    """一次设备身份核对记录：设备、时间、预期、观测、结果。"""

    model_config = ConfigDict(extra="allow")

    check_id: str
    purpose: Literal["manual", "pre_run"]
    test_type: Literal["ui", "performance", "joint"]
    checked_at: str
    resource: dict[str, Any]
    device: dict[str, Any]
    expected: dict[str, Any]
    observed: dict[str, Any]
    items: list[BuildIdentityItemOut]
    result: Literal["match", "conflict", "unknown"]
    blocking: list[BuildIdentityBlockingOut]
    execution_allowed: bool
    identity_state: Literal["pending", "confirmed"]
    verification_level: str
    apk_digest_verified: bool
    verification_note: str
    superseded_by: str | None = None
    superseded_at: str | None = None


class BuildRecordOut(BaseModel):
    """构建视图：声明身份 + 核对状态 + 固定基准 + 最近一次核对。"""

    model_config = ConfigDict(extra="allow")

    id: UuidStr
    project_id: UuidStr
    application_id: UuidStr
    application_name: str | None = None
    platform: str | None = None
    package_name: str | None = None
    version: str
    build_key: str
    source_commit: str | None = None
    sha256: str | None = None
    created_at: datetime | None = None
    identity_state: Literal["pending", "confirmed"] = "pending"
    verification_level: str = "none"
    apk_digest_verified: bool = False
    verification_note: str
    baseline: BuildIdentityBaselineOut | None = None
    latest_check: BuildIdentityCheckOut | None = None
    checks: list[BuildIdentityCheckOut] = Field(default_factory=list)
    duplicate: bool = False


class BuildsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[BuildRecordOut]
    total: int
