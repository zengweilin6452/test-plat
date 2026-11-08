/**
 * 页面级复用片段：上下文条、能力不可用提示、数据占位。
 * 上下文条统一由 EffectiveContextProvider 提供真实项目 / 应用名称，
 * 不再写死业务名称；规划态文案由服务端能力摘要驱动。
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { SCOPE_OPTIONS } from '../constants'
import { useEffectiveContext } from '../store/effectiveContext'
import { isPlatformSupported, usePlatform } from '../store/platform'
import type { TargetScope } from '../types'
import { Button } from './Button'
import { Empty } from './Empty'
import { Icon, type IconName } from './Icon'
import { Notice } from './Notice'
import { ScopeSelect } from './TargetCard'

interface ContextBarProps {
  scope: TargetScope
  onScopeChange: (scope: TargetScope) => void
  /** 右侧附加操作 */
  extra?: ReactNode
}

/** 全站统一的上下文条：真实项目 / 应用，或明确的未选择状态 */
export function ContextBar({ scope, onScopeChange, extra }: ContextBarProps) {
  const label = SCOPE_OPTIONS.find((option) => option.value === scope)?.label ?? '全部目标端'
  const ctx = useEffectiveContext()
  const projectLabel = ctx.loading
    ? '正在加载项目…'
    : ctx.error
      ? '上下文不可用'
      : ctx.allProjects || !ctx.projectId
        ? '全部项目'
        : (ctx.project?.name ?? '项目读取失败')
  const appLabel = ctx.loading
    ? '正在加载应用…'
    : ctx.application?.name ?? '未选择应用'

  return (
    <div className="context-strip">
      <span className="app-icon">
        <Icon name="layers" size={15} />
      </span>
      <div>
        <strong style={{ fontSize: 13 }} className="context-project-name" title={projectLabel}>
          {projectLabel}
        </strong>
        <div className="muted" style={{ fontSize: 11 }} title={appLabel}>
          {appLabel} · {label}
        </div>
      </div>
      <span className="divider" aria-hidden="true" />
      <span className="muted small">目标端</span>
      <ScopeSelect scope={scope} onChange={onScopeChange} />
      <span className="grow" />
      {ctx.error ? (
        <Notice tone="red" title="当前上下文无效">
          {ctx.error} <Link className="link-btn" to="/apps">前往项目与应用页修正</Link>
        </Notice>
      ) : null}
      {ctx.projectArchived || ctx.applicationArchived ? (
        <Notice tone="amber" title="只读历史对象">
          当前项目或应用已归档，仅可查看历史记录；恢复后才能开展新业务。
        </Notice>
      ) : null}
      {extra}
    </div>
  )
}

/**
 * 未接入执行能力的目标端：能力事实来自服务端；读取失败时不声称可用。
 */
export function PlannedNotice({ scope }: { scope: TargetScope }) {
  const label = SCOPE_OPTIONS.find((option) => option.value === scope)?.label ?? '该目标端'
  const { capabilities, error } = usePlatform()
  if (scope !== 'all' && capabilities && !isPlatformSupported(capabilities, scope)) {
    return (
      <Notice tone="blue" icon="clock" title={label + ' 尚未支持执行'}>
        该目标端当前没有接入执行能力，历史数据仍可只读查看。请改用 Android，
        或在帮助页查看接入说明；平台不会生成占位假数据。
      </Notice>
    )
  }
  if (!capabilities && error) {
    return (
      <Notice tone="red" title="能力信息读取失败">
        无法确认该目标端是否可用，因此不显示可执行入口。请检查 API 后重试。
      </Notice>
    )
  }
  return null
}

/**
 * 数据占位：读取失败与空态分开，不展示研发阶段文案。
 */
export function ApiPending({
  title,
  description,
  icon = 'box',
  action,
}: {
  title: string
  description?: ReactNode
  icon?: IconName
  action?: ReactNode
}) {
  return (
    <Empty
      icon={icon}
      title={title}
      description={
        <>
          {description}
          <div className="muted small" style={{ marginTop: 8 }}>
            当前没有可展示的数据；如接口读取失败，上方会显示错误码和下一步。
          </div>
        </>
      }
      actions={action}
    />
  )
}

/** 工具条 + 搜索框：300ms 防抖，避免每个击键都触发 URL 写入或服务端过滤请求 */
export function Toolbar({ children, search, onSearch }: { children?: ReactNode; search?: string; onSearch?: (value: string) => void }) {
  const [draft, setDraft] = useState(search ?? '')
  const timer = useRef<number | undefined>(undefined)
  // 外部值变化（清除筛选、URL 恢复）同步进输入框
  useEffect(() => { setDraft(search ?? '') }, [search])
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <div className="toolbar">
      {onSearch ? (
        <label className="search">
          <Icon name="search" size={15} />
          <input
            value={draft}
            onChange={(event) => {
              const value = event.target.value
              setDraft(value)
              window.clearTimeout(timer.current)
              timer.current = window.setTimeout(() => onSearch(value), 300)
            }}
            placeholder="搜索"
            aria-label="搜索"
          />
        </label>
      ) : null}
      {children}
    </div>
  )
}

/** 页面右上角主操作按钮 */
export function PrimaryAction({ label, icon = 'plus', onClick, disabled, busy }: { label: string; icon?: IconName; onClick?: () => void; disabled?: boolean; busy?: boolean }) {
  if (!onClick) {
    return (
      <Button kind="primary" icon={icon} disabled title="该操作尚未开放">
        {label}
      </Button>
    )
  }
  // busy 时禁用，防止长操作期间连点重复提交；文案变化由调用方控制
  return (
    <Button kind="primary" icon={icon} onClick={onClick} disabled={disabled || busy}>
      {label}
    </Button>
  )
}
