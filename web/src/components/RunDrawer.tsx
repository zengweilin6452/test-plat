import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, describeError } from '../api/client'
import { fetchRunArtifacts } from '../api/endpoints'
import type { RunRecord, RunState } from '../types'
import { displayStatus } from '../lib/display'
import { DASH, fmtDateTime } from '../lib/fmt'
import { Drawer } from './Dialog'
import { Button } from './Button'
import { Notice } from './Notice'
import { StatusBadge } from './Badge'
import { Progress } from './Progress'

export interface RunDetail extends RunRecord {
  revision_id: string | null
  last_sequence: number
  cancel_requested: boolean
  config_snapshot: Record<string, unknown>
  components: { kind: string; state: RunState; outcome: RunRecord['outcome'] }[]
}
export interface RunEvent {
  sequence: number
  event_type: string
  occurred_at: string
  payload: Record<string, unknown>
}
interface EventPage { items: RunEvent[]; next_after: number; has_more: boolean }
export interface RunTracking { run: RunDetail; events: RunEvent[] }
export const isRunTerminal = (state: RunState) => ['completed', 'errored', 'cancelled'].includes(state)

/** Poll durable detail and recover every event up to that response's watermark. */
export async function fetchRunTracking(runId: string, previous?: RunTracking, signal?: AbortSignal): Promise<RunTracking> {
  const path = '/runs/' + encodeURIComponent(runId)
  const run = await api.get<RunDetail>(path, undefined, signal)
  const events = new Map((previous?.run.id === runId ? previous.events : []).map(event => [event.sequence, event]))
  let after = [...events.keys()].reduce((latest, sequence) => Math.max(latest, sequence), 0)
  while (after < run.last_sequence) {
    const page = await api.get<EventPage>(path + '/events', { after, limit: 500 }, signal)
    for (const event of page.items) events.set(event.sequence, event)
    if (page.next_after <= after) throw new Error('运行事件尚未完整返回，请重试')
    after = page.next_after
  }
  return { run, events: [...events.values()].sort((a, b) => a.sequence - b.sequence) }
}

export function RunDrawer({ open, runId, onClose }: { open: boolean; runId: string | null; onClose: () => void }) {
  const client = useQueryClient()
  const key = ['run-tracking', runId]
  const tracking = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => fetchRunTracking(runId!, client.getQueryData<RunTracking>(key), signal),
    enabled: open && Boolean(runId),
    retry: false,
    refetchInterval: query => query.state.data && isRunTerminal(query.state.data.run.state) ? false : 2000,
  })
  const run = tracking.data?.run
  useEffect(() => {
    if (!open || !run || !isRunTerminal(run.state)) return
    void client.invalidateQueries({ queryKey: ['run-artifacts', run.id] })
    for (const prefix of ['tasks', 'runs', 'overview']) {
      void client.invalidateQueries({ queryKey: [prefix] })
    }
  }, [open, run?.id, run?.state, client])
  const artifacts = useQuery({
    queryKey: ['run-artifacts', runId],
    queryFn: ({ signal }) => fetchRunArtifacts(runId!, signal),
    enabled: open && Boolean(runId), retry: false,
    refetchInterval: run && isRunTerminal(run.state) ? false : 4000,
  })
  const cancel = useMutation({
    mutationFn: () => api.post('/runs/' + encodeURIComponent(runId!) + '/cancel'),
    onSuccess: () => {
      client.setQueryData<RunTracking>(key, old => old ? { ...old, run: { ...old.run, cancel_requested: true } } : old)
      void client.invalidateQueries({ queryKey: key })
      void client.invalidateQueries({ queryKey: ['runs'] })
      void client.invalidateQueries({ queryKey: ['tasks'] })
      void client.invalidateQueries({ queryKey: ['overview'] })
    },
  })
  const error = tracking.isError ? describeError(tracking.error) : null
  return <Drawer open={open && Boolean(runId)} onClose={onClose} title={run ? '运行详情 · ' + run.display_id : '运行详情'}
    footer={<><Button onClick={() => { void tracking.refetch(); void artifacts.refetch() }}>刷新</Button><Button onClick={onClose}>关闭</Button>
      {run && !isRunTerminal(run.state) ? <Button disabled={cancel.isPending || run.cancel_requested} onClick={() => cancel.mutate()}>{run.cancel_requested ? '已请求取消，等待停止' : cancel.isPending ? '正在请求取消…' : '取消运行'}</Button> : null}</>}>
    {error ? <Notice tone="red" title={'运行读取失败（' + error.code + '）'}>{error.message}。已取得的数据保留，可刷新重试。</Notice> : null}
    {tracking.isLoading ? <p role="status">正在加载运行…</p> : null}
    {cancel.isError ? <Notice tone="red" title="取消请求失败">{describeError(cancel.error).message}</Notice> : null}
    {run ? <>
      <section className="drawer-section"><h3>{run.name}</h3><StatusBadge status={displayStatus(run.state, run.outcome)} />
        <Progress value={run.progress} />
        <dl className="summary-dl"><dt>进度</dt><dd>{run.progress === null ? DASH : run.progress + '%'}</dd><dt>执行资源</dt><dd>{run.resource ?? '未分配'}</dd><dt>创建时间</dt><dd>{fmtDateTime(run.created_at)}</dd><dt>开始时间</dt><dd>{fmtDateTime(run.started_at)}</dd><dt>结束时间</dt><dd>{fmtDateTime(run.ended_at)}</dd><dt>固定修订</dt><dd>{run.revision_id ?? DASH}</dd><dt>原因</dt><dd>{run.reason_code ?? run.not_tested_reason ?? DASH}</dd></dl>
        {run.cancel_requested ? <p role="status">已受理取消请求，最终状态以执行停止后的结果为准。</p> : null}
      </section>
      <section className="drawer-section"><h3>执行组件</h3>{run.components.length ? run.components.map(component => <p key={component.kind}>{component.kind} · <StatusBadge status={displayStatus(component.state, component.outcome)} /></p>) : <p className="muted">暂无组件</p>}</section>
      <section className="drawer-section"><h3>执行时间线</h3>{tracking.data!.events.length ? <ol>{tracking.data!.events.map(event => <li key={event.sequence}><strong>#{event.sequence} {event.event_type}</strong> · {fmtDateTime(event.occurred_at)}<pre className="code-block">{JSON.stringify(event.payload, null, 2)}</pre></li>)}</ol> : <p className="muted">暂无执行事件</p>}</section>
      <section className="drawer-section"><h3>固定执行配置</h3><pre className="code-block">{JSON.stringify(run.config_snapshot, null, 2)}</pre></section>
    </> : null}
    <section className="drawer-section"><h3>运行证据</h3>{artifacts.isError ? <Notice tone="red" title="证据读取失败">{describeError(artifacts.error).message}</Notice> : artifacts.isLoading ? <p>正在加载证据…</p> : !artifacts.data?.items.length ? <p className="muted">暂无可用证据</p> : artifacts.data.items.map(item => <p key={item.id}>{item.availability === 'available' && item.download_url ? <a href={item.download_url}>{item.logical_key}</a> : <span>{item.logical_key} · {item.availability}</span>}</p>)}</section>
  </Drawer>
}
