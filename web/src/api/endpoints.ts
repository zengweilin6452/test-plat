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
