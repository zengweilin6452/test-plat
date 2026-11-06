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
  BuildsResponse,
  TaskRecord,
} from '../types'

/** 工作台聚合：projectId 为空 = 显式「全部项目」跨项目汇总（工单 05） */
export function fetchOverview(scope: string | undefined, signal?: AbortSignal, projectId?: string | null) {
  return api.get<OverviewSummary>('/overview', { scope: scope || undefined, project_id: projectId || undefined }, signal)
}

export function fetchApplications(
  signal?: AbortSignal,
  params: {
    project_id?: string | null
    platform?: string | null
    include_archived?: boolean
    archived_only?: boolean
  } = {},
) {
  return api.get<ApplicationsResponse>('/applications', params, signal)
}

export function fetchApplication(id: string, signal?: AbortSignal) {
  return api.get<import('../types').ApplicationRecord>('/applications/' + encodeURIComponent(id), undefined, signal)
}

export function createProject(body: { code: string; name: string }) {
  return api.post<import('../types').ProjectRecord>('/projects', body)
}

export function renameProject(id: string, name: string) {
  return api.patch<import('../types').ProjectRecord>('/projects/' + encodeURIComponent(id), { name })
}

export function createApplication(body: {
  project_id: string
  platform: string
  name: string
  identifier: string
}) {
  return api.post<import('../types').ApplicationRecord>('/applications', body)
}

export function renameApplication(id: string, name: string) {
  return api.patch<import('../types').ApplicationRecord>('/applications/' + encodeURIComponent(id), { name })
}

export function fetchArchivePreview(entity: 'project' | 'application', id: string, signal?: AbortSignal) {
  const base = entity === 'project' ? '/projects/' : '/applications/'
  return api.get<import('../types').ArchivePreview>(base + encodeURIComponent(id) + '/archive-preview', undefined, signal)
}

export function archiveEntity(entity: 'project' | 'application', id: string) {
  const base = entity === 'project' ? '/projects/' : '/applications/'
  return api.post<import('../types').ArchiveResult>(base + encodeURIComponent(id) + '/archive', {})
}

export function restoreEntity(entity: 'project' | 'application', id: string) {
  const base = entity === 'project' ? '/projects/' : '/applications/'
  return api.post<import('../types').ArchiveResult>(base + encodeURIComponent(id) + '/restore', {})
}

export function fetchWorkspace(signal?: AbortSignal) {
  return api.get<import('../types').WorkspaceSettings>('/workspace', undefined, signal)
}

export function renameWorkspace(name: string) {
  return api.patch<import('../types').WorkspaceSettings>('/workspace', { name })
}

export function fetchCapabilities(signal?: AbortSignal) {
  return api.get<import('../types').Capabilities>('/capabilities', undefined, signal)
}

export function fetchOnboardingStatus(signal?: AbortSignal) {
  return api.get<import('../types').OnboardingStatus>('/onboarding/status', undefined, signal)
}

export function fetchLegacyReview(signal?: AbortSignal) {
  return api.get<import('../types').LegacyReview>('/legacy-review', undefined, signal)
}

export function applyLegacyActions(body: {
  preview_token: string
  actions: import('../types').LegacyAction[]
}) {
  return api.post<import('../types').LegacyApplyResult>('/legacy-review/apply', body)
}

export function fetchResources(scope: TargetScope, signal?: AbortSignal, projectId?: string | null) {
  // /resources 支持 status 与 project_id 过滤；平台过滤在前端按 platform 字段做（见 DevicesPage）
  void scope
  return api.get<ResourcesResponse>('/resources', { project_id: projectId || undefined }, signal)
}

/** GET /api/v1/projects —— 项目清单（管理列表可筛选归档） */
export function fetchProjects(
  signal?: AbortSignal,
  params: { include_archived?: boolean; archived_only?: boolean } = {},
) {
  return api.get<ProjectsResponse>('/projects', params, signal)
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
  extra?: { state?: string; application_id?: string; test_type?: string; q?: string; cursor?: string; project_id?: string | null },
) {
  return api.get<RunsResponse>('/runs', {
    scope: scope === 'all' ? undefined : scope,
    limit,
    ...extra,
  }, signal)
}

export function fetchTasks(
  testType: string | undefined,
  q: string | undefined,
  signal?: AbortSignal,
  runState?: string,
  testTypeOverride?: string,
  projectId?: string | null,
) {
  return api.get<TasksResponse>('/tasks', {
    // 兼容旧签名：fetchTasks(testType, q)（工单 20 新增 run_state 过滤）
    test_type: testTypeOverride ?? testType,
    q,
    run_state: runState,
    project_id: projectId || undefined,
  }, signal)
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

/** GET /api/v1/builds?application_id= —— 应用的构建清单（version 倒序由服务端保证） */
export function fetchBuilds(applicationId: string, signal?: AbortSignal) {
  return api.get<BuildsResponse>('/builds', { application_id: applicationId }, signal)
}

/** PATCH /api/v1/tasks/{id} —— CAS 补齐草稿的 build_id / suite_version_id */
export function patchTask(
  taskId: string,
  body: { lock_version: number; build_id?: string; suite_version_id?: string },
) {
  return api.patch<TaskRecord>('/tasks/' + encodeURIComponent(taskId), body)
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

/** ---- 套件与用例（P2 suites router；用例清单在 suite_versions.manifest 里）---- */

import type { SuiteVersionsResponse, SuitesResponse } from './types'

/** GET /api/v1/suites —— 套件列表；test_type 精确过滤（ui / performance / joint） */
export function fetchSuites(testType: string | undefined, signal?: AbortSignal, projectId?: string | null) {
  return api.get<SuitesResponse>('/suites', { test_type: testType, project_id: projectId || undefined }, signal)
}

/** GET /api/v1/suites/{id}/versions —— 版本列表（version 倒序，manifest 带用例清单） */
export function fetchSuiteVersions(suiteId: string, signal?: AbortSignal) {
  return api.get<SuiteVersionsResponse>(
    '/suites/' + encodeURIComponent(suiteId) + '/versions',
    undefined,
    signal,
  )
}

/** ---- 以下为 P5 调试会话 / 模板端点（api-design.md §2.7，后端由同事并行实现）---- */

import type {
  CreateDebugSessionResponse,
  CreateTemplateRequest,
  DebugControlState,
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

/** POST /api/v1/debug-sessions/{id}/control —— 领取/释放真机控制权（token 不出服务端） */
export function setDebugControl(sessionId: string | number, enabled: boolean) {
  return api.post<DebugControlState>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) + '/control',
    { enabled },
  )
}

/** POST /api/v1/debug-sessions/{id}/control/heartbeat —— 2s 续期，失效会返回 control_expired */
export function heartbeatDebugControl(sessionId: string | number) {
  return api.post<DebugControlState>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) + '/control/heartbeat',
    {},
  )
}

/** POST /api/v1/debug-sessions/{id}/input/key —— 直接操控的返回/Home 等有限键 */
export function sendDebugKey(sessionId: string | number, name: string) {
  return api.post<{ ok?: boolean }>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) + '/input/key',
    { name },
  )
}

/** H.264 预览 WS 路径（Phase 2；失败时前端回退 JPEG） */
export function debugVideoWsPath(sessionId: string | number): string {
  return '/api/v1/ws/debug/' + encodeURIComponent(String(sessionId)) + '/video'
}

/** 手势 WS 路径（与预览同一 Vite/平台代理；协议由 vendor 定义） */
export function debugGestureWsPath(sessionId: string | number): string {
  return '/api/v1/ws/debug/' + encodeURIComponent(String(sessionId)) + '/gesture'
}

/** POST /api/v1/debug-sessions/{id}/snapshots —— 采集快照（with_tree 时一并采集层级树） */
export function captureSnapshot(sessionId: string | number, withTree = true) {
  return api.post<SnapshotCaptureResponse>(
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) + '/snapshots',
    { with_tree: withTree },
  )
}

/** GET /api/v1/debug-sessions/{id}/snapshots/{nid}/image —— 快照原图（PNG/JPEG） */
export function snapshotImagePath(sessionId: string | number, snapshotId: string | number): string {
  return (
    '/debug-sessions/' + encodeURIComponent(String(sessionId)) +
    '/snapshots/' + encodeURIComponent(String(snapshotId)) + '/image'
  )
}

export function fetchSnapshotImage(
  sessionId: string | number,
  snapshotId: string | number,
  signal?: AbortSignal,
) {
  return api.blob(snapshotImagePath(sessionId, snapshotId), signal)
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

/** ---- 以下为性能分析端点（routers/analyses.py，P4）---- */

import type { GateEvaluationResponse, RunAnalysis } from './types'

/**
 * GET /api/v1/analyses?run_id= —— 单次运行的分析。
 * 默认返回**原始判定**；传 evaluation_id 才切到那条（通常是试算产生的 reanalysis）。
 */
export function fetchAnalysis(
  runId: string,
  evaluationId?: string | null,
  signal?: AbortSignal,
) {
  return api.get<RunAnalysis>(
    '/analyses',
    { run_id: runId, evaluation_id: evaluationId || undefined },
    signal,
  )
}

/**
 * POST /api/v1/runs/{id}/gate-evaluations —— 规则试算：只新增判定行，
 * 绝不改写原始判定与历史报告。request_key 幂等。
 */
export function createGateEvaluation(
  runId: string,
  body: { request_key: string; policy_id?: string | null; baseline_run_id?: string | null },
) {
  return api.post<GateEvaluationResponse>(
    '/runs/' + encodeURIComponent(runId) + '/gate-evaluations',
    body,
  )
}
