/**
 * 数据设计（原型 #database / L25–L43 的 db-* 样式）。
 *
 * 三个 tab：关系总览 / 字段字典 / 写入流程。
 * 内容是本项目的数据库设计事实（24 张表、7 个分组、4 条写入流程），
 * 不是运行时业务数据，所以静态呈现是合理的；表结构一旦改动需要同步这里。
 */
import { useMemo, useState } from 'react'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Button } from '../components/Button'
import { ContextBar } from '../components/PageBits'
import { Notice } from '../components/Notice'
import { Tabs, type TabItem } from '../components/Tabs'
import { useTargetScope } from '../store/scope'

type DbTab = 'overview' | 'fields' | 'writes'

const TABS: TabItem<DbTab>[] = [
  { value: 'overview', label: '关系总览' },
  { value: 'fields', label: '字段字典' },
  { value: 'writes', label: '写入流程' },
]

interface DbTable {
  name: string
  group: TableGroup
  note: string
}

type TableGroup = '基础资产' | '执行资源' | '测试定义' | '任务运行' | '结果证据' | '性能质量' | '治理追溯'

const GROUP_ORDER: TableGroup[] = [
  '基础资产',
  '执行资源',
  '测试定义',
  '任务运行',
  '结果证据',
  '性能质量',
  '治理追溯',
]

/** 24 张表（与 docs/platform-prototype/schema.sql 一一对应） */
const TABLES: DbTable[] = [
  { name: 'projects', group: '基础资产', note: '项目：测试资产的归属容器' },
  { name: 'applications', group: '基础资产', note: '被测应用，按目标端分别登记' },
  { name: 'target_platforms', group: '基础资产', note: '目标端字典（android / ios / web）' },
  { name: 'execution_resources', group: '执行资源', note: '设备与浏览器资源，含状态与档案' },
  { name: 'resource_profiles', group: '执行资源', note: '资源档案：系统版本、分辨率、性能档位' },
  { name: 'resource_leases', group: '执行资源', note: '资源租约，记录占用者与起止时间' },
  { name: 'test_tasks', group: '测试定义', note: '任务主体，生命周期 draft / ready / archived' },
  { name: 'test_task_revisions', group: '测试定义', note: '任务修订版本，readiness 标记是否可用' },
  { name: 'test_suites', group: '测试定义', note: '套件：用例集合' },
  { name: 'test_cases', group: '测试定义', note: '用例：断言定义与步骤' },
  { name: 'test_runs', group: '任务运行', note: '运行记录：state + outcome 双字段' },
  { name: 'run_events', group: '任务运行', note: '运行事件流：进度、状态迁移、错误' },
  { name: 'run_assignments', group: '任务运行', note: '运行与资源、执行者的绑定关系' },
  { name: 'run_artifacts', group: '结果证据', note: '产物索引：截图、日志、下载件' },
  { name: 'artifacts', group: '结果证据', note: '产物实体与可用性（available / missing / expired）' },
  { name: 'run_results', group: '结果证据', note: '运行结果主体：结论与摘要' },
  { name: 'run_metrics', group: '性能质量', note: '性能指标样本，按 key 聚合统计' },
  { name: 'metric_baselines', group: '性能质量', note: '指标基线，绑定资源档案保证可比性' },
  { name: 'gate_rules', group: '性能质量', note: '门禁阈值规则：指标、阈值、级别' },
  { name: 'gate_evaluations', group: '性能质量', note: '门禁评估结果：模式、结论、逐项检查' },
  { name: 'audit_logs', group: '治理追溯', note: '审计日志：谁在何时改了什么' },
  { name: 'idempotency_keys', group: '治理追溯', note: '幂等键，保证写入重试不重复' },
  { name: 'schema_migrations', group: '治理追溯', note: '迁移记录，用于版本追溯' },
  { name: 'retention_policies', group: '治理追溯', note: '保留策略：产物的清理规则' },
]

const RELATIONS: { from: string; to: string; label: string }[] = [
  { from: 'projects', to: 'applications', label: '1:N' },
  { from: 'applications', to: 'test_tasks', label: '1:N' },
  { from: 'test_tasks', to: 'test_task_revisions', label: '1:N' },
  { from: 'test_suites', to: 'test_cases', label: '1:N' },
  { from: 'test_task_revisions', to: 'test_runs', label: '1:N' },
  { from: 'execution_resources', to: 'resource_leases', label: '1:N' },
  { from: 'test_runs', to: 'run_events', label: '1:N' },
  { from: 'test_runs', to: 'run_results', label: '1:1' },
  { from: 'test_runs', to: 'run_metrics', label: '1:N' },
  { from: 'test_runs', to: 'gate_evaluations', label: '1:N' },
  { from: 'gate_rules', to: 'gate_evaluations', label: '1:N' },
  { from: 'resource_profiles', to: 'metric_baselines', label: '1:N' },
]

const FIELDS: Record<string, { field: string; type: string; note: string }[]> = {
  test_runs: [
    { field: 'id', type: 'text pk', note: '运行编号（RUN- 前缀在展示层拼装）' },
    { field: 'task_revision_id', type: 'text fk', note: '引用的任务修订版本' },
    { field: 'state', type: 'enum', note: 'queued / dispatching / running / finalizing / completed / errored / cancelled' },
    { field: 'outcome', type: 'enum null', note: 'passed / failed / not_tested，仅 completed 时非空' },
    { field: 'error_code', type: 'text null', note: 'state=errored 时的原因码' },
    { field: 'started_at', type: 'timestamptz null', note: '开始执行时间（UTC 存储）' },
    { field: 'finished_at', type: 'timestamptz null', note: '结束时间，终态才写入' },
  ],
  gate_evaluations: [
    { field: 'id', type: 'text pk', note: '评估编号' },
    { field: 'run_id', type: 'text fk', note: '关联运行' },
    { field: 'mode', type: 'enum', note: 'original / reanalysis' },
    { field: 'verdict', type: 'enum', note: 'passed / failed / not_tested' },
    { field: 'reason_code', type: 'text null', note: 'INSUFFICIENT_SAMPLES / BASELINE_INCOMPARABLE 等' },
    { field: 'checks', type: 'jsonb', note: '逐项检查：指标、阈值、级别、是否满足' },
  ],
  execution_resources: [
    { field: 'id', type: 'text pk', note: '资源编号' },
    { field: 'status', type: 'enum', note: 'ready / offline / unauthorized / draining' },
    { field: 'profile_id', type: 'text fk', note: '资源档案，决定基线可比性' },
    { field: 'serial', type: 'text null', note: '设备序列号或浏览器标识' },
    { field: 'holder_run_id', type: 'text null', note: '当前占用者运行编号' },
  ],
}

const WRITE_FLOWS: { title: string; steps: string[] }[] = [
  {
    title: 'save · 保存任务配置',
    steps: [
      '校验目标应用与目标端是否已登记',
      '写入 test_tasks 与新的 test_task_revisions',
      'readiness=draft，只有校验通过才置为 validated',
      '写 audit_logs 记录变更人与变更内容',
    ],
  },
  {
    title: 'lease · 申请执行资源',
    steps: [
      '按资源档案与目标端筛选可用资源',
      'BEGIN IMMEDIATE 事务内检查是否有未释放租约',
      '写入 resource_leases，资源 status 变为 draining',
      '释放时写结束时间并恢复 status',
    ],
  },
  {
    title: 'report · 上报执行结果',
    steps: [
      '幂等键去重，避免重试造成重复运行',
      '写 run_results 与 run_artifacts / artifacts',
      'run_events 追加状态迁移事件',
      'state=completed 时才写 outcome',
    ],
  },
  {
    title: 'gate · 门禁评估',
    steps: [
      '读取 run_metrics 的样本与对应基线',
      '检查样本数与基线可比性，不足则 verdict=not_tested',
      '按 gate_rules 逐项检查，任一 fail 级不满足则 failed',
      '写入 gate_evaluations，前端只读取展示',
    ],
  },
]

export function DatabasePage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const [tab, setTab] = useState<DbTab>('overview')
  const [selectedTable, setSelectedTable] = useState<string>(TABLES[0].name)

  const grouped = useMemo(() => {
    return GROUP_ORDER.map((group) => ({
      group,
      tables: TABLES.filter((table) => table.group === group),
    }))
  }, [])

  const fieldRows = FIELDS[selectedTable] ?? []

  return (
    <>
      <PageHeading
        title="数据设计"
        description="24 张表的实体关系、字段字典与写入流程"
        actions={
          <Button icon="download" onClick={() => undefined}>
            导出字典
          </Button>
        }
      />
      <ContextBar scope={targetScope} onScopeChange={setTargetScope} extra={<span className="muted small">共 {TABLES.length} 张表</span>} />

      <div className="mb">
        <Notice tone="blue" icon="alert" title="状态与结论都在库里">
          state / outcome / verdict 三处枚举都有数据库约束兜底。前端不参与推导结论，
          因此这里看到的就是接口能给的唯一事实。
        </Notice>
      </div>

      <Tabs items={TABS} active={tab} onChange={setTab} ariaLabel="数据设计视图" />

      {tab === 'overview' ? (
        <div className="db-layout">
          <Panel className="db-table-list">
            <div style={{ padding: '10px 12px' }} className="muted small">
              表清单（{TABLES.length}）
            </div>
            {grouped.map((group) => (
              <div key={group.group}>
                <div className="nav-label" style={{ margin: '10px 0 4px', padding: '0 12px' }}>
                  {group.group}
                </div>
                {group.tables.map((table) => (
                  <button
                    key={table.name}
                    type="button"
                    className="db-table-btn"
                    aria-pressed={selectedTable === table.name}
                    onClick={() => {
                      setSelectedTable(table.name)
                      setTab('fields')
                    }}
                  >
                    <strong>{table.name}</strong>
                    <code>{table.note}</code>
                  </button>
                ))}
              </div>
            ))}
          </Panel>

          <div className="stack">
            <Panel>
              <PanelHead title="表分组" hint="7 个分组，共 24 张表" />
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

            <Panel>
              <PanelHead title="主要外键关系" hint="核心链路：应用 → 任务 → 修订 → 运行 → 结果 / 指标 / 门禁" />
              <div className="panel-pad">
                <div className="flex wrap" style={{ gap: 8 }}>
                  {RELATIONS.map((relation) => (
                    <span key={relation.from + relation.to} className="badge blue">
                      <i className="dot" />
                      {relation.from} → {relation.to} · {relation.label}
                    </span>
                  ))}
                </div>
              </div>
            </Panel>
          </div>
        </div>
      ) : null}

      {tab === 'fields' ? (
        <div className="db-layout">
          <Panel className="db-table-list">
            {grouped.map((group) => (
              <div key={group.group}>
                <div className="nav-label" style={{ margin: '10px 0 4px', padding: '0 12px' }}>
                  {group.group}
                </div>
                {group.tables.map((table) => (
                  <button
                    key={table.name}
                    type="button"
                    className="db-table-btn"
                    aria-pressed={selectedTable === table.name}
                    onClick={() => setSelectedTable(table.name)}
                  >
                    <strong>{table.name}</strong>
                    <code>{table.note}</code>
                  </button>
                ))}
              </div>
            ))}
          </Panel>

          <Panel>
            <PanelHead
              title={selectedTable}
              hint={TABLES.find((table) => table.name === selectedTable)?.note}
            />
            {fieldRows.length === 0 ? (
              <div className="panel-pad muted small">
                该表的字段字典随后端迁移文件同步；骨架阶段先展示三张核心表（test_runs / gate_evaluations /
                execution_resources）的字段约定。
              </div>
            ) : (
              <div className="table-wrap">
                <table className="task-table db-field-table" aria-label={selectedTable + ' 字段字典'}>
                  <thead>
                    <tr>
                      <th>字段</th>
                      <th>类型</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fieldRows.map((field) => (
                      <tr key={field.field}>
                        <td>{field.field}</td>
                        <td>
                          <code>{field.type}</code>
                        </td>
                        <td>{field.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>
      ) : null}

      {tab === 'writes' ? (
        <div className="integration-grid">
          {WRITE_FLOWS.map((flow) => (
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
      ) : null}
    </>
  )
}
