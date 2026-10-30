/**
 * 页面级复用片段：上下文条（原型 L122）、规划态提示、数据占位。
 * 目的是让 9 个页面骨架风格一致，同时把"无后端数据"的处理收敛到一处。
 */
import type { ReactNode } from 'react'
import { SCOPE_OPTIONS } from '../constants'
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

/** 全站统一的"当前目标端"上下文条 */
export function ContextBar({ scope, onScopeChange, extra }: ContextBarProps) {
  const label = SCOPE_OPTIONS.find((option) => option.value === scope)?.label ?? '全部目标端'
  return (
    <div className="context-strip">
      <span className="app-icon">
        <Icon name="layers" size={15} />
      </span>
      <div>
        <strong style={{ fontSize: 13 }}>星河</strong>
        <div className="muted" style={{ fontSize: 11 }}>
          {label}
        </div>
      </div>
      <span className="divider" aria-hidden="true" />
      <span className="muted small">目标端</span>
      <ScopeSelect scope={scope} onChange={onScopeChange} />
      <span className="grow" />
      {extra}
    </div>
  )
}

/**
 * 规划态提示：该端尚未接入执行能力（原型的"规划中"分支）。
 * 用于 iOS / Web —— 不渲染任何伪造数据。
 */
export function PlannedNotice({ scope }: { scope: TargetScope }) {
  const label = SCOPE_OPTIONS.find((option) => option.value === scope)?.label ?? '该目标端'
  return (
    <Notice tone="blue" icon="clock" title={label + ' 规划中'}>
      该目标端尚未接入执行能力。当前只有 Android 具备组件基础，此页保持骨架状态，
      接入后按同一套接口与展示规则开通，不做占位假数据。
    </Notice>
  )
}

/**
 * 数据占位：后端未接入时的统一空态。
 * 明确写出"接口未接入"，避免被误读为"确实没有数据"。
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
            P1 阶段前端骨架已就位，数据接口接入后在此渲染。
          </div>
        </>
      }
      actions={action}
    />
  )
}

/** 工具条 + 搜索框（原型 .toolbar / .search） */
export function Toolbar({ children, search, onSearch }: { children?: ReactNode; search?: string; onSearch?: (value: string) => void }) {
  return (
    <div className="toolbar">
      {onSearch ? (
        <label className="search">
          <Icon name="search" size={15} />
          <input
            value={search ?? ''}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="搜索"
            aria-label="搜索"
          />
        </label>
      ) : null}
      {children}
    </div>
  )
}

/** 页面右上角主操作按钮（原型 heading actions） */
export function PrimaryAction({ label, icon = 'plus', onClick }: { label: string; icon?: IconName; onClick?: () => void }) {
  // AC-UX-01：没有接真实结果的动作必须显式"不可用"，不能渲染成点了没反应的按钮
  if (!onClick) {
    return (
      <Button kind="primary" icon={icon} disabled title="该操作尚未开放">
        {label}
      </Button>
    )
  }
  return (
    <Button kind="primary" icon={icon} onClick={onClick}>
      {label}
    </Button>
  )
}
