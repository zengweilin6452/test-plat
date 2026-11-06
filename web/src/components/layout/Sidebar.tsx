/**
 * 侧栏：统一品牌定义、真实工作空间名称、本机模式与全站导航。
 * 不再展示虚构团队、头像身份或研发阶段标签。
 */
import { NavLink, useLocation } from 'react-router-dom'
import { SCOPE_OPTIONS } from '../../constants'
import { BRAND, usePlatform } from '../../store/platform'
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
  const { search } = useLocation()
  const { workspace, capabilities, loading, error } = usePlatform()

  const workspaceName = loading
    ? '正在加载工作空间…'
    : error || !workspace
      ? '工作空间读取失败'
      : workspace.name

  return (
    <aside className={'sidebar' + (open ? ' open' : '')} aria-label="主导航">
      <NavLink to="/overview" className="brand" onClick={onNavigate}>
        <span className="brand-mark">
          <Icon name="pulse" size={19} />
        </span>
        {BRAND.name}
      </NavLink>

      <div className="workspace" title={workspaceName}>
        <span className="workspace-icon">
          <Icon name="box" size={16} />
        </span>
        <div>
          <strong className="workspace-name">{workspaceName}</strong>
          <small>{BRAND.mode}</small>
        </div>
      </div>

      {capabilities?.demo_mode || workspace?.demo_mode ? (
        <div className="demo-badge" role="status" aria-label="演示环境">
          <span aria-hidden="true">●</span> {BRAND.demoBadge}
        </div>
      ) : null}

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
          <span className="avatar" aria-hidden="true">
            <Icon name="box" size={15} />
          </span>
          <div>
            <strong>{BRAND.mode}</strong>
            <div className="muted small">无登录 · 本机使用</div>
          </div>
        </div>
      </div>
    </aside>
  )
}
