/**
 * 目标端选择器（targetScope）。
 *
 * 需求：all / android / ios / web 四选一，选择结果要能在刷新、复制链接后保持。
 * 实现（为什么不放 localStorage）：
 * - 权威来源是 URL query ?scope=android，页面刷新、分享链接、浏览器前进后退都天然一致；
 * - localStorage 只做「本次会话的兜底」：直接打开 #/tasks（不带 scope）时，
 *   回填上一次选择，但一旦 URL 里有值就以 URL 为准；
 * - 组件通过 useTargetScope() 读写，写入时同时更新 URL（replace，不产生历史纪录）
 *   与 localStorage，读取时 URL 优先。
 *
 * 注意：路由用的是 HashRouter，所以 scope 落在 hash 内部的 query 上，
 * 形如 /#/tasks?scope=android，这样与原型 #tasks 的深链风格兼容。
 */
import { useCallback, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { create } from 'zustand'
import type { TargetScope } from '../types'

export const SCOPE_QUERY_KEY = 'scope'
const SCOPE_STORAGE_KEY = 'testdock.targetScope'
export const DEFAULT_SCOPE: TargetScope = 'all'

const VALID_SCOPES: TargetScope[] = ['all', 'android', 'ios', 'web']

export function isTargetScope(value: unknown): value is TargetScope {
  return typeof value === 'string' && (VALID_SCOPES as string[]).includes(value)
}

/** 解析 URLSearchParams；非法值回退到 localStorage，再回退到 'all' */
export function readScopeFromSearch(search: string): TargetScope {
  const fromUrl = new URLSearchParams(search).get(SCOPE_QUERY_KEY)
  if (isTargetScope(fromUrl)) return fromUrl
  return readScopeFromStorage()
}

function readScopeFromStorage(): TargetScope {
  try {
    const stored = window.localStorage.getItem(SCOPE_STORAGE_KEY)
    if (isTargetScope(stored)) return stored
  } catch {
    // 隐私模式 / 存储被禁用时静默降级为默认值，不影响主流程
  }
  return DEFAULT_SCOPE
}

function writeScopeToStorage(scope: TargetScope): void {
  try {
    window.localStorage.setItem(SCOPE_STORAGE_KEY, scope)
  } catch {
    // 忽略写入失败：URL 仍然是权威来源
  }
}

interface ScopeState {
  targetScope: TargetScope
  setTargetScope: (scope: TargetScope) => void
}

/** 全局镜像，供非路由上下文（如 api 层、事件）读取当前端 */
export const useScopeStore = create<ScopeState>((set) => ({
  targetScope: DEFAULT_SCOPE,
  setTargetScope: (scope) => set({ targetScope: scope }),
}))

export interface TargetScopeHandle {
  targetScope: TargetScope
  setTargetScope: (scope: TargetScope) => void
}

/**
 * 页面读取 / 切换目标端的唯一入口。
 * - 挂载时把 URL 里的 scope 同步进 store（URL 优先，缺失则回填 localStorage 值并写回 URL）；
 * - setTargetScope 同时改 store、改 URL（replace）与 localStorage。
 */
export function useTargetScope(): TargetScopeHandle {
  const location = useLocation()
  const navigate = useNavigate()
  const setStore = useScopeStore((state) => state.setTargetScope)
  const targetScope = readScopeFromSearch(location.search)

  useEffect(() => {
    setStore(targetScope)
  }, [targetScope, setStore])

  const setTargetScope = useCallback(
    (scope: TargetScope) => {
      setStore(scope)
      writeScopeToStorage(scope)
      const params = new URLSearchParams(location.search)
      if (scope === DEFAULT_SCOPE) {
        params.delete(SCOPE_QUERY_KEY)
      } else {
        params.set(SCOPE_QUERY_KEY, scope)
      }
      const search = params.toString()
      const nextSearch = search ? '?' + search : ''
      // 已一致时不触发导航，避免多余渲染
      if (nextSearch !== location.search) {
        navigate({ pathname: location.pathname, search: nextSearch, hash: location.hash }, { replace: true })
      }
    },
    [location.hash, location.pathname, location.search, navigate, setStore],
  )

  return { targetScope, setTargetScope }
}

/** 给非组件代码用：从当前 location 的 search 读一次 */
export function currentScope(): TargetScope {
  return useScopeStore.getState().targetScope
}
