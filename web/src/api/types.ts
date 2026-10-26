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

/** POST /api/v1/debug-sessions 的 201 响应（契约只保证 id 与 state） */
export interface CreateDebugSessionResponse {
  id: string | number
  state?: DebugSessionState
}

/** POST /api/v1/debug-sessions/{id}/locators/validate 的返回匹配项 */
export interface LocatorMatch {
  x?: number | null
  y?: number | null
  confidence?: number | null
  [key: string]: unknown
}

export interface LocatorValidateResponse {
  matches?: LocatorMatch[] | null
  count?: number | null
  [key: string]: unknown
}

/** GET /api/v1/templates 的一行（vendor TemplateStore 清单） */
export interface TemplateRecord {
  logical_path: string
  version?: number | string | null
  confidence?: number | null
  updated_at?: string | null
  size?: number | null
  [key: string]: unknown
}

export interface TemplatesResponse {
  items: TemplateRecord[]
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
