/**
 * 页签（原型 .tabs 下划线式）。
 * 受控组件：当前值由父级持有，切换时回调。
 */
import type { ReactNode } from 'react'

export interface TabItem<T extends string = string> {
  value: T
  label: ReactNode
  /** 右侧计数，如"24 表" */
  count?: number | string
}

interface TabsProps<T extends string> {
  items: readonly TabItem<T>[]
  active: T
  onChange: (value: T) => void
  /** 页签栏右侧的操作区 */
  action?: ReactNode
  /** 无障碍标签 */
  ariaLabel?: string
}

export function Tabs<T extends string>({
  items,
  active,
  onChange,
  action,
  ariaLabel,
}: TabsProps<T>) {
  const bar = (
    <div className="tabs" role="tablist" aria-label={ariaLabel}>
      {items.map((item) => {
        const on = item.value === active
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={on}
            className={'tab' + (on ? ' active' : '')}
            onClick={() => onChange(item.value)}
          >
            {item.label}
            {item.count !== undefined ? <span className="muted"> {item.count}</span> : null}
          </button>
        )
      })}
    </div>
  )
  if (!action) return bar
  return (
    <div className="between">
      {bar}
      <div className="flex">{action}</div>
    </div>
  )
}
