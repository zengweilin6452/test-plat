/**
 * 提示条（原型 .notice，含 blue / green / red 变体）。
 */
import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

export type NoticeTone = 'amber' | 'blue' | 'green' | 'red'

interface NoticeProps {
  tone?: NoticeTone
  icon?: IconName
  /** 标题行，可选 */
  title?: ReactNode
  children?: ReactNode
}

const DEFAULT_ICON: Record<NoticeTone, IconName> = {
  amber: 'alert',
  blue: 'clock',
  green: 'check',
  red: 'alert',
}

export function Notice({ tone = 'amber', icon, title, children }: NoticeProps) {
  const classes = ['notice']
  if (tone !== 'amber') classes.push(tone)
  return (
    <div className={classes.join(' ')} role="note">
      <Icon name={icon ?? DEFAULT_ICON[tone]} size={16} />
      <div className="grow">
        {title ? <div style={{ fontWeight: 600 }}>{title}</div> : null}
        {children}
      </div>
    </div>
  )
}
