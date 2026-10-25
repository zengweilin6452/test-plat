/**
 * 展示态推导。对应 frontend-spec.md §4「展示态推导」：
 *   completed+passed → passed，completed+failed → failed，completed+not_tested → not_tested，
 *   queued|dispatching → queued，running|finalizing → running，errored → failed(带错误标)，cancelled → cancelled。
 *
 * 硬规则：outcome 为 null 且 state 非 completed 时，绝不推导为 passed / failed。
 */
import { STATUS_MAP } from '../constants'
import type { DisplayStatus, RunOutcome, RunState, TaskLifecycle, TaskReadiness } from '../types'

export function displayStatus(
  state: RunState,
  outcome: RunOutcome | null | undefined,
): DisplayStatus {
  switch (state) {
    case 'queued':
    case 'dispatching':
      return 'queued'
    case 'running':
    case 'finalizing':
      return 'running'
    case 'errored':
      return 'errored'
    case 'cancelled':
      return 'cancelled'
    case 'completed':
      // completed 时 outcome 才有效；缺失属于后端数据问题，降级为未判定而不是猜猜看
      return outcome ?? 'not_tested'
    default:
      return 'not_tested'
  }
}

/** 任务生命周期 + 修订就绪度 → 展示态（草稿/已验证） */
export function displayTaskStatus(
  lifecycle: TaskLifecycle,
  readiness?: TaskReadiness | null,
): DisplayStatus {
  if (lifecycle === 'archived') return 'cancelled'
  if (readiness === 'validated') return 'ready'
  return 'draft'
}

/** 展示态 → [颜色, 中文] */
export function statusMeta(status: DisplayStatus): readonly [string, string] {
  return STATUS_MAP[status] ?? ['gray', String(status)]
}

/**
 * 是否已判定。只有 completed 才可能已判定，
 * 且 not_tested 也不计入通过率分母（prototype-ui-spec §2.1 标准）。
 */
export function isDecided(state: RunState, outcome: RunOutcome | null | undefined): boolean {
  return state === 'completed' && (outcome === 'passed' || outcome === 'failed')
}

/** 是否终态 */
export function isTerminal(state: RunState): boolean {
  return state === 'completed' || state === 'errored' || state === 'cancelled'
}

/** errored 展示为 failed 语义 + 错误标（frontend-spec §4） */
export function hasErrorTag(state: RunState): boolean {
  return state === 'errored'
}

/** 运营筛选可选的展示态（原型 L187 的 7 个状态） */
export const FILTERABLE_STATUSES: { value: DisplayStatus | 'all'; label: string }[] = [
  { value: 'all', label: '全部状态' },
  { value: 'draft', label: STATUS_MAP.draft[1] },
  { value: 'queued', label: STATUS_MAP.queued[1] },
  { value: 'running', label: STATUS_MAP.running[1] },
  { value: 'passed', label: STATUS_MAP.passed[1] },
  { value: 'failed', label: STATUS_MAP.failed[1] },
  { value: 'not_tested', label: STATUS_MAP.not_tested[1] },
  { value: 'cancelled', label: STATUS_MAP.cancelled[1] },
]
