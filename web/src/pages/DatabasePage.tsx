/**
 * 数据设计（原型 #database / L25–L43 的 db-* 样式）。
 *
 * 三个 tab：关系总览 / 字段字典 / 写入流程。
 * 内容是本项目的数据库设计事实（24 张表、7 个分组、4 条写入流程），
 * 不是运行时业务数据，所以静态呈现是合理的；表结构一旦改动需要同步这里。
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchSchema } from '../api/endpoints'
import type { SchemaDoc, SchemaLane, SchemaRelation, SchemaTable, SchemaWriteFlow } from '../api/types'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Button } from '../components/Button'
import { ContextBar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Tabs, type TabItem } from '../components/Tabs'
import { useTargetScope } from '../store/scope'

type DbTab = 'overview' | 'dictionary' | 'flow'

const TABS: TabItem<DbTab>[] = [
  { value: 'overview', label: '关系总览' },
  { value: 'dictionary', label: '字段字典' },
  { value: 'flow', label: '写入流程' },
]

/** 归一 GET /api/v1/schema：键名/字段名以实际返回为准，缺失一律按空数组/破折号处理，不猜值 */
function normalizeTables(doc: SchemaDoc | undefined): SchemaTable[] {
  const raw = doc?.tables
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    const bag = (item ?? {}) as Record<string, unknown>
    const fieldsRaw = bag.fields ?? bag.columns
    const fields = Array.isArray(fieldsRaw)
      ? fieldsRaw.map((field) => {
          const fb = (field ?? {}) as Record<string, unknown>
          return {
            field: String(fb.field ?? fb.name ?? fb.column ?? '—'),
            type: typeof fb.type === 'string' ? fb.type : null,
            note: typeof (fb.note ?? fb.comment ?? fb.description) === 'string' ? String(fb.note ?? fb.comment ?? fb.description) : null,
          }
        })
      : null
    return {
      name: String(bag.name ?? bag.table ?? '—'),
      group: typeof bag.group === 'string' ? bag.group : null,
      note: typeof (bag.note ?? bag.comment ?? bag.description) === 'string' ? String(bag.note ?? bag.comment ?? bag.description) : null,
      fields,
    }
  })
}

function normalizeLanes(doc: SchemaDoc | undefined): SchemaLane[] {
  const raw = doc?.lanes
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    const bag = (item ?? {}) as Record<string, unknown>
    return {
      name: String(bag.name ?? bag.title ?? '—'),
      tables: Array.isArray(bag.tables) ? bag.tables.map(String) : [],
    }
  })
}

function normalizeFlows(doc: SchemaDoc | undefined): SchemaWriteFlow[] {
  const raw = doc?.write_flows ?? doc?.flows
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    const bag = (item ?? {}) as Record<string, unknown>
    return {
      title: String(bag.title ?? bag.name ?? '—'),
      // 后端 /schema 的 steps 是 {title, description, tables} 对象，转成可读文本
      steps: Array.isArray(bag.steps)
        ? bag.steps
            .map((step) => {
              if (typeof step === 'string') return step
              const sb = (step ?? {}) as Record<string, unknown>
              const title = typeof sb.title === 'string' ? sb.title : ''
              const desc = typeof sb.description === 'string' ? sb.description : ''
              return [title, desc].filter(Boolean).join('：')
            })
            .filter(Boolean)
        : [],
    }
  })
}

function normalizeRelations(doc: SchemaDoc | undefined): SchemaRelation[] {
  const raw = doc?.relations
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    const bag = (item ?? {}) as Record<string, unknown>
    return {
      from: String(bag.from ?? bag.source ?? '—'),
      to: String(bag.to ?? bag.target ?? '—'),
      label: typeof (bag.label ?? bag.cardinality) === 'string' ? String(bag.label ?? bag.cardinality) : null,
    }
  })
}

/** 从表分组的聚合结果推导 7 组徽章计数（分组名来自 /schema，前端不硬编码分组清单） */
function groupTables(tables: SchemaTable[]): { group: string; tables: SchemaTable[] }[] {
  const map = new Map<string, SchemaTable[]>()
  for (const table of tables) {
    const key = table.group ?? '未分组'
    const list = map.get(key)
    if (list) list.push(table)
    else map.set(key, [table])
  }
  return [...map.entries()].map(([group, list]) => ({ group, tables: list }))
}

export function DatabasePage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const [tab, setTab] = useState<DbTab>('overview')
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [keyword, setKeyword] = useState('')

  const schemaQuery = useQuery({
    queryKey: ['schema'],
    queryFn: ({ signal }) => fetchSchema(signal),
    retry: false,
  })

  const schemaError = schemaQuery.isError ? describeError(schemaQuery.error) : null
  const doc = schemaQuery.data
  const tables = useMemo(() => normalizeTables(doc), [doc])
  const lanes = useMemo(() => normalizeLanes(doc), [doc])
  const flows = useMemo(() => normalizeFlows(doc), [doc])
  const relations = useMemo(() => normalizeRelations(doc), [doc])
  const grouped = useMemo(() => groupTables(tables), [tables])

  const activeTable =
    (selectedTable && tables.find((table) => table.name === selectedTable)) || tables[0] || null

  const keywordLower = keyword.trim().toLowerCase()
  const dictionaryTables = useMemo(() => {
    if (!keywordLower) return tables
    return tables.filter(
      (table) =>
        table.name.toLowerCase().includes(keywordLower) ||
        (table.fields ?? []).some((field) => field.field.toLowerCase().includes(keywordLower)),
    )
  }, [tables, keywordLower])

  return (
    <>
      <PageHeading
        title="数据设计"
        description="表关系、字段字典与写入流程（数据源 GET /api/v1/schema）"
        actions={
          <Button icon="download" onClick={() => undefined}>
            导出字典
          </Button>
        }
      />
      <ContextBar
        scope={targetScope}
        onScopeChange={setTargetScope}
        extra={<span className="muted small">共 {schemaQuery.isSuccess ? tables.length : '—'} 张表</span>}
      />

      {schemaError ? (
        <div className="mb">
          <Notice tone="red" title={'schema 获取失败（' + schemaError.code + '）'}>
            {schemaError.message}
            {schemaError.code === 'HTTP_404' || schemaError.code === 'not_found' ? (
              <div className="small" style={{ marginTop: 6 }}>
                GET /api/v1/schema 可能尚未上线，页面将在端点就绪后自动展示。
              </div>
            ) : null}
          </Notice>
        </div>
      ) : null}

      <Tabs items={TABS} active={tab} onChange={setTab} ariaLabel="数据设计视图" />

      {schemaQuery.isLoading ? (
        <Empty icon="box" title="正在加载 schema" description="正在请求 /api/v1/schema" />
      ) : null}

      {schemaQuery.isSuccess && tables.length === 0 ? (
        <Empty
          icon="box"
          title="schema 为空"
          description="端点已返回但没有表数据；请确认后端 schema 生成脚本已执行。"
        />
      ) : null}

      {tables.length > 0 && tab === 'overview' ? (
        <div className="db-layout">
          <Panel className="db-table-list">
            <div style={{ padding: '10px 12px' }} className="muted small">
              表清单（{tables.length}）
            </div>
            {grouped.map((group) => (
              <div key={group.group}>
                <div className="nav-label" style={{ margin: '10px 0 4px', padding: '0 12px' }}>
                  {group.group}
                  <span className="badge" style={{ marginLeft: 6 }}>
                    <i className="dot" />
                    {group.tables.length}
                  </span>
                </div>
                {group.tables.map((table) => (
                  <button
                    key={table.name}
                    type="button"
                    className="db-table-btn"
                    aria-pressed={activeTable?.name === table.name}
                    onClick={() => {
                      setSelectedTable(table.name)
                      setTab('dictionary')
                    }}
                  >
                    <strong>{table.name}</strong>
                    <code>{table.note ?? '—'}</code>
                  </button>
                ))}
              </div>
            ))}
          </Panel>

          <div className="stack">
            <Panel>
              <PanelHead title="表分组" hint={grouped.length + ' 个分组，共 ' + tables.length + ' 张表'} />
              <div className="panel-pad">
                <div className="db-entities">
                  {grouped.map((group) => (
                    <div key={group.group} className="db-entity">
                      <strong>{group.group}</strong>
                      <small>{group.tables.length} 张表</small>
                      <code>{group.tables.map((table) => table.name).join(' · ')}</code>
                    </div>
                  ))}
                </div>
              </div>
            </Panel>

            {lanes.length > 0 ? (
              <Panel>
                <PanelHead title="泳道" hint="按职责划分的表泳道（来自 /schema lanes）" />
                <div className="panel-pad">
                  <div className="db-entities">
                    {lanes.map((lane) => (
                      <div key={lane.name} className="db-entity">
                        <strong>{lane.name}</strong>
                        <small>{lane.tables.length} 张表</small>
                        <code>{lane.tables.join(' · ')}</code>
                      </div>
                    ))}
                  </div>
                </div>
              </Panel>
            ) : null}

            {relations.length > 0 ? (
              <Panel>
                <PanelHead title="主要外键关系" hint="核心链路来自 /schema relations" />
                <div className="panel-pad">
                  <div className="flex wrap" style={{ gap: 8 }}>
                    {relations.map((relation, index) => (
                      <span key={relation.from + relation.to + index} className="badge blue">
                        <i className="dot" />
                        {relation.from} → {relation.to}
                        {relation.label ? ' · ' + relation.label : ''}
                      </span>
                    ))}
                  </div>
                </div>
              </Panel>
            ) : null}
          </div>
        </div>
      ) : null}

      {tables.length > 0 && tab === 'dictionary' ? (
        <div className="db-layout">
          <Panel className="db-table-list">
            <div style={{ padding: '10px 12px' }}>
              <ToolbarLike value={keyword} onChange={setKeyword} />
            </div>
            {dictionaryTables.map((table) => (
              <button
                key={table.name}
                type="button"
                className="db-table-btn"
                aria-pressed={activeTable?.name === table.name}
                onClick={() => setSelectedTable(table.name)}
              >
                <strong>{table.name}</strong>
                <code>{table.note ?? '—'}</code>
              </button>
            ))}
          </Panel>

          <Panel>
            <PanelHead
              title={activeTable?.name ?? '—'}
              hint={activeTable?.note ?? undefined}
            />
            {activeTable && (activeTable.fields ?? []).length > 0 ? (
              <div className="table-wrap">
                <table className="task-table db-field-table" aria-label={activeTable.name + ' 字段字典'}>
                  <thead>
                    <tr>
                      <th>字段</th>
                      <th>类型</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(activeTable.fields ?? []).map((field) => (
                      <tr key={field.field}>
                        <td>{field.field}</td>
                        <td>
                          <code>{field.type ?? '—'}</code>
                        </td>
                        <td>{field.note ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="panel-pad muted small">
                该表字段由 /schema 提供；当前返回未包含字段明细。
              </div>
            )}
          </Panel>
        </div>
      ) : null}

      {tables.length > 0 && tab === 'flow' ? (
        flows.length > 0 ? (
          <div className="integration-grid">
            {flows.map((flow) => (
              <Panel key={flow.title}>
                <PanelHead title={flow.title} />
                <div className="panel-pad" style={{ paddingTop: 4 }}>
                  {flow.steps.map((step, index) => (
                    <div className="db-step" key={step}>
                      <span className="db-step-number">{index + 1}</span>
                      <div>{step}</div>
                    </div>
                  ))}
                </div>
              </Panel>
            ))}
          </div>
        ) : (
          <Empty icon="box" title="写入流程未提供" description="/schema 未返回 write_flows 数据。" />
        )
      ) : null}
    </>
  )
}

/** 字典页签内的搜索框（沿用 Toolbar 样式但不依赖其 props） */
function ToolbarLike({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="search" style={{ width: '100%' }}>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="搜索表名 / 字段名"
        aria-label="搜索表名或字段名"
      />
    </label>
  )
}
