/**
 * 折叠区（渐进式披露，任务 docs/plan/ui-progressive-disclosure.md）。
 *
 * 规则：折叠区必须有明确入口与摘要（如「高级选项 · 2 项已修改」），
 * 键盘可达，aria-expanded / aria-controls 关联内容区；不引入新依赖。
 */
import { useId, useState, type ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

interface DisclosureProps {
  title: ReactNode
  /** 收起时显示的摘要，保证关键信息不藏在折叠区里 */
  summary?: ReactNode
  icon?: IconName
  defaultOpen?: boolean
  /** 受控模式：传入 open 时由 onToggle 驱动（用于同时只展开一个的场景） */
  open?: boolean
  onToggle?: (open: boolean) => void
  children: ReactNode
}

export function Disclosure({ title, summary, icon, defaultOpen = false, open, onToggle, children }: DisclosureProps) {
  const [uncontrolled, setUncontrolled] = useState(defaultOpen)
  const isOpen = open ?? uncontrolled
  const panelId = useId()
  const toggle = () => {
    const next = !isOpen
    onToggle?.(next)
    if (open === undefined) setUncontrolled(next)
  }
  return (
    <section className={'disclosure' + (isOpen ? ' open' : '')}>
      <button type="button" className="disclosure-head" aria-expanded={isOpen} aria-controls={panelId} onClick={toggle}>
        <Icon name="chevron" size={13} className="disclosure-chevron" />
        {icon ? <Icon name={icon} size={15} /> : null}
        <span className="disclosure-title">{title}</span>
        {summary ? <span className="disclosure-summary">{summary}</span> : null}
      </button>
      {isOpen ? (
        <div className="disclosure-body" id={panelId}>
          {children}
        </div>
      ) : null}
    </section>
  )
}
