/**
 * 设备调试抽屉（P5）。
 *
 * 三栏：预览 canvas（WS /api/v1/ws/debug/{id}）+ 层级树 + 定位验证表单。
 * WS 帧约定（api-design.md §3.2，双向透传 vendor 帧）：
 *  - binary 帧 → 图像 Blob → createObjectURL 绘制到 canvas；
 *  - text(json) 帧 → 控制消息；带 tree 字段时刷新快照层级树。
 * 硬约束：
 *  - 会话创建失败 / 端点 404 时显示 Notice + 错误码，不伪造画面；
 *  - 关闭抽屉先 DELETE /debug-sessions/{id} 再清 WS；
 *  - WS 断开（非主动关闭）提示「会话已结束」。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { closeDebugSession, createDebugSession, fetchDebugSession, validateLocator } from '../api/endpoints'
import type { LocatorMatch } from '../api/types'
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

/** 快照树节点：字段名宽松匹配（node_id / id、children 等），缺失显示破折号 */
export interface TreeNode {
  id?: string | number
  label?: string
  cls?: string
  bounds?: string
  children?: TreeNode[]
  [key: string]: unknown
}

function readTree(payload: unknown): TreeNode | null {
  if (!payload || typeof payload !== 'object') return null
  const bag = payload as Record<string, unknown>
  const raw = bag.tree ?? bag.root ?? bag.snapshot ?? payload
  if (raw && typeof raw === 'object') return raw as TreeNode
  return null
}

function nodeLabel(node: TreeNode): string {
  const text = node.label ?? node.cls ?? node.id
  return text === undefined || text === null ? DASH : String(text)
}

/** 递归渲染层级树 */
function TreeBranch({ node, depth, onPick }: { node: TreeNode; depth: number; onPick: (n: TreeNode) => void }) {
  const [open, setOpen] = useState(depth < 2)
  const kids = Array.isArray(node.children) ? node.children : []
  return (
    <div style={{ paddingLeft: depth ? 14 : 0 }}>
      <div className="flex" style={{ gap: 6, alignItems: 'center' }}>
        {kids.length > 0 ? (
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
          {node.bounds ? <span className="muted small"> {node.bounds}</span> : null}
        </button>
      </div>
      {open ? kids.map((kid, index) => (
        <TreeBranch key={kid.id ?? index} node={kid} depth={depth + 1} onPick={onPick} />
      )) : null}
    </div>
  )
}

interface DebugDrawerProps {
  open: boolean
  target: DebugTarget | null
  onClose: () => void
}

export function DebugDrawer({ open, target, onClose }: DebugDrawerProps) {
  const toast = useToast()
  const queryClient = useQueryClient()

  const [session, setSession] = useState<{ id: string | number } | null>(null)
  const [snapshot, setSnapshot] = useState<TreeNode | null>(null)
  const [selected, setSelected] = useState<TreeNode | null>(null)
  const [locator, setLocator] = useState('')
  const [matches, setMatches] = useState<LocatorMatch[] | null>(null)
  const [validateError, setValidateError] = useState<string | null>(null)
  const [wsStatus, setWsStatus] = useState<'idle' | 'connecting' | 'open' | 'closed'>('idle')
  const [wsNotice, setWsNotice] = useState<string | null>(null)
  const [closeError, setCloseError] = useState<string | null>(null)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  /** 主动关闭标记：区别于服务端断开 */
  const closingRef = useRef(false)
  const wsRef = useRef<WebSocket | null>(null)
  const sessionRef = useRef<string | number | null>(null)
  const objectUrlRef = useRef<string | null>(null)

  const reset = useCallback(() => {
    setSession(null)
    setSnapshot(null)
    setSelected(null)
    setLocator('')
    setMatches(null)
    setValidateError(null)
    setWsStatus('idle')
    setWsNotice(null)
    setCloseError(null)
  }, [])

  /** 打开抽屉 → 创建调试会话 */
  const createMutation = useMutation({
    mutationFn: () => createDebugSession(target!.serial, '定位排查'),
    onSuccess: (created) => {
      setSession({ id: created.id })
      sessionRef.current = created.id
    },
    onError: (error) => {
      const described = describeError(error)
      setWsNotice('调试会话创建失败（' + described.code + '）：' + described.message)
    },
  })

  const detailQuery = useQuery({
    queryKey: ['debug-session', session?.id],
    queryFn: ({ signal }) => fetchDebugSession(session!.id, signal),
    enabled: open && Boolean(session),
    retry: false,
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
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
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

  /** WS 建立：binary 帧 → Blob 绘制；json 帧解析 tree */
  useEffect(() => {
    if (!open || !session || wsStatus !== 'idle') return
    const detail = detailQuery.data
    if (!detail) return
    const path = detail.ws_path ?? '/api/v1/ws/debug/' + String(session.id)
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = proto + '//' + window.location.host + path

    setWsStatus('connecting')
    const socket = new WebSocket(url)
    wsRef.current = socket
    closingRef.current = false

    socket.onopen = () => {
      setWsStatus('open')
      setWsNotice(null)
      socket.send(JSON.stringify({ type: 'ping' }))
    }
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const message = JSON.parse(event.data) as Record<string, unknown>
          const tree = readTree(message)
          if (tree) setSnapshot(tree)
          if (message.type === 'error' && typeof message.message === 'string') {
            setWsNotice(String(message.message))
          }
        } catch {
          // 非 JSON 文本帧：透传帧不做解析，忽略
        }
        return
      }
      event.data.blob().then((blob: Blob) => {
        if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
        const url = URL.createObjectURL(blob)
        objectUrlRef.current = url
        const image = new Image()
        image.onload = () => {
          const canvas = canvasRef.current
          if (!canvas) return
          canvas.width = image.naturalWidth
          canvas.height = image.naturalHeight
          const ctx = canvas.getContext('2d')
          ctx?.drawImage(image, 0, 0)
        }
        image.src = url
      }).catch(() => undefined)
    }
    socket.onclose = () => {
      wsRef.current = null
      setWsStatus('closed')
      if (!closingRef.current) {
        // 服务端关闭（会话结束 / 1000），明确提示而不是静默黑屏
        setWsNotice('连接已断开：会话已结束')
      }
    }
    socket.onerror = () => {
      setWsStatus('closed')
      if (!closingRef.current) setWsNotice('预览连接失败，请确认后端 WS 端点已上线')
    }

    return () => {
      closingRef.current = true
      if (wsRef.current === socket) wsRef.current = null
      try {
        socket.close(1000)
      } catch {
        // 忽略
      }
    }
  }, [open, session, detailQuery.data, wsStatus])

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

  const validateMutation = useMutation({
    mutationFn: () => {
      const id = sessionRef.current
      const snapshotId = selected?.id
      if (id === null || snapshotId === undefined || snapshotId === null) {
        throw new Error('缺少会话或快照节点')
      }
      return validateLocator(id, { snapshot_id: snapshotId, locator })
    },
    onSuccess: (result) => {
      setValidateError(null)
      const list = Array.isArray(result?.matches) ? result.matches : []
      setMatches(list)
      if (list.length === 0) toast.show('定位验证完成：无匹配')
    },
    onError: (error) => {
      const described = describeError(error)
      setValidateError(described.code + '：' + described.message)
    },
  })

  const detailError = detailQuery.isError ? describeError(detailQuery.error) : null

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
                <canvas
                  ref={canvasRef}
                  className="debug-canvas"
                  aria-label="设备画面预览"
                />
                {detailError ? (
                  <div className="mt">
                    <Notice tone="red" title={'会话详情获取失败（' + detailError.code + '）'}>
                      {detailError.message}
                    </Notice>
                  </div>
                ) : null}
              </div>

              {/* 栏二：层级树 */}
              <div>
                <strong className="small">快照层级树</strong>
                <div className="debug-tree mt">
                  {snapshot ? (
                    <TreeBranch node={snapshot} depth={0} onPick={(node) => setSelected(node)} />
                  ) : (
                    <span className="muted small">等待 WS json 帧下发快照树；端点上线后自动刷新。</span>
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
                      <span className="mono"> {nodeLabel(selected)}{selected.bounds ? ' ' + selected.bounds : ''}</span>
                    ) : (
                      ' 未选择（在层级树中点击节点）'
                    )}
                  </div>
                  <label className="small">
                    表达式
                    <input
                      className="search"
                      style={{ width: '100%' }}
                      value={locator}
                      onChange={(event) => setLocator(event.target.value)}
                      placeholder="xpath / id / 文本"
                    />
                  </label>
                  <Button
                    kind="primary"
                    size="small"
                    icon="check"
                    disabled={!locator.trim() || !selected || validateMutation.isPending}
                    onClick={() => validateMutation.mutate()}
                  >
                    {validateMutation.isPending ? '验证中…' : '验证定位'}
                  </Button>
                  {validateError ? (
                    <Notice tone="red" title="验证失败">
                      {validateError}
                    </Notice>
                  ) : null}
                  {matches !== null && !validateError ? (
                    matches.length === 0 ? (
                      <span className="muted small">无匹配节点</span>
                    ) : (
                      <div className="table-wrap">
                        <table className="task-table" aria-label="定位验证结果">
                          <thead>
                            <tr>
                              <th>#</th>
                              <th>x</th>
                              <th>y</th>
                              <th>置信度</th>
                            </tr>
                          </thead>
                          <tbody>
                            {matches.map((match, index) => (
                              <tr key={index}>
                                <td>{index + 1}</td>
                                <td className="mono">{match.x ?? DASH}</td>
                                <td className="mono">{match.y ?? DASH}</td>
                                <td className="mono">
                                  {typeof match.confidence === 'number' ? match.confidence.toFixed(2) : DASH}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
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
