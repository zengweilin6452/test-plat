/**
 * 统计卡（原型 .stat）。
 *
 * 数值口径由调用方按后端返回的数据计算并显式传入 label/foot，
 * 组件不猜口径；值为 null 时显示破折号而不是 0。
 */
import type { ReactNode } from 'react'
import { DASH } from '../lib/fmt'

interface StatCardProps {
  label: string
  value: number | string | null | undefined
  /** 数值单位后缀（如 "%"），紧贴数字 */
  unit?: string
  /** 右上角补充（图标或说明） */
  extra?: ReactNode
  /** 底部口径说明 */
  foot?: ReactNode
}

export function StatCard({ label, value, unit, extra, foot }: StatCardProps) {
  const display = value === null || value === undefined ? DASH : String(value)
  return (
    <div className="stat">
      <div className="stat-label">
        <span>{label}</span>
        {extra}
      </div>
      <div className="stat-number">
        {display}
        {unit && display !== DASH ? <span>{unit}</span> : null}
      </div>
      {foot ? <div className="stat-foot">{foot}</div> : null}
    </div>
  )
}
