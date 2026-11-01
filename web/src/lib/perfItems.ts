/**
 * mobile-perf 的 SoloPi 采集项（perf-start --items）。
 *
 * 只列会作为 items 传给 SoloPi 的项；Temperature / GPU 由 mobile-perf
 * 补采旁路自动采集，不能通过 items 选择，所以不在这里。
 */
export interface PerfItemOption {
  value: string
  label: string
  description: string
}

export const PERF_ITEM_OPTIONS: PerfItemOption[] = [
  { value: 'CPU', label: 'CPU', description: '应用进程 / 全局 CPU 占用' },
  { value: 'Memory', label: 'Memory', description: 'PSS / PrivateDirty / 全局内存' },
  { value: 'FPS', label: 'FPS', description: '帧率与卡顿；首次可能弹系统告知框' },
  { value: 'Network', label: 'Network', description: '全局上下行速率与累计流量' },
  { value: 'Battery', label: 'Battery', description: '电流 / 功率 / 电量；充电时可能降级' },
]

/** 保持与旧向导一致：默认仍采 CPU / Memory / FPS，用户可自行增删。 */
export const DEFAULT_PERF_ITEMS = ['CPU', 'Memory', 'FPS'] as const

/** 去重并保留顺序；不认识的项原样保留，避免旧版本场景被静默改写。 */
export function normalizePerfItems(items: readonly string[] | undefined): string[] {
  // 不用 [...new Set(...)]：本仓库测试以 ES5 转译执行，Set 展开会退化。
  const result: string[] = []
  for (const item of items ?? []) {
    const value = String(item).trim()
    if (value && !result.includes(value)) result.push(value)
  }
  return result
}

export function perfItemsLabel(items: readonly string[] | undefined): string {
  const selected = normalizePerfItems(items)
  return selected
    .map((item) => PERF_ITEM_OPTIONS.find((option) => option.value === item)?.label ?? item)
    .join(' / ')
}
