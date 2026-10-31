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
 *  - 图像识别（vendor imaging + TemplateStore）：
 *      GET  /templates?session_id=            模板清单（逻辑名 / 版本 / 摘要）
 *      POST /templates {snapshot_id, region, logical}
 *                                             从**服务端保留的快照**裁剪建档，
 *                                             vendor 不接受浏览器上传图片
 *    匹配本身仍走 locators/validate（by='image'，value=逻辑名），命中框叠在画面上。
 *    框选区域直接在预览画面上拖拽得到（设备像素坐标 = 快照像素坐标）。
 * 硬约束：
 *  - 会话创建失败 / 端点不可用只显示 Notice + 错误码，不伪造画面；
 *  - 关闭面板先 DELETE /debug-sessions/{id} 再清 WS；
 *  - WS 断开（非主动关闭）提示「会话已结束」。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import {
  captureSnapshot,
  closeDebugSession,
  createDebugSession,
  createTemplate,
  fetchDebugSession,
  fetchSnapshotTree,
  fetchTemplates,
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
 * 节点展示名：文本优先，其次 resource_id / 类名；都没有显示 #下标。
 * 空串按「没有」处理 —— vendor 对无文本节点给的是 text="" 而不是 null，
 * 否则 content_desc 会被空串挡掉。
 */
export function nodeLabel(node: SnapshotTreeNode): string {
  for (const candidate of [node.text, node.content_desc, node.resource_id, node.class_name]) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate
  }
  return '#' + node.index
}

function nodeBounds(node: SnapshotTreeNode): string | null {
  const bounds = node.bounds
  if (!Array.isArray(bounds) || bounds.length !== 4) return null
  const [left, top, right, bottom] = bounds
  return `${left},${top} → ${right},${bottom}`
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
        <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
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

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  /** 主动关闭标记：区别于服务端断开 */
  const closingRef = useRef(false)
  const wsRef = useRef<WebSocket | null>(null)
  const sessionRef = useRef<string | number | null>(null)
  const wsRetriesRef = useRef(0)
  /** frozen 的 ref 镜像：WS onmessage 闭包不随 frozen 重建（重建会断流重连） */
  const frozenRef = useRef(false)

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
  }, [])

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
    if (!open || !session) return
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
  }, [open, session, detailQuery.data?.ws_path, wsAttempt])

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

  /** 图像识别：从服务端保留的快照裁剪建档（vendor 不收浏览器图片） */
  const createTemplateMutation = useMutation({
    mutationFn: () => {
      const id = sessionRef.current
      if (id === null) throw new Error('缺少调试会话')
      if (!snapshotId) throw new Error('先「采集快照」，模板只能从快照裁剪')
      if (!region) throw new Error('先在画面上拖拽框选模板区域')
      const logical = newLogical.trim()
      if (!logical) throw new Error('模板逻辑名不能为空')
      return createTemplate(id, {
        snapshot_id: snapshotId,
        region: [region.x, region.y, region.w, region.h],
        logical,
      })
    },
    onSuccess: (record) => {
      setTemplateError(null)
      toast.show('模板已登记：' + record.logical + '（v' + String(record.version_id ?? '').slice(0, 8) + '）')
      setNewLogical('')
      setRegion(null)
      void templatesQuery.refetch()
    },
    onError: (error) => {
      const described = describeError(error)
      setTemplateError(described.code + '：' + described.message)
    },
  })

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
    const point = pointToDevice(event)
    if (!point) return
    setDragging({ x: point.x, y: point.y, w: 0, h: 0 })
  }

  const handleStageMove = (event: React.MouseEvent) => {
    if (!dragging) return
    const point = pointToDevice(event)
    if (!point) return
    setDragging(normalizeRegion(dragging.x, dragging.y, point.x, point.y))
  }

  const handleStageUp = () => {
    if (!dragging) return
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
            onClick={() => setInspectMode(value)}
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
          onChange={(event) => {
            const picked = devices.find((d) => d.resource_key === event.target.value)
            if (picked) onTargetChange(toWorkspaceTarget(picked))
          }}
        >
          {devices.length === 0 ? <option value="">没有可调试设备</option> : null}
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
        <span className="small muted">{wsText}</span>
        {target?.leaseHint ? <span className="small muted">· {target.leaseHint}</span> : null}
        <span className="spacer" />
        <Button size="small" onClick={handleClose}>返回设备池</Button>
        {frozen ? (
          <Button
            size="small"
            icon="play"
            onClick={() => {
              // socket 一直活着，恢复后下一帧就会覆盖 canvas
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
              <span className="small muted">{wsText}</span>
            </div>
            <div
              className="debug-stage phone-stage"
              onMouseDown={handleStageDown}
              onMouseMove={handleStageMove}
              onMouseUp={handleStageUp}
              onMouseLeave={handleStageUp}
            >
              <div className="phone">
                <div className="phone-camera" />
                <div className="debug-frame" ref={stageRef} style={{ display: frameSize ? undefined : 'none' }}>
                  <canvas ref={canvasRef} aria-label="设备画面预览" />
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
                  {overlayRegion && coordinateSize ? (
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
              </div>
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
                          // 选中节点时把它的标识直接填进定位值，减少手输
                          if (picked.text) {
                            setLocatorBy('text')
                            setLocator(String(picked.text))
                          } else if (picked.resource_id) {
                            setLocatorBy('resource_id')
                            setLocator(String(picked.resource_id))
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
                      onClick={() => {
                        void navigator.clipboard?.writeText(locatorExpression)
                        toast.show('表达式已复制')
                      }}
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
                <div className="flex wrap" style={{ gap: 8 }}>
                  <Button
                    kind="primary"
                    size="small"
                    icon="plus"
                    disabled={createTemplateMutation.isPending || !snapshotId || !region || !newLogical.trim()}
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
                    disabled={templatesQuery.isFetching}
                    onClick={() => void templatesQuery.refetch()}
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
                    onClick={() => {
                      void navigator.clipboard?.writeText(locatorExpression)
                      toast.show('表达式已复制')
                    }}
                  >
                    复制 IMAGE 表达式
                  </Button>
                </div>
              </section>
            </>
          )}
        </div>
      </div>

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
