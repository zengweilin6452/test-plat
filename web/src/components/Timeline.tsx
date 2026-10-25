/**
 * 时间线（原型 .timeline / .timeline-item）。
 * 用于执行详情、报告证据链；状态由调用方给出，本组件不推导。
 */
import type { ReactNode } from 'react'

export type TimelineState = 'pending' | 'done' | 'error'

export interface TimelineItem {
  id: string
  title: ReactNode
  /** 次要说明（时间、操作人、错误码） */
  meta?: ReactNode
  state?: TimelineState
}

export function Timeline({ items }: { items: TimelineItem[] }) {
  if (items.length === 0) {
    return <div className="muted small">暂无事件记录</div>
  }
  return (
    <div className="timeline">
      {items.map((item) => (
        <div
          key={item.id}
          className={'timeline-item' + (item.state === 'done' ? ' done' : item.state === 'error' ? ' error' : '')}
        >
          <p>{item.title}</p>
          {item.meta ? <small>{item.meta}</small> : null}
        </div>
      ))}
    </div>
  )
}
