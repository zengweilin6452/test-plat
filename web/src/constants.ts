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

/**
 * 后端 test_type -> 展示名。
 * 后端枚举是 ui / performance / joint（DB CHECK），前端向导内部用 perf；
 * 两种写法都要认，否则页面会把 performance 显示成"未指定类型"。
 */
export function moduleName(value: string | null | undefined): string {
  if (!value) return '未指定类型'
  if (value === 'performance' || value === 'perf') return MODULE_NAMES.perf
  if (value === 'ui' || value === 'joint') return MODULE_NAMES[value]
  return value
}

/** 该运行是否属于性能类（含历史/前端写法 perf） */
export function isPerformanceType(value: string | null | undefined): boolean {
  return value === 'performance' || value === 'perf'
}

/** 目标端展示名；实际能力摘要来自服务端 GET /api/v1/capabilities（工单 06） */
export const TARGET_CATALOG: Record<Platform, { label: string; capability: string }> = {
  android: { label: 'Android', capability: '支持 UI 自动化与性能采集' },
  ios: { label: 'iOS', capability: '尚未支持执行' },
  web: { label: 'Web', capability: '尚未支持执行' },
}

/** 目标端下拉文案（原型 L122 context 条） */
export const SCOPE_OPTIONS: { value: 'all' | Platform; label: string }[] = [
  { value: 'all', label: '全部目标端' },
  { value: 'android', label: 'Android' },
  { value: 'ios', label: 'iOS' },
  { value: 'web', label: 'Web' },
]

/**
 * 兼容常量：服务端 /capabilities 是能力事实来源，这里只保留供表单过渡使用的
 * 旧枚举默认值；实际「是否可执行」判断必须读服务端响应，读取失败时不显示可执行。
 */
export const IMPLEMENTED_PLATFORMS: Platform[] = ['android']

export function isImplementedPlatform(scope: 'all' | Platform): boolean {
  return scope === 'all' || IMPLEMENTED_PLATFORMS.includes(scope)
}

/** 原型 L93–L102：草稿用 TASK- 前缀，其余用 RUN- 前缀 */
export function runCodePrefix(isDraft: boolean): string {
  return isDraft ? 'TASK-' : 'RUN-'
}

/** 帮助示例（仅用于 placeholder，绝不自动提交）：例如 3.8.0-rc.2 */
export const BUILD_LABEL_EXAMPLE = '例如 3.8.0-rc.2'
