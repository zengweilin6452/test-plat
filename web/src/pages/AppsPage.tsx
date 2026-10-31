/**
 * 项目与应用（原型 #apps）。
 *
 * 数据源：GET /api/v1/applications（applications 表 + 每个应用的关联任务数）。
 * 目标端的"执行能力"是设计常量（只有 Android 有组件基础），来自 constants.TARGET_CATALOG，
 * 不来自数据库 —— 因此不会被误当成业务数据。
 */
import { useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchApplications } from '../api/endpoints'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PrimaryAction } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import { Badge } from '../components/Badge'
import { SCOPE_OPTIONS, TARGET_CATALOG } from '../constants'
import { useTargetScope } from '../store/scope'
import type { ApplicationRecord } from '../types'

export function AppsPage() {
  const { targetScope, setTargetScope } = useTargetScope()

  const appsQuery = useQuery({
    queryKey: ['applications'],
    queryFn: ({ signal }) => fetchApplications(signal),
    retry: false,
  })

  const error = appsQuery.isError ? describeError(appsQuery.error) : null
  const all = appsQuery.data?.items ?? []
  const rows = all.filter((app) => targetScope === 'all' || app.platform === targetScope)
  // 工单 19：从应用行携带应用身份进入工作区（AC-APP-01）

  const columns: Column<ApplicationRecord>[] = [
    {
      key: 'name',
      header: '应用名称',
      render: (row) => <span className="task-name">{row.name}</span>,
    },
    {
      key: 'platform',
      header: '目标端',
      render: (row) => <span className="module-pill">{TARGET_CATALOG[row.platform]?.label ?? row.platform}</span>,
    },
    {
      key: 'identifier',
      header: '标识',
      render: (row) => <span className="mono muted">{row.identifier}</span>,
    },
    {
      key: 'taskCount',
      header: '关联任务',
      render: (row) => <span className="muted small">{row.task_count}</span>,
    },
    {
      key: 'capability',
      header: '执行能力',
      render: (row) => (
        <Badge tone={row.platform === 'android' ? 'green' : 'gray'}>
          {TARGET_CATALOG[row.platform]?.capability ?? '未接入'}
        </Badge>
      ),
    },
    {
      key: 'enter',
      header: '工作区',
      render: (row) => (
        <a
          className="link-btn"
          href={`#/ui?app=${row.id}`}
          aria-label={`进入 ${row.name} 工作区`}
        >
          进入工作区 ›
        </a>
      ),
    },
  ]

  const scopeLabel = SCOPE_OPTIONS.find((option) => option.value === targetScope)?.label ?? '全部目标端'

  return (
    <>
      <PageHeading
        title="项目与应用"
        description="一个产品项目下分别登记 Web、Android 与 iOS 应用，作为创建与报告的入口。"
        actions={<PrimaryAction label="登记应用" />}
      />
      <ContextBar scope={targetScope} onScopeChange={setTargetScope} />

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'应用列表获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      <Panel>
        <PanelHead
          title="目标端与应用"
          hint="同一应用可按目标端分别登记，任务只引用已登记的目标"
        />
        {appsQuery.isLoading ? (
          <Empty icon="layers" title="正在加载应用清单" description="正在请求 /api/v1/applications" />
        ) : rows.length === 0 && !error ? (
          <Empty
            icon="layers"
            title={targetScope === 'all' ? '尚未登记任何应用' : '该目标端尚未登记应用'}
            description="应用登记接口（POST /api/v1/applications）在 P2 提供；当前展示数据库中已登记的应用。"
          />
        ) : (
          <Table
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            ariaLabel="应用清单"
            footer={
              <span>
                共 {rows.length} 个应用 · 当前筛选 {scopeLabel}
                {appsQuery.data ? ` · 全库 ${appsQuery.data.total} 个` : ''}
              </span>
            }
          />
        )}
      </Panel>
    </>
  )
}
