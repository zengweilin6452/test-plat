/**
 * 格式化工具。只做展示层转换，不做任何业务判定（门禁结论一律来自后端）。
 */

/** 缺失值统一用破折号，绝不用 0 兜底（frontend-spec.md §8 第 3 条） */
export const DASH = '—'

/** 数值 + 单位；null 渲染为破折号 */
export function fmtNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return Number.isInteger(value) ? String(value) : value.toFixed(digits)
}

export function fmtWithUnit(value: number | null | undefined, unit: string, digits = 1): string {
  if (value === null || value === undefined) return DASH
  return `${fmtNumber(value, digits)} ${unit}`
}

/** 有符号百分比变化，用于"较基线"展示 */
export function fmtDelta(current: number | null | undefined, base: number | null | undefined): string {
  if (current === null || current === undefined) return DASH
  if (base === null || base === undefined || base === 0) return DASH
  const diff = ((current - base) / base) * 100
  return `${diff >= 0 ? '+' : ''}${diff.toFixed(1)}%`
}

/** 百分比（0–100），分母为 0 时返回 0，调用方需自行说明口径 */
export function fmtPercent(part: number, whole: number): number {
  if (!whole) return 0
  return Math.round((part / whole) * 100)
}

/** 秒 → 人类可读时长；跨过 60s 显示分秒 */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return DASH
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s ? `${m}分${s}秒` : `${m}分钟`
}

/**
 * UTC ISO 串 → 本地时间展示。
 * 原型的固定"14:32"是演示数据缺陷（prototype-ui-spec §8 第 13 条），这里统一走时区渲染。
 */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return DASH
  return d.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return DASH
  return d.toLocaleTimeString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

/** 顶栏日期（原型为固定字符串，这里改为真实日期 + 明确时区） */
export function fmtToday(): string {
  return new Date().toLocaleDateString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}
