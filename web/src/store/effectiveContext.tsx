/**
 * 统一有效上下文（工单 03）：工作空间 → 项目 → 应用 → 目标端。
 *
 * 解析优先级（规格 §6）：
 *   1. URL 明确选择（含显式 project=all）；
 *   2. 经过服务端对象有效性校验的上次选择（localStorage 只保存选择）；
 *   3. 未选择。
 * - 仅 app 参数时从实际应用解析项目；project 与 app 冲突时拒绝混用并显示错误；
 * - 显式「全部项目」用 project=all 表达，不会被缓存覆盖；
 * - 深链接按对象身份解析，不受其他项目缓存干扰；归档对象仍可只读访问。
 *
 * 缓存只保存选择，不充当业务数据来源：所有对象都从 GET /applications/{id}
 * 或项目/应用列表的服务端响应校验。
 */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { fetchApplication, fetchApplications, fetchProjects } from '../api/endpoints'
import type { ApplicationRecord, ProjectRecord } from '../types'

export const PROJECT_QUERY_KEY = 'project'
export const APP_QUERY_KEY = 'app'
export const PROJECT_STORAGE_KEY = 'testdock.projectId'
export const APP_STORAGE_KEY = 'testdock.appId'
export const ALL_PROJECTS = 'all'

export function isValidId(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f-]{36}$/i.test(value)
}

export function requestedContext(urlProject: string | null, urlApp: string | null, cachedProject: string | null, cachedApp: string | null) {
  const explicitAll = urlProject === ALL_PROJECTS
  return {
    requestedProject: explicitAll ? null : isValidId(urlProject) ? urlProject : urlProject === null && urlApp === null ? cachedProject : null,
    requestedApp: explicitAll ? null : isValidId(urlApp) ? urlApp : urlApp === null && urlProject === null ? cachedApp : null,
  }
}

export interface EffectiveContext {
  /** 加载服务端对象校验中；首屏与切换时必须区分，不能伪造已配置名称 */
  loading: boolean
  /** 解析错误（对象不存在 / 已归档 / 关联不匹配 / 读取失败） */
  error: string | null
  /** 供排障展开的错误码与请求 ID */
  errorDetail: { code: string; requestId: string | null } | null
  projectId: string | null
  project: ProjectRecord | null
  appId: string | null
  application: ApplicationRecord | null
  /** 是否有显式「全部项目」选择 */
  allProjects: boolean
  /** 当前项目是否归档（历史只读详情仍可访问） */
  projectArchived: boolean
  /** 当前应用是否归档 */
  applicationArchived: boolean
  projects: ProjectRecord[]
  applications: ApplicationRecord[]
  refresh: () => void
  setProject: (id: string | null) => void
  setApplication: (id: string | null) => void
}

const Context = createContext<EffectiveContext | null>(null)

function readStorage(key: string): string | null {
  try {
    const stored = window.localStorage.getItem(key)
    return isValidId(stored) ? stored : null
  } catch {
    return null
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value) window.localStorage.setItem(key, value)
    else window.localStorage.removeItem(key)
  } catch {
    // URL 仍是权威来源
  }
}

function describe(error: unknown): { message: string; code: string; requestId: string | null } {
  if (error && typeof error === 'object' && 'code' in error) {
    const err = error as { code: string; message?: string; requestId?: string | null }
    return { message: err.message || '读取上下文失败', code: err.code, requestId: err.requestId ?? null }
  }
  return { message: error instanceof Error ? error.message : '读取上下文失败', code: 'NETWORK_ERROR', requestId: null }
}

export function EffectiveContextProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<ProjectRecord[]>([])
  const [applications, setApplications] = useState<ApplicationRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [errorDetail, setErrorDetail] = useState<EffectiveContext['errorDetail']>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  const params = useMemo(() => new URLSearchParams(location.search), [location.search])
  const urlProject = params.get(PROJECT_QUERY_KEY)
  const urlApp = params.get(APP_QUERY_KEY)
  const explicitAll = urlProject === ALL_PROJECTS
  // URL 明确选择优先；非法 project 值不静默回退缓存，而是报错
  const invalidProject = urlProject !== null && !explicitAll && !isValidId(urlProject)
  const invalidApp = urlApp !== null && !isValidId(urlApp)
  const cachedProject = readStorage(PROJECT_STORAGE_KEY)
  const cachedApp = readStorage(APP_STORAGE_KEY)
  const { requestedProject, requestedApp } = requestedContext(urlProject, urlApp, cachedProject, cachedApp)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setErrorDetail(null)

    async function resolve() {
      // 无效参数与冲突参数：不静默落到另一个项目
      if (invalidProject || invalidApp) {
        if (!cancelled) {
          setError('链接中的项目或应用标识无效；请从项目与应用页重新选择。')
          setErrorDetail({ code: 'INVALID_CONTEXT_ID', requestId: null })
          setLoading(false)
        }
        return
      }
      try {
        // 服务端对象有效性校验：项目列表含归档筛选，应用列表含归档筛选
        const [projectList, appList] = await Promise.all([
          fetchProjects(undefined, { include_archived: true }),
          fetchApplications(undefined, { include_archived: true }),
        ])
        if (cancelled) return
        setProjects(projectList.items)
        setApplications(appList.items)

        let resolvedApp: ApplicationRecord | null = null
        if (requestedApp) {
          // 单应用详情端点：归档对象仍可读；找不到时给明确错误
          try {
            resolvedApp = await fetchApplication(requestedApp)
          } catch {
            resolvedApp = appList.items.find((item) => item.id === requestedApp) ?? null
          }
          if (!resolvedApp) {
            setError('链接中的应用不存在或读取失败；请从项目与应用页重新选择。')
            setErrorDetail({ code: 'APPLICATION_NOT_FOUND', requestId: null })
            setLoading(false)
            return
          }
        }
        if (requestedProject && resolvedApp && requestedProject !== resolvedApp.project_id) {
          setError('链接中的项目与应用归属冲突，不能混用；请从项目与应用页重新选择。')
          setErrorDetail({ code: 'CONTEXT_MISMATCH', requestId: null })
          setLoading(false)
          return
        }
        const resolvedProjectId = explicitAll
          ? null
          : requestedProject || (resolvedApp ? resolvedApp.project_id : null)
        if (resolvedProjectId && !projectList.items.some((p) => p.id === resolvedProjectId)) {
          setError('链接中的项目不存在或已被归档；请从项目与应用页重新选择。')
          setErrorDetail({ code: 'PROJECT_NOT_FOUND', requestId: null })
          setLoading(false)
          return
        }
        // 缓存只保存有效选择，不充当业务数据
        writeStorage(PROJECT_STORAGE_KEY, explicitAll ? null : resolvedProjectId)
        writeStorage(APP_STORAGE_KEY, resolvedApp?.id ?? null)
        // 仅 app 参数时把解析出的项目写回 URL，刷新与跨页一致
        if (!explicitAll && !requestedProject && resolvedApp) {
          const next = new URLSearchParams(location.search)
          next.set(PROJECT_QUERY_KEY, resolvedApp.project_id)
          navigate({ pathname: location.pathname, search: '?' + next.toString(), hash: location.hash }, { replace: true })
        }
      } catch (cause) {
        if (cancelled) return
        const info = describe(cause)
        setError('无法读取项目与应用清单：' + info.message)
        setErrorDetail({ code: info.code, requestId: info.requestId })
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void resolve()
    return () => { cancelled = true }
  }, [
    explicitAll,
    invalidApp,
    invalidProject,
    location.hash,
    location.pathname,
    location.search,
    navigate,
    refreshToken,
    requestedApp,
    requestedProject,
  ])

  const appId = requestedApp
  const projectId = explicitAll ? null : requestedProject ?? applications.find((a) => a.id === appId)?.project_id ?? null
  const project = projectId ? projects.find((p) => p.id === projectId) ?? null : null
  const application = appId ? applications.find((a) => a.id === appId) ?? null : null

  const setProject = (next: string | null) => {
    // 项目切换清除不兼容的应用选择，并同步 URL / 本地偏好 / 共享状态
    writeStorage(PROJECT_STORAGE_KEY, next)
    writeStorage(APP_STORAGE_KEY, null)
    const nextParams = new URLSearchParams(location.search)
    nextParams.delete(APP_QUERY_KEY)
    // 清空选择写入显式的 project=all，避免旧缓存被重新解释成当前项目
    if (next === null) nextParams.set(PROJECT_QUERY_KEY, ALL_PROJECTS)
    else nextParams.set(PROJECT_QUERY_KEY, next)
    // 清除不兼容的设备/构建/套件/待提交表单选择（05）
    const keys = Object.keys(window.localStorage)
    for (const key of keys) {
      if (key.startsWith('testdock.selection.')) window.localStorage.removeItem(key)
    }
    const search = nextParams.toString()
    navigate(
      { pathname: location.pathname, search: search ? '?' + search : '', hash: location.hash },
      { replace: true },
    )
    setRefreshToken((token) => token + 1)
  }

  const setApplication = (next: string | null) => {
    writeStorage(APP_STORAGE_KEY, next)
    const nextParams = new URLSearchParams(location.search)
    if (next) nextParams.set(APP_QUERY_KEY, next)
    else nextParams.delete(APP_QUERY_KEY)
    const search = nextParams.toString()
    navigate(
      { pathname: location.pathname, search: search ? '?' + search : '', hash: location.hash },
      { replace: true },
    )
    setRefreshToken((token) => token + 1)
  }

  const value: EffectiveContext = {
    loading,
    error,
    errorDetail,
    projectId,
    project,
    appId,
    application,
    allProjects: explicitAll,
    projectArchived: Boolean(project?.archived_at),
    applicationArchived: Boolean(application?.archived_at),
    projects,
    applications,
    refresh: () => setRefreshToken((token) => token + 1),
    setProject,
    setApplication,
  }

  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useEffectiveContext(): EffectiveContext {
  const value = useContext(Context)
  if (!value) throw new Error('useEffectiveContext 必须在 EffectiveContextProvider 内使用')
  return value
}

/** 查询缓存键必须包含当前项目与应用，避免旧请求被展示为新范围数据（工单 05） */
export function scopeKey(projectId: string | null, appId: string | null): string {
  return `${projectId ?? 'all'}:${appId ?? 'none'}`
}

export { isValidId as isValidContextId }
