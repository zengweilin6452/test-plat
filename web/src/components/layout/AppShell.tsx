/**
 * 应用外壳：侧栏 + 顶栏 + 主内容区，并承载全局 Toast 容器。
 * 目标端 scope 从 URL 读取，切页时保持不变（由 NavLink 带上 search 实现）。
 */
import { useEffect, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useTargetScope } from '../../store/scope'
import { ToastProvider } from '../Toast'
import { findNavItem } from './navItems'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { targetScope } = useTargetScope()
  const [menuOpen, setMenuOpen] = useState(false)
  const current = findNavItem(location.pathname)

  // 路由变化后自动收起移动端抽屉
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  return (
    <ToastProvider>
      <Sidebar scope={targetScope} open={menuOpen} onNavigate={() => setMenuOpen(false)} />
      <div
        className={'sidebar-overlay' + (menuOpen ? ' open' : '')}
        onClick={() => setMenuOpen(false)}
        aria-hidden="true"
      />
      <div className="app">
        <Topbar current={current} onToggleMenu={() => setMenuOpen((open) => !open)} />
        <main className="main">{children}</main>
      </div>
    </ToastProvider>
  )
}

/** 上下文条里展示的应用信息（原型 L122） */
export function ContextStrip({ children }: { children: ReactNode }) {
  return <div className="context-strip">{children}</div>
}
