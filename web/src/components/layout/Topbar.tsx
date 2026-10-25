/**
 * 顶栏（原型 L48 的 header）：面包屑 + 原型标识 + 日期 + 移动端菜单按钮。
 */
import { fmtToday } from '../../lib/fmt'
import { Button } from '../Button'
import type { NavItem } from './navItems'

interface TopbarProps {
  current?: NavItem
  onToggleMenu: () => void
}

export function Topbar({ current, onToggleMenu }: TopbarProps) {
  return (
    <header className="topbar">
      <div className="flex">
        <span className="menu-toggle" style={{ display: 'none' }}>
          <Button iconOnly icon="menu" aria-label="打开导航" onClick={onToggleMenu} />
        </span>
        <nav className="breadcrumb" aria-label="面包屑">
          <span>星河工作空间</span>
          <span aria-hidden="true">/</span>
          <strong>{current ? current.title : '工作台'}</strong>
        </nav>
      </div>
      <div className="flex">
        <span className="prototype-tag">
          <i />
          P2 · 任务创建与执行已接入
        </span>
        <span className="topbar-date">{fmtToday()}</span>
      </div>
    </header>
  )
}
