/**
 * 项目维度选择器（device-registration.md D5 配套）。
 *
 * 与 store/scope.ts 同一套模式：
 * - 权威来源是 URL query ?project=<uuid>（HashRouter，落在 hash 内部 query 上）；
 * - localStorage 只做「本次会话的兜底」；
 * - 两者都没有时返回 null，由页面决定默认值（设备页取第一个未归档项目）；
 * - '' 不是合法值：清除选择用 setProjectId(null)，对应「全部项目」。
 */
import { useCallback, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { create } from 'zustand'

export const PROJECT_QUERY_KEY = 'project'
const PROJECT_STORAGE_KEY = 'testdock.projectId'

export function isValidProjectId(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f-]{36}$/i.test(value)
}

/** URL ?project= 优先；非法值忽略（返回 null 交给兜底链） */
export function readProjectFromSearch(search: string): string | null {
  const fromUrl = new URLSearchParams(search).get(PROJECT_QUERY_KEY)
  return isValidProjectId(fromUrl) ? fromUrl : null
}

function readProjectFromStorage(): string | null {
  try {
    const stored = window.localStorage.getItem(PROJECT_STORAGE_KEY)
    return isValidProjectId(stored) ? stored : null
  } catch {
    return null // 隐私模式 / 存储被禁用时静默降级
  }
}

function writeProjectToStorage(projectId: string | null): void {
  try {
    if (projectId) window.localStorage.setItem(PROJECT_STORAGE_KEY, projectId)
    else window.localStorage.removeItem(PROJECT_STORAGE_KEY)
  } catch {
    // 忽略写入失败：URL 仍然是权威来源
  }
}

interface ProjectScopeState {
  projectId: string | null
  setProjectId: (projectId: string | null) => void
}

/** 全局镜像，供非路由上下文读取当前项目 */
export const useProjectStore = create<ProjectScopeState>((set) => ({
  projectId: null,
  setProjectId: (projectId) => set({ projectId }),
}))

export interface ProjectScopeHandle {
  projectId: string | null
  setProjectId: (projectId: string | null) => void
}

/** 页面读取 / 切换项目的唯一入口（同步 store、URL 与 localStorage）。 */
export function useProjectScope(): ProjectScopeHandle {
  const location = useLocation()
  const navigate = useNavigate()
  const setStore = useProjectStore((state) => state.setProjectId)
  const projectId = readProjectFromSearch(location.search) ?? readProjectFromStorage()

  useEffect(() => {
    setStore(projectId)
  }, [projectId, setStore])

  const setProjectId = useCallback(
    (next: string | null) => {
      setStore(next)
      writeProjectToStorage(next)
      const params = new URLSearchParams(location.search)
      if (next) params.set(PROJECT_QUERY_KEY, next)
      else params.delete(PROJECT_QUERY_KEY)
      const search = params.toString()
      const nextSearch = search ? '?' + search : ''
      if (nextSearch !== location.search) {
        navigate({ pathname: location.pathname, search: nextSearch, hash: location.hash }, { replace: true })
      }
    },
    [location.hash, location.pathname, location.search, navigate, setStore],
  )

  return { projectId, setProjectId }
}
