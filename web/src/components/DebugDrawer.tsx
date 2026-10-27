/**
 * 设备调试抽屉（P5）。
 *
 * 数据来源（全部经平台代理到活动调试会话的 vendor viewer）：
 *  - 实时预览：WS /api/v1/ws/debug/{id}，vendor 下发 **JSON 文本帧**
 *    `{kind: 'frame'|'status'|'error', jpeg_base64?, message?}`；不是二进制帧，
 *    所以这里解析 JSON 后把 jpeg_base64 画到 canvas，status/error 显示成状态行。
 *  - 层级树：WS 不带树。点「采集快照」→ POST .../snapshots {with_tree} →
 *    GET .../snapshots/{nid}/tree，vendor 返回 `{nodes: [{index, children: [下标]}]}`。
 *  - 定位验证：POST .../locators/validate，体是 `{target: {by, value}}`，
 *    返回 matches[]（x/y/width/height）。唯一匹配才算通过，vendor 给 passed 字段。
 * 硬约束：
 *  - 会话创建失败 / 端点不可用只显示 Notice + 错误码，不伪造画面；
 *  - 关闭抽屉先 DELETE /debug-sessions/{id} 再清 WS；
 *  - WS 断开（非主动关闭）提示「会话已结束」。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import {
  captureSnapshot,
  closeDebugSession,
  createDebugSession,
  fetchDebugSession,
  fetchSnapshotTree,
  validateLocator,
} from '../api/endpoints'
import type { LocatorMatch, SnapshotTreeNode } from '../api/types'
import { Badge } from './Badge'
import { Button } from './Button'
import { Drawer } from './Dialog'
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

/** 递归渲染层级树（children 存下标，超过 200 层视为脏数据直接停） */
function TreeBranch({
  node,
  depth,
  byIndex,
  onPick,
}: {
  node: SnapshotTreeNode
  depth: number
  byIndex: Map<number, SnapshotTreeNode>
  onPick: (node: SnapshotTreeNode) => void
}) {
  const [open, setOpen] = useState(depth < 2)
  const kids = (node.children ?? [])
    .map((index) => byIndex.get(index))
    .filter((kid): kid is SnapshotTreeNode => Boolean(kid))
  const bounds = nodeBounds(node)
  return (
    <div style={{ paddingLeft: depth ? 14 : 0 }}>
      <div className="flex" style={{ gap: 6, alignItems: 'center' }}>
        {kids.length > 0 && depth < 200 ? (
          <button
            type="button"
            className="link-btn"
            style={{ minWidth: 14 }}
            aria-label={open ? '收起' : '展开'}
            onClick={() => setOpen(!open)}
          >
            {open ? '▾' : '▸'}
          </button>
        ) : (
          <span style={{ minWidth: 14 }} />
        )}
        <button type="button" className="link-btn" onClick={() => onPick(node)} title="选中该节点做定位验证">
          <span className="mono small">{nodeLabel(node)}</span>
          {bounds ? <span className="muted small"> {bounds}</span> : null}
        </button>
      </div>
      {open && depth < 200
        ? kids.map((kid) => (
            <TreeBranch
              key={kid.index}
              node={kid}
              depth={depth + 1}
              byIndex={byIndex}
              onPick={onPick}
            />
          ))
        : null}
    </div>
  )
}

interface DebugDrawerProps {
  open: boolean
  target: DebugTarget | null
  onClose: () => void
  /** 会话建立/释放时上抛，供模板页签等按会话隔离的调用方使用 */
  onSessionChange?: (sessionId: string | number | null) => void
}

export function DebugDrawer({ open, target, onClose, onSessionChange }: DebugDrawerProps) {
  const toast = useToast()
  const queryClient = useQueryClient()

  const [session, setSession] = useState<{ id: string | number } | null>(null)
  const [nodes, setNodes] = useState<SnapshotTreeNode[] | null>(null)
  const [snapshotId, setSnapshotId] = useState<string | null>(null)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [selected, setSelected] = useState<SnapshotTreeNode | null>(null)
  const [locatorBy, setLocatorBy] = useState<LocatorBy>('text')
  const [locator, setLocator] = useState('')
  const [matches, setMatches] = useState<LocatorMatch[] | null>(null)
  const [validateNote, setValidateNote] = useState<string | null>(null)
  const [validateError, setValidateError] = useState<string | null>(null)
  const [wsStatus, setWsStatus] = useState<'idle' | 'connecting' | 'open' | 'closed'>('idle')
  // 重试计数：作为建连 effect 的依赖。不能把 wsStatus 放进依赖——effect 自己
  // setWsStatus('connecting') 会触发重渲染，cleanup 立刻 close 掉刚建的 socket，
  // 表现为握手后 1ms 内 1006 并循环耗尽重试。
  const [wsAttempt, setWsAttempt] = useState(0)
  const [wsNotice, setWsNotice] = useState<string | null>(null)
  const [closeError, setCloseError] = useState<string | null>(null)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  /** 主动关闭标记：区别于服务端断开 */
  const closingRef = useRef(false)
  const wsRef = useRef<WebSocket | null>(null)
  const sessionRef = useRef<string | number | null>(null)
  const wsRetriesRef = useRef(0)

  const reset = useCallback(() => {
    setSession(null)
    wsRetriesRef.current = 0
    setWsAttempt(0)
    setNodes(null)
    setSnapshotId(null)
    setTreeError(null)
    setSelected(null)
    setMatches(null)
    setValidateNote(null)
    setValidateError(null)
    setWsStatus('idle')
    setWsNotice(null)
    setCloseError(null)
  }, [])

  /** open 的 ref 镜像：mutation 回调里读 props 会拿到过期闭包 */
  const openRef = useRef(open)
  openRef.current = open

  /** 打开抽屉 → 创建调试会话 */
  const createMutation = useMutation({
    mutationFn: () => createDebugSession(target!.serial, '定位排查'),
    onSuccess: (created) => {
      if (!openRef.current) {
        // 创建请求在途时抽屉已被关掉：立即释放，否则留下孤儿 active 会话占住设备租约
        void closeDebugSession(created.id).catch(() => undefined)
        return
      }
      setSession({ id: created.id })
      sessionRef.current = created.id
    },
    onError: (error) => {
      const described = describeError(error)
      setWsNotice('调试会话创建失败（' + described.code + '）：' + described.message)
    },
  })

  /** 打开抽屉 → 自动创建调试会话（否则停留在空态，没有任何入口能发起） */
  const createPendingRef = useRef(false)
  useEffect(() => {
    if (!open) {
      createPendingRef.current = false
      return
    }
    if (session || createPendingRef.current) return
    createPendingRef.current = true
    createMutation.mutate()
    // 只跟随 open 变化；session/mutation 状态用 ref 与守卫读取，避免重渲染反复建会话
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

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
        drawFrame(canvasRef.current, message.jpeg_base64)
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

  /** open 转 false 的兜底：抽屉仍挂载、但父组件清掉了 target（或任何不经
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
      return { snapshotId: captured.snapshot_id, tree }
    },
    onSuccess: ({ snapshotId: capturedId, tree }) => {
      setSnapshotId(capturedId)
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

  const validateMutation = useMutation({
    mutationFn: () => {
      const id = sessionRef.current
      if (id === null) throw new Error('缺少调试会话')
      if (!locator.trim()) throw new Error('定位值不能为空')
      return validateLocator(id, { by: locatorBy, value: locator.trim() })
    },
    onSuccess: (result) => {
      setValidateError(null)
      const list = Array.isArray(result?.matches) ? result.matches : []
      setMatches(list)
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

  const detailError = detailQuery.isError ? describeError(detailQuery.error) : null
  /** 上游不可达（viewer 未起）与无活动会话给出更具体的提示 */
  const upstreamHint = (error: ReturnType<typeof describeError> | null): string | null => {
    if (!error) return null
    if (error.code === 'viewer_unavailable') return 'viewer 上游不可达：runner 可能尚未起 viewer 或已退出。'
    if (error.code === 'debug_session_not_active') return '调试会话尚未激活，等 runner 回报端口后重试。'
    return null
  }

  return (
    <Drawer
      open={open}
      onClose={handleClose}
      title={target ? target.label + ' · 调试' : '设备调试'}
      description={target ? 'serial ' + target.serial : undefined}
      footer={
        <>
          <Button onClick={handleClose} disabled={closeMutation.isPending}>
            {closeMutation.isPending ? '正在关闭…' : '关闭会话'}
          </Button>
        </>
      }
      footHint="关闭抽屉会同时关闭调试会话并释放资源租约"
    >
      {!target ? null : (
        <>
          {wsNotice ? (
            <div className="mb">
              <Notice tone="amber" title="调试会话">
                {wsNotice}
              </Notice>
            </div>
          ) : null}
          {closeError ? (
            <div className="mb">
              <Notice tone="red" title="关闭失败">
                {closeError}
              </Notice>
            </div>
          ) : null}

          {!session && !createMutation.isPending && !wsNotice ? (
            <Empty
              icon="phone"
              title="尚未建立调试会话"
              description="POST /api/v1/debug-sessions 建立会话后，这里展示实时预览与快照树。"
            />
          ) : null}
          {createMutation.isPending ? (
            <Empty icon="phone" title="正在创建调试会话" description="正在请求 POST /api/v1/debug-sessions" />
          ) : null}

          {session ? (
            <div className="debug-grid">
              {/* 栏一：实时预览 */}
              <div>
                <div className="flex" style={{ gap: 8, marginBottom: 6 }}>
                  <strong className="small">实时预览</strong>
                  <Badge tone={wsStatus === 'open' ? 'green' : wsStatus === 'connecting' ? 'blue' : 'gray'} dot>
                    {wsStatus === 'open' ? '已连接' : wsStatus === 'connecting' ? '连接中' : '未连接'}
                  </Badge>
                </div>
                <canvas ref={canvasRef} className="debug-canvas" aria-label="设备画面预览" />
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
              </div>

              {/* 栏二：快照层级树 */}
              <div>
                <div className="flex" style={{ gap: 8, alignItems: 'center' }}>
                  <strong className="small">快照层级树</strong>
                  <Button
                    size="small"
                    icon="image"
                    disabled={snapshotMutation.isPending}
                    onClick={() => snapshotMutation.mutate()}
                  >
                    {snapshotMutation.isPending ? '采集中…' : '采集快照'}
                  </Button>
                </div>
                {snapshotId ? (
                  <div className="muted small mono" style={{ marginTop: 4 }}>
                    snapshot {snapshotId}
                  </div>
                ) : null}
                {treeError ? (
                  <div className="mt">
                    <Notice tone="red" title="快照 / 层级树获取失败">{treeError}</Notice>
                  </div>
                ) : null}
                <div className="debug-tree mt">
                  {nodes === null ? (
                    <span className="muted small">
                      点「采集快照」后展示 vendor 采集的层级树（POST /snapshots → GET /tree）。
                    </span>
                  ) : nodes.length === 0 ? (
                    <span className="muted small">该快照没有 UI 树（vendor 未采集或设备不支持）。</span>
                  ) : (
                    tree.roots.map((node) => (
                      <TreeBranch
                        key={node.index}
                        node={node}
                        depth={0}
                        byIndex={tree.byIndex}
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
              </div>

              {/* 栏三：定位验证 */}
              <div>
                <strong className="small">定位验证</strong>
                <div className="mt" style={{ display: 'grid', gap: 8 }}>
                  <div className="muted small">
                    选中节点：
                    {selected ? (
                      <span className="mono">
                        {' '}
                        {nodeLabel(selected)}
                        {nodeBounds(selected) ? ' ' + nodeBounds(selected) : ''}
                      </span>
                    ) : (
                      ' 未选择（在层级树中点击节点）'
                    )}
                  </div>
                  <label className="small">
                    定位方式
                    <select
                      className="search"
                      style={{ width: '100%' }}
                      value={locatorBy}
                      onChange={(event) => setLocatorBy(event.target.value as LocatorBy)}
                    >
                      {LOCATOR_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="small">
                    定位值
                    <input
                      className="search"
                      style={{ width: '100%' }}
                      value={locator}
                      onChange={(event) => setLocator(event.target.value)}
                      placeholder={locatorBy === 'image' ? '模板逻辑名，如 buttons/confirm.png' : '文本 / resource-id / xpath'}
                    />
                  </label>
                  <Button
                    kind="primary"
                    size="small"
                    icon="check"
                    disabled={!locator.trim() || validateMutation.isPending}
                    onClick={() => validateMutation.mutate()}
                  >
                    {validateMutation.isPending ? '验证中…' : '验证定位'}
                  </Button>
                  {validateError ? (
                    <Notice tone="red" title="验证失败">{validateError}</Notice>
                  ) : null}
                  {matches !== null && !validateError ? (
                    matches.length === 0 ? (
                      <span className="muted small">{validateNote ?? '无匹配节点'}</span>
                    ) : (
                      <>
                        <span className="muted small">{validateNote}</span>
                        <div className="table-wrap">
                          <table className="task-table" aria-label="定位验证结果">
                            <thead>
                              <tr>
                                <th>#</th>
                                <th>x</th>
                                <th>y</th>
                                <th>宽</th>
                                <th>高</th>
                              </tr>
                            </thead>
                            <tbody>
                              {matches.map((match, index) => (
                                <tr key={index}>
                                  <td>{index + 1}</td>
                                  <td className="mono">{match.x ?? DASH}</td>
                                  <td className="mono">{match.y ?? DASH}</td>
                                  <td className="mono">{match.width ?? DASH}</td>
                                  <td className="mono">{match.height ?? DASH}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </Drawer>
  )
}

/** 把 vendor 的 base64 JPEG 帧画到 canvas；解码失败保留上一帧 */
function drawFrame(canvas: HTMLCanvasElement | null, base64: string): void {
  if (!canvas) return
  const image = new Image()
  image.onload = () => {
    canvas.width = image.naturalWidth
    canvas.height = image.naturalHeight
    const ctx = canvas.getContext('2d')
    ctx?.drawImage(image, 0, 0)
  }
  image.src = 'data:image/jpeg;base64,' + base64
}
