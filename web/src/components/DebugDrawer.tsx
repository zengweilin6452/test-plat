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
  fetchSnapshotImage,
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
import {
  CropVerification,
  DebugTarget,
  LocatorBy,
  buildTreeIndex,
  controlAvailability,
  copyExpression,
  cropSelectionEnabled,
  FrameSize,
  Region,
  cropVerificationKey,
  gestureMessage,
  locatorValueForNode,
  normalizeStagePoint,
  preferredLocator,
  resolveCropVerification,
  shouldSendGestureMove,
  toWorkspaceTarget,
  drawFrame,
  WS_CONNECT_RETRIES,
  WS_RETRY_DELAY_MS,
  drawSnapshotImage,
  normalizeRegion,
  nodeBounds,
  LOCATOR_OPTIONS,
  editRegion,
  initialOpenTreeSet,
  nodeOverlayRegion,
  stageViewBadge,
  treeNavAction,
  visibleTreeRows,
} from './debug/debugModel'
import { TreeBranch } from './debug/TreeBranch'
export type { ControlAvailabilityInput } from './debug/debugModel'
export type { CropVerification } from './debug/debugModel'
export type { DebugTarget } from './debug/debugModel'
export type { LocatorBy } from './debug/debugModel'
export { buildTreeIndex } from './debug/debugModel'
export { controlAvailability } from './debug/debugModel'
export { copyExpression } from './debug/debugModel'
export { cropSelectionEnabled } from './debug/debugModel'
export { cropVerificationKey } from './debug/debugModel'
export { gestureMessage } from './debug/debugModel'
export { hasNodeIdentity } from './debug/debugModel'
export { locatorValueForNode } from './debug/debugModel'
export { nodeLabel } from './debug/debugModel'
export { normalizeStagePoint } from './debug/debugModel'
export { initialOpenTreeSet } from './debug/debugModel'
export { nodeOverlayRegion } from './debug/debugModel'
export { preferredLocator } from './debug/debugModel'
export { resolveCropVerification } from './debug/debugModel'
export { shouldSendGestureMove } from './debug/debugModel'
export { stageViewBadge } from './debug/debugModel'
export { toWorkspaceTarget } from './debug/debugModel'
export { treeNavAction } from './debug/debugModel'
export { visibleTreeRows } from './debug/debugModel'


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
  /** 聚焦投屏：隐藏两侧检查面板，画面按视口高度放大（审查 F2）。状态由页面持有 */
  focus?: boolean
  onFocusChange?: (next: boolean) => void
}

export function DebugDrawer({ open, target, devices, onTargetChange, onClose, onSessionChange, focus = false, onFocusChange }: DebugDrawerProps) {
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
  /** 本次「转实时」以来是否真实绘制过新帧（F1：恢复/重连后旧图不冒充新帧） */
  const [liveFrameSeen, setLiveFrameSeen] = useState(false)
  /** 最近一帧距今秒数（被动提示，不判故障；持续断流需可控复现后再定） */
  const [previewStaleSec, setPreviewStaleSec] = useState<number | null>(null)
  /** 树的受控展开集合与 roving tabindex 焦点行（审查 F5） */
  const [openNodes, setOpenNodes] = useState<Set<number>>(() => new Set())
  const [treeFocus, setTreeFocus] = useState<number | null>(null)

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
  /** 最近一次真实绘制帧的时间戳（被动「N 秒未更新」提示用） */
  const lastFrameAtRef = useRef<number | null>(null)
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
    setPreviewStaleSec(null)
    setLiveFrameSeen(false)
    lastFrameAtRef.current = null
    previewFrameCountRef.current = 0
    setOpenNodes(new Set())
    setTreeFocus(null)
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
    // closed/lost 是终态，继续轮询只会空转——恢复入口是「重建会话」。
    refetchInterval: (query) => {
      const state = query.state.data?.state
      return state && state !== 'active' && state !== 'closed' && state !== 'lost' ? 1500 : false
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

  /**
   * Esc 关闭（原先是原生 <dialog> 自带的行为）。
   * 打开的确认框/对话框优先消费 Esc（原生 dialog 自带关闭），不连带销毁调试会话；
   * 输入控件聚焦时（如定位符输入框打字按 Esc）也不销毁会话。
   */
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (document.querySelector('dialog[open]')) return
      const target = event.target as HTMLElement | null
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return
      }
      handleClose()
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
        }, () => frozenRef.current)
        previewFrameCountRef.current += 1
        lastFrameAtRef.current = Date.now()
        setLiveFrameSeen(true)
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
    socket.onclose = (event) => {
      wsRef.current = null
      setWsStatus('closed')
      if (closingRef.current) return
      // 平台是 accept 之后再校验会话：4403/4404 的拒绝也会先触发 onopen，
      // 把重试计数清零——「重试耗尽」永远等不到，终态判定必须直接看关闭码。
      // （opening 会话没有 ws_path，这个 socket 连不上，不会误伤正常建连。）
      const code = typeof event?.code === 'number' ? event.code : 1000
      const cachedState = detailQuery.data?.state
      if ((code === 4403 || code === 4404) && cachedState && cachedState !== 'opening') {
        // 会话激活后被拒（已关闭，或后端重启丢了 viewer 端口表）：重连救不了。
        // 探一次 detail，closed 终态的「重建会话」入口靠这次 refetch 浮出来。
        setWsNotice('连接已断开：会话已结束或采集服务失效，可重建会话或返回设备池重试。')
        void queryClient.refetchQueries({ queryKey: ['debug-session', sessionRef.current] })
        return
      }
      // 会话刚创建时 runner 还在拉起 viewer（state=opening），平台会立刻拒绝 WS。
      // 有限次退避重连，成功即清零；耗尽后才告知断开。
      if (sessionRef.current !== null && wsRetriesRef.current < WS_CONNECT_RETRIES) {
        wsRetriesRef.current += 1
        window.setTimeout(() => {
          setWsStatus('idle')
          // 重连窗口里旧帧不得再标「实时画面」：等真正画出新帧再翻绿
          setLiveFrameSeen(false)
          setWsAttempt((n) => n + 1)
        }, WS_RETRY_DELAY_MS)
        return
      }
      // 服务端关闭（会话结束 / 1000），明确提示而不是静默黑屏
      setWsNotice('连接已断开：会话已结束')
      // detailQuery 在 active 后就停轮了，会话后端侧被关（runner 死/平台重启）
      // 前端不会自己知道——重试耗尽说明媒体通道救不了，主动探一次会话状态，
      // closed 终态的「重建会话」入口就靠这次 refetch 浮出来。
      void queryClient.refetchQueries({ queryKey: ['debug-session', sessionRef.current] })
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
    // 依赖 state 字符串而非 data 对象：refetch 换新对象不触发重连，只有状态
    // 真变化（opening→active / →closed）才重跑。onclose 里的 cachedState 读它。
  }, [open, session, detailQuery.data?.ws_path, detailQuery.data?.state, wsAttempt, previewMode])

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

  /** 采集快照 + 层级树 + 同一快照的图片 */
  const snapshotMutation = useMutation({
    mutationFn: async () => {
      const id = sessionRef.current
      if (id === null) throw new Error('缺少调试会话')
      const captured = await captureSnapshot(id, true)
      if (!captured.snapshot_id) throw new Error('快照响应缺少 snapshot_id')
      // 树和画面必须来自同一个 snapshot_id：只冻结实时流会把错帧当成快照展示
      const [tree, image] = await Promise.all([
        fetchSnapshotTree(id, captured.snapshot_id),
        fetchSnapshotImage(id, captured.snapshot_id),
      ])
      return {
        sessionId: id,
        snapshotId: captured.snapshot_id,
        tree,
        image,
      }
    },
    onSuccess: async ({ sessionId: capturedSession, snapshotId: capturedId, tree, image }) => {
      if (sessionRef.current !== capturedSession) return
      // 先冻结 ref 再解码：解码期间到达的实时帧（含已排队的 onload）不得覆盖快照
      frozenRef.current = true
      let size: FrameSize
      try {
        size = await drawSnapshotImage(canvasRef.current, image)
      } catch (error) {
        frozenRef.current = false
        setFrozen(false)
        const described = describeError(error)
        setTreeError('快照画面加载失败（' + described.code + '）：' + described.message)
        return
      }
      if (sessionRef.current !== capturedSession) return
      setSnapshotId(capturedId)
      setSnapshotSize(size)
      setFrozen(true)
      setTreeError(null)
      const list = Array.isArray(tree?.nodes) ? tree.nodes : []
      setNodes(list)
      // 新快照重置展开状态（默认展开前两层）与键盘焦点行，不跨快照残留
      const index = buildTreeIndex(list)
      setOpenNodes(initialOpenTreeSet(index.roots, index.byIndex))
      setTreeFocus(list[0]?.index ?? null)
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
  /** 终态会话（closed/lost）：媒体通道重连救不了，唯一出口是重建会话。 */
  const sessionClosed = detailQuery.data?.state === 'closed' || detailQuery.data?.state === 'lost'
  const closeReason = detailQuery.data?.close_reason ?? null

  /** close_reason → 可行动文案；未知原因如实带上原值。 */
  const closeReasonText = useCallback((reason: string | null) => {
    const known: Record<string, string> = {
      local_lease_busy:
        '设备被另一个调试进程占用（多为平台重启残留的旧会话进程；稍候再试或重启平台）',
      spawn_failed: '采集服务（runner）启动失败',
      client_closed: '会话已被关闭（本页或其他页面操作）',
      runner_exit: '采集服务已退出',
    }
    if (!reason) return '会话已结束，请重建会话。'
    return known[reason] ?? ('会话已结束（原因：' + reason + '）')
  }, [])

  // ------------------------------------------------------------ 预览传输（H.264 → JPEG 回退）
  /** 手动重连实时画面：清退避计数、按当前传输模式重开通道，不必拆掉整个会话。
   * 自动重连有 30s 上限（WS_CONNECT_RETRIES），租约过期/通道僵死时这是唯一出口。 */
  const reconnectLive = useCallback(() => {
    setWsNotice(null)
    setPreviewNote(null)
    setWsStatus('idle')
    wsRetriesRef.current = 0
    // 重连期间旧帧不再标「实时画面」；画出新帧后由帧回调翻回
    setLiveFrameSeen(false)
    setWsAttempt((n) => n + 1)
  }, [])

  /** 终态/僵死会话就地重建：先尽力 DELETE 旧会话再走与自动建会话相同的
   * 创建路径，不必「返回设备池再进」。DELETE 对终态是幂等空操作；对
   * 「行仍 active 但通道已死」（runner 悄悄死掉）则释放租约并按命令行
   * 杀掉孤儿 runner——跳过这步直接建，新 runner 会 DeviceBusy 秒关。
   * 不能用 createPendingRef 做入口守卫：初始自动建会话成功后它一直是 true。 */
  const recreatePendingRef = useRef(false)
  const recreateSession = useCallback(async () => {
    if (!target?.serial || recreatePendingRef.current || createMutation.isPending) return
    recreatePendingRef.current = true
    try {
      const staleId = sessionRef.current
      sessionRef.current = null
      teardownSocket()
      reset()
      if (staleId !== null) {
        try {
          await closeDebugSession(staleId)
        } catch {
          // 旧会话关闭失败不拦重建：新会话若真被旧租约挡住，409 会自己上屏
        }
      }
      createMutation.mutate()
    } finally {
      recreatePendingRef.current = false
    }
  }, [createMutation, reset, target?.serial, teardownSocket])
  useEffect(() => {
    if (!open || !session) return
    const choice = choosePreviewTransport(typeof VideoDecoder !== 'undefined')
    if (choice.mode === 'jpeg' && previewMode !== 'jpeg') {
      setPreviewMode('jpeg')
      setPreviewNote(choice.reason)
      setLiveFrameSeen(false)
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
        lastFrameAtRef.current = Date.now()
        setLiveFrameSeen(true)
        setFrameSize((prev) => (prev && prev.w === size.w && prev.h === size.h ? prev : size))
      },
      onError: (code, message) => {
        if (code === 'closed-4429') {
          // 视频信道每会话限一个客户端：另一个页面（或僵死的旧连接）正占着画面。
          setWsNotice('该会话的视频画面已在另一个页面打开；关闭那边的调试工作区后点「重新连接」。')
          setPreviewMode('jpeg')
          setPreviewFps(null)
          setLiveFrameSeen(false)
          setWsStatus('closed')
          return
        }
        if (code === 'closed-4403' || code === 'closed-4404' || code === 'closed-4450') {
          // 平台明确说会话不在/未就绪/视频上游死了：本地可能已过期（active 后
          // 停轮），探一次 detail 让终态与「重建会话」入口浮出来。
          void queryClient.refetchQueries({ queryKey: ['debug-session', sessionRef.current] })
        }
        if (code === 'closed-4450') {
          // 平台到 viewer 的视频通道没起来（runner/viewer 已失效）：重连救不了。
          // 行仍 active 时按钮还是「重新连接」，如实告诉用户它救不了。
          setWsNotice('视频通道不可用（设备采集服务已失效）；请点「返回设备池」重新进入调试。')
          setPreviewMode('jpeg')
          setPreviewFps(null)
          setLiveFrameSeen(false)
          setWsStatus('closed')
          return
        }
        setPreviewNote('H.264 不可用，已回退 JPEG（' + code + '：' + message + '）')
        setPreviewMode('jpeg')
        setPreviewFps(null)
        setLiveFrameSeen(false)
        setWsStatus('closed')
      },
    })
    h264PlayerRef.current = player
    player.open()
    return () => {
      player.close()
      if (h264PlayerRef.current === player) h264PlayerRef.current = null
    }
  }, [open, session, previewMode, sessionActive, wsAttempt])

  useEffect(() => {
    if (!open || previewMode !== 'h264') return
    const timer = window.setInterval(() => {
      setPreviewFps(previewFrameCountRef.current)
      previewFrameCountRef.current = 0
      // 被动信息：连接保持着但帧停了（画面可能未更新）。只提示不暂停——
      // 静态画面是否持续发帧取决于真机编码器策略，需可控断流复现后再定。
      const last = lastFrameAtRef.current
      setPreviewStaleSec(last === null ? null : Math.max(0, Math.floor((Date.now() - last) / 1000)))
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
        return
      }
      if (message?.kind === 'ended') {
        // vendor 手势信道按设计一次手势一条连接：end/cancel 或 2s 无消息都会
        // ended + 关闭（viewer app.py idle-timeout）。下一次 pointerdown 会
        // 重新开信道（handleControlPointerDown → openGesture），这里本地静默
        // 收尾，不走 onclose，也不退出操控——关连接不是故障。
        closeGestureSocket()
      }
    }
    // 只有手势进行中断连才值得提示：vendor 侧已尽力补 UP（_cleanup），
    // 本地中止拖动即可；操控保持启用，下一次按下画面会自动重开手势信道。
    // 正常生命周期（ended/idle-timeout）已在 onmessage 里静默关闭，不进这里。
    ws.onclose = (event) => {
      if (gestureWsRef.current !== ws) return
      gestureWsRef.current = null
      if (pointerStartRef.current) {
        pointerStartRef.current = null
        setTouchDot(null)
        const code = typeof event?.code === 'number' ? event.code : 1006
        setControlError(
          '手势进行中通道中断（' + code + '），该次拖动已中止；再次按下画面会自动重连手势通道',
        )
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
      if (!snapshotId) throw new Error('先「冻结并检查」，模板只能从快照裁剪')
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
      toast.show('模板已登记：' + record.logical + '（v' + String(record.version_id ?? '').slice(0, 8) + '）', 'success')
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

  /** F1：画面徽标状态机（会话/连接/首帧/冻结共同决定，断线后旧图不标实时） */
  const stageView = useMemo(
    () =>
      stageViewBadge({
        frozen,
        sessionClosed,
        wsOpen: wsStatus === 'open',
        hasFrame: frameSize !== null,
        liveFrameSeen,
      }),
    [frozen, sessionClosed, wsStatus, frameSize, liveFrameSeen],
  )
  /** F5：选中节点的画面边框（蓝框，与定位命中绿框/框选橙框语义区分） */
  const selectedRegion = useMemo(
    () => (frozen && selected ? nodeOverlayRegion(selected) : null),
    [frozen, selected],
  )
  /** F5：当前展开状态下实际渲染的树行（键盘导航的基准顺序） */
  const visibleRows = useMemo(
    () => visibleTreeRows(tree.roots, tree.byIndex, openNodes),
    [tree, openNodes],
  )
  /** 拾取节点：选中 + 填充定位候选 + roving tabindex 同步 */
  const pickTreeNode = useCallback((node: SnapshotTreeNode) => {
    setSelected(node)
    setTreeFocus(node.index)
    // 选中节点时把它的标识直接填进定位值，减少手输；
    // resource-id 优先于 text（文案会变，id 更稳）
    const preferred = preferredLocator(node)
    if (preferred) {
      setLocatorBy(preferred.by)
      setLocator(preferred.value)
    }
  }, [])
  /** 树行键盘事件：Enter 选中；方向键在可见行上导航（展开/折叠/回父级） */
  const handleTreeKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>, node: SnapshotTreeNode) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        pickTreeNode(node)
        return
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
      event.preventDefault()
      const action = treeNavAction(visibleRows, node, event.key, openNodes, tree.byIndex, tree.parentOf)
      if (!action) return
      if (action.toggle !== undefined) {
        setOpenNodes((prev) => {
          const next = new Set(prev)
          if (next.has(action.toggle!)) next.delete(action.toggle!)
          else next.add(action.toggle!)
          return next
        })
      }
      if (action.focus !== null) {
        setTreeFocus(action.focus)
        const row = document.querySelector<HTMLElement>('[data-tree-index="' + action.focus + '"]')
        row?.focus()
      }
    },
    [pickTreeNode, visibleRows, openNodes, tree],
  )

  // F6 状态口径统一：已连接 / 连接中 / 已断开（idle 是还没开始连，仍叫未连接）
  const wsText =
    wsStatus === 'open' ? '已连接'
      : wsStatus === 'connecting' ? '连接中'
        : wsStatus === 'closed' ? '已断开'
          : '未连接'

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
    <div className={'debug-workspace' + (focus ? ' focus' : '')} aria-label={target ? target.label + ' · 调试' : '设备调试'}>
      {/* 原型 inspectorPage：定位方式切换器在 toolbar 之前，独立一行 */}
      <div className="flex wrap mb" role="group" aria-label="调试模式">
        {([['native', '原生节点'], ['image', '图像框选']] as const).map(([value, label]) => (
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
            {/* 选中态用 ✓ 前缀做非颜色标识：强制颜色/高对比下不靠背景色也能辨认（审查 F7） */}
            {inspectMode === value ? '✓ ' : ''}{label}
          </Button>
        ))}
        <span className="small muted">
          {inspectMode === 'native'
            ? '冻结画面后点击树节点拾取元素；验证定位会实时采集画面校验。'
            : '在冻结画面上框选区域并登记为模板；匹配验证由服务端校验。'}
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
              } catch {
                // 关闭旧会话失败：不静默中止——用户换了设备却毫无反应会以为页面坏了
                toast.show('关闭当前调试会话失败，已保留原设备会话；可稍后重试切换。', 'error')
                return
              }
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
        {/* 聚焦投屏：两侧检查面板收起、画面按视口高度放大（审查 F2）；快照与选中不丢失 */}
        <Button
          size="small"
          aria-pressed={focus}
          onClick={() => onFocusChange?.(!focus)}
        >
          {focus ? '✓ 展开检查' : '聚焦投屏'}
        </Button>
        {frozen ? (
          <Button
            size="small"
            icon="play"
            disabled={sessionClosed || validateMutation.isPending || cropValidation.isPending || createTemplateMutation.isPending}
            title={sessionClosed ? '会话已结束，旧画面不再代表设备状态；请先重建会话' : undefined}
            onClick={() => {
              // socket 一直活着，恢复后下一帧就会覆盖 canvas
              clearInspection()
              setSnapshotId(null)
              setSnapshotSize(null)
              setNodes(null)
              setTreeError(null)
              // F1：恢复后旧图不再冒充新帧，画出新帧才翻回「实时画面」
              setLiveFrameSeen(false)
              frozenRef.current = false
              setFrozen(false)
            }}
          >
            恢复实时
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
            {snapshotMutation.isPending ? '冻结中…' : '冻结并检查'}
          </Button>
        )}
      </div>

      <div className="debug-workspace-body">
        {sessionClosed ? (
          // F4：终态只有一条主提示，恢复动作（重建会话）就在提示内；
          // 关闭码/传输细节收进可展开详情，不再三条提示重复刷屏。
          <div className="mb">
            <Notice tone="red" title="调试会话已结束">
              {closeReasonText(closeReason)}点「重建会话」可就地重新开始，不必返回设备池。
              <div className="flex" style={{ marginTop: 8 }}>
                <Button
                  size="small"
                  kind="primary"
                  onClick={() => void recreateSession()}
                  disabled={createMutation.isPending}
                >
                  {createMutation.isPending ? '重建中…' : '重建会话'}
                </Button>
              </div>
              {wsNotice || previewNote ? (
                <details className="notice-details">
                  <summary>连接与传输详情</summary>
                  {wsNotice ? <div>媒体通道：{wsNotice}</div> : null}
                  {previewNote ? <div>传输：{previewNote}</div> : null}
                </details>
              ) : null}
            </Notice>
          </div>
        ) : wsNotice ? (
          <div className="mb">
            <Notice tone="amber" title="调试会话">
              {wsNotice}
              {wsStatus !== 'open' ? (
                <div className="flex" style={{ marginTop: 8 }}>
                  <Button size="small" onClick={reconnectLive}>重新连接</Button>
                </div>
              ) : null}
            </Notice>
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
        {!sessionClosed && previewMode === 'jpeg' && previewNote ? (
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
              {/* F1：标签由会话/连接/首帧/冻结共同决定，断线后的旧图不再标「实时画面」 */}
              <Badge tone={stageView.tone} dot>{stageView.label}</Badge>
              <span className="flex" style={{ gap: 8 }}>
                <span className="small muted">
                  {frozen
                    ? '已暂停预览'
                    : previewMode === 'h264'
                      ? 'H.264 · ' + (wsStatus === 'open' ? (previewFps ?? 0) + 'fps' : wsText) +
                        (wsStatus === 'open' && (previewStaleSec ?? 0) >= 5
                          ? ' · 画面 ' + previewStaleSec + ' 秒未更新'
                          : '')
                      : 'JPEG · ' + wsText}
                </span>
                {sessionClosed ? (
                  // 终态会话的媒体通道已无东西可连：给重建入口而不是无效的「重新连接」
                  <Button size="small" onClick={recreateSession} disabled={createMutation.isPending}>
                    {createMutation.isPending ? '重建中…' : '重建会话'}
                  </Button>
                ) : wsStatus !== 'open' ? (
                  <Button size="small" onClick={reconnectLive}>
                    重新连接
                  </Button>
                ) : null}
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
                  {/* F1：断线/终态后旧图明确标记过期，盖在画面上不挡操作 */}
                  {stageView.stale && stageView.staleNote ? (
                    <div className="debug-stage-stale" role="status">{stageView.staleNote}</div>
                  ) : null}
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
                  {/* F5：当前选中节点的蓝框（不是定位验证结果） */}
                  {selectedRegion && coordinateSize ? (
                    <div
                      className="debug-box node-pick"
                      style={{
                        left: (selectedRegion.x / coordinateSize.w) * 100 + '%',
                        top: (selectedRegion.y / coordinateSize.h) * 100 + '%',
                        width: (selectedRegion.w / coordinateSize.w) * 100 + '%',
                        height: (selectedRegion.h / coordinateSize.h) * 100 + '%',
                      }}
                    >
                      <span>选中</span>
                    </div>
                  ) : null}
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
                  : controlState.reason ?? '直接操控未启用 · 点工具栏「直接操控」'}
              </span>
              <Button
                size="small"
                disabled={!controlEnabled}
                title={controlEnabled ? undefined : controlState.reason ?? '先启用直接操控'}
                onClick={() => void handleControlKey('back')}
              >
                返回
              </Button>
              <Button
                size="small"
                disabled={!controlEnabled}
                title={controlEnabled ? undefined : controlState.reason ?? '先启用直接操控'}
                onClick={() => void handleControlKey('home')}
              >
                主页
              </Button>
            </div>
            <div className="between small muted phone-meta-row">
              <span>{snapshotId ? '快照 ' + snapshotId : frozen ? '快照待采集' : '设备画面未冻结'}</span>
              <span>{deviceResolution}</span>
            </div>
            <div className="debug-kv" style={{ marginTop: 8 }}>
              <span>绿框 = 最近一次定位命中</span>
              <span>蓝框 = 当前选中节点</span>
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
                        onPick={pickTreeNode}
                        onKeyDown={handleTreeKeyDown}
                        selectedIndex={selected?.index ?? null}
                        focusIndex={treeFocus ?? visibleRows[0]?.index ?? null}
                        onFocusRow={setTreeFocus}
                        openSet={openNodes}
                        onToggle={(index) => {
                          setOpenNodes((prev) => {
                            const next = new Set(prev)
                            if (next.has(index)) next.delete(index)
                            else next.add(index)
                            return next
                          })
                        }}
                      />
                    ))
                  )}
                </div>
                <div className="tree-foot small muted">
                  {frozen && snapshotId
                    ? '已绑定同一次冻结快照，点击节点查看定位描述。'
                    : '先点击「冻结并检查」，采集画面与 UI 树。'}
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
                      description={frozen ? '在层级树中点击节点，这里显示其属性与定位候选。' : '先点击「冻结并检查」采集画面与 UI 树。'}
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
                        onChange={(event) => {
                          const nextBy = event.target.value as LocatorBy
                          setLocatorBy(nextBy)
                          // 切换定位方式时按选中节点生成该形态的定位值：
                          // u2 selector 需要 JSON、xpath 需要表达式，直接沿用
                          // 上一形态的原文会被 vendor 判 InvalidTarget。
                          setLocator(locatorValueForNode(nextBy, selected))
                        }}
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
                        placeholder={
                          locatorBy === 'image'
                            ? '模板逻辑名，如 buttons/confirm.png'
                            : locatorBy === 'u2_selector'
                              ? 'JSON，如 {"text": "登录"}'
                              : '文本 / resource-id / xpath'
                        }
                      />
                      {locatorBy === 'u2_selector' ? (
                        <span className="field-hint">u2 selector 需为 JSON object（resourceId/text/description/className 等白名单字段）；选中节点后切换会自动生成</span>
                      ) : null}
                      {locatorBy === 'xpath' ? (
                        <span className="field-hint">xpath 为表达式（如 //TextView[@text='首页']）；选中节点后切换会自动生成</span>
                      ) : null}
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
                  {snapshotId ? '在冻结画面上拖拽框选，或填写坐标。' : '先点击「冻结并检查」冻结画面。'}
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
                  <span>模板文件名（.png，如 buttons/confirm.png）</span>
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
          点击/拖动左侧真机画面即可操作设备；冻结画面、切到图像框选模式或关闭会话会自动退出。
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
