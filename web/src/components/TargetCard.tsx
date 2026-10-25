/**
 * 目标端卡（原型 .target-card）：三端卡片，选中态高亮。
 * 只做选择，不发请求；切换后由 scope store 写回 URL。
 */
import { TARGET_CATALOG, SCOPE_OPTIONS } from '../constants'
import type { Platform, TargetScope } from '../types'

const PLATFORMS: Platform[] = ['android', 'ios', 'web']

interface TargetCardProps {
  scope: TargetScope
  onSelect: (scope: TargetScope) => void
}

export function TargetCardGrid({ scope, onSelect }: TargetCardProps) {
  return (
    <div className="target-overview">
      {PLATFORMS.map((platform) => {
        const meta = TARGET_CATALOG[platform]
        return (
          <button
            key={platform}
            type="button"
            className={'target-card' + (scope === platform ? ' selected' : '')}
            aria-pressed={scope === platform}
            onClick={() => onSelect(platform)}
          >
            <strong>{meta.label}</strong>
            <p>{meta.capability}</p>
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
