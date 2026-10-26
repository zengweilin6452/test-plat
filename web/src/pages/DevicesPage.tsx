/**
 * 执行资源（原型 #devices / L85–L92 设备池）。
 *
 * 数据源：GET /api/v1/resources。
 * 注意两件事：
 *  1. busy 不是库列，由后端按"存在未释放租约"实时推导；
 *  2. 操作系统与分辨率来自 resource_profiles.spec(jsonb)，档案缺失时为 null → 显示破折号。
 * 状态枚举按 schema.sql execution_resources.status：ready / offline / unauthorized / draining。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchResources } from '../api/endpoints'
import { DebugDrawer, type DebugTarget } from '../components/DebugDrawer'
import { ResourceStatusBadge, Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PrimaryAction } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { StatCard } from '../components/StatCard'
import { Table, type Column } from '../components/Table'
import { TARGET_CATALOG } from '../constants'
import { DASH } from '../lib/fmt'
import { useTargetScope } from '../store/scope'
import type { ResourceRecord } from '../types'

export function DevicesPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const [debugTarget, setDebugTarget] = useState<DebugTarget | null>(null)

  const resourcesQuery = useQuery({
    queryKey: ['resources'],
    queryFn: ({ signal }) => fetchResources(targetScope, signal),
    retry: false,
  })

  const error = resourcesQuery.isError ? describeError(resourcesQuery.error) : null
  const all = resourcesQuery.data?.items ?? []
  const rows = all.filter((item) => targetScope === 'all' || item.platform === targetScope)

  const readyCount = rows.filter((item) => item.status === 'ready').length
  const busyCount = rows.filter((item) => item.busy).length
  const unavailableCount = rows.filter(
    (item) => item.status === 'offline' || item.status === 'unauthorized',
  ).length

  function openDebug(row: ResourceRecord) {
    const hint = row.lease
      ? row.lease.run_id
        ? '运行 ' + row.lease.run_id.slice(0, 8) + ' 占用中'
        : '调试会话占用中'
      : null
    setDebugTarget({ serial: row.resource_key ?? row.resource_key, label: row.name, leaseHint: hint })
  }

  const columns: Column<ResourceRecord>[] = [
    {
      key: 'name',
      header: '资源',
      render: (row) => (
        <>
          <span className="task-name mono">{row.resource_key}</span>
          <div className="task-sub">{row.kind}</div>
        </>
      ),
    },
    {
      key: 'platform',
      header: '平台',
      render: (row) => (
        <span className="module-pill">{TARGET_CATALOG[row.platform]?.label ?? row.platform}</span>
      ),
    },
    {
      key: 'profile',
      header: '系统 / 分辨率',
      render: (row) => {
        const p = row.profile
        // 档案缺失或 spec 里没有该字段 → 破折号，不编造
        const os = p?.os_name ? `${p.os_name} ${p.os_version ?? ''}`.trim() : DASH
        return (
          <>
            <span className="muted small">{os}</span>
            <div className="task-sub">{p?.screen_resolution ?? DASH}</div>
          </>
        )
      },
    },
    {
      key: 'status',
      header: '状态',
      render: (row) => (
        <div>
          <ResourceStatusBadge status={row.status} />
          {row.busy ? (
            <div style={{ marginTop: 4 }}>
              <Badge tone="blue">已占用</Badge>
            </div>
          ) : null}
        </div>
      ),
    },
    {
      key: 'lease',
      header: '占用者',
      render: (row) => (
        <span className="muted small mono">
          {row.lease?.run_id ? 'run ' + row.lease.run_id.slice(0, 8) : row.lease?.debug_session_id ? '调试会话' : DASH}
        </span>
      ),
    },
    {
      key: 'debug',
      header: '操作',
      align: 'right',
      render: (row) => {
        const busy = row.busy || row.status !== 'ready'
        return (
          <Button
            size="small"
            disabled={busy}
            title={
              busy
                ? '资源不可用或被占用' + (row.lease?.run_id ? '（run ' + row.lease.run_id.slice(0, 8) + '）' : row.lease?.debug_session_id ? '（调试会话）' : '')
                : undefined
            }
            onClick={() => openDebug(row)}
          >
            打开调试
          </Button>
        )
      },
    },
  ]

  return (
    <>
      <PageHeading
        title="执行资源"
        description="设备与浏览器资源池：可用状态、占用情况与授权"
        actions={<PrimaryAction label="登记资源" icon="plus" />}
      />
      <ContextBar scope={targetScope} onScopeChange={setTargetScope} />

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'资源列表获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      <div className="stats">
        <StatCard
          label="资源总数"
          value={resourcesQuery.isSuccess ? rows.length : null}
          foot="按当前目标端过滤"
        />
        <StatCard label="可用" value={resourcesQuery.isSuccess ? readyCount : null} foot="status = ready" />
        <StatCard label="占用中" value={resourcesQuery.isSuccess ? busyCount : null} foot="存在未释放租约" />
        <StatCard
          label="不可用"
          value={resourcesQuery.isSuccess ? unavailableCount : null}
          foot="离线 + 待授权"
        />
      </div>

      <Panel>
        <PanelHead
          title="资源池"
          hint="租约由后端发放；前端只读展示"
          actions={
            <Button size="small" onClick={() => resourcesQuery.refetch()}>
              刷新
            </Button>
          }
        />
        {resourcesQuery.isLoading ? (
          <Empty icon="devices" title="正在加载资源池" description="正在请求 /api/v1/resources" />
        ) : rows.length === 0 && !error ? (
          <Empty
            icon="devices"
            title="资源池为空"
            description="登记资源后，这里按可用 / 占用 / 离线 / 待授权展示。"
          />
        ) : (
          <Table
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            ariaLabel="执行资源"
            footer={
              <span>
                {resourcesQuery.data?.summary ?? '—'} · 当前筛选{' '}
                {targetScope === 'all' ? '全部目标端' : TARGET_CATALOG[targetScope].label}
              </span>
            }
          />
        )}
      </Panel>

      <DebugDrawer
        open={Boolean(debugTarget)}
        target={debugTarget}
        onClose={() => setDebugTarget(null)}
      />
    </>
  )
}
