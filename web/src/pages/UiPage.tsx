/**
 * UI 自动化（原型 #ui / L188 起）。
 *
 * 数据源（P1 可用部分）：
 *  - 用例套件 / 执行记录：GET /api/v1/runs 里 test_type='ui' 的运行
 *  - 套件清单本身要等 test_suites 的读接口（P2），当前不伪造
 * 硬约束：断言结果与失败现场都来自后端，接口未接入时只显示空态。
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchRuns } from '../api/endpoints'
import { StatusBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { LinkButton } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PlannedNotice, PrimaryAction, Toolbar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import { Tabs, type TabItem } from '../components/Tabs'
import { MODULE_NAMES, TARGET_CATALOG, isImplementedPlatform } from '../constants'
import { displayStatus } from '../lib/display'
import { fmtDateTime } from '../lib/fmt'
import { useTargetScope } from '../store/scope'
import type { RunRecord } from '../types'

type UiTab = 'runs' | 'suites' | 'cases'

const TABS: TabItem<UiTab>[] = [
  { value: 'runs', label: '执行记录' },
  { value: 'suites', label: '用例套件' },
  { value: 'cases', label: '用例' },
]

export function UiPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const [tab, setTab] = useState<UiTab>('runs')
  const [keyword, setKeyword] = useState('')
  const planned = !isImplementedPlatform(targetScope)

  const runsQuery = useQuery({
    queryKey: ['runs', 'ui', targetScope],
    queryFn: ({ signal }) => fetchRuns(targetScope, 100, signal),
    retry: false,
  })

  const error = runsQuery.isError ? describeError(runsQuery.error) : null
  const uiRuns = useMemo(() => {
    const all = (runsQuery.data?.items ?? []).filter((run) => run.test_type === 'ui')
    const key = keyword.trim().toLowerCase()
    if (!key) return all
    return all.filter(
      (run) =>
        run.name.toLowerCase().includes(key) ||
        run.display_id.toLowerCase().includes(key),
    )
  }, [runsQuery.data, keyword])

  const columns: Column<RunRecord>[] = [
    {
      key: 'name',
      header: '运行 / 编号',
      render: (run) => (
        <>
          <span className="task-name">{run.name}</span>
          <div className="task-sub">{run.display_id}</div>
        </>
      ),
    },
    {
      key: 'platform',
      header: '目标端',
      render: (run) => (
        <span className="module-pill">{TARGET_CATALOG[run.platform]?.label ?? run.platform}</span>
      ),
    },
    {
      key: 'status',
      header: '状态',
      render: (run) => <StatusBadge status={displayStatus(run.state, run.outcome)} />,
    },
    {
      key: 'resource',
      header: '资源',
      render: (run) => <span className="muted small">{run.resource ?? '—'}</span>,
    },
    {
      key: 'time',
      header: '创建时间',
      render: (run) => <span className="muted small">{fmtDateTime(run.created_at)}</span>,
    },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: () => (
        <LinkButton onClick={() => undefined}>
          查看报告<span aria-hidden="true">›</span>
        </LinkButton>
      ),
    },
  ]

  return (
    <>
      <PageHeading
        title="UI 自动化"
        description="用例、套件与执行记录：断言结果可追溯到报告与现场证据"
        actions={<PrimaryAction label="新建用例" icon="plus" />}
      />
      <ContextBar
        scope={targetScope}
        onScopeChange={setTargetScope}
        extra={<span className="muted small">断言与现场证据均在后端留存</span>}
      />

      {planned ? (
        <div className="mb">
          <PlannedNotice scope={targetScope} />
        </div>
      ) : null}

      <Tabs items={TABS} active={tab} onChange={setTab} ariaLabel="UI 自动化视图" />

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'执行记录获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      <Panel>
        <PanelHead
          title={TABS.find((item) => item.value === tab)?.label ?? ''}
          hint={
            tab === 'runs'
              ? '失败运行的现场证据（截图 / 日志 / 步骤断言）随报告提供'
              : '套件与用例的读接口在 P2 提供（test_suites / 用例表）'
          }
          actions={
            <Button kind="soft" size="small" icon="download">
              导出清单
            </Button>
          }
        />
        {tab === 'runs' ? (
          <>
            <div style={{ padding: '0 20px' }}>
              <Toolbar search={keyword} onSearch={setKeyword}>
                <span className="muted small">按运行名称或编号搜索</span>
              </Toolbar>
            </div>
            {uiRuns.length === 0 && !error ? (
              <Empty
                icon="phone"
                title={planned ? '该目标端尚未接入' : '还没有 UI 自动化运行'}
                description={
                  planned
                    ? 'iOS / Web 目标端暂无执行能力，接入后按同一套接口开通。'
                    : '创建 UI 用例并提交运行后，执行记录会出现在这里。'
                }
              />
            ) : (
              <Table
                columns={columns}
                rows={uiRuns}
                rowKey={(run) => run.id}
                ariaLabel="UI 自动化执行记录"
                footer={<span>共 {uiRuns.length} 条 UI 运行 · 类型 {MODULE_NAMES.ui}</span>}
              />
            )}
          </>
        ) : (
          <Empty
            icon="layers"
            title={tab === 'suites' ? '用例套件尚未接入' : '用例清单尚未接入'}
            description="套件与用例的读接口（test_suites / 用例表）在 P2 提供。当前不展示任何占位数据。"
          />
        )}
      </Panel>
    </>
  )
}
