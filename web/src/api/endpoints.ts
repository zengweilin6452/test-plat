/**
 * 端点封装：一处维护 URL 与查询参数，页面只调用这些函数。
 * 端点清单见 docs/plan/api-design.md；当前 P1 已实现 6 个只读端点。
 */
import { api, request } from './client'
import type {
  ApplicationsResponse,
  CreateTaskRequest,
  CreateTaskResponse,
  OverviewSummary,
  ProjectsResponse,
  ResourcesResponse,
  ResourceSyncResponse,
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

export function fetchResources(scope: TargetScope, signal?: AbortSignal, projectId?: string | null) {
  // /resources 目前只支持 status 与 project_id 过滤；平台过滤在前端按 platform 字段做（见 DevicesPage）
  void scope
  return api.get<ResourcesResponse>('/resources', { project_id: projectId || undefined }, signal)
}

/** GET /api/v1/projects —— 项目清单（设备页项目过滤用，device-registration.md D5） */
export function fetchProjects(signal?: AbortSignal) {
  return api.get<ProjectsResponse>('/projects', undefined, signal)
}

/**
 * POST /api/v1/resources/sync —— 问 adb「现在插着什么设备」并登记进设备池。
 * body 可空（缺省 = 所有项目 × 所有 online 节点）；写操作自动带 X-TestDock-Client: web。
 */
export function syncResources(body: { project_id?: string; node_id?: string } = {}) {
  return api.post<ResourceSyncResponse>('/resources/sync', body)
}

export function fetchRuns(
  scope: TargetScope,
  limit = 100,
  signal?: AbortSignal,
  extra?: { state?: string; application_id?: string; test_type?: string; q?: string; cursor?: string },
) {
  return api.get<RunsResponse>('/runs', {
    scope: scope === 'all' ? undefined : scope,
    limit,
    ...extra,
  }, signal)
}

export function fetchTasks(testType: string | undefined, q: string | undefined, signal?: AbortSignal) {
  return api.get<TasksResponse>('/tasks', { test_type: testType, q }, signal)
}

/** ---- 以下为 P2 新建任务 / 任务详情抽屉端点（api-design.md §2.3，追加，不改既有函数）---- */

/** POST /api/v1/tasks —— 建任务 + 首个修订（写操作，自动带 X-TestDock-Client: web） */
export function createTask(body: CreateTaskRequest, requestKey: string) {
  return request<CreateTaskResponse>('/tasks', {
    method: 'POST', body, headers: { 'Idempotency-Key': requestKey },
  })
}

/** GET /api/v1/tasks/{id}/revisions —— 修订历史（抽屉时间线） */
export function fetchTaskRevisions(taskId: string, signal?: AbortSignal) {
  return api.get<TaskRevisionsResponse>(`/tasks/${encodeURIComponent(taskId)}/revisions`, undefined, signal)
}

/** POST /api/v1/tasks/{id}/validate —— readiness draft -> validated */
export function validateTask(taskId: string) {
  return api.post<TaskValidateResponse>(`/tasks/${encodeURIComponent(taskId)}/validate`)
}

/** POST /api/v1/runs —— 发起运行；重跑用 parent_run_id 关联原运行（工单 11） */
export function createRun(body: {
  application_id: string
  task_id: string
  revision_id?: string
  platform: string
  request_key: string
  parent_run_id?: string
}) {
  return api.post<{ id: string; display_id: string; state: string; duplicate?: boolean }>(
    '/runs',
    body,
  )
}

/** ---- 以下为 P5 调试会话 / 模板端点（api-design.md §2.7，后端由同事并行实现）---- */

import type {
  CreateDebugSessionResponse,
  CreateTemplateRequest,
  DebugSessionRecord,
  LocatorValidateResponse,
  SnapshotCaptureResponse,
  SnapshotTreeResponse,
  TemplateVersionRecord,
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

/**
 * POST /api/v1/debug-sessions/{id}/locators/validate —— 定位验证。
 * vendor 契约是 `{target: {by, value, index?, confidence?, region?}}`，
 * 返回 `{snapshot_id, captured_at, count, matches[], passed, note}`。
 */
export function validateLocator(
  sessionId: string | number,
  target: {
    by: 'resource_id' | 'text' | 'accessibility_id' | 'u2_selector' | 'xpath' | 'image'
    value: string
    index?: number
    confidence?: number
  },
) {
  return api.post<LocatorValidateResponse>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) + '/locators/validate',
    { target },
  )
}

/** POST /api/v1/debug-sessions/{id}/snapshots —— 采集快照（with_tree 时一并采集层级树） */
export function captureSnapshot(sessionId: string | number, withTree = true) {
  return api.post<SnapshotCaptureResponse>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) + '/snapshots',
    { with_tree: withTree },
  )
}

/** GET /api/v1/debug-sessions/{id}/snapshots/{nid}/tree —— vendor 归一化节点表 */
export function fetchSnapshotTree(sessionId: string | number, snapshotId: string | number, signal?: AbortSignal) {
  return api.get<SnapshotTreeResponse>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) +
      '/snapshots/' + encodeURIComponent(String(snapshotId)) + '/tree',
    undefined,
    signal,
  )
}

/**
 * 模板代理一律显式携带调试会话：vendor TemplateStore 绑定 session.assets_dir，
 * 模板数据按调试会话隔离，后端对缺失 session_id 的请求返回 400 validation_error。
 */
function templateQuery(sessionId: string | number | null | undefined) {
  return sessionId !== null && sessionId !== undefined && sessionId !== ''
    ? { session_id: String(sessionId) }
    : undefined
}

/** GET /api/v1/templates —— vendor TemplateStore 清单（`{templates: [...]}`） */
export function fetchTemplates(sessionId: string | number | null | undefined, signal?: AbortSignal) {
  return api.get<TemplatesResponse>('/templates', templateQuery(sessionId), signal)
}

/**
 * POST /api/v1/templates —— 从**服务端保留的快照**裁剪生成模板。
 * vendor 不接受浏览器上传的图片：必须给 snapshot_id + region + logical。
 */
export function createTemplate(sessionId: string | number | null | undefined, body: CreateTemplateRequest) {
  return request<TemplateVersionRecord>('/templates', {
    method: 'POST',
    body,
    query: templateQuery(sessionId),
  })
}

/**
 * POST /api/v1/templates/validate —— IMAGE 定位验证（vendor 专用端点）。
 * `/debug-sessions/{id}/locators/validate` 传 by='image' 会 500（vendor 解包 bug），
 * 图像匹配必须走这里；响应额外带 `scores`（每次命中的相关系数）。
 */
export function validateTemplate(
  sessionId: string | number | null | undefined,
  body: { target: { by?: string; value: string; index?: number | null; confidence?: number | null; region?: number[] | null } },
) {
  return request<LocatorValidateResponse>('/templates/validate', {
    method: 'POST',
    body,
    query: templateQuery(sessionId),
  })
}

/**
 * PUT /api/v1/templates/{logical} —— 确认更新同名模板。
 * expected_old_sha256 必须等于当前版本摘要，否则 vendor 返回 409（乐观锁）。
 */
export function updateTemplate(
  logical: string,
  body: { snapshot_id: string; region: [number, number, number, number]; expected_old_sha256: string; note?: string },
  sessionId?: string | number | null,
) {
  return request<TemplateVersionRecord>(
    '/templates/' + logical.split('/').map(encodeURIComponent).join('/'),
    { method: 'PUT', body, query: templateQuery(sessionId) },
  )
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

/** ---- 以下为 P3/P4 报告与证据端点（routers/runs.py）---- */

import type { RunArtifactsResponse, RunReport } from './types'

/** GET /api/v1/runs/{id}/report —— 平台计算的报告（metricsSummary / junit / verdict / mode） */
export function fetchRunReport(runId: string, signal?: AbortSignal) {
  return api.get<RunReport>('/runs/' + encodeURIComponent(runId) + '/report', undefined, signal)
}

/** GET /api/v1/runs/{id}/artifacts —— 证据清单，download_url 由后端拼好 */
export function fetchRunArtifacts(runId: string, signal?: AbortSignal) {
  return api.get<RunArtifactsResponse>(
    '/runs/' + encodeURIComponent(runId) + '/artifacts',
    undefined,
    signal,
  )
}

/** GET /api/v1/health —— 能力核查：{status, db, vendor, runners} */
export function fetchHealth(signal?: AbortSignal) {
  return api.get<HealthDoc>('/health', undefined, signal)
}
