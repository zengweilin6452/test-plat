/**
 * 执行资源 → UI 自动化调试标签的跨页交接（原型：打开调试 = go('ui') + uiTab='inspect'）。
 * 只存一次跳转意图，消费即清空；不持久化。
 */
import { create } from 'zustand'
import type { DebugTarget } from '../components/DebugDrawer'

interface DebugHandoffState {
  pending: DebugTarget | null
  setPending: (target: DebugTarget | null) => void
  consume: () => DebugTarget | null
}

export const useDebugHandoff = create<DebugHandoffState>((set, get) => ({
  pending: null,
  setPending: (target) => set({ pending: target }),
  consume: () => {
    const pending = get().pending
    set({ pending: null })
    return pending
  },
}))
