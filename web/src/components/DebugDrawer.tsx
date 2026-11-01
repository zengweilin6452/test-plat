/**
 * 设备调试工作区（P5）。
 *
 * 布局：原型 nativeInspectorPage 的页面内三栏（不再挂 `<Panel>`，也不再是右浮层）：
 * 定位方式切换器一行 → toolbar → 左 `.phone-panel`（真机画面）+ 中/右两个 `.panel`
 * （UI 层级树 / 元素与定位描述）。图像模板模式把第 2、3 栏换成「框选与保存模板」
 * 与「图像匹配验证」两个 `.panel.image-form`，对应原型 inspectorPage 的切割方式。
 *
 * 数据来源（全部经平台代理到活动调试会话的 vendor viewer）：
 *  - 实时预览：WS /api/v1/ws/debug/{id}，vendor 下发 **JSON 文本帧**
 *    `{kind: 'frame'|'status'|'error', jpeg_base64?, message?}`；不是二进制帧，
 *    所以这里解析 JSON 后把 jpeg_base64 画到 canvas，status/error 显示成状态行。
 *  - 层级树：WS 不带树。点「采集快照」→ POST .../snapshots {with_tree} →
 *    GET .../snapshots/{nid}/tree，vendor 返回 `{nodes: [{index, children: [下标]}]}`。
 *  - 定位验证：POST .../locators/validate，体是 `{target: {by, value}}`，
 *    返回 matches[]（x/y/width/height/confidence）。唯一匹配才算通过。
 *  - 图像识别（vendor imaging + TemplateStore，存储是跨会话共享的 server/assets）：
 *      GET  /templates?session_id=            模板清单（逻辑名 / 版本 / 摘要）
 *      POST /templates/validate-crop {snapshot_id, region, threshold}
 *                                             **新捕获画面**真实匹配；唯一命中才返回
 *                                             verification 凭证 + 新快照 + 命中框
 *      POST /templates {snapshot_id, region, threshold, logical, verification}
 *                                             凭证是登记的必要条件：服务端独立校验
 *                                             （会话/快照/框选/阈值任一变化即失效，
 *                                             一次性、有有效期），前端 disabled 只是体验；
 *                                             登记从验证时的新快照 + 命中框裁剪
 *    匹配本身仍走 locators/validate（by='image'，value=逻辑名），命中框叠在画面上。
 *    框选区域直接在预览画面上拖拽得到（设备像素坐标 = 快照像素坐标）。
 * 硬约束：
 *  - 会话创建失败 / 端点不可用只显示 Notice + 错误码，不伪造画面；
 *  - 关闭面板先 DELETE /debug-sessions/{id} 再清 WS；
 *  - WS 断开（非主动关闭）提示「会话已结束」。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError, request } from '../api/client'
import {
  captureSnapshot,
  closeDebugSession,
  createDebugSession,
  createTemplate,
  debugGestureWsPath,
  debugVideoWsPath,
  fetchDebugSession,
  fetchSnapshotTree,
  fetchTemplates,
  heartbeatDebugControl,
  sendDebugKey,
  setDebugControl,
  validateLocator,
  validateTemplate,
} from '../api/endpoints'
import type { LocatorMatch, SnapshotTreeNode, TemplateRecord } from '../api/types'
import type { ResourceRecord } from '../types'
import { Badge } from './Badge'
import { Button } from './Button'
import { Empty } from './Empty'
import { Notice } from './Notice'
import { useToast } from './Toast'
import { DASH } from '../lib/fmt'
import { Dialog } from './Dialog'
import { choosePreviewTransport, createH264Preview, type H264PreviewHandle } from '../lib/h264Preview'

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
const WS_CONNECT_RETRIES = 15
const WS_RETRY_DELAY_MS = 2000

/** 定位方式（vendor Locator 枚举，网页接口用成员值） */
export type LocatorBy =
  | 'resource_id'
  | 'text'
  | 'accessibility_id'
  | 'u2_selector'
  | 'xpath'
  | 'image'

const LOCATOR_OPTIONS: { value: LocatorBy; label: string }[] = [
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

interface Region {
  x: number
  y: number
  w: number
  h: number
}

interface FrameSize {
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

function nodeBounds(node: SnapshotTreeNode): string | null {
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

/** 递归渲染层级树（children 存下标，超过 200 层视为脏数据直接停）。
 *  行样式照原型 .tree-row：当前选中节点高亮，整行可点（真实场景允许选任意节点）。 */
function TreeBranch({
  node,
  depth,
  byIndex,
  onPick,
  selectedIndex,
  frozen,
}: {
  node: SnapshotTreeNode
  depth: number
  byIndex: Map<number, SnapshotTreeNode>
  onPick: (node: SnapshotTreeNode) => void
  selectedIndex: number | null
  frozen: boolean
}) {
  const [open, setOpen] = useState(depth < 2)
  const kids = (node.children ?? [])
    .map((index) => byIndex.get(index))
    .filter((kid): kid is SnapshotTreeNode => Boolean(kid))
  if (!hasNodeIdentity(node)) {
    return (
      <>
        {kids.map((kid) => (
          <TreeBranch
            key={kid.index}
            node={kid}
            depth={depth}
            byIndex={byIndex}
            onPick={onPick}
            selectedIndex={selectedIndex}
            frozen={frozen}
          />
        ))}
      </>
    )
  }
  const bounds = nodeBounds(node)
  const selected = frozen && selectedIndex === node.index
  return (
    <div>
      <div
        className={'tree-row' + (selected ? ' selected' : '')}
        style={{ paddingLeft: 8 + depth * 16 }}
        role="treeitem"
        aria-selected={selected}
        tabIndex={0}
        onClick={() => onPick(node)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onPick(node)
          }
        }}
      >
        {kids.length > 0 && depth < 200 ? (
          <button
            type="button"
            className="link-btn"
            style={{ minWidth: 14 }}
            aria-label={open ? '收起' : '展开'}
            onClick={(event) => {
              event.stopPropagation()
              setOpen(!open)
            }}
          >
            {open ? '▾' : '▸'}
          </button>
        ) : (
          <span style={{ minWidth: 14 }} />
        )}
        <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }} title={nodeLabel(node)}>
          {nodeLabel(node)}
        </span>
        {bounds ? (
          <span className="muted" style={{ marginLeft: 'auto', fontSize: 9 }}>{bounds}</span>
        ) : null}
      </div>
      {open && depth < 200
        ? kids.map((kid) => (
            <TreeBranch
              key={kid.index}
              node={kid}
              depth={depth + 1}
              byIndex={byIndex}
              onPick={onPick}
              selectedIndex={selectedIndex}
              frozen={frozen}
            />
          ))
        : null}
    </div>
  )
}

interface DebugDrawerProps {
  open: boolean
  target: DebugTarget | null
  /** 可调设备清单（原型 toolbar 的设备下拉；ready 设备） */
  devices: ResourceRecord[]
  /** toolbar 下拉切换调试设备 */
  onTargetChange: (target: DebugTarget | null) => void
  onClose: () => void
  /** 会话建立/释放时上抛，供模板页签等按会话隔离的调用方使用 */
  onSessionChange?: (sessionId: string | number | null) => void
}

export function DebugDrawer({ open, target, devices, onTargetChange, onClose, onSessionChange }: DebugDrawerProps) {
  const toast = useToast()
  const queryClient = useQueryClient()

  const [session, setSession] = useState<{ id: string | number } | null>(null)
  const [nodes, setNodes] = useState<SnapshotTreeNode[] | null>(null)
  const [snapshotId, setSnapshotId] = useState<string | null>(null)
  /** 采集检查后冻结画面：WS 帧不再覆盖 canvas，框选与模板裁剪都基于同一张快照 */
  const [frozen, setFrozen] = useState(false)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [selected, setSelected] = useState<SnapshotTreeNode | null>(null)
  const [inspectMode, setInspectMode] = useState<'native' | 'image'>('native')
  const [locatorBy, setLocatorBy] = useState<LocatorBy>('text')
  const [locator, setLocator] = useState('')
  /** 图像匹配阈值（AC-DBG-05）：0.10-1.00；越界在提交前拦下 */
  const [matchThreshold, setMatchThreshold] = useState('0.80')
  const [matches, setMatches] = useState<LocatorMatch[] | null>(null)
  /** 图像匹配的相关系数（vendor /templates/validate 的 scores，与 matches 对齐） */
  const [scores, setScores] = useState<number[] | null>(null)
  const [validateNote, setValidateNote] = useState<string | null>(null)
  /** 最近一次定位验证实际使用的快照（vendor 每次定位都会重新采集） */
  const [locatorSnapshotId, setLocatorSnapshotId] = useState<string | null>(null)
  const [validateError, setValidateError] = useState<string | null>(null)
  const [wsStatus, setWsStatus] = useState<'idle' | 'connecting' | 'open' | 'closed'>('idle')
  // 重试计数：作为建连 effect 的依赖。不能把 wsStatus 放进依赖——effect 自己
  // setWsStatus('connecting') 会触发重渲染，cleanup 立刻 close 掉刚建的 socket，
  // 表现为握手后 1ms 内 1006 并循环耗尽重试。
  const [wsAttempt, setWsAttempt] = useState(0)
  const [wsNotice, setWsNotice] = useState<string | null>(null)
  const [closeError, setCloseError] = useState<string | null>(null)
  /** 当前帧尺寸（设备像素）：命中框与框选都按它换算成百分比 */
  const [frameSize, setFrameSize] = useState<FrameSize | null>(null)
  /** 采集检查得到的快照像素尺寸：模板坐标以快照为准，不能拿缩放的实时流尺寸 */
  const [snapshotSize, setSnapshotSize] = useState<FrameSize | null>(null)
  /** 框选中的区域（设备像素），松手后落到 region */
  const [region, setRegion] = useState<Region | null>(null)
  const [dragging, setDragging] = useState<Region | null>(null)
  const [newLogical, setNewLogical] = useState('')
  const [templateError, setTemplateError] = useState<string | null>(null)
  /** 最近一次框选验证的登记依据（新快照 + 命中框 + 凭证）；框选/阈值/快照/
   *  会话任一变化后 key 不匹配即视为未验证，必须重新验证。 */
  const [cropVerification, setCropVerification] = useState<CropVerification | null>(null)

  /** H.264 预览优先；WebCodecs 缺失/视频信道失败时回退 JPEG。 */
  const [previewMode, setPreviewMode] = useState<'h264' | 'jpeg'>('h264')
  const [previewNote, setPreviewNote] = useState<string | null>(null)
  const [previewFps, setPreviewFps] = useState<number | null>(null)

  /** 直接操控：控制权在服务端，前端只反映 enabled；手势 WS 每次手势一条。 */
  const [controlEnabled, setControlEnabled] = useState(false)
  const [controlPending, setControlPending] = useState(false)
  const [controlError, setControlError] = useState<string | null>(null)
  const [controlConfirmOpen, setControlConfirmOpen] = useState(false)
  /** 触点提示（相对 .debug-frame 的百分比） */
  const [touchDot, setTouchDot] = useState<{ left: number; top: number } | null>(null)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  /** 主动关闭标记：区别于服务端断开 */
  const closingRef = useRef(false)
  const wsRef = useRef<WebSocket | null>(null)
  const sessionRef = useRef<string | number | null>(null)
  const wsRetriesRef = useRef(0)
  /** frozen 的 ref 镜像：WS onmessage 闭包不随 frozen 重建（重建会断流重连） */
  const frozenRef = useRef(false)
  const h264PlayerRef = useRef<H264PreviewHandle | null>(null)
  const previewFrameCountRef = useRef(0)
  const gestureWsRef = useRef<WebSocket | null>(null)
  const gestureQueueRef = useRef<string[]>([])
  const gestureSeqRef = useRef(0)
  const lastMoveAtRef = useRef<number | null>(null)
  const pointerStartRef = useRef<{ nx: number; ny: number; at: number } | null>(null)

  const closeGestureSocket = useCallback(() => {
    const ws = gestureWsRef.current
    gestureWsRef.current = null
    gestureQueueRef.current = []
    gestureSeqRef.current = 0
    lastMoveAtRef.current = null
    pointerStartRef.current = null
    if (ws) {
      try {
        ws.close(1000)
      } catch {
        // socket 已关闭
      }
    }
  }, [])

  /** 退出直接操控：本地先停，再尽力让服务端释放 vendor 控制权。 */
  const disableControl = useCallback(
    (release = true) => {
      closeGestureSocket()
      setControlEnabled(false)
      setControlPending(false)
      setTouchDot(null)
      setControlError(null)
      const id = sessionRef.current
      if (release && id !== null) {
        void setDebugControl(id, false).catch(() => undefined)
      }
    },
    [closeGestureSocket],
  )

  const reset = useCallback(() => {
    setSession(null)
    wsRetriesRef.current = 0
    setWsAttempt(0)
    setNodes(null)
    setSnapshotId(null)
    setSnapshotSize(null)
    frozenRef.current = false
    setFrozen(false)
    setTreeError(null)
    setSelected(null)
    setMatches(null)
    setScores(null)
    setValidateNote(null)
    setValidateError(null)
    setLocatorSnapshotId(null)
    setWsStatus('idle')
    setWsNotice(null)
    setCloseError(null)
    setFrameSize(null)
    setRegion(null)
    setDragging(null)
    setNewLogical('')
    setTemplateError(null)
    setCropVerification(null)
    h264PlayerRef.current?.close()
    h264PlayerRef.current = null
    setPreviewMode('h264')
    setPreviewNote(null)
    setPreviewFps(null)
    previewFrameCountRef.current = 0
    closeGestureSocket()
    setControlEnabled(false)
    setControlPending(false)
    setControlError(null)
    setTouchDot(null)
    setControlConfirmOpen(false)
  }, [closeGestureSocket])

  /** open 的 ref 镜像：mutation 回调里读 props 会拿到过期闭包 */
  const openRef = useRef(open)
  openRef.current = open

  /** 打开面板 → 创建调试会话 */
  const createMutation = useMutation({
    mutationFn: () => createDebugSession(target!.serial, '定位排查'),
    onSuccess: (created) => {
      if (!openRef.current) {
        // 创建请求在途时面板已被关掉：立即释放，否则留下孤儿 active 会话占住设备租约
        void closeDebugSession(created.id).catch(() => undefined)
        return
      }
      setSession({ id: created.id })
      sessionRef.current = created.id
      setWsNotice(null)
    },
    onError: (error) => {
      createPendingRef.current = false
      const described = describeError(error)
      setWsNotice('调试会话创建失败（' + described.code + '）：' + described.message)
    },
  })

  /** 工作区打开且选定设备 → 自动创建调试会话；失败后换设备/重进即重试 */
  const createPendingRef = useRef(false)
  useEffect(() => {
    if (!open || !target?.serial) {
      createPendingRef.current = false
      return
    }
    if (session || createPendingRef.current) return
    createPendingRef.current = true
    createMutation.mutate()
    // 跟随 open 与目标设备变化；session/mutation 用 ref 守卫避免重复建会话
  }, [open, target?.serial])

  const detailQuery = useQuery({
    queryKey: ['debug-session', session?.id],
    queryFn: ({ signal }) => fetchDebugSession(session!.id, signal),
    enabled: open && Boolean(session),
    retry: false,
    // 会话刚创建时 state=opening，响应里还没有 ws_path（viewer 端口未回报）。
    // 轮询到 active 才停：建连 effect 依赖 ws_path，没有轮询它永远不会出现。
    refetchInterval: (query) => {
      const state = query.state.data?.state
      return state && state !== 'active' ? 1500 : false
    },
    // 调试页可能被切到后台（或由浏览器自动化驱动）：opening→active 的轮询
    // 不能因为标签页不可见而暂停，否则画面一直停在「未连接」。
    refetchIntervalInBackground: true,
  })

  /** 关闭会话：DELETE + 关 WS */
  const closeMutation = useMutation({
    mutationFn: (id: string | number) => closeDebugSession(id),
    onError: (error) => {
      const described = describeError(error)
      setCloseError('关闭会话失败（' + described.code + '）：' + described.message)
    },
  })

  const teardownSocket = useCallback(() => {
    const socket = wsRef.current
    wsRef.current = null
    if (socket) {
      closingRef.current = true
      try {
        socket.close(1000)
      } catch {
        // socket 已断开，忽略
      }
    }
  }, [])

  const handleClose = useCallback(() => {
    const id = sessionRef.current
    if (id !== null) {
      closingRef.current = true
      teardownSocket()
      closeMutation.mutate(id)
      sessionRef.current = null
    }
    onClose()
    reset()
    void queryClient.invalidateQueries({ queryKey: ['resources'] })
  }, [closeMutation, onClose, queryClient, reset, teardownSocket])

  /** 页面级工作区：离开调试标签（卸载）时释放会话，设备不被占死 */
  const unmountCloseRef = useRef(handleClose)
  unmountCloseRef.current = handleClose
  useEffect(() => {
    return () => {
      if (sessionRef.current !== null) unmountCloseRef.current()
    }
  }, [])

  /** Esc 关闭（原先是原生 <dialog> 自带的行为） */
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') handleClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, handleClose])

  /** WS 建立：vendor 下发 JSON 帧（jpeg_base64），解析后画到 canvas */
  useEffect(() => {
    if (!open || !session || previewMode !== 'jpeg') return
    // 只依赖 ws_path 字符串：detailQuery.data 每次轮询都是新对象，直接依赖它
    // 会在 refetch 时 cleanup 掉已连好的 socket。
    const path = detailQuery.data?.ws_path ?? null
    if (!path) return
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = proto + '//' + window.location.host + path

    setWsStatus('connecting')
    const socket = new WebSocket(url)
    wsRef.current = socket
    closingRef.current = false

    socket.onopen = () => {
      setWsStatus('open')
      wsRetriesRef.current = 0
      setWsNotice(null)
    }
    socket.onmessage = (event) => {
      if (typeof event.data !== 'string') return
      let message: Record<string, unknown>
      try {
        message = JSON.parse(event.data) as Record<string, unknown>
      } catch {
        // 非 JSON 文本帧：vendor 不会发，忽略而不是崩掉
        return
      }
      const kind = message.kind
      if (kind === 'frame' && typeof message.jpeg_base64 === 'string') {
        // 已冻结：保留「采集检查」那一刻的画面，后续帧丢弃（恢复实时后自动接上）
        if (frozenRef.current) return
        drawFrame(canvasRef.current, message.jpeg_base64, (size) => {
          setFrameSize((prev) => (prev && prev.w === size.w && prev.h === size.h ? prev : size))
        })
        previewFrameCountRef.current += 1
        return
      }
      if (kind === 'status') {
        // 设备忙 / 未就绪：显示状态行，不遮掉最后一帧
        const text = typeof message.message === 'string' ? message.message : '设备状态不可用'
        setWsNotice(text)
        return
      }
      if (kind === 'error') {
        const text = typeof message.message === 'string' ? message.message : '预览帧采集失败'
        setWsNotice(text)
      }
    }
    socket.onclose = () => {
      wsRef.current = null
      setWsStatus('closed')
      if (closingRef.current) return
      // 会话刚创建时 runner 还在拉起 viewer（state=opening），平台会立刻拒绝 WS。
      // 有限次退避重连，成功即清零；耗尽后才告知断开。
      if (sessionRef.current !== null && wsRetriesRef.current < WS_CONNECT_RETRIES) {
        wsRetriesRef.current += 1
        window.setTimeout(() => {
          setWsStatus('idle')
          setWsAttempt((n) => n + 1)
        }, WS_RETRY_DELAY_MS)
        return
      }
      // 服务端关闭（会话结束 / 1000），明确提示而不是静默黑屏
      setWsNotice('连接已断开：会话已结束')
    }
    socket.onerror = () => {
      // 只记录状态；重连决策统一放在 onclose（error 后必有 close），
      // 这里若改 wsStatus 会先触发 effect cleanup，把手动关闭标记误置位。
      setWsStatus('closed')
    }

    return () => {
      // 注意：effect 重跑/卸载的清理不动 closingRef——它只由手动关闭路径
      // （handleClose / 卸载兜底）置位，否则 onerror 先改状态引发的 cleanup
      // 会让随后的 onclose 误判为手动关闭，重试永远不会排程。
      if (wsRef.current === socket) wsRef.current = null
      // 先摘掉回调再关：cleanup 关掉的 socket 不应再触发 onclose 的重试排程
      // （会话切换/卸载时重试没有意义，卸载后 setState 也会告警）。
      socket.onclose = null
      socket.onerror = null
      socket.onmessage = null
      socket.onopen = null
      try {
        socket.close(1000)
      } catch {
        // 忽略
      }
    }
  }, [open, session, detailQuery.data?.ws_path, wsAttempt, previewMode])

  /** 卸载兜底：组件销毁（页面切换）也要关会话 */
  useEffect(() => {
    return () => {
      const id = sessionRef.current
      if (id !== null) {
        teardownSocket()
        void closeDebugSession(id).catch(() => undefined)
        sessionRef.current = null
      }
    }
  }, [teardownSocket])

  /** open 转 false 的兜底：面板仍挂载、但父组件清掉了 target（或任何不经
   *  handleClose 的关闭路径）时，活动会话必须就地释放，否则成为孤儿会话，
   *  一直占住设备租约到 expires_at。handleClose 已先清 sessionRef，不会重复关。 */
  useEffect(() => {
    if (open) return
    const id = sessionRef.current
    if (id === null) return
    sessionRef.current = null
    teardownSocket()
    void closeDebugSession(id).catch(() => undefined)
    // session state 也要清掉：否则残留的旧会话 id 会挡住下次自动建会话，
    // 并让 detailQuery/WS effect 拿着已关闭的会话空转。
    reset()
  }, [open, reset, teardownSocket])

  /** 会话建立/释放上抛（模板页签按会话隔离调用 /templates） */
  useEffect(() => {
    onSessionChange?.(session ? session.id : null)
  }, [onSessionChange, session])

  /** 采集快照 + 层级树 */
  const snapshotMutation = useMutation({
    mutationFn: async () => {
      const id = sessionRef.current
      if (id === null) throw new Error('缺少调试会话')
      const captured = await captureSnapshot(id, true)
      if (!captured.snapshot_id) throw new Error('快照响应缺少 snapshot_id')
      const tree = await fetchSnapshotTree(id, captured.snapshot_id)
      return {
        snapshotId: captured.snapshot_id,
        width: captured.width ?? null,
        height: captured.height ?? null,
        tree,
      }
    },
    onSuccess: ({ snapshotId: capturedId, width, height, tree }) => {
      setSnapshotId(capturedId)
      setSnapshotSize(width && height ? { w: width, h: height } : null)
      frozenRef.current = true
      setFrozen(true)
      setTreeError(null)
      const list = Array.isArray(tree?.nodes) ? tree.nodes : []
      setNodes(list)
      if (list.length === 0) toast.show('快照已采集，但层级树为空')
    },
    onError: (error) => {
      const described = describeError(error)
      setTreeError(described.code + '：' + described.message)
    },
  })

  const tree = useMemo(() => buildTreeIndex(nodes ?? []), [nodes])

  /** 坐标基准：优先快照像素（模板裁剪的服务端坐标），没有快照时退回实时流尺寸 */
  const coordinateSize = snapshotSize ?? frameSize

  /** 会话必须 active 才能碰 vendor：opening 期间 /templates 一律
   * `debug_session_not_active`，提前请求只会在界面上挂一条红字。 */
  const sessionActive = detailQuery.data?.state === 'active'

  // ------------------------------------------------------------ 预览传输（H.264 → JPEG 回退）
  useEffect(() => {
    if (!open || !session) return
    const choice = choosePreviewTransport(typeof VideoDecoder !== 'undefined')
    if (choice.mode === 'jpeg' && previewMode !== 'jpeg') {
      setPreviewMode('jpeg')
      setPreviewNote(choice.reason)
    }
  }, [open, session, previewMode])

  useEffect(() => {
    if (!open || !session || previewMode !== 'h264' || !sessionActive) return
    const id = sessionRef.current
    if (id === null) return
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const player = createH264Preview({
      canvas: canvasRef.current,
      wsUrl: proto + '//' + window.location.host + debugVideoWsPath(id),
      isPaused: () => frozenRef.current,
      onState: (state) => {
        if (state === 'open') {
          setWsStatus('open')
          setWsNotice(null)
        } else if (state === 'connecting') {
          setWsStatus('connecting')
        } else {
          setWsStatus('closed')
        }
      },
      onSession: (size) => {
        setFrameSize((prev) => (prev && prev.w === size.w && prev.h === size.h ? prev : size))
      },
      onFrame: (size) => {
        previewFrameCountRef.current += 1
        setFrameSize((prev) => (prev && prev.w === size.w && prev.h === size.h ? prev : size))
      },
      onError: (code, message) => {
        setPreviewNote('H.264 不可用，已回退 JPEG（' + code + '：' + message + '）')
        setPreviewMode('jpeg')
        setPreviewFps(null)
        setWsStatus('closed')
      },
    })
    h264PlayerRef.current = player
    player.open()
    return () => {
      player.close()
      if (h264PlayerRef.current === player) h264PlayerRef.current = null
    }
  }, [open, session, previewMode, sessionActive])

  useEffect(() => {
    if (!open || previewMode !== 'h264') return
    const timer = window.setInterval(() => {
      setPreviewFps(previewFrameCountRef.current)
      previewFrameCountRef.current = 0
    }, 1000)
    return () => window.clearInterval(timer)
  }, [open, previewMode])

  // ------------------------------------------------------------ 直接操控
  const controlState = useMemo(
    () =>
      controlAvailability({
        sessionActive,
        wsOpen: wsStatus === 'open',
        frozen,
        inspectMode,
        hasFrame: frameSize !== null,
        busy: createMutation.isPending || closeMutation.isPending || controlPending,
      }),
    [
      sessionActive,
      wsStatus,
      frozen,
      inspectMode,
      frameSize,
      createMutation.isPending,
      closeMutation.isPending,
      controlPending,
    ],
  )

  /** 心跳：vendor 5s 无心跳自动撤权；2s 续期，失败即退出操控并说明原因。 */
  useEffect(() => {
    if (!controlEnabled || !session) return
    let stopped = false
    const timer = setInterval(() => {
      void heartbeatDebugControl(session.id).catch((error) => {
        if (stopped) return
        const described = describeError(error)
        setControlError('控制权已失效（' + described.code + '）：' + described.message)
        setControlEnabled(false)
        setTouchDot(null)
        closeGestureSocket()
      })
    }, 2000)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [controlEnabled, session, closeGestureSocket])

  /** 冻结/切图像模式/会话失效时强制退出操控（释放服务端控制权）。 */
  useEffect(() => {
    if (!controlEnabled) return
    if (frozen || inspectMode !== 'native' || !sessionActive) {
      disableControl(sessionActive)
    }
  }, [controlEnabled, frozen, inspectMode, sessionActive, disableControl])

  /** 组件卸载/切设备时关闭手势 WS（会话关闭由 handleClose 负责）。 */
  useEffect(() => () => closeGestureSocket(), [closeGestureSocket])

  const confirmEnableControl = useCallback(async () => {
    const id = sessionRef.current
    if (id === null) return
    setControlConfirmOpen(false)
    setControlPending(true)
    setControlError(null)
    try {
      await setDebugControl(id, true)
      setControlEnabled(true)
    } catch (error) {
      const described = describeError(error)
      setControlError('启用直接操控失败（' + described.code + '）：' + described.message)
    } finally {
      setControlPending(false)
    }
  }, [])

  const handleControlToggle = useCallback(() => {
    if (controlEnabled) {
      disableControl(true)
      return
    }
    if (!controlState.enabled) return
    setControlConfirmOpen(true)
  }, [controlEnabled, controlState.enabled, disableControl])

  const handleControlKey = useCallback(async (name: 'back' | 'home') => {
    const id = sessionRef.current
    if (id === null) return
    try {
      await sendDebugKey(id, name)
    } catch (error) {
      const described = describeError(error)
      setControlError('按键失败（' + described.code + '）：' + described.message)
      if (described.code === 'control_expired' || described.code === 'control_not_enabled') {
        setControlEnabled(false)
        setTouchDot(null)
        closeGestureSocket()
      }
    }
  }, [closeGestureSocket])

  const gestureSend = useCallback((payload: object) => {
    const text = JSON.stringify(payload)
    const ws = gestureWsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(text)
    } else if (ws) {
      gestureQueueRef.current.push(text)
    }
  }, [])

  const openGesture = useCallback(() => {
    const id = sessionRef.current
    if (id === null) return
    closeGestureSocket()
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(proto + '://' + window.location.host + debugGestureWsPath(id))
    gestureWsRef.current = ws
    ws.onopen = () => {
      for (const text of gestureQueueRef.current) ws.send(text)
      gestureQueueRef.current = []
    }
    ws.onmessage = (event) => {
      let message: { kind?: string; code?: string; message?: string } | null = null
      try {
        message = JSON.parse(String(event.data))
      } catch {
        return
      }
      if (message?.kind === 'error') {
        setControlError(
          '操控失败（' + (message.code ?? 'error') + '）：' + (message.message ?? ''),
        )
        setControlEnabled(false)
        setTouchDot(null)
        closeGestureSocket()
      }
    }
    ws.onerror = () => setControlError('操控通道连接失败，请重新启用直接操控')
  }, [closeGestureSocket])

  const stagePoint = useCallback((event: React.PointerEvent) => {
    const frame = stageRef.current
    if (!frame) return null
    const rect = frame.getBoundingClientRect()
    return normalizeStagePoint(rect, event.clientX, event.clientY)
  }, [])

  const handleControlPointerDown = (event: React.PointerEvent) => {
    if (!controlEnabled) return
    if (event.pointerType === 'mouse' && event.button !== 0) return
    const point = stagePoint(event)
    if (!point) return
    event.preventDefault()
    try {
      ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    } catch {
      // 指针已释放
    }
    // 必须先 openGesture：它会调用 closeGestureSocket 清空 pointerStartRef；
    // 反过来会把刚记下的指针清掉，pointerup 时 end 永远发不出去（vendor 只能等
    // 2s 空闲超时补 UP，点击响应被拖到 UP 才发生）。
    openGesture()
    pointerStartRef.current = { nx: point.nx, ny: point.ny, at: Date.now() }
    lastMoveAtRef.current = null
    gestureSend(gestureMessage('start', point.nx, point.ny, ++gestureSeqRef.current))
    setTouchDot({ left: point.nx * 100, top: point.ny * 100 })
  }

  const handleControlPointerMove = (event: React.PointerEvent) => {
    if (!controlEnabled || !pointerStartRef.current) return
    const point = stagePoint(event)
    if (!point) return
    event.preventDefault()
    setTouchDot({ left: point.nx * 100, top: point.ny * 100 })
    const now = Date.now()
    if (!shouldSendGestureMove(lastMoveAtRef.current, now)) return
    lastMoveAtRef.current = now
    gestureSend(gestureMessage('move', point.nx, point.ny, ++gestureSeqRef.current))
  }

  const finishControlPointer = (event: React.PointerEvent) => {
    if (!controlEnabled || !pointerStartRef.current) return
    const point = stagePoint(event) ?? pointerStartRef.current
    event.preventDefault()
    gestureSend(gestureMessage('end', point.nx, point.ny, ++gestureSeqRef.current))
    pointerStartRef.current = null
    setTouchDot(null)
    try {
      ;(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId)
    } catch {
      // 指针已释放
    }
  }

  /** 模板清单（图像识别）：按调试会话隔离，vendor 返回 {templates: [...]} */
  const templatesQuery = useQuery({
    queryKey: ['debug-templates', session?.id],
    queryFn: ({ signal }) => fetchTemplates(session!.id, signal),
    enabled: open && Boolean(session) && sessionActive,
    retry: false,
  })
  const templates: TemplateRecord[] = useMemo(
    () => (Array.isArray(templatesQuery.data?.templates) ? templatesQuery.data!.templates : []),
    [templatesQuery.data],
  )
  const templatesError = templatesQuery.isError ? describeError(templatesQuery.error) : null

  /** 定位验证（含图像模板匹配：by='image' 时 value 是模板逻辑名）。
   * 图像目标必须走 /templates/validate：vendor 的 /locators/validate 对 image
   * 目标解包 3 元组、实际返回 4 个值，稳定 500。 */
  const validateMutation = useMutation({
    mutationFn: (input: { by: LocatorBy; value: string; threshold?: string }) => {
      const id = sessionRef.current
      if (id === null) throw new Error('缺少调试会话')
      if (!input.value.trim()) throw new Error('定位值不能为空')
      const target: { by: LocatorBy; value: string; confidence?: number } = {
        by: input.by,
        value: input.value.trim(),
      }
      if (input.by === 'image') {
        const threshold = Number(matchThreshold)
        if (!Number.isFinite(threshold) || threshold < 0.1 || threshold > 1.0) {
          throw new Error('阈值必须在 0.10-1.00 之间')
        }
        target.confidence = threshold
        return validateTemplate(id, { target })
      }
      return validateLocator(id, target)
    },
    onSuccess: (result) => {
      setValidateError(null)
      setLocatorSnapshotId(typeof result?.snapshot_id === 'string' ? result.snapshot_id : null)
      const list = Array.isArray(result?.matches) ? result.matches : []
      setMatches(list)
      setScores(Array.isArray(result?.scores) ? result.scores : null)
      setValidateNote(
        typeof result?.note === 'string'
          ? result.note
          : list.length === 1
            ? '唯一匹配'
            : list.length === 0
              ? '零匹配'
              : `多匹配 ${list.length} 个`,
      )
      if (list.length === 0) toast.show('定位验证完成：无匹配')
    },
    onError: (error) => {
      const described = describeError(error)
      setValidateError(described.code + '：' + described.message)
    },
  })

  const cropKey = cropVerificationKey(session?.id ?? null, snapshotId, region, matchThreshold)
  const cropValidation = useMutation({
    mutationFn: async (input: { key: string; sessionId: string | number; snapshotId: string; region: Region; threshold: number }) => {
      const result = await request<{
        count: number
        scores: number[]
        snapshot_id: string
        source_snapshot_id?: string
        region?: number[] | null
        verification?: string | null
      }>('/templates/validate-crop', {
        method: 'POST', query: { session_id: String(input.sessionId) },
        body: { snapshot_id: input.snapshotId, region: [input.region.x, input.region.y, input.region.w, input.region.h], threshold: input.threshold },
      })
      return { ...result, key: input.key }
    },
    onSuccess: (result) => {
      // 服务端发的一次性凭证 + 新快照/命中框就是登记依据；没有凭证（零匹配/
      // 多匹配）就只能是「未验证」，按钮也不能放行。
      setCropVerification(resolveCropVerification(result, result.key))
      setTemplateError(null)
    },
    onError: () => setCropVerification(null),
  })
  /** 只有「验证通过的 key」等于「当前会话/快照/框选/阈值」才算已验证 */
  const cropVerified = cropVerification !== null && cropVerification.key === cropKey

  /** 图像识别：从**验证时的新快照**裁剪建档（vendor 不收浏览器图片） */
  const createTemplateMutation = useMutation({
    mutationFn: () => {
      const id = sessionRef.current
      if (id === null) throw new Error('缺少调试会话')
      if (!snapshotId) throw new Error('先「采集快照」，模板只能从快照裁剪')
      if (!region) throw new Error('先在画面上拖拽框选模板区域')
      if (!cropVerified || !cropVerification) throw new Error('请先验证当前框选区域，唯一匹配后才能登记')
      const logical = newLogical.trim()
      if (!logical) throw new Error('模板逻辑名不能为空')
      return createTemplate(id, {
        snapshot_id: cropVerification.snapshotId,
        region: [
          cropVerification.region.x,
          cropVerification.region.y,
          cropVerification.region.w,
          cropVerification.region.h,
        ],
        logical,
        threshold: Number(matchThreshold),
        verification: cropVerification.token,
      })
    },
    onSuccess: (record) => {
      setTemplateError(null)
      toast.show('模板已登记：' + record.logical + '（v' + String(record.version_id ?? '').slice(0, 8) + '）')
      setNewLogical('')
      setRegion(null)
      // 凭证一次性：用过即失效，再登记必须重新验证
      setCropVerification(null)
      cropValidation.reset()
      void templatesQuery.refetch()
    },
    onError: (error) => {
      const described = describeError(error)
      setTemplateError(described.code + '：' + described.message)
    },
  })

  function clearInspection() {
    setSelected(null)
    setMatches(null)
    setScores(null)
    setValidateNote(null)
    setValidateError(null)
    setLocatorSnapshotId(null)
    setLocator('')
    setRegion(null)
    setDragging(null)
    setNewLogical('')
    setTemplateError(null)
    setCropVerification(null)
    cropValidation.reset()
    validateMutation.reset()
  }

  const detailError = detailQuery.isError ? describeError(detailQuery.error) : null
  /** 上游不可达（viewer 未起）与无活动会话给出更具体的提示 */
  const upstreamHint = (error: ReturnType<typeof describeError> | null): string | null => {
    if (!error) return null
    if (error.code === 'viewer_unavailable') return 'viewer 上游不可达：runner 可能尚未起 viewer 或已退出。'
    if (error.code === 'debug_session_not_active') return '调试会话尚未激活，等 runner 回报端口后重试。'
    return null
  }

  // ---------------------------------------------------------------- 框选
  /** 鼠标位置 → 设备像素。取 `.debug-frame` 的 rect：它收缩到 canvas 盒子
   *  （stage 只负责居中，多出来的留白不能被算进比例）。 */
  const pointToDevice = (event: React.MouseEvent): { x: number; y: number } | null => {
    const frame = stageRef.current
    if (!frame || !coordinateSize) return null
    const rect = frame.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return null
    const x = ((event.clientX - rect.left) / rect.width) * coordinateSize.w
    const y = ((event.clientY - rect.top) / rect.height) * coordinateSize.h
    return {
      x: Math.min(Math.max(Math.round(x), 0), coordinateSize.w),
      y: Math.min(Math.max(Math.round(y), 0), coordinateSize.h),
    }
  }

  const handleStageDown = (event: React.MouseEvent) => {
    if (controlEnabled || !cropSelectionEnabled(inspectMode)) return
    const point = pointToDevice(event)
    if (!point) return
    setDragging({ x: point.x, y: point.y, w: 0, h: 0 })
  }

  const handleStageMove = (event: React.MouseEvent) => {
    if (controlEnabled || !cropSelectionEnabled(inspectMode) || !dragging) return
    const point = pointToDevice(event)
    if (!point) return
    setDragging(normalizeRegion(dragging.x, dragging.y, point.x, point.y))
  }

  const handleStageUp = () => {
    if (controlEnabled || !cropSelectionEnabled(inspectMode) || !dragging) return
    const box = dragging
    setDragging(null)
    // 太小的框多半是误点：清掉而不是留一个 1px 的模板区域
    if (box.w < 8 || box.h < 8) return
    setRegion(box)
  }

  const overlayRegion = dragging ?? region
  const overlayBoxes = useMemo(() => {
    if (!coordinateSize || !matches) return []
    return matches
      .map((match, index) => ({ match, index }))
      .filter(({ match }) => typeof match.x === 'number' && typeof match.y === 'number'
        && typeof match.width === 'number' && typeof match.height === 'number')
      .map(({ match, index }) => ({
        index,
        left: ((match.x as number) / coordinateSize.w) * 100,
        top: ((match.y as number) / coordinateSize.h) * 100,
        width: ((match.width as number) / coordinateSize.w) * 100,
        height: ((match.height as number) / coordinateSize.h) * 100,
        // 图像匹配的分数在顶层 scores 里，元素匹配才有 match.confidence
        confidence:
          typeof match.confidence === 'number' ? match.confidence : scores?.[index] ?? null,
      }))
  }, [coordinateSize, matches, scores])

  const wsText = wsStatus === 'open' ? '已连接' : wsStatus === 'connecting' ? '连接中' : '未连接'

  /** 设备档案分辨率（原型 d.res）；vendor 实时流可能是缩放帧，不能拿它冒充分辨率 */
  const currentDevice = devices.find((device) => device.resource_key === target?.serial) ?? null
  const deviceResolution = currentDevice?.profile?.screen_resolution
    ?? (frameSize ? frameSize.w + ' × ' + frameSize.h : '—')

  /** 原型「Target(...)」表达式：当前定位方式 + 定位值（图像则带阈值） */
  const locatorExpression = useMemo(() => {
    if (!locator.trim()) return ''
    if (locatorBy === 'image') {
      return 'Target(Locator.IMAGE, "' + locator.trim() + '", confidence=' + matchThreshold + ')'
    }
    const names: Record<LocatorBy, string> = {
      resource_id: 'RESOURCE_ID',
      text: 'TEXT',
      accessibility_id: 'ACCESSIBILITY_ID',
      u2_selector: 'U2_SELECTOR',
      xpath: 'XPATH',
      image: 'IMAGE',
    }
    return 'Target(Locator.' + names[locatorBy] + ', "' + locator.trim() + '")'
  }, [locatorBy, locator, matchThreshold])

  if (!open) return null

  return (
    <div className="debug-workspace" aria-label={target ? target.label + ' · 调试' : '设备调试'}>
      {/* 原型 inspectorPage：定位方式切换器在 toolbar 之前，独立一行 */}
      <div className="flex wrap mb" role="group" aria-label="定位方式">
        {([['native', '原生节点'], ['image', '图像模板']] as const).map(([value, label]) => (
          <Button
            key={value}
            size="small"
            kind={inspectMode === value ? 'soft' : 'default'}
            aria-pressed={inspectMode === value}
            onClick={() => {
              setInspectMode(value)
              if (value === 'native') {
                setDragging(null)
                setRegion(null)
                setCropVerification(null)
              }
            }}
          >
            {label}
          </Button>
        ))}
        <span className="small muted">
          {inspectMode === 'native'
            ? '冻结快照后点击树节点；定位结果来自 vendor 实时校验。'
            : '图像模板从服务端保留的快照裁剪登记，匹配经 vendor TemplateStore 校验。'}
        </span>
      </div>

      {/* 原型 nativeInspectorPage 的 toolbar：设备下拉 + 状态 + 采集/恢复（同一个按钮） */}
      <div className="toolbar mb">
        <select
          aria-label="调试设备"
          value={target?.serial ?? ''}
          disabled={createMutation.isPending || closeMutation.isPending}
          onChange={async (event) => {
            const picked = devices.find((d) => d.resource_key === event.target.value)
            if (!picked || picked.resource_key === target?.serial) return
            const id = sessionRef.current
            if (id !== null) {
              try {
                await closeMutation.mutateAsync(id)
              } catch { return }
              sessionRef.current = null
              teardownSocket()
            }
            reset()
            createPendingRef.current = false
            onTargetChange(toWorkspaceTarget(picked))
            void queryClient.invalidateQueries({ queryKey: ['resources'] })
          }}
        >
          {target && !devices.some((device) => device.resource_key === target.serial) ? <option value={target.serial}>{target.label} · 当前调试设备</option> : null}
          {!target && devices.length === 0 ? <option value="">没有可调试设备</option> : null}
          {devices.map((device) => {
            // 原型口径：name / os；档案缺失时如实回落设备编号
            const os = device.profile?.os_name
              ? (device.profile.os_name + ' ' + (device.profile.os_version ?? '')).trim()
              : device.resource_key
            return (
              <option key={device.id} value={device.resource_key}>
                {device.name} / {os}
              </option>
            )
          })}
        </select>
        <Badge tone={target ? 'green' : 'gray'} dot>{target ? '可用' : '无设备'}</Badge>
        {/* 会话身份如实显示：实际 adb serial + 会话状态 + WS 连接状态 */}
        <span className="small muted mono" title="设备 serial">{target ? target.serial : '—'}</span>
        <span className="small muted">
          会话 {detailQuery.data?.state ?? (session ? 'opening' : '未建立')} · {wsText}
        </span>
        {target?.leaseHint ? <span className="small muted">· {target.leaseHint}</span> : null}
        <Button
          size="small"
          kind={controlEnabled ? 'soft' : 'default'}
          disabled={!controlEnabled && (!controlState.enabled || controlPending)}
          title={
            controlEnabled
              ? '退出直接操控，恢复只读预览'
              : controlState.reason ?? '向真机发送点击/滑动（单操作者）'
          }
          onClick={handleControlToggle}
        >
          {controlPending ? '领取控制权…' : controlEnabled ? '退出操控' : '直接操控'}
        </Button>
        {controlEnabled ? <Badge tone="green" dot>操控中</Badge> : null}
        <span className="spacer" />
        <Button size="small" onClick={handleClose}>返回设备池</Button>
        {frozen ? (
          <Button
            size="small"
            icon="play"
            disabled={validateMutation.isPending || cropValidation.isPending || createTemplateMutation.isPending}
            onClick={() => {
              // socket 一直活着，恢复后下一帧就会覆盖 canvas
              clearInspection()
              setSnapshotId(null)
              setSnapshotSize(null)
              setNodes(null)
              setTreeError(null)
              frozenRef.current = false
              setFrozen(false)
            }}
          >
            恢复预览
          </Button>
        ) : (
          <Button
            kind="primary"
            size="small"
            icon="freeze"
            disabled={!sessionActive || snapshotMutation.isPending}
            title={sessionActive ? '冻结当前画面并采集 UI 树' : '调试会话尚未激活'}
            onClick={() => snapshotMutation.mutate()}
          >
            {snapshotMutation.isPending ? '采集中…' : '采集检查'}
          </Button>
        )}
      </div>

      <div className="debug-workspace-body">
        {wsNotice ? (
          <div className="mb">
            <Notice tone="amber" title="调试会话">{wsNotice}</Notice>
          </div>
        ) : null}
        {closeError ? (
          <div className="mb">
            <Notice tone="red" title="关闭失败">{closeError}</Notice>
          </div>
        ) : null}
        {controlError ? (
          <div className="mb">
            <Notice tone="amber" title="直接操控">{controlError}</Notice>
          </div>
        ) : null}
        {previewMode === 'jpeg' && previewNote ? (
          <div className="mb">
            <Notice tone="amber" title="预览已回退 JPEG">{previewNote}</Notice>
          </div>
        ) : null}
        {!target && !createMutation.isPending ? (
          <div className="mb">
            <Notice tone="amber" title="没有可调试设备">
              当前没有 ready 且空闲的 Android 设备（可能正被运行或其他调试会话占用）；设备空闲后自动建立会话。
            </Notice>
          </div>
        ) : null}
        {createMutation.isPending ? (
          <div className="mb">
            <Notice tone="blue" title="正在创建调试会话">正在请求 POST /api/v1/debug-sessions</Notice>
          </div>
        ) : null}

        {/* 原型 nativeInspectorPage：三栏常驻（左 .phone-panel + 中右两个 .panel） */}
        <div className={'inspector' + (inspectMode === 'image' ? ' mode-image' : '')}>
          {/* 第 1 栏：手机外壳内的真机实时画面 */}
          <section className="phone-panel">
            <div className="between">
              <Badge tone={frozen ? 'amber' : 'blue'} dot>{frozen ? '冻结快照' : '实时画面'}</Badge>
              <span className="small muted">
                {previewMode === 'h264'
                  ? wsStatus === 'open'
                    ? 'H.264 · ' + (previewFps ?? 0) + 'fps'
                    : 'H.264 连接中'
                  : previewNote
                    ? 'JPEG 回退'
                    : wsText}
              </span>
            </div>
            <div
              className={'debug-stage phone-stage' + (controlEnabled ? ' control-mode' : '')}
              onMouseDown={handleStageDown}
              onMouseMove={handleStageMove}
              onMouseUp={handleStageUp}
              onMouseLeave={handleStageUp}
              onPointerDown={handleControlPointerDown}
              onPointerMove={handleControlPointerMove}
              onPointerUp={finishControlPointer}
              onPointerCancel={finishControlPointer}
            >
              <div className="phone">
                <div className="phone-camera" />
                <div className="debug-frame" ref={stageRef} style={{ display: frameSize ? undefined : 'none' }}>
                  <canvas ref={canvasRef} aria-label="设备画面预览" />
                  {controlEnabled && touchDot ? (
                    <span
                      className="debug-touch-dot"
                      style={{ left: touchDot.left + '%', top: touchDot.top + '%' }}
                    />
                  ) : null}
                  {overlayBoxes.map((box) => (
                    <div
                      key={box.index}
                      className="debug-box"
                      style={{ left: box.left + '%', top: box.top + '%', width: box.width + '%', height: box.height + '%' }}
                    >
                      <span>
                        #{box.index + 1}
                        {typeof box.confidence === 'number' ? ' ' + box.confidence.toFixed(2) : ''}
                      </span>
                    </div>
                  ))}
                  {cropSelectionEnabled(inspectMode) && overlayRegion && coordinateSize ? (
                    <div
                      className="debug-box pick"
                      style={{
                        left: (overlayRegion.x / coordinateSize.w) * 100 + '%',
                        top: (overlayRegion.y / coordinateSize.h) * 100 + '%',
                        width: (overlayRegion.w / coordinateSize.w) * 100 + '%',
                        height: (overlayRegion.h / coordinateSize.h) * 100 + '%',
                      }}
                    >
                      <span>
                        {overlayRegion.w}×{overlayRegion.h}
                      </span>
                    </div>
                  ) : null}
                </div>
                {!frameSize ? (
                  <div className="debug-stage-empty">
                    {wsStatus === 'open' ? '等待设备画面…' : '画面尚未连接（' + wsText + '）'}
                  </div>
                ) : null}
                <div className="phone-bottom" aria-hidden="true" />
              </div>
            </div>
            <div className="debug-control-bar">
              <span className="small muted">
                {controlEnabled
                  ? '直接操控中 · 点击/拖动画面（单操作者）'
                  : '直接操控未启用 · 先在工具栏点「直接操控」'}
              </span>
              <Button
                size="small"
                disabled={!controlEnabled}
                title={controlEnabled ? undefined : '先启用直接操控'}
                onClick={() => void handleControlKey('back')}
              >
                返回键
              </Button>
              <Button
                size="small"
                disabled={!controlEnabled}
                title={controlEnabled ? undefined : '先启用直接操控'}
                onClick={() => void handleControlKey('home')}
              >
                Home
              </Button>
            </div>
            <div className="between small muted">
              <span>{snapshotId ? '快照 ' + snapshotId : frozen ? '快照待采集' : '设备画面未冻结'}</span>
              <span>{deviceResolution}</span>
            </div>
            <div className="debug-kv" style={{ marginTop: 8 }}>
              <span>绿框 = 最近一次定位命中</span>
              <span>橙框 = 框选区域（用于新建模板）</span>
            </div>
            {detailError ? (
              <div className="mt">
                <Notice tone="red" title={'会话详情获取失败（' + detailError.code + '）'}>
                  {detailError.message}
                  {upstreamHint(detailError) ? (
                    <div className="small" style={{ marginTop: 6 }}>{upstreamHint(detailError)}</div>
                  ) : null}
                </Notice>
              </div>
            ) : null}
          </section>

          {inspectMode === 'native' ? (
            <>
              {/* 第 2 栏：UI 层级树 */}
              <section className="panel">
                <div className="panel-head">
                  <h2>UI 层级树</h2>
                  <span className="small muted">{nodes === null ? '未采集' : nodes.length + ' 个节点'}</span>
                </div>
                <div className="tree" role="tree" aria-label="UI 层级树">
                  {treeError ? (
                    <Notice tone="red" title="快照 / 层级树获取失败">{treeError}</Notice>
                  ) : nodes === null ? null : nodes.length === 0 ? (
                    <p className="small muted" style={{ padding: 12 }}>该快照没有 UI 树（vendor 未采集或设备不支持）。</p>
                  ) : (
                    tree.roots.map((node) => (
                      <TreeBranch
                        key={node.index}
                        node={node}
                        depth={0}
                        byIndex={tree.byIndex}
                        selectedIndex={selected?.index ?? null}
                        frozen={frozen}
                        onPick={(picked) => {
                          setSelected(picked)
                          // 选中节点时把它的标识直接填进定位值，减少手输；
                          // resource-id 优先于 text（文案会变，id 更稳）
                          const preferred = preferredLocator(picked)
                          if (preferred) {
                            setLocatorBy(preferred.by)
                            setLocator(preferred.value)
                          }
                        }}
                      />
                    ))
                  )}
                </div>
                <div className="tree-foot small muted">
                  {frozen && snapshotId
                    ? '已绑定同一次冻结快照，点击节点查看定位描述。'
                    : '先点击「采集检查」，冻结画面与 UI 树。'}
                </div>
              </section>

              {/* 第 3 栏：元素与定位描述 + 定位验证（原型 attribute-list / locator-option） */}
              <section className="panel">
                <div className="panel-head">
                  <h2>元素与定位描述</h2>
                  <span className="badge gray">原生定位</span>
                </div>
                <div className="attribute-list">
                  {selected ? (
                    <>
                      <div className="attribute"><span>text</span><span>{selected.text || '—'}</span></div>
                      <div className="attribute"><span>resource-id</span><span className="mono">{selected.resource_id || '—'}</span></div>
                      <div className="attribute"><span>class</span><span className="mono">{selected.class_name || '—'}</span></div>
                      <div className="attribute"><span>clickable</span><span>{selected.clickable ? 'true' : 'false'}</span></div>
                      <div className="attribute"><span>bounds</span><span className="mono">{nodeBounds(selected) || '—'}</span></div>
                    </>
                  ) : (
                    <Empty
                      icon="search"
                      title="等待拾取"
                      description={frozen ? '在层级树中点击节点，这里显示其属性与定位候选。' : '先点击「采集检查」冻结画面与 UI 树。'}
                    />
                  )}

                  {selected ? (
                    <>
                      {selected.resource_id || selected.text ? (
                        <h3 style={{ margin: '20px 0 10px', fontSize: 12 }}>定位候选</h3>
                      ) : null}
                      {selected.resource_id ? (
                        <button
                          type="button"
                          className={'locator-option' + (locatorBy === 'resource_id' ? ' active' : '')}
                          onClick={() => { setLocatorBy('resource_id'); setLocator(String(selected.resource_id)) }}
                        >
                          <div className="between"><b>resource-id</b><span className="badge green">优先候选</span></div>
                          <code>{String(selected.resource_id)}</code>
                        </button>
                      ) : null}
                      {selected.text ? (
                        <button
                          type="button"
                          className={'locator-option' + (locatorBy === 'text' ? ' active' : '')}
                          onClick={() => { setLocatorBy('text'); setLocator(String(selected.text)) }}
                        >
                          <div className="between"><b>text</b><span className="small text-amber">文案变动会失效</span></div>
                          <code>{String(selected.text)}</code>
                        </button>
                      ) : null}
                      {!selected.resource_id && !selected.text ? (
                        <p className="small muted">
                          该节点没有 resource-id / text，无法自动生成定位候选；请手动填写定位值或改选其他节点。
                        </p>
                      ) : null}
                    </>
                  ) : null}

                  {locatorExpression ? <pre className="code-block">{locatorExpression}</pre> : null}

                  <div className="debug-form">
                    <label>
                      定位方式
                      <select
                        value={locatorBy}
                        onChange={(event) => setLocatorBy(event.target.value as LocatorBy)}
                      >
                        {LOCATOR_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      定位值
                      <input
                        value={locator}
                        onChange={(event) => setLocator(event.target.value)}
                        placeholder={locatorBy === 'image' ? '模板逻辑名，如 buttons/confirm.png' : '文本 / resource-id / xpath'}
                      />
                    </label>
                    {locatorBy === 'image' ? (
                      <label className="full">
                        阈值 0.10-1.00
                        <input
                          value={matchThreshold}
                          onChange={(event) => setMatchThreshold(event.target.value)}
                          aria-label="图像匹配阈值"
                        />
                      </label>
                    ) : null}
                  </div>

                  <div className="flex wrap" style={{ marginTop: 10, gap: 8 }}>
                    <Button
                      kind="primary"
                      size="small"
                      icon="check"
                      disabled={!locator.trim() || validateMutation.isPending}
                      onClick={() =>
                        validateMutation.mutate({
                          by: locatorBy,
                          value: locator,
                          threshold: matchThreshold,
                        })
                      }
                    >
                      {validateMutation.isPending ? '验证中…' : '验证定位'}
                    </Button>
                    <Button
                      size="small"
                      icon="copy"
                      disabled={!locatorExpression}
                      onClick={() => copyExpression(locatorExpression, toast.show)}
                    >
                      复制表达式
                    </Button>
                  </div>

                  {validateError ? (
                    <div className="mt">
                      <Notice tone="red" title="验证失败">{validateError}</Notice>
                    </div>
                  ) : null}

                  <div className="mt" role="status">
                    <p className="small muted">
                      {matches === null ? '验证后在这里显示匹配结果。' : validateNote ?? ''}
                      {locatorSnapshotId
                        ? ' · 定位快照 ' + locatorSnapshotId +
                          (frozen && snapshotId && locatorSnapshotId !== snapshotId
                            ? '（vendor 重新采集，与冻结画面不同）'
                            : '')
                        : ''}
                    </p>
                    {matches !== null && matches.length > 0 ? (
                      <div className="mt">
                        {matches.map((match, index) => (
                          <div className="locator-match" key={index}>
                            <span className="muted">#{index + 1}</span>
                            <span className="mono">
                              {match.x ?? DASH},{match.y ?? DASH} · {match.width ?? DASH}×{match.height ?? DASH}
                            </span>
                            <span className="mono">
                              {typeof match.confidence === 'number'
                                ? match.confidence.toFixed(3)
                                : typeof scores?.[index] === 'number'
                                  ? scores[index].toFixed(3)
                                  : DASH}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </section>
            </>
          ) : (
            <>
              {/* 图像模式第 2 栏：原型 imagePanel 的「框选与保存模板」 */}
              <section className="panel panel-pad image-form">
                <h2 style={{ fontSize: 14 }}>框选与保存模板</h2>
                <p className="small muted">
                  {snapshotId ? '在冻结画面上拖拽框选，或填写坐标。' : '先点击「采集检查」冻结画面。'}
                  坐标单位：设备像素，范围 {coordinateSize ? coordinateSize.w + ' × ' + coordinateSize.h : '—'}。
                </p>
                <div className="image-coords">
                  {([['x', 'X'], ['y', 'Y'], ['w', '宽度'], ['h', '高度']] as const).map(([key, label]) => (
                    <label className="field" key={key}>
                      <span>{label}</span>
                      <input
                        inputMode="numeric"
                        aria-label={'框选' + label}
                        value={region ? String(region[key]) : ''}
                        onChange={(event) => setRegion(editRegion(region, key, event.target.value))}
                      />
                    </label>
                  ))}
                </div>
                <p className="small muted">
                  {region ? '选区 [X, Y, 宽度, 高度]：[' + region.x + ', ' + region.y + ', ' + region.w + ', ' + region.h + ']' : '尚未框选区域'}
                </p>
                <div className="debug-kv">
                  <span>快照：{snapshotId ? snapshotId.slice(0, 12) : '未采集（模板只能从服务端保留的快照裁剪）'}</span>
                </div>
                <label className="field">
                  <span>模板逻辑名（.png，POSIX 相对路径）</span>
                  <input
                    value={newLogical}
                    onChange={(event) => setNewLogical(event.target.value)}
                    placeholder="buttons/confirm.png"
                  />
                </label>
                {templateError ? <Notice tone="red" title="模板登记失败">{templateError}</Notice> : null}
                {cropValidation.isError ? <Notice tone="red" title="框选验证失败">{describeError(cropValidation.error).message}</Notice> : null}
                {cropValidation.data?.key === cropKey ? <p role="status" className="small muted">{cropValidation.data.count === 1 ? '验证通过，唯一匹配' : `验证未通过，匹配到 ${cropValidation.data.count} 处`} · 最高分 {cropValidation.data.scores.length ? Math.max(...cropValidation.data.scores).toFixed(3) : '—'} · 验证快照 {cropValidation.data.snapshot_id}</p> : null}
                {cropVerified && cropVerification ? (
                  <p role="status" className="small muted">
                    登记依据：验证快照 {cropVerification.snapshotId} · 命中框 [{cropVerification.region.x}, {cropVerification.region.y}, {cropVerification.region.w}, {cropVerification.region.h}]（凭证一次性，改动框选/阈值/快照后需重新验证）
                  </p>
                ) : null}
                <div className="flex wrap" style={{ gap: 8 }}>
                  <Button size="small" icon="check" disabled={!sessionActive || !snapshotId || !region || region.w < 4 || region.h < 4 || !coordinateSize || region.x < 0 || region.y < 0 || region.x + region.w > coordinateSize.w || region.y + region.h > coordinateSize.h || !matchThreshold.trim() || !Number.isFinite(Number(matchThreshold)) || Number(matchThreshold) < 0.1 || Number(matchThreshold) > 1 || cropValidation.isPending} onClick={() => {
                    if (session && snapshotId && region) cropValidation.mutate({ key: cropKey, sessionId: session.id, snapshotId, region, threshold: Number(matchThreshold) })
                  }}>{cropValidation.isPending ? '验证中…' : '验证框选匹配'}</Button>
                  <Button
                    kind="primary"
                    size="small"
                    icon="plus"
                    disabled={createTemplateMutation.isPending || cropValidation.isPending || !cropVerified || !snapshotId || !region || !newLogical.trim()}
                    onClick={() => createTemplateMutation.mutate()}
                  >
                    {createTemplateMutation.isPending ? '登记中…' : '从框选登记模板'}
                  </Button>
                  <Button size="small" onClick={() => setRegion(null)} disabled={!region}>清除框选</Button>
                </div>
              </section>

              {/* 图像模式第 3 栏：原型 imagePanel 的「重新匹配验证」 */}
              <section className="panel panel-pad image-form">
                <div className="between">
                  <h2 style={{ fontSize: 14 }}>图像匹配验证</h2>
                  <Button
                    size="small"
                    icon="image"
                    disabled={templatesQuery.isFetching || validateMutation.isPending || cropValidation.isPending || createTemplateMutation.isPending}
                    onClick={() => { clearInspection(); void templatesQuery.refetch() }}
                  >
                    {templatesQuery.isFetching ? '刷新中…' : '刷新'}
                  </Button>
                </div>
                <label className="field">
                  <span>匹配阈值（0.10 至 1.00）</span>
                  <input
                    type="number"
                    min={0.1}
                    max={1}
                    step={0.01}
                    value={matchThreshold}
                    aria-label="图像匹配阈值"
                    onChange={(event) => setMatchThreshold(event.target.value)}
                  />
                </label>
                {templatesError ? (
                  <Notice tone="red" title={'模板清单获取失败（' + templatesError.code + '）'}>
                    {templatesError.message}
                  </Notice>
                ) : null}
                <div className="image-template-list">
                  {templates.length === 0 ? (
                    <p className="small muted">
                      {!sessionActive
                        ? '等待调试会话激活…'
                        : templatesQuery.isLoading
                          ? '正在加载模板…'
                          : '该调试会话还没有模板：先在第 2 栏框选区域并登记。'}
                    </p>
                  ) : (
                    <table className="task-table" aria-label="模板清单">
                      <thead>
                        <tr>
                          <th>逻辑名</th>
                          <th>版本</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {templates.map((template) => (
                          <tr key={template.logical}>
                            <td className="mono">{template.logical}</td>
                            <td className="mono">{String(template.version_id ?? '').slice(0, 8) || DASH}</td>
                            <td>
                              <Button
                                size="small"
                                icon="search"
                                disabled={validateMutation.isPending}
                                onClick={() => {
                                  setLocatorBy('image')
                                  setLocator(template.logical)
                                  validateMutation.mutate({ by: 'image', value: template.logical, threshold: matchThreshold })
                                }}
                              >
                                图像匹配
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
                {locatorExpression && locatorBy === 'image' ? (
                  <pre className="code-block">{locatorExpression}</pre>
                ) : null}
                <div className="image-status" role="status">
                  {validateError ? <Notice tone="red" title="验证失败">{validateError}</Notice> : null}
                  {!validateError && matches !== null ? (
                    <p className="small muted">
                      {validateNote ?? ''}
                      {matches.length > 0 ? ' · 命中 ' + matches.length + ' 个区域' : ''}
                      {locatorSnapshotId ? ' · 定位快照 ' + locatorSnapshotId : ''}
                    </p>
                  ) : null}
                  {!validateError && matches === null ? (
                    <p className="small muted">选择模板并填写有效阈值后点击「图像匹配」。</p>
                  ) : null}
                </div>
                <div className="flex wrap" style={{ gap: 8 }}>
                  <Button
                    kind="primary"
                    size="small"
                    icon="check"
                    disabled={!locator.trim() || locatorBy !== 'image' || validateMutation.isPending}
                    onClick={() => validateMutation.mutate({ by: 'image', value: locator, threshold: matchThreshold })}
                  >
                    {validateMutation.isPending ? '验证中…' : '验证匹配'}
                  </Button>
                  <Button
                    size="small"
                    icon="copy"
                    disabled={!locatorExpression}
                    onClick={() => copyExpression(locatorExpression, toast.show)}
                  >
                    复制 IMAGE 表达式
                  </Button>
                </div>
              </section>
            </>
          )}
        </div>
      </div>

      <Dialog
        open={controlConfirmOpen}
        onClose={() => setControlConfirmOpen(false)}
        title="启用直接操控"
        description="会向真机发送点击与滑动；单操作者，其他操作者占用时会被拒绝。"
        footer={
          <>
            <Button onClick={() => setControlConfirmOpen(false)}>取消</Button>
            <Button kind="primary" onClick={() => void confirmEnableControl()}>
              启用
            </Button>
          </>
        }
      >
        <p className="small muted">
          点击/拖动左侧真机画面即可操作设备；冻结画面、切到图像模板模式或关闭会话会自动退出。
          控制权约 5 秒无心跳自动释放。
        </p>
      </Dialog>

      <footer className="debug-pane-foot">
        <span className="foot-hint">关闭面板会同时关闭调试会话并释放资源租约</span>
        <Button onClick={handleClose} disabled={closeMutation.isPending}>
          {closeMutation.isPending ? '正在关闭…' : '关闭会话'}
        </Button>
      </footer>
    </div>
  )
}

/** 由拖拽起止点归一化出左上角 + 宽高（允许反向拖拽） */
function normalizeRegion(x0: number, y0: number, x1: number, y1: number): Region {
  return {
    x: Math.min(x0, x1),
    y: Math.min(y0, y1),
    w: Math.abs(x1 - x0),
    h: Math.abs(y1 - y0),
  }
}

/** 手工编辑区域输入框：空串视为 0，非数字忽略 */
function editRegion(region: Region | null, key: keyof Region, raw: string): Region | null {
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

/** 把 vendor 的 base64 JPEG 帧画到 canvas；解码失败保留上一帧 */
function drawFrame(
  canvas: HTMLCanvasElement | null,
  base64: string,
  onSize?: (size: FrameSize) => void,
): void {
  if (!canvas) return
  const image = new Image()
  image.onload = () => {
    canvas.width = image.naturalWidth
    canvas.height = image.naturalHeight
    const ctx = canvas.getContext('2d')
    ctx?.drawImage(image, 0, 0)
    onSize?.({ w: image.naturalWidth, h: image.naturalHeight })
  }
  image.src = 'data:image/jpeg;base64,' + base64
}
