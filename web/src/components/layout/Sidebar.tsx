/**
 * 侧栏（原型 L47–L60 的 aside）。
 * 包含：品牌、工作空间、4 组导航、底部"当前目标端"提示与用户信息。
 */
import { NavLink, useLocation } from 'react-router-dom'
import { SCOPE_OPTIONS } from '../../constants'
import { Icon } from '../Icon'
import { NAV_GROUPS } from './navItems'
import type { TargetScope } from '../../types'

interface SidebarProps {
  scope: TargetScope
  open: boolean
  onNavigate: () => void
}

function scopeLabel(scope: TargetScope): string {
  const hit = SCOPE_OPTIONS.find((option) => option.value === scope)
  return hit ? hit.label : SCOPE_OPTIONS[0].label
}

export function Sidebar({ scope, open, onNavigate }: SidebarProps) {
  // 切页时保留 ?scope=，保证目标端选择在导航之间不丢失
  const { search } = useLocation()

  return (
    <aside className={'sidebar' + (open ? ' open' : '')} aria-label="主导航">
      <NavLink to="/overview" className="brand" onClick={onNavigate}>
        <span className="brand-mark">
          <Icon name="pulse" size={19} />
        </span>
        TestDock
      </NavLink>

      <div className="workspace">
        <span className="workspace-icon">
          <Icon name="box" size={16} />
        </span>
        <div>
          <strong>星河工作空间</strong>
          <small>内部测试平台</small>
        </div>
      </div>

      {NAV_GROUPS.map((group, index) => (
        <div key={group.label ?? 'root-' + index}>
          {group.label ? <div className="nav-label">{group.label}</div> : <div className="nav-label">概览</div>}
          {group.items.map((item) => (
            <NavLink
              key={item.path}
              to={{ pathname: item.path, search }}
              className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}
              onClick={onNavigate}
            >
              <Icon name={item.icon} size={18} />
              {item.label}
            </NavLink>
          ))}
        </div>
      ))}

      <div className="sidebar-foot">
        <div className="scope-note">
          <strong>当前目标端</strong>
          {scopeLabel(scope)} · 切换会同步到地址栏
        </div>
        <div className="profile">
          <span className="avatar">测</span>
          <div>
            <strong>测试工程组</strong>
            <div className="muted small">P1 骨架阶段</div>
          </div>
        </div>
      </div>
    </aside>
  )
}
