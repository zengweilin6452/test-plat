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
}

export function Empty({ title, description, icon = 'box', actions }: EmptyProps) {
  return (
    <div className="empty">
      <Icon name={icon} size={30} />
      <strong>{title}</strong>
      {description ? <div>{description}</div> : null}
      {actions ? <div style={{ marginTop: 14 }}>{actions}</div> : null}
    </div>
  )
}
