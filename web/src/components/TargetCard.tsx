/**
 * 目标端切换（渐进式披露改造：原先的三张大卡压缩为一行紧凑 chips，
 * 能力说明收进 chip 内的小字；切换行为不变，仍由 scope store 写回 URL）。
 */
import { TARGET_CATALOG, SCOPE_OPTIONS } from '../constants'
import type { Platform, TargetScope } from '../types'

const PLATFORMS: Platform[] = ['android', 'ios', 'web']

interface TargetChipRowProps {
  scope: TargetScope
  onSelect: (scope: TargetScope) => void
}

export function TargetChipRow({ scope, onSelect }: TargetChipRowProps) {
  const options: { value: TargetScope; label: string; capability?: string }[] = [
    { value: 'all', label: '全部', capability: '所有平台' },
    ...PLATFORMS.map((platform) => ({
      value: platform as TargetScope,
      label: TARGET_CATALOG[platform].label,
      capability: TARGET_CATALOG[platform].capability,
    })),
  ]
  return (
    <div className="scope-chips" role="group" aria-label="目标端切换">
      {options.map((option) => {
        const on = scope === option.value
        return (
          <button
            key={option.value}
            type="button"
            className={'scope-chip' + (on ? ' selected' : '')}
            aria-pressed={on}
            onClick={() => onSelect(option.value)}
          >
            <strong>{option.label}</strong>
            <span className="scope-chip-cap">{option.capability}</span>
          </button>
        )
      })}
    </div>
  )
}

/** 目标端下拉（原型 context 条里的 select） */
export function ScopeSelect({
  scope,
  onChange,
}: {
  scope: TargetScope
  onChange: (scope: TargetScope) => void
}) {
  return (
    <select value={scope} onChange={(event) => onChange(event.target.value as TargetScope)} aria-label="目标端">
      {SCOPE_OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}
