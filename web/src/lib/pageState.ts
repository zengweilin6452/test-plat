/**
 * 页面区块的展示阶段（工单 09）。
 *
 * 统一顺序：加载中 → 失败 → 空态 → 就绪。
 * 「请求还没回来」和「后端确实没有数据」是两种不同的状态，页面必须分开呈现，
 * 否则验收时会把加载中误读成真实空态（原缺陷：Overview / Reports / Ui / Perf）。
 */
export type PagePhase = 'loading' | 'error' | 'empty' | 'ready'

export interface PagePhaseInput {
  /** 首次加载或换筛选条件后的首次请求（react-query 的 isLoading） */
  isLoading?: boolean
  /** 请求失败（页面另有 Notice 展示错误码，这里只用于选择占位文案） */
  isError?: boolean
  /** 已拿到的行数；没有列表语义的区块传 0/1 */
  count: number
}

export function pagePhase({ isLoading, isError, count }: PagePhaseInput): PagePhase {
  // 加载优先：isLoading 时还没有任何可信结果，绝不能据此断言「没有数据」
  if (isLoading) return 'loading'
  if (isError) return 'error'
  return count === 0 ? 'empty' : 'ready'
}
