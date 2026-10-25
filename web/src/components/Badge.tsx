/**
 * 状态徽章（原型 L71 badge()）。
 *
 * 重要：所有状态文案与颜色都来自 constants.STATUS_MAP / RESOURCE_STATUS_MAP，
 * 页面不允许自己拼颜色。outcome 缺失时由 lib/display 推导成 not_tested，
 * 绝不会显示成 failed 或 passed。
 */
import type { ReactNode } from 'react'
import { RESOURCE_STATUS_MAP } from '../constants'
import { statusMeta } from '../lib/display'
import type { DisplayStatus, ResourceStatus } from '../types'

export type BadgeTone = 'green' | 'red' | 'blue' | 'amber' | 'gray'

interface BadgeProps {
  tone?: BadgeTone
  dot?: boolean
  children: ReactNode
}

export function Badge({ tone = 'gray', dot = true, children }: BadgeProps) {
  return (
    <span className={'badge ' + tone}>
      {dot ? <i className="dot" /> : null}
      {children}
    </span>
  )
}

/** 执行/任务状态徽章 */
export function StatusBadge({ status }: { status: DisplayStatus }) {
  const [tone, label] = statusMeta(status)
  return <Badge tone={tone as BadgeTone}>{label}</Badge>
}

/** 执行资源状态徽章 */
export function ResourceStatusBadge({ status }: { status: ResourceStatus }) {
  const [tone, label] = RESOURCE_STATUS_MAP[status] ?? ['gray', String(status)]
  return <Badge tone={tone as BadgeTone}>{label}</Badge>
}
