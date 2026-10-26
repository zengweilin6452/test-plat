/**
 * 端点封装：一处维护 URL 与查询参数，页面只调用这些函数。
 * 端点清单见 docs/plan/api-design.md；当前 P1 已实现 6 个只读端点。
 */
import { api } from './client'
import type {
  ApplicationsResponse,
  CreateTaskRequest,
  CreateTaskResponse,
  OverviewSummary,
  ResourcesResponse,
  RunsResponse,
  TargetScope,
  TaskRevisionsResponse,
  TasksResponse,
  TaskValidateResponse,
} from '../types'

/** overview 不接受 scope（后端按 Android 统计），保留参数位以便后续扩展 */
export function fetchOverview(signal?: AbortSignal) {
  return api.get<OverviewSummary>('/overview', undefined, signal)
}

export function fetchApplications(signal?: AbortSignal) {
  return api.get<ApplicationsResponse>('/applications', undefined, signal)
}

export function fetchResources(scope: TargetScope, signal?: AbortSignal) {
  // /resources 目前只支持按 status 过滤；平台过滤在前端按 platform 字段做（见 DevicesPage）
  void scope
  return api.get<ResourcesResponse>('/resources', undefined, signal)
}

export function fetchRuns(scope: TargetScope, limit = 100, signal?: AbortSignal) {
  return api.get<RunsResponse>('/runs', {
    scope: scope === 'all' ? undefined : scope,
    limit,
  }, signal)
}

export function fetchTasks(testType: string | undefined, q: string | undefined, signal?: AbortSignal) {
  return api.get<TasksResponse>('/tasks', { test_type: testType, q }, signal)
}

/** ---- 以下为 P2 新建任务 / 任务详情抽屉端点（api-design.md §2.3，追加，不改既有函数）---- */

/** POST /api/v1/tasks —— 建任务 + 首个修订（写操作，自动带 X-TestDock-Client: web） */
export function createTask(body: CreateTaskRequest) {
  return api.post<CreateTaskResponse>('/tasks', body)
}

/** GET /api/v1/tasks/{id}/revisions —— 修订历史（抽屉时间线） */
export function fetchTaskRevisions(taskId: string, signal?: AbortSignal) {
  return api.get<TaskRevisionsResponse>(`/tasks/${encodeURIComponent(taskId)}/revisions`, undefined, signal)
}

/** POST /api/v1/tasks/{id}/validate —— readiness draft -> validated */
export function validateTask(taskId: string) {
  return api.post<TaskValidateResponse>(`/tasks/${encodeURIComponent(taskId)}/validate`)
}

/** ---- 以下为 P5 调试会话 / 模板端点（api-design.md §2.7，后端由同事并行实现）---- */

import type {
  CreateDebugSessionResponse,
  DebugSessionRecord,
  LocatorValidateResponse,
  TemplateRecord,
  TemplatesResponse,
} from './types'

/** POST /api/v1/debug-sessions —— 创建调试会话（写操作，自动带 X-TestDock-Client: web） */
export function createDebugSession(serial: string, purpose?: string) {
  return api.post<CreateDebugSessionResponse>('/debug-sessions', { serial, purpose })
}

/** GET /api/v1/debug-sessions/{id} —— 含 base_url 与 ws_path */
export function fetchDebugSession(id: string | number, signal?: AbortSignal) {
  return api.get<DebugSessionRecord>('/debug-sessions/' + encodeURIComponent(String(id)), undefined, signal)
}

/** DELETE /api/v1/debug-sessions/{id} —— 关闭会话并释放租约 */
export function closeDebugSession(id: string | number) {
  return api.delete<unknown>('/debug-sessions/' + encodeURIComponent(String(id)))
}

/** POST /api/v1/debug-sessions/{id}/locators/validate —— 定位验证，返回 matches[] */
export function validateLocator(
  sessionId: string | number,
  body: { snapshot_id: string | number; locator: string },
) {
  return api.post<LocatorValidateResponse>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) + '/locators/validate',
    body,
  )
}

/** GET /api/v1/debug-sessions/{id}/snapshots —— 快照清单（层级树浏览用） */
export function fetchSnapshotTree(sessionId: string | number, snapshotId: string | number, signal?: AbortSignal) {
  return api.get<unknown>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) +
      '/snapshots/' + encodeURIComponent(String(snapshotId)),
    undefined,
    signal,
  )
}

/** GET /api/v1/templates —— 复用 vendor TemplateStore 清单 */
export function fetchTemplates(signal?: AbortSignal) {
  return api.get<TemplatesResponse>('/templates', undefined, signal)
}

/** POST /api/v1/templates —— { logical_path, png_base64, confidence }；同名冲突 409 */
export function createTemplate(body: { logical_path: string; png_base64: string; confidence: number }) {
  return api.post<TemplateRecord>('/templates', body)
}

/** ---- 以下为 P6 元信息端点（api-design.md §2.8）---- */

import type { AuditEventsResponse, HealthDoc, SchemaDoc } from './types'

/** GET /api/v1/schema —— 数据设计页数据源（静态 JSON，构建时从 schema.sql 生成） */
export function fetchSchema(signal?: AbortSignal) {
  return api.get<SchemaDoc>('/schema', undefined, signal)
}

/** GET /api/v1/audit-events?run_id=&limit= —— 审计（谁改过阈值 / 取消了运行） */
export function fetchAuditEvents(
  params: { run_id?: string | null; limit?: number } = {},
  signal?: AbortSignal,
) {
  return api.get<AuditEventsResponse>('/audit-events', { run_id: params.run_id, limit: params.limit }, signal)
}

/** GET /api/v1/health —— 能力核查：{status, db, vendor, runners} */
export function fetchHealth(signal?: AbortSignal) {
  return api.get<HealthDoc>('/health', undefined, signal)
}
