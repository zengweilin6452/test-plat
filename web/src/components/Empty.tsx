/**
 * 空态（原型 .empty）。
 * 骨架阶段所有页面在没有后端数据时都落到这里 —— 不用假数据填充。
 */
import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

interface EmptyProps {
  title: string
  description?: ReactNode
  icon?: IconName
  /** 底部操作区 */
  actions?: ReactNode
  /**
   * 加载态（工单 09）：视觉与语义都要和真实空态区分开 ——
   * aria-busy + role=status 让读屏与验收脚本都能识别「还没回来」，而不是「没有数据」。
   */
  loading?: boolean
}

export function Empty({ title, description, icon = 'box', actions, loading = false }: EmptyProps) {
  return (
    <div
      className="empty"
      data-state={loading ? 'loading' : 'empty'}
      role={loading ? 'status' : undefined}
      aria-busy={loading ? true : undefined}
      aria-live={loading ? 'polite' : undefined}
    >
      <Icon name={loading ? 'clock' : icon} size={30} />
      <strong>{title}</strong>
      {description ? <div>{description}</div> : null}
      {actions ? <div style={{ marginTop: 14 }}>{actions}</div> : null}
    </div>
  )
}
