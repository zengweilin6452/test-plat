/**
 * P5 / P6 新增类型（调试会话、模板、schema、审计、健康检查）。
 * 契约来源：docs/plan/api-design.md L237-258（§2.7 / §2.8）。
 * 原则：后端未给出的字段一律可空，前端显示破折号，绝不猜值。
 */

/** debug_sessions.state：opening → active → closing → closed（lost 为设备失联） */
export type DebugSessionState = 'opening' | 'active' | 'closing' | 'closed' | 'lost'

/** GET /api/v1/debug-sessions/{id}（含 base_url 与 ws_path） */
export interface DebugSessionRecord {
  id: string | number
  serial: string
  state: DebugSessionState
  base_url?: string | null
  ws_path?: string | null
  purpose?: string | null
  created_at?: string | null
  closed_at?: string | null
}

/** POST /api/v1/debug-sessions/{id}/control —— 控制权状态（token 永不下发） */
export interface DebugControlState {
  enabled: boolean
  ttl_seconds?: number
  note?: string | null
}

/** POST /api/v1/debug-sessions 的 201 响应（契约只保证 id 与 state） */
export interface CreateDebugSessionResponse {
  id: string | number
  state?: DebugSessionState
}

/** POST /api/v1/debug-sessions/{id}/locators/validate 的返回匹配项（vendor 给的是矩形） */
export interface LocatorMatch {
  x?: number | null
  y?: number | null
  width?: number | null
  height?: number | null
  confidence?: number | null
  [key: string]: unknown
}

export interface LocatorValidateResponse {
  snapshot_id?: string | null
  captured_at?: string | null
  matches?: LocatorMatch[] | null
  count?: number | null
  /** 图像模板匹配的相关系数（仅 /templates/validate 返回，与 matches 一一对应） */
  scores?: number[] | null
  /** 唯一匹配才算通过；多匹配/零匹配 vendor 给 false */
  passed?: boolean | null
  note?: string | null
  [key: string]: unknown
}

/** POST /api/v1/debug-sessions/{id}/snapshots 的响应（vendor create_snapshot） */
export interface SnapshotCaptureResponse {
  snapshot_id: string
  width?: number | null
  height?: number | null
  orientation?: string | null
  captured_at?: string | null
  tree_captured_at?: string | null
  tree_error?: string | null
  consistent?: boolean | null
}

/** vendor 归一化层级树节点（_normalized_tree_json：children 是节点下标） */
export interface SnapshotTreeNode {
  index: number
  class_name?: string | null
  resource_id?: string | null
  text?: string | null
  content_desc?: string | null
  bounds?: number[] | null
  clickable?: boolean | null
  children?: number[]
}

export interface SnapshotTreeResponse {
  nodes?: SnapshotTreeNode[] | null
  [key: string]: unknown
}

/**
 * GET /api/v1/templates 的一行 —— vendor viewer `list_templates` 原样透传：
 * `{logical, version_id, image_sha256}`。平台不做二次包装，因此没有
 * logical_path / confidence / updated_at 这些字段（旧声明是猜的）。
 */
export interface TemplateRecord {
  logical: string
  version_id?: string | null
  image_sha256?: string | null
  [key: string]: unknown
}

/** vendor 返回的是 `{templates: [...]}`，不是 `{items: [...]}` */
export interface TemplatesResponse {
  templates: TemplateRecord[]
}

/** POST /api/v1/templates 的请求体（vendor 契约：服务端从保留快照裁剪，不收浏览器图片） */
export interface CreateTemplateRequest {
  /** POST /debug-sessions/{id}/snapshots 返回的快照 id（验证时的新快照） */
  snapshot_id: string
  /** 裁剪区域 [x, y, width, height]，必须是四个整数（验证返回的命中框） */
  region: [number, number, number, number]
  /** 模板逻辑名，必须以 .png 结尾的 POSIX 相对路径 */
  logical: string
  /** 验证时使用的阈值：凭证按阈值发放，必须与验证时一致 */
  threshold: number
  /** POST /templates/validate-crop 返回的一次性验证凭证（未验证不可登记） */
  verification: string
  note?: string
}

/** POST/PUT 的成功响应（vendor `_template_payload`） */
export interface TemplateVersionRecord {
  logical: string
  version_id: string
  sha256?: string | null
  width?: number | null
  height?: number | null
  [key: string]: unknown
}

/**
 * GET /api/v1/runs/{id}/report（server/app/routers/runs.py: get_run_report）。
 * 后端字段是 camelCase，与 vendor report.json 同源；缺失字段一律可空，页面显示破折号。
 */
export interface RunReport {
  runId: string
  hostRunId?: string | null
  /** 运行引用的修订与构建（工单 11：报告可追溯原输入） */
  revision?: {
    id: string
    readiness?: string | null
    test_type?: string | null
    /** 工单 05：修订绑定的套件版本 id；旧修订可能为 null */
    suite_version_id?: string | null
  } | null
  build?: {
    id: string
    version?: string | null
    build_key?: string | null
    source_commit?: string | null
    sha256?: string | null
  } | null
  /**
   * 工单 05：套件版本与其固定代码副本摘要（只读 suite_versions 行）。
   * 未绑定套件 / 旧版本没有 code_copy 时明确为 null，不拿当前版本冒充。
   */
  suite?: {
    id: string
    version?: number | null
    source_ref?: string | null
    source_commit?: string | null
    code_copy?: {
      tree_sha256?: string | null
      file_count?: number | null
      root_rel?: string | null
    } | null
  } | null
  /** 运行时资源档案（不可变行内容）；缺失为 null，不用设备 serial 冒充 */
  resourceProfile?: { id: string; name?: string | null; fingerprint?: string | null } | null
  /** 服务端导出的证据清单：available 才有 download_url（AC-REP-03） */
  evidence?: Array<{
    id: string
    kind: string
    logical_key: string
    byte_size?: number | null
    sha256?: string | null
    availability: string
    /** 工单 05：不可用原因（file_missing / retention_expired / storage_unresolvable） */
    unavailable_reason?: string | null
    download_url?: string | null
  }> | null
  gateEvaluations?: Array<{
    mode: string
    verdict: string
    reason_code?: string | null
  }> | null
  name?: string | null
  projectId?: string | null
  applicationId?: string | null
  platform?: string | null
  resourceId?: string | null
  module?: string | null
  status?: string | null
  /** 后端门禁结论：passed / failed / not_tested；null 表示尚未判定 */
  verdict?: 'passed' | 'failed' | 'not_tested' | null
  target?: { id?: string | null; name?: string | null } | null
  deviceProfile?: string | null
  durationS?: number | null
  /** vendor metricsSummary 原样透传：{metric_key: {unit, median, sampleCount, ...}} */
  metricsSummary?: Record<string, Record<string, unknown>> | null
  /**
   * joint 采集窗口（真实时间戳）：collect_* 包围 ui.* 执行窗。
   * null 表示该运行没有联合采集窗口，不编造。
   */
  collectWindow?: {
    collect_started_at: string
    collect_stopped_at: string
    ui: { started_at: string; ended_at: string; timeout_s: number }
  } | null
  thresholdsAtRun?: Record<string, unknown> | null
  reason?: string | null
  reasonText?: string | null
  evaluatedAt?: string | null
  /** live = 真跑产物；imported = 导入补录 */
  mode?: 'live' | 'imported' | string | null
  vendorReports?: { kind?: string | null; artifact_id?: string | null }[] | null
  /** junit 用例计数：{present, tests, failures, errors, skipped, failed} */
  junit?: Record<string, unknown> | null
}

/** GET /api/v1/runs/{id}/artifacts 的一行 */
export interface RunArtifact {
  id: string
  run_id?: string | null
  component_id?: string | null
  logical_key: string
  kind?: string | null
  mime_type?: string | null
  byte_size?: number | null
  sha256?: string | null
  availability?: string | null
  /** 工单 05：不可用原因（后端按磁盘与保留期复核后给出） */
  unavailable_reason?: string | null
  /** 保留期到期时间；null 表示未配置保留策略 */
  expires_at?: string | null
  created_at?: string | null
  /** 由后端拼接，前端不自己拼路径；仅 available 才有 */
  download_url?: string | null
  [key: string]: unknown
}

export interface RunArtifactsResponse {
  items: RunArtifact[]
  total?: number
}

/** GET /api/v1/schema 的静态 JSON（表/字段/分组/泳道/写入流程）。键名以实际返回为准，这里声明为 unknown 后归一。 */
export interface SchemaDoc {
  tables?: unknown
  groups?: unknown
  lanes?: unknown
  write_flows?: unknown
  flows?: unknown
  relations?: unknown
  [key: string]: unknown
}

/** 归一后的表 / 字段 */
export interface SchemaField {
  field: string
  type: string | null
  note: string | null
}

export interface SchemaTable {
  name: string
  group: string | null
  note: string | null
  fields: SchemaField[] | null
}

export interface SchemaLane {
  name: string
  tables: string[]
}

export interface SchemaWriteFlow {
  title: string
  steps: string[]
}

export interface SchemaRelation {
  from: string
  to: string
  label: string | null
}

/** GET /api/v1/audit-events?run_id=&limit= 的一行 */
export interface AuditEventRecord {
  id: string | number
  ts?: string | null
  created_at?: string | null
  actor?: string | null
  action?: string | null
  target?: string | null
  detail?: string | null
  [key: string]: unknown
}

export interface AuditEventsResponse {
  items: AuditEventRecord[]
  total?: number
}

/** ---- 套件与用例（GET /api/v1/suites、/suites/{id}/versions；P2 suites router）---- */

/**
 * 用例清单没有独立表：存在 `suite_versions.manifest.cases`（jsonb）。
 * 字段名以 `domain/suite.normalize_case` 为准，缺失一律按"没有"处理。
 */
export interface SuiteCaseRecord {
  case_key: string
  node_id?: string | null
  file?: string | null
  entry?: string | null
  tags?: string[] | null
  [key: string]: unknown
}

export interface SuiteManifest {
  schema_version?: number
  case_count?: number
  cases?: SuiteCaseRecord[] | null
  /** 固定代码副本摘要（相对文件清单 + 树摘要）；旧版本可能没有，用 has_code_copy 判断 */
  code_copy?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface SuiteVersionRecord {
  id: string
  suite_id: string
  version: number
  source_ref?: string | null
  source_commit?: string | null
  case_count: number
  case_keys?: string[] | null
  /** UI / joint 版本是否保留固定代码副本（services/suites.py serialize_version） */
  has_code_copy?: boolean
  manifest?: SuiteManifest | null
  created_at?: string | null
}

export interface SuiteVersionsResponse {
  items: SuiteVersionRecord[]
  total?: number
}

/** GET /api/v1/suites 的单条（services/suites._suite_dict） */
export interface SuiteRecord {
  id: string
  project_id: string
  name: string
  /** ui / performance / joint（task_revisions.test_type 同一套枚举） */
  test_type: string
  application: { id: string; name: string; platform: string }
  created_at?: string | null
  archived_at?: string | null
  version_count: number
  /** 没有 discover 过的套件为 null —— 此时没有用例可展示 */
  latest_version: {
    id: string
    version: number
    case_count: number
    created_at?: string | null
  } | null
}

export interface SuitesResponse {
  items: SuiteRecord[]
  total?: number
}

/** GET /api/v1/health：{status, db, vendor:{mobile_auto,mobile_perf,versions}, runners:{active}} */
export interface HealthDoc {
  status: string
  /** 以下字段后端当前未全部返回；缺失时不渲染对应核查项（不造假数据）。 */
  db?: string
  vendor?: {
    mobile_auto?: string
    mobile_perf?: string
    versions?: unknown
  }
  runners?: {
    active?: number
  }
  version?: string
  database_target?: string
  [key: string]: unknown
}

/** ---- GET /api/v1/analyses?run_id= （性能分析页，P4）---- */

/** 分析里的单条指标（median 口径；value 为 null 时看 missing_reason，绝不用 0 顶替） */
export interface AnalysisMetric {
  key: string
  metric_key: string
  statistic?: string | null
  scope?: string | null
  window_key?: string | null
  metric_version?: string | null
  median?: number | null
  value?: number | null
  unit?: string | null
  sample_count?: number | null
  supported?: boolean | null
  missing_reason?: string | null
  missing_reason_text?: string | null
  [key: string]: unknown
}

/** 门禁检查项：vendor judge 产出的 checks 行 */
export interface GateCheck {
  metricKey: string
  median?: number | null
  op?: string | null
  threshold?: number | null
  level?: 'fail' | 'warn' | string | null
  ok?: boolean | null
  baselineValue?: number | null
  baselineSourceRunId?: string | null
  sampleCount?: number | null
  sourceRunId?: string | null
  window?: { startedAt?: string | null; stoppedAt?: string | null } | null
  reason?: string | null
  [key: string]: unknown
}

export interface BaselineOption {
  id: string
  baseline_name?: string | null
  version?: number | null
  source_run_id?: string | null
  profile?: string | null
  profile_error?: string | null
  same_profile?: boolean | null
  [key: string]: unknown
}

export interface AnalysisEvaluation {
  id: string
  component_id?: string | null
  mode?: 'original' | 'reanalysis' | string | null
  verdict?: 'passed' | 'failed' | 'not_tested' | null
  reason_code?: string | null
  reason_text?: string | null
  policy_id?: string | null
  policy_version?: number | null
  baseline_id?: string | null
  baseline_name?: string | null
  baseline_version?: number | null
  created_at?: string | null
  [key: string]: unknown
}

export interface RunAnalysis {
  run: {
    id: string
    application_id?: string | null
    application_name?: string | null
    task_id?: string | null
    task_name?: string | null
    test_type?: string | null
    platform?: string | null
    state?: string | null
    outcome?: string | null
    reason_code?: string | null
    not_tested_reason?: string | null
    started_at?: string | null
    ended_at?: string | null
    created_at?: string | null
    [key: string]: unknown
  }
  verdict?: 'passed' | 'failed' | 'not_tested' | null
  mode?: 'original' | 'reanalysis' | string | null
  original_missing?: boolean
  selected_evaluation_id?: string | null
  reason?: string | null
  reason_text?: string | null
  checks?: GateCheck[] | null
  metrics?: AnalysisMetric[] | null
  thresholds?: Record<string, unknown> | null
  context?: {
    device_profile?: string | null
    device_profile_error?: string | null
    window?: string | null
    statistic?: string | null
    platform?: string | null
    [key: string]: unknown
  } | null
  components?: { id: string; kind?: string | null; state?: string | null; outcome?: string | null; reason_code?: string | null }[] | null
  evaluations?: AnalysisEvaluation[] | null
  baseline_options?: BaselineOption[] | null
  trial?: unknown
  [key: string]: unknown
}

/** POST /api/v1/runs/{id}/gate-evaluations 的响应（试算新增判定行） */
export interface GateEvaluationResponse {
  id: string
  evaluation_id?: string | null
  mode?: 'original' | 'reanalysis' | string | null
  verdict?: 'passed' | 'failed' | 'not_tested' | null
  reason?: string | null
  reason_code?: string | null
  reason_text?: string | null
  checks?: GateCheck[] | null
  policy_id?: string | null
  policy_version?: number | null
  baseline_id?: string | null
  request_key?: string | null
  created_at?: string | null
  created?: boolean
  note?: string | null
  [key: string]: unknown
}
