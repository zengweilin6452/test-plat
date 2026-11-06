/**
 * 顶栏：面包屑第一段取真实工作空间名称；显示本机模式与版本信息入口。
 */
import { Link } from 'react-router-dom'
import { fmtToday } from '../../lib/fmt'
import { BRAND, usePlatform } from '../../store/platform'
import { Button } from '../Button'
import type { NavItem } from './navItems'

interface TopbarProps {
  current?: NavItem
  onToggleMenu: () => void
}

export function Topbar({ current, onToggleMenu }: TopbarProps) {
  const { workspace, loading, error, capabilities } = usePlatform()
  const workspaceName = loading
    ? '正在加载…'
    : error || !workspace
      ? '工作空间读取失败'
      : workspace.name

  return (
    <header className="topbar">
      <div className="flex">
        <span className="menu-toggle" style={{ display: 'none' }}>
          <Button iconOnly icon="menu" aria-label="打开导航" onClick={onToggleMenu} />
        </span>
        <nav className="breadcrumb" aria-label="面包屑">
          <span className="breadcrumb-workspace" title={workspaceName}>{workspaceName}</span>
          <span aria-hidden="true">/</span>
          <strong>{current ? current.title : BRAND.name}</strong>
        </nav>
      </div>
      <div className="flex">
        <span className="mode-tag">
          <i />
          {BRAND.mode}
          {capabilities?.version ? ` · v${capabilities.version}` : ''}
        </span>
        <Link className="link-btn small" to="/about" aria-label="关于 TestDock">
          关于
        </Link>
        <span className="topbar-date">{fmtToday()}</span>
      </div>
    </header>
  )
}
