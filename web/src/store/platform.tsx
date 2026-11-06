/**
 * 工作空间设置、品牌与能力摘要的共享来源（工单 01/06/07）。
 *
 * - 第一次加载显示加载态；读取失败显示错误和重试，不展示伪造的已配置名称；
 * - 保存失败保留输入但不显示成功（由 SettingsPage 负责表单状态）；
 * - 品牌常量只在处定义，侧栏 / 面包屑 / index.html 浏览器标题共用；
 * - 演示环境标识持续可见；能力读取失败时不默认显示可执行。
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchCapabilities, fetchWorkspace, renameWorkspace } from '../api/endpoints'
import type { Capabilities, WorkspaceSettings } from '../types'

/** TestDock 统一品牌定义：本期不提供品牌编辑界面 */
export const BRAND = {
  name: 'TestDock',
  mode: '本机模式',
  demoBadge: '演示环境',
} as const

interface PlatformState {
  workspace: WorkspaceSettings | null
  capabilities: Capabilities | null
  loading: boolean
  error: string | null
  errorDetail: { code: string; requestId: string | null } | null
  refresh: () => void
  saveWorkspace: (name: string) => Promise<WorkspaceSettings>
}

const Context = createContext<PlatformState | null>(null)

function describe(error: unknown): { message: string; code: string; requestId: string | null } {
  if (error && typeof error === 'object' && 'code' in error) {
    const err = error as { code: string; message?: string; requestId?: string | null }
    return { message: err.message || '读取失败', code: err.code, requestId: err.requestId ?? null }
  }
  return { message: error instanceof Error ? error.message : '读取失败', code: 'NETWORK_ERROR', requestId: null }
}

export function PlatformProvider({ children }: { children: ReactNode }) {
  const [workspace, setWorkspace] = useState<WorkspaceSettings | null>(null)
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [errorDetail, setErrorDetail] = useState<PlatformState['errorDetail']>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([fetchWorkspace(), fetchCapabilities()])
      .then(([ws, caps]) => {
        if (cancelled) return
        setWorkspace(ws)
        setCapabilities(caps)
        setError(null)
        setErrorDetail(null)
      })
      .catch((cause) => {
        if (cancelled) return
        const info = describe(cause)
        setError('无法读取工作空间设置：' + info.message)
        setErrorDetail({ code: info.code, requestId: info.requestId })
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [refreshToken])

  async function saveWorkspace(name: string): Promise<WorkspaceSettings> {
    // 服务端校验；失败时原状态与输入都不改，更不显示成功
    const updated = await renameWorkspace(name)
    setWorkspace(updated)
    return updated
  }

  return (
    <Context.Provider value={{
      workspace, capabilities, loading, error, errorDetail,
      refresh: () => setRefreshToken((token) => token + 1), saveWorkspace,
    }}>
      {children}
    </Context.Provider>
  )
}

export function usePlatform(): PlatformState {
  const value = useContext(Context)
  if (!value) throw new Error('usePlatform 必须在 PlatformProvider 内使用')
  return value
}

/** 能力未读到时一律返回 false，不默认显示可执行（工单 06） */
export function isPlatformSupported(caps: Capabilities | null, platform: string): boolean {
  return caps?.platforms.some((item) => item.platform === platform && item.supported) ?? false
}
