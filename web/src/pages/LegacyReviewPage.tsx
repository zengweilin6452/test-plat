/** 旧演示数据预览与逐项处理（默认不执行任何写操作）。 */
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { describeError } from '../api/client'
import { applyLegacyActions, fetchLegacyReview } from '../api/endpoints'
import { Badge } from '../components/Badge'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Dialog } from '../components/Dialog'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import type { LegacyAction, LegacyCandidate } from '../types'

export function LegacyReviewPage() {
  const query = useQuery({ queryKey: ['legacy-review'], queryFn: ({ signal }) => fetchLegacyReview(signal), retry: false })
  const [selections, setSelections] = useState<Record<string, { action: string; name: string }>>({})
  // 批量写库前二次确认：说明会执行哪几类操作（渐进式披露规则 5）
  const [confirming, setConfirming] = useState(false)
  const apply = useMutation({
    mutationFn: () => {
      if (!query.data) throw new Error('预览尚未加载')
      const actions: LegacyAction[] = Object.entries(selections)
        .filter(([, value]) => value.action)
        .map(([id, value]) => {
          const candidate = query.data.items.find((item) => item.id === id)!
          return { id, entity: candidate.entity, action: value.action as LegacyAction['action'], name: value.name || undefined }
        })
      return applyLegacyActions({ preview_token: query.data.preview_token, actions })
    },
    onSuccess: () => { setConfirming(false); setSelections({}); void query.refetch() },
  })
  const error = query.isError ? describeError(query.error) : null
  const applyError = apply.isError ? describeError(apply.error) : null

  const columns: Column<LegacyCandidate>[] = [
    { key: 'name', header: '名称 / 稳定 ID', render: (row) => (
      <div className="wrap-cell">
        <strong>{row.current_name}</strong>
        <div className="mono muted small">{row.id}</div>
        {row.current_name !== row.name ? <div className="muted small">原始名称：{row.name}</div> : null}
      </div>
    ) },
    { key: 'entity', header: '类型', render: (row) => <span className="module-pill">{row.entity}</span> },
    { key: 'basis', header: '识别依据', render: (row) => (
      <div className="wrap-cell">
        {row.match_basis.join('；')}
        <div><Badge tone={row.confidence === 'confirmed' ? 'green' : 'amber'}>
          {row.confidence === 'confirmed' ? '可确认' : '需人工判断'}
        </Badge></div>
      </div>
    ) },
    { key: 'counts', header: '关联与真实活动', render: (row) => (
      <div className="wrap-cell small">
        {Object.entries(row.related_counts).map(([key, value]) => `${key} ${value}`).join(' · ')}
        <div>真实运行 {row.real_run_count} · 活动占用 {row.active_occupancy ? '是' : '否'}</div>
      </div>
    ) },
    { key: 'note', header: '处理说明', render: (row) => <span className="muted small wrap-cell">{row.note}</span> },
    { key: 'actions', header: '逐项选择', render: (row) => {
      const selected = selections[row.id] ?? { action: '', name: row.current_name }
      return (
        <div className="flex form-stack">
          <select
            aria-label={`选择 ${row.current_name} 的处理方式`}
            value={selected.action}
            onChange={(event) => setSelections({ ...selections, [row.id]: { ...selected, action: event.target.value } })}
          >
            <option value="">不处理</option>
            {row.allowed_actions.map((action) => (
              <option key={action} value={action}>
                {action === 'keep' ? '保留' : action === 'rename' ? '改名' : '归档'}
              </option>
            ))}
          </select>
          {selected.action === 'rename' ? (
            <input
              aria-label={`输入 ${row.current_name} 的新名称`}
              value={selected.name}
              maxLength={80}
              onChange={(event) => setSelections({ ...selections, [row.id]: { ...selected, name: event.target.value } })}
            />
          ) : null}
        </div>
      )
    } },
  ]

  return (
    <>
      <PageHeading title="旧演示数据预览" description="按固定身份、原字段及关联关系识别；默认只预览，不自动改名或归档" />
      <Notice tone="blue" title="操作边界">
        仅对用户勾选的对象执行；不按名称批量删除，不搬移数据、不改身份与历史证据。
        执行前请备份数据库；处理真实库须另有具体清单确认。
      </Notice>
      {error ? <Notice tone="red" title={'预览读取失败（' + error.code + '）'}>{error.message}</Notice> : null}
      {applyError ? <Notice tone="red" title={'处理未完成（' + applyError.code + '）'}>{applyError.message}</Notice> : null}
      {apply.data ? (
        <Notice tone="green" title="逐项处理完成">
          已执行 {apply.data.applied.length} 项；被拒绝 {apply.data.rejected.length} 项。
          {apply.data.rejected.map((item) => <div key={item.id} className="small">{item.id}：{item.reason}</div>)}
        </Notice>
      ) : null}
      <Panel>
        <PanelHead title="候选清单" hint="只有实际支持的操作才可选；已改名或信息不足的对象标为需人工判断" />
        {query.isLoading ? <Empty loading title="正在读取候选清单" description="正在核对固定身份与关联记录…" /> : null}
        {query.data ? (
          <>
            <Table columns={columns} rows={query.data.items} rowKey={(row) => row.id} ariaLabel="旧演示数据候选" empty={<p className="panel-pad">未识别到旧演示数据候选。</p>} />
            <div className="panel-pad flex">
              <button
                className="btn primary"
                type="button"
                disabled={apply.isPending || Object.values(selections).every((s) => !s.action)}
                onClick={() => setConfirming(true)}
              >
                执行已选操作
              </button>
              <span className="muted small">预览指纹 {query.data.preview_token}</span>
            </div>
          </>
        ) : null}
      </Panel>

      <Dialog open={confirming} title="确认执行已选操作" onClose={() => { if (!apply.isPending) setConfirming(false) }} footHint="执行前请备份数据库；处理真实库须另有具体清单确认。">
        {(() => {
          const planned = Object.entries(selections).filter(([, value]) => value.action)
          const counts = { rename: 0, archive: 0, keep: 0 } as Record<string, number>
          for (const [, value] of planned) counts[value.action] = (counts[value.action] ?? 0) + 1
          return (
            <>
              <p>即将对 {planned.length} 项执行写操作：</p>
              <ul>
                {counts.keep ? <li>保留 {counts.keep} 项（仅标记，不做写操作）</li> : null}
                {counts.rename ? <li>改名 {counts.rename} 项（仅显示名，稳定 ID 与历史引用不变）</li> : null}
                {counts.archive ? <li>归档 {counts.archive} 项（归档后不可开展新业务，历史记录仍只读可见；归档不可自动恢复为执行入口）</li> : null}
              </ul>
              <Notice tone="amber" title="该操作直接写库">
                归档与改名会立即生效；被占用的对象会被服务端拒绝并逐项列出原因。
              </Notice>
            </>
          )
        })()}
        {applyError ? <Notice tone="red" title="处理未完成">{applyError.message}</Notice> : null}
        <div className="flex">
          <button className="btn primary" type="button" disabled={apply.isPending} onClick={() => apply.mutate()}>
            {apply.isPending ? '执行中…' : '确认执行'}
          </button>
          <button className="btn" type="button" disabled={apply.isPending} onClick={() => setConfirming(false)}>取消</button>
        </div>
      </Dialog>
    </>
  )
}
