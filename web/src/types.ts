/**
 * 平台领域类型。字段名以 docs/plan/api-design.md 与 docs/platform-prototype/schema.sql 为准。
 *
 * 关键原则（frontend-spec.md §8）：
 * - state 与 outcome 是两个字段，不能压成一个 status；outcome=null 不等于失败或通过。
 * - 指标 value=null 表示缺失/不支持，必须显示原因，不能用 0 代替。
 */

export type Platform = 'android' | 'ios' | 'web'

/** 目标端选择器取值，'all' 表示不按端过滤 */
export type TargetScope = 'all' | Platform

/** schema.sql test_runs.state */
export type RunState =
  | 'queued'
  | 'dispatching'
  | 'running'
  | 'finalizing'
  | 'completed'
  | 'errored'
  | 'cancelled'

/** schema.sql test_runs.outcome（仅 completed 时非空） */
export type RunOutcome = 'passed' | 'failed' | 'not_tested'

/** schema.sql test_tasks.lifecycle */
export type TaskLifecycle = 'draft' | 'ready' | 'archived'

/** schema.sql task_revisions.readiness */
export type TaskReadiness = 'draft' | 'validated'

/** schema.sql execution_resources.status */
export type ResourceStatus = 'ready' | 'offline' | 'unauthorized' | 'draining'

/** schema.sql gate_evaluations.mode */
export type GateMode = 'original' | 'reanalysis'

/** schema.sql artifacts.availability */
export type ArtifactAvailability = 'available' | 'missing' | 'expired'

/**
 * 测试类型：UI 自动化 / 性能测试 / 联动。
 * 这是**前端向导与页面**的词汇；提交给后端时要映射成 TestType（perf -> performance）。
 */
export type TestModule = 'ui' | 'perf' | 'joint'

/**
 * 后端 task_revisions.test_type 的原始取值（DB CHECK：ui / performance / joint）。
 * 页面展示一律用 MODULE_NAMES 映射，不能直接拿 'perf' 去比对接口返回值。
 */
export type TestType = 'ui' | 'performance' | 'joint'

/**
 * 展示态：由 state + outcome 合成，只用于渲染徽章，不回写后端。
 * 推导规则见 lib/display.ts。
 */
export type DisplayStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'passed'
  | 'failed'
  | 'not_tested'
  | 'errored'
  | 'cancelled'
  | 'ready'

export interface ResourceSummary {
  id: string
  name: string
  status: ResourceStatus
  profile: string
  os: string
  resolution?: string | null
  serial?: string | null
  /** 占用者运行 ID；status=ready 时为 null */
  holderRunId?: string | null
  queueCount?: number
  readinessHint?: string | null
  host?: string | null
}

/** 一次性列表响应（游标分页留到接入真实数据时补 pageCursor） */
export interface ListResponse<T> {
  items: T[]
  total?: number
}

/** 统一错误信封（frontend-spec §3 / api-design.md） */
export interface ApiErrorEnvelope {
  code: string
  message: string
  /** 服务端中间件始终回带；与响应头 X-Request-Id 一致 */
  request_id: string
  details?: Record<string, unknown>
}

/** ---- 以下为 P1 接入 /api/v1 后新增的后端响应类型（字段名与 server/app/routers/*.py 一致）---- */

/** GET /api/v1/overview（server/app/routers/overview.py 的 OverviewOut） */
export interface OverviewSummary {
  application_total: number
  resource_total: number
  resource_ready: number
  run_total: number
  run_running: number
  passed: number
  failed: number
  not_tested: number
  /** passed / (passed + failed)；分母为 0 时后端返回 null，前端显示破折号 */
  pass_rate: number | null
  needs_attention: number
}

/** GET /api/v1/applications 的一行 */
export interface ApplicationRecord {
  id: string
  project_id: string
  name: string
  platform: Platform
  identifier: string
  task_count: number
  archived_at?: string | null
  created_at?: string | null
}

export interface ApplicationsResponse {
  items: ApplicationRecord[]
  total: number
  by_platform: Record<string, number>
}

/** GET /api/v1/resources 里嵌套的档案（来自 resource_profiles.spec jsonb） */
export interface ResourceProfile {
  name: string | null
  os_name: string | null
  os_version: string | null
  screen_resolution: string | null
}

/** GET /api/v1/resources 的一行（server/app/routers/resources.py） */
export interface ResourceRecord {
  id: string
  project_id: string
  node_id: string | null
  name: string
  resource_key: string
  status: ResourceStatus
  kind: string
  platform: Platform
  profile_id: string | null
  /** 最近一次被 /resources/sync 确认在线；null = 从未同步过 */
  last_seen_at: string | null
  profile: ResourceProfile | null
  /** 由未释放租约推导，不是库列 */
  busy: boolean
  lease: { run_id: string | null; debug_session_id: string | null } | null
}

export interface ResourceCounts {
  ready_idle: number
  ready_busy: number
  offline: number
  unauthorized: number
  draining: number
}

export interface ResourcesResponse {
  items: ResourceRecord[]
  total: number
  ready: number
  /** 五状态 × 空闲/占用的服务端计数（工单 15），覆盖完整过滤集合 */
  counts?: ResourceCounts
  summary: string
}

/** ---- 以下为设备注册 / 资源同步新增的类型（docs/plan/device-registration.md §4）---- */

/** GET /api/v1/projects 的一行（D5 配套） */
export interface ProjectRecord {
  id: string
  code: string
  name: string
  archived_at: string | null
}

export interface ProjectsResponse {
  items: ProjectRecord[]
  total: number
}

/** ---- 正式化改造：工作空间 / 能力 / 管理 / 引导 / 归档 / 旧数据（工单 01–10）---- */

/** GET /api/v1/workspace（单工作空间；demo_mode 为显式演示环境标识） */
export interface WorkspaceSettings {
  name: string
  customized_at: string | null
  updated_at: string | null
  demo_mode: boolean
}

/** GET /api/v1/capabilities（服务端能力摘要，前端不自行推导可执行能力） */
export interface PlatformCapability {
  platform: Platform
  supported: boolean
}

export interface Capabilities {
  version: string
  commit: string | null
  demo_mode: boolean
  fake_runner_enabled: boolean
  platforms: PlatformCapability[]
}

/** GET /api/v1/onboarding/status：完成状态由真实数据计算 */
export interface OnboardingStep {
  key: string
  title: string
  description: string
  done: boolean
  target: string | null
  count: number
}

export interface OnboardingStatus {
  complete: boolean
  steps: OnboardingStep[]
}

/** 归档预览：关联数量、活动占用与是否归档 */
export interface ArchiveBlockers {
  active_runs: { id: string; state: string }[]
  open_debug_sessions: { id: string; state: string; resource_id: string }[]
  active_leases: { id: string; resource_id: string; run_id: string | null; debug_session_id: string | null }[]
}

export interface ArchivePreview {
  entity: 'project' | 'application'
  object: Record<string, unknown>
  related_counts: Record<string, number>
  blockers: ArchiveBlockers
  archived: boolean
}

export interface ArchiveResult {
  id: string
  name: string
  archived_at: string | null
  already: boolean
}

/** GET /api/v1/legacy-review：旧演示数据候选（默认只预览） */
export interface LegacyCandidate {
  id: string
  entity: 'project' | 'application' | 'resource' | 'suite' | 'node'
  name: string
  current_name: string
  match_basis: string[]
  confidence: 'confirmed' | 'needs_manual_review'
  related_counts: Record<string, number>
  has_real_runs: boolean
  active_occupancy: boolean
  real_run_count: number
  allowed_actions: ('keep' | 'rename' | 'archive')[]
  note: string
}

export interface LegacyReview {
  items: LegacyCandidate[]
  total: number
  preview_token: string
}

export interface LegacyAction {
  id: string
  entity: string
  action: 'keep' | 'rename' | 'archive'
  name?: string
}

export interface LegacyApplyResult {
  applied: { id: string; action: string; result: string }[]
  rejected: { id: string; reason: string }[]
  preview_token: string
}

/** POST /api/v1/resources/sync 响应里的一台设备 */
export interface ResourceSyncDevice {
  resource_key: string
  status: ResourceStatus
  action: 'created' | 'updated'
  profile: { id: string; name: string; created: boolean }
}

/** POST /api/v1/resources/sync 响应里的一个节点 */
export interface ResourceSyncNode {
  node_id: string
  node_name: string
  status: 'ok' | 'unreachable'
  seen: number
  created: number
  updated: number
  offlined: number
  busy_skipped: string[]
  devices: ResourceSyncDevice[]
}

export interface ResourceSyncResponse {
  started_at: string
  duration_ms: number
  adb_path: string
  nodes: ResourceSyncNode[]
}

/** GET /api/v1/runs 的一行（server/app/routers/runs.py） */
export interface RunRecord {
  id: string
  /** 后端按 created_at 升序计算，形如 RUN-0001 */
  display_id: string
  name: string
  task_id: string | null
  application: { id: string; name: string }
  platform: Platform
  /** 来自 task_revisions.test_type（ui / performance / joint）；没有修订时为 null */
  test_type: TestType | null
  state: RunState
  outcome: RunOutcome | null
  reason_code: string | null
  not_tested_reason: string | null
  /** 由 run_components 完成比例推导；无组件时为 null（不显示 0%） */
  progress: number | null
  resource: string | null
  started_at: string | null
  ended_at: string | null
  created_at: string
}

export interface RunsResponse {
  items: RunRecord[]
  total: number
  /** 下一页游标（服务端封了过滤条件与创建水位）；尽头/空页为 null */
  next_cursor?: string | null
  has_more?: boolean
}

/** GET /api/v1/tasks 的一行（server/app/routers/tasks.py） */
export interface TaskRecord {
  id: string
  display_id: string
  name: string
  test_type: TestType | null
  lifecycle: TaskLifecycle
  /** 乐观锁版本；写操作必须回带 */
  lock_version: number
  application: { id: string; name: string }
  platform: Platform
  revision_id: string | null
  readiness: TaskReadiness | null
  run: {
    id: string
    state: RunState
    outcome: RunOutcome | null
    created_at: string | null
    ended_at: string | null
    component_total: number | null
  } | null
  revision_count: number
}

export interface TasksResponse {
  items: TaskRecord[]
  total: number
}


/** ---- 以下为 P2 新建任务向导 / 任务详情抽屉新增的类型（契约见 docs/plan/api-design.md §2.3，后端由同事并行实现）---- */

/** POST /tasks：对齐 TaskCreateIn；幂等键通过 Idempotency-Key 头携带。 */
export interface CreateTaskRequest {
  project_id?: string
  application_id: string
  name: string
  test_type: 'ui' | 'performance' | 'joint'
  platform: Platform
  /** 验证（readiness=validated）的必要绑定；缺省时任务只能是草稿 */
  build_id?: string
  suite_version_id?: string | null
  config: {
    package_name?: string
    identifier?: string
    app_version: string | null
    scenario: string | null
    device: { resource_id: string; allow_busy_queue: boolean } | null
    perf?: { duration_s: number; items: string[] }
  }
}

/** POST /api/v1/tasks 的响应（201） */
export interface CreateTaskResponse {
  id: string
  display_id: string
  lifecycle: TaskLifecycle
  lock_version: number
  readiness: TaskReadiness
  revision: {
    id: string
    readiness: TaskReadiness
    revision: number
  }
}

/**
 * GET /api/v1/tasks/{id}/revisions 的一行。
 *
 * 字段与后端严格模型 TaskRevisionRecord（extra="forbid"）逐字段一致：
 * 可空字段的键一定存在（NULL 是合法值），前端可以无条件读取。
 */
export interface TaskRevisionRecord {
  id: string
  /** 所属任务 id */
  task_id: string
  /** 修订号，从 1 开始单调递增 */
  revision: number
  readiness: TaskReadiness
  /** 后端原始枚举：ui / performance / joint */
  test_type: TestType
  created_at: string
  created_by: string
  build_id: string | null
  suite_version_id: string | null
  environment_id: string | null
  /** 脱敏配置快照（整份替换语义） */
  config: Record<string, unknown>
  /** 该修订是否已绑定运行（绑定后不可修改，api-design.md §1.3） */
  bound_run_id?: string | null
  note?: string | null
}

/** GET /api/v1/tasks/{id}/revisions 响应（列表） */
export interface TaskRevisionsResponse {
  items: TaskRevisionRecord[]
  total: number
}

/**
 * POST /api/v1/tasks/{id}/validate 的响应。
 * 422 readiness_incomplete 时返回 { code, message, details: { missing: [...] } }，
 * details 里的缺失项由后端给出，前端只展示不推导。
 */
export interface TaskValidateResponse {
  id: string
  lifecycle?: TaskLifecycle
  readiness: TaskReadiness
  revision?: { id: string; readiness: TaskReadiness; lock_version: number } | null
}

/** 422 readiness_incomplete 的 details（字段名可能是 missing / missing_checks / items） */
export interface ReadinessIncompleteDetails {
  missing?: unknown
  missing_checks?: unknown
  items?: unknown
  [key: string]: unknown
}

/** GET /api/v1/builds 的单条（工单 04 构建；字段以 services/builds.serialize_build 为准） */
export interface BuildRecord {
  id: string
  application_id: string
  version: string
  build_key: string
  source_commit?: string | null
  sha256?: string | null
  identity_state?: string
  created_at?: string | null
  [key: string]: unknown
}

export interface BuildsResponse {
  items: BuildRecord[]
  total: number
}

