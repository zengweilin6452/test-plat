/**
 * 卡片 / 面板（原型 .panel、.panel-head）。
 */
import type { ReactNode } from 'react'

interface PanelProps {
  children: ReactNode
  className?: string
  /** 内边距；默认无（自行用 PanelHead / PanelBody） */
  pad?: boolean
  as?: 'section' | 'div' | 'article'
}

export function Panel({ children, className, pad = false, as = 'section' }: PanelProps) {
  const Tag = as
  const classes = ['panel']
  if (pad) classes.push('panel-pad')
  if (className) classes.push(className)
  return <Tag className={classes.join(' ')}>{children}</Tag>
}

interface PanelHeadProps {
  title: ReactNode
  /** 标题下的补充说明 */
  hint?: ReactNode
  /** 右侧操作区 */
  actions?: ReactNode
}

export function PanelHead({ title, hint, actions }: PanelHeadProps) {
  return (
    <div className="panel-head">
      <div>
        <h2>{title}</h2>
        {hint ? <div className="muted small" style={{ marginTop: 4 }}>{hint}</div> : null}
      </div>
      {actions ? <div className="flex">{actions}</div> : null}
    </div>
  )
}

/** 页头：标题 + 说明 + 右侧操作（原型 heading()） */
interface PageHeadingProps {
  title: string
  description?: ReactNode
  actions?: ReactNode
}

export function PageHeading({ title, description, actions }: PageHeadingProps) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  )
}
