/**
 * 展示常量。全部照原型 docs/platform-prototype/index.html 抽取，不新增文案。
 */
import type { DisplayStatus, Platform, TestModule } from './types'

/** 原型 L70 statusMap：状态 → [颜色, 中文] */
export const STATUS_MAP: Record<DisplayStatus, readonly [string, string]> = {
  draft: ['amber', '配置草稿'],
  passed: ['green', '已通过'],
  failed: ['red', '未通过'],
  not_tested: ['amber', '未判定'],
  running: ['blue', '执行中'],
  queued: ['gray', '排队中'],
  cancelled: ['gray', '已取消'],
  errored: ['gray', '执行错误'],
  ready: ['green', '可用'],
}

/** 执行资源四态（schema.sql execution_resources.status），文案沿用原型设备卡 */
export const RESOURCE_STATUS_MAP: Record<string, readonly [string, string]> = {
  ready: ['green', '可用'],
  draining: ['blue', '占用中'],
  offline: ['gray', '离线'],
  unauthorized: ['amber', '待授权'],
}

/** 原型 L72 moduleNames */
export const MODULE_NAMES: Record<TestModule, string> = {
  ui: 'UI 自动化',
  perf: '性能测试',
  joint: 'UI + 性能',
}

/** 原型 L74 targetCatalog */
export const TARGET_CATALOG: Record<Platform, { label: string; capability: string }> = {
  android: { label: 'Android', capability: '已有组件基础' },
  ios: { label: 'iOS', capability: '规划中' },
  web: { label: 'Web', capability: '规划中' },
}

/** 目标端下拉文案（原型 L122 context 条） */
export const SCOPE_OPTIONS: { value: 'all' | Platform; label: string }[] = [
  { value: 'all', label: '全部目标端' },
  { value: 'android', label: 'Android' },
  { value: 'ios', label: 'iOS' },
  { value: 'web', label: 'Web' },
]

/**
 * 只有这些端已接入执行能力；其余端走"规划态"页面（原型 L141）。
 * 平台侧同样以 android 为已接入端，iOS / Web 待接入。
 */
export const IMPLEMENTED_PLATFORMS: Platform[] = ['android']

export function isImplementedPlatform(scope: 'all' | Platform): boolean {
  return scope === 'all' || IMPLEMENTED_PLATFORMS.includes(scope)
}

/** 原型 L93–L102：草稿用 TASK- 前缀，其余用 RUN- 前缀 */
export function runCodePrefix(isDraft: boolean): string {
  return isDraft ? 'TASK-' : 'RUN-'
}

/** 原型 L186 应用版本缺省值 */
export const DEFAULT_BUILD_LABEL = '3.8.0-rc.2'
