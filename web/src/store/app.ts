/**
 * 应用维度工作区选择器（工单 19）。
 *
 * 与 store/project.ts 同一套模式：
 * - 权威来源是 URL query ?app=<uuid>（从应用列表"进入工作区"携带进来）；
 * - localStorage 只做本次会话兜底；'' / 非法值 = 未选择（null）。
 * 运行创建（POST /runs）要求显式 application_id（工单 08），所以工作区必须
 * 知道自己属于哪个应用——两个同平台应用逐个进入时，所选应用必须准确。
 */
import { useCallback, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { create } from 'zustand'

export const APP_QUERY_KEY = 'app'
const APP_STORAGE_KEY = 'testdock.appId'

export function isValidAppId(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f-]{36}$/i.test(value)
}

export function readAppFromSearch(search: string): string | null {
  const fromUrl = new URLSearchParams(search).get(APP_QUERY_KEY)
  return isValidAppId(fromUrl) ? fromUrl : null
}

function readAppFromStorage(): string | null {
  try {
    const stored = window.localStorage.getItem(APP_STORAGE_KEY)
    return isValidAppId(stored) ? stored : null
  } catch {
    return null
  }
}

function writeAppToStorage(appId: string | null): void {
  try {
    if (appId) window.localStorage.setItem(APP_STORAGE_KEY, appId)
    else window.localStorage.removeItem(APP_STORAGE_KEY)
  } catch {
    // URL 仍是权威来源
  }
}

interface AppScopeState {
  appId: string | null
  setAppId: (appId: string | null) => void
}

export const useAppStore = create<AppScopeState>((set) => ({
  appId: null,
  setAppId: (appId) => set({ appId }),
}))

export interface AppScopeHandle {
  appId: string | null
  setAppId: (appId: string | null) => void
}

export function useAppScope(): AppScopeHandle {
  const location = useLocation()
  const navigate = useNavigate()
  const setStore = useAppStore((state) => state.setAppId)
  const appId = readAppFromSearch(location.search) ?? readAppFromStorage()

  useEffect(() => {
    setStore(appId)
  }, [appId, setStore])

  const setAppId = useCallback(
    (next: string | null) => {
      setStore(next)
      writeAppToStorage(next)
      const params = new URLSearchParams(location.search)
      if (next) params.set(APP_QUERY_KEY, next)
      else params.delete(APP_QUERY_KEY)
      const search = params.toString()
      const nextSearch = search ? '?' + search : ''
      if (nextSearch !== location.search) {
        navigate(
          { pathname: location.pathname, search: nextSearch, hash: location.hash },
          { replace: true },
        )
      }
    },
    [location.hash, location.pathname, location.search, navigate, setStore],
  )

  return { appId, setAppId }
}
