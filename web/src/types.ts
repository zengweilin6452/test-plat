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

/** 测试类型：UI 自动化 / 性能测试 / 联动 */
export type TestModule = 'ui' | 'perf' | 'joint'

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

export interface TargetApp {
  platform: Platform
  /** 应用名称 */
  name: string
  /** Android 包名 / iOS Bundle ID / Web 站点地址 */
  identifier: string
  /** 该端执行能力说明（已有组件基础 / 规划中） */
  capability: string
}

export interface RunSummary {
  id: string
  taskId: string
  name: string
  platform: Platform
  module: TestModule
  state: RunState
  /** completed 前必须为 null */
  outcome: RunOutcome | null
  /** errored 时的原因码，展示为徽章 */
  errorCode?: string | null
  /** 0–100，由 run_events 的进度事件推导，不做前端模拟 */
  progress?: number
  resourceLabel?: string | null
  build?: string | null
  suite?: string | null
  startedAt?: string | null
  finishedAt?: string | null
  parentRunId?: string | null
}

export interface MetricSummary {
  metricKey: string
  name: string
  unit: string
  /** null = 缺失或该设备不支持，必须配合 missingReason 展示 */
  value: number | null
  statistic: 'median' | 'p95' | 'mean' | 'min' | 'max'
  sampleCount: number | null
  missingReason?: string | null
  baselineValue?: number | null
  /** 基线不可比时给出原因（如设备档案不同） */
  baselineNotComparable?: string | null
}

/** gate_evaluations 的一行，结论由后端给出，前端只展示 */
export interface GateCheck {
  metricKey: string
  name: string
  value: number | null
  threshold: number
  operator: 'lt' | 'le' | 'gt' | 'ge'
  unit: string
  level: 'warn' | 'fail'
  sampleCount: number | null
  satisfied: boolean
}

export interface GateEvaluation {
  id: string
  mode: GateMode
  verdict: RunOutcome
  reasonCode?: string | null
  reasonText?: string | null
  checks: GateCheck[]
}

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
  request_id?: string
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
  name: string
  resource_key: string
  status: ResourceStatus
  kind: string
  platform: Platform
  profile_id: string | null
  profile: ResourceProfile | null
  /** 由未释放租约推导，不是库列 */
  busy: boolean
  lease: { run_id: string | null; debug_session_id: string | null } | null
}

export interface ResourcesResponse {
  items: ResourceRecord[]
  total: number
  ready: number
  summary: string
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
  /** 来自 task_revisions.test_type；没有修订时为 null */
  test_type: TestModule | null
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
}

/** GET /api/v1/tasks 的一行（server/app/routers/tasks.py） */
export interface TaskRecord {
  id: string
  display_id: string
  name: string
  test_type: TestModule | null
  lifecycle: TaskLifecycle
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

/**
 * POST /api/v1/tasks 的请求体（api-design.md §2.3 请求样例）。
 *
 * 只发后端契约里声明的字段，不塞前端自造字段：
 * - android 端 package_name 必填；web / ios 端应用标识走 URL / Bundle ID（由目标应用决定），
 *   因此 package_name 可省略，不在这里伪造一个包名。
 * - duration_s 只有 module != 'ui' 才发（api-design.md：module != ui 必填）。
 */
export interface CreateTaskRequest {
  /** 幂等键 UUIDv4（api-design.md §1.3） */
  request_key: string
  project_id?: string
  application_id?: string
  /** 1–60 字符 */
  name: string
  module: TestModule
  platform: Platform
  /** Android 包名：^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$，≤120 */
  package_name?: string | null
  /** 应用版本，≤40 */
  app_version?: string | null
  suite_id?: string | null
  scenario?: string | null
  device?: { resource_id: string; allow_busy_queue: boolean } | null
  perf?: { duration_s: number; items: string[]; extra_items?: string[] } | null
  ui?: null
}

/** POST /api/v1/tasks 的响应（201） */
export interface CreateTaskResponse {
  id: string
  display_id: string
  lifecycle: TaskLifecycle
  revision: {
    id: string
    readiness: TaskReadiness
    lock_version: number
  }
}

/**
 * GET /api/v1/tasks/{id}/revisions 的一行。
 *
 * 后端字段名尚未冻结，这里按 api-design.md 的命名习惯（snake_case）声明，
 * 同时把 P2 可能出现的等价写法标为可选 —— 渲染时用 asRevisionView 归一，
 * 缺失字段显示破折号，绝不猜值。
 */
export interface TaskRevisionRecord {
  id: string
  /** 修订号（revision 或 revision_no） */
  revision: number | null
  readiness: TaskReadiness | null
  test_type: TestModule | null
  created_at: string | null
  created_by?: string | null
  build_id?: string | null
  suite_version_id?: string | null
  environment_id?: string | null
  /** 脱敏配置快照 */
  config?: Record<string, unknown> | null
  /** 该修订是否已绑定运行（绑定后不可修改，api-design.md §1.3） */
  bound_run_id?: string | null
  note?: string | null
}

/** GET /api/v1/tasks/{id}/revisions 响应（列表） */
export interface TaskRevisionsResponse {
  items: TaskRevisionRecord[]
  total?: number
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
