/**
 * 设备调试工作区的纯逻辑层（自 DebugDrawer.tsx 迁入，P2-03 分层）。
 *
 * 只放无 React 状态的模型与算法：调试目标形状、定位方式选项、定位值推导、
 * 层级树索引/标签、框选凭证的键与解析、拖拽归一化、直接操控可用性与手势
 * 消息、canvas 绘制。组件状态、WS 生命周期与面板 JSX 留在 DebugDrawer.tsx。
 * DebugDrawer.tsx 再导出本模块全部公开名，用例（debug-locator / debug-control /
 * debug-crop-state / report-and-debug）的 require 路径不需要变化。
 */
import type { SnapshotTreeNode } from '../../api/types'
import type { ResourceRecord } from '../../types'

export interface DebugTarget {
  /** 执行资源 serial（adb serial 或浏览器标识） */
  serial: string
  /** 资源名，仅展示用 */
  label: string
  /** 占用者说明（resource.lease），busy 时禁用按钮并提示 */
  leaseHint?: string | null
}

/** 会话 opening 期间平台会拒绝 WS；实测就绪约 3s，viewer 冷启动可拖到 ~15s
 * （前一个 viewer 的 scrcpy 拆卸 + adb 竞争），故给 30s 退避窗口 */
export const WS_CONNECT_RETRIES = 15
export const WS_RETRY_DELAY_MS = 2000

/** 定位方式（vendor Locator 枚举，网页接口用成员值） */
export type LocatorBy =
  | 'resource_id'
  | 'text'
  | 'accessibility_id'
  | 'u2_selector'
  | 'xpath'
  | 'image'

export const LOCATOR_OPTIONS: { value: LocatorBy; label: string }[] = [
  { value: 'text', label: '文本' },
  { value: 'resource_id', label: 'resource-id' },
  { value: 'accessibility_id', label: 'accessibility-id' },
  { value: 'u2_selector', label: 'u2 selector' },
  { value: 'xpath', label: 'xpath' },
  { value: 'image', label: '图像模板（逻辑名）' },
]

/** 资源行 → 工作区目标（下拉切换与入口跳转共用同一形状） */
export function toWorkspaceTarget(device: ResourceRecord): DebugTarget {
  const hint = device.lease
    ? device.lease.run_id
      ? '运行 ' + device.lease.run_id.slice(0, 8) + ' 占用中'
      : '调试会话占用中'
    : null
  return {
    serial: device.resource_key ?? '',
    label: device.name,
    leaseHint: hint,
  }
}

export interface Region {
  x: number
  y: number
  w: number
  h: number
}

export interface FrameSize {
  w: number
  h: number
}

/** 框选验证凭证：validate-crop 用**新捕获的画面**唯一命中后，服务端发放的
 *  一次性证明。登记必须带它，并且快照/命中框/阈值必须与验证时完全一致——
 *  所以这里把「新快照 + 新画面里的命中框」也一起存下来作为登记依据，
 *  不再拿冻结时的旧快照去登记（旧快照前端只展示，不能当依据）。 */
export interface CropVerification {
  /** 与 cropVerificationKey 对齐：会话/快照/框选/阈值任一改变即失效 */
  key: string
  /** 服务端一次性凭证（POST /templates 的 verification） */
  token: string
  /** 验证时真实匹配用的新快照（登记就从它裁剪） */
  snapshotId: string
  /** 新画面里的唯一命中框（设备像素） */
  region: Region
}

/** 框选验证的失效口令：会话、来源快照、框选区域、阈值任一变化都会换 key。 */
export function cropVerificationKey(
  sessionId: string | number | null,
  snapshotId: string | null,
  region: Region | null,
  threshold: string,
): string {
  return JSON.stringify([sessionId ?? null, snapshotId, region, threshold])
}

/** validate-crop 响应 → 登记依据。只有唯一匹配且服务端给了凭证才成立；
 *  零匹配/多匹配/缺凭证一律 null（UI 只能显示失败，不能允许登记）。 */
export function resolveCropVerification(
  result:
    | {
        count?: number | null
        snapshot_id?: string | null
        region?: number[] | null
        verification?: string | null
      }
    | null
    | undefined,
  key: string,
): CropVerification | null {
  if (!result || result.count !== 1) return null
  const snapshotId = typeof result.snapshot_id === 'string' ? result.snapshot_id : ''
  const token = typeof result.verification === 'string' ? result.verification : ''
  const box = Array.isArray(result.region) ? result.region : null
  if (!snapshotId || !token || !box || box.length !== 4) return null
  if (!box.every((value) => typeof value === 'number' && Number.isInteger(value) && value >= 0)) return null
  if (box[2] <= 0 || box[3] <= 0) return null
  return {
    key,
    token,
    snapshotId,
    region: { x: box[0], y: box[1], w: box[2], h: box[3] },
  }
}

/** 节点拾取：resource-id 优先（文案会变，id 更稳），其次 text；都没有如实为空。 */
export function preferredLocator(node: SnapshotTreeNode): { by: LocatorBy; value: string } | null {
  if (typeof node.resource_id === 'string' && node.resource_id.trim()) {
    return { by: 'resource_id', value: node.resource_id }
  }
  if (typeof node.text === 'string' && node.text.trim()) {
    return { by: 'text', value: node.text }
  }
  return null
}

const U2_SHORT_CLASS = (className: string | null | undefined) => {
  const full = (className ?? '').trim()
  if (!full) return ''
  return full.split('.').pop() || full
}

/**
 * 按定位方式从选中节点生成对应形态的定位值（vendor selectors.py 契约）：
 * u2_selector 必须是白名单 JSON object（resourceId/text/description/className
 * 等字符串字段），xpath 是表达式——切类型不复用原文，否则验证必然
 * InvalidTarget（如 u2 选择器拿到纯文本）。节点给不出该形态时返回空串，
 * 由调用方如实留空提示，不猜值。
 */
export function locatorValueForNode(by: LocatorBy, node: SnapshotTreeNode | null): string {
  if (!node) return ''
  const text = (node.text ?? '').trim()
  switch (by) {
    case 'resource_id':
      return (node.resource_id ?? '').trim()
    case 'text':
      return text
    case 'accessibility_id':
      return (node.content_desc ?? '').trim()
    case 'u2_selector': {
      if ((node.resource_id ?? '').trim()) {
        return JSON.stringify({ resourceId: (node.resource_id ?? '').trim() })
      }
      if (text) return JSON.stringify({ text })
      if ((node.content_desc ?? '').trim()) {
        return JSON.stringify({ description: (node.content_desc ?? '').trim() })
      }
      const shortClass = U2_SHORT_CLASS(node.class_name)
      return shortClass ? JSON.stringify({ className: shortClass }) : ''
    }
    case 'xpath': {
      const shortClass = U2_SHORT_CLASS(node.class_name)
      if (!shortClass) return ''
      if (text) return `//${shortClass}[@text='${text.replace(/'/g, "\\'")}']`
      return `//${shortClass}`
    }
    case 'image':
      return ''
  }
}

/** 层级树节点：vendor 用 children 存下标，渲染前先按 index 建表 */
export function buildTreeIndex(nodes: SnapshotTreeNode[]): {
  byIndex: Map<number, SnapshotTreeNode>
  roots: SnapshotTreeNode[]
} {
  const byIndex = new Map<number, SnapshotTreeNode>()
  for (const node of nodes) byIndex.set(node.index, node)
  const referenced = new Set<number>()
  for (const node of nodes) {
    for (const child of node.children ?? []) referenced.add(child)
  }
  const roots = nodes.filter((node) => !referenced.has(node.index))
  return { byIndex, roots }
}

/**
 * 节点展示名：与 mobile-auto viewer（static/app.js nodeLabel）同口径——
 * 短类名 · resource_id · text · content_desc 组合，缺项跳过。
 * 空串按「没有」处理（vendor 对无文本节点给 text=""，filter(Boolean) 挡掉）。
 * 无标识的纯容器由 hasNodeIdentity 整行跳过，#下标 只是兜底。
 */
export function nodeLabel(node: SnapshotTreeNode): string {
  const parts = [
    node.class_name ? node.class_name.split('.').pop() : '',
    node.resource_id ?? '',
    node.text ?? '',
    node.content_desc ?? '',
  ].filter((part) => typeof part === 'string' && part.trim())
  return parts.length > 0 ? parts.join(' · ') : '#' + node.index
}

export function nodeBounds(node: SnapshotTreeNode): string | null {
  const bounds = node.bounds
  if (!Array.isArray(bounds) || bounds.length !== 4) return null
  const [left, top, right, bottom] = bounds
  return `${left},${top} → ${right},${bottom}`
}

/** 与 mobile-auto viewer renderTree 同规则：text / resource_id / content_desc
 *  三者全无的纯容器（FrameLayout、虚拟 root 等）整行跳过，子树原位上移。 */
export function hasNodeIdentity(node: SnapshotTreeNode): boolean {
  return Boolean(node.text || node.resource_id || node.content_desc)
}

/**
 * 复制表达式：只有剪贴板真的写入成功才提示成功。
 * 非安全上下文（http + 非 localhost）或浏览器拒绝剪贴板权限时给出失败提示，
 * 不让「表达式已复制」变成假成功（工单 09）。
 */
export function copyExpression(text: string, show: (message: string) => void): void {
  const clipboard = typeof navigator === 'undefined' ? undefined : navigator.clipboard
  if (!clipboard?.writeText) {
    show('复制失败：当前环境不支持剪贴板，请手动选中表达式复制')
    return
  }
  clipboard.writeText(text).then(
    () => show('表达式已复制'),
    () => show('复制失败：剪贴板被拒绝，请手动选中表达式复制'),
  )
}

export function normalizeRegion(x0: number, y0: number, x1: number, y1: number): Region {
  return {
    x: Math.min(x0, x1),
    y: Math.min(y0, y1),
    w: Math.abs(x1 - x0),
    h: Math.abs(y1 - y0),
  }
}

/** 手工编辑区域输入框：空串视为 0，非数字忽略 */
export function editRegion(region: Region | null, key: keyof Region, raw: string): Region | null {
  const value = raw.trim()
  if (value === '') return null
  if (!/^\d+$/.test(value)) return region
  return { ...(region ?? { x: 0, y: 0, w: 0, h: 0 }), [key]: Number(value) }
}

/** 框选只在图像模板模式可用；原生节点模式拖拽不应产生/保留选择框。 */
export function cropSelectionEnabled(inspectMode: 'native' | 'image'): boolean {
  return inspectMode === 'image'
}

/** 直接操控：把指针位置换算成 vendor 手势 WS 的归一化坐标（0..1）。 */
export function normalizeStagePoint(
  rect: { left: number; top: number; width: number; height: number },
  clientX: number,
  clientY: number,
): { nx: number; ny: number } {
  const clamp = (value: number) => Math.min(Math.max(value, 0), 1)
  if (rect.width <= 0 || rect.height <= 0) return { nx: 0, ny: 0 }
  return {
    nx: clamp((clientX - rect.left) / rect.width),
    ny: clamp((clientY - rect.top) / rect.height),
  }
}

export interface ControlAvailabilityInput {
  sessionActive: boolean
  wsOpen: boolean
  frozen: boolean
  inspectMode: 'native' | 'image'
  hasFrame: boolean
  busy: boolean
}

/** 直接操控可用性：每个禁用都必须有可读原因，前端 disabled 只是体验，
 *  服务端仍会独立校验控制权。 */
export function controlAvailability(
  input: ControlAvailabilityInput,
): { enabled: boolean; reason: string | null } {
  if (!input.sessionActive) return { enabled: false, reason: '调试会话尚未激活' }
  if (input.inspectMode === 'image') {
    return { enabled: false, reason: '图像模板框选模式下不可操控' }
  }
  if (input.frozen) return { enabled: false, reason: '冻结快照时不可操控，先恢复预览' }
  if (!input.wsOpen) return { enabled: false, reason: '实时画面未连接' }
  if (!input.hasFrame) return { enabled: false, reason: '画面尚未就绪' }
  if (input.busy) return { enabled: false, reason: '会话切换中' }
  return { enabled: true, reason: null }
}

/** vendor /api/v1/input/gesture 的消息形状（start/move/end + 序号）。 */
export function gestureMessage(
  type: 'start' | 'move' | 'end',
  nx: number,
  ny: number,
  seq: number,
): { type: string; nx: number; ny: number; seq: number } {
  return { type, nx, ny, seq }
}

/** 拖动 MOVE 按 20Hz 节流；DOWN/UP 不节流。 */
export function shouldSendGestureMove(
  lastSentAt: number | null,
  now: number,
  intervalMs = 50,
): boolean {
  return lastSentAt === null || now - lastSentAt >= intervalMs
}

/** 把 vendor 的 base64 JPEG 帧画到 canvas；解码失败保留上一帧。
 *  onload 是异步的：到帧时未冻结、解码完成时已冻结的情况必须复查。 */
export function drawFrame(
  canvas: HTMLCanvasElement | null,
  base64: string,
  onSize?: (size: FrameSize) => void,
  isPaused?: () => boolean,
): void {
  if (!canvas) return
  const image = new Image()
  image.onload = () => {
    if (isPaused?.()) return
    canvas.width = image.naturalWidth
    canvas.height = image.naturalHeight
    const ctx = canvas.getContext('2d')
    ctx?.drawImage(image, 0, 0)
    onSize?.({ w: image.naturalWidth, h: image.naturalHeight })
  }
  image.src = 'data:image/jpeg;base64,' + base64
}

/** 把快照原图画到 canvas：冻结画面必须与层级树来自同一张快照。 */
export async function drawSnapshotImage(canvas: HTMLCanvasElement | null, blob: Blob): Promise<FrameSize> {
  if (!canvas) throw new Error('画布未就绪')
  const url = URL.createObjectURL(blob)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error('快照图片解码失败'))
      img.src = url
    })
    canvas.width = image.naturalWidth
    canvas.height = image.naturalHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('画布不可用')
    ctx.drawImage(image, 0, 0)
    return { w: image.naturalWidth, h: image.naturalHeight }
  } finally {
    URL.revokeObjectURL(url)
  }
}
