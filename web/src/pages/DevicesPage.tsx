/**
 * 执行资源（原型 #devices / L85–L92 设备池）。
 *
 * 数据源：GET /api/v1/resources（?project_id= 按项目过滤）。
 * 注意三件事：
 *  1. busy 不是库列，由后端按"存在未释放租约"实时推导；
 *  2. 操作系统与分辨率来自 resource_profiles.spec(jsonb)，档案缺失时为 null → 显示破折号；
 *  3. last_seen_at 来自 POST /resources/sync，null = 从未同步过 → 破折号。
 * 状态枚举按 schema.sql execution_resources.status：ready / offline / unauthorized / draining。
 * 「同步设备池」触发 POST /resources/sync（device-registration.md §4.1），按节点汇总结果。
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchProjects, fetchResources, syncResources } from '../api/endpoints'
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
import { DASH, fmtDateTime } from '../lib/fmt'
import { useTargetScope } from '../store/scope'
import { useProjectScope } from '../store/project'
import type { ResourceRecord, ResourceSyncResponse } from '../types'

/** 把一轮同步结果压成一行人话；没有可说的节点返回 null */
function summarizeSync(result: ResourceSyncResponse): string {
  const parts = result.nodes.map((node) => {
    if (node.status === 'unreachable') return `${node.node_name}：节点不可达`
    const bits = [`新增 ${node.created}`, `更新 ${node.updated}`, `离线 ${node.offlined}`]
    if (node.busy_skipped.length) bits.push(`占用跳过 ${node.busy_skipped.join('、')}`)
    return `${node.node_name}：${bits.join(' / ')}`
  })
  return `同步完成（${result.duration_ms}ms，adb: ${result.adb_path}）\n` + parts.join('\n')
}

export function DevicesPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const { projectId, setProjectId } = useProjectScope()
  const [debugTarget, setDebugTarget] = useState<DebugTarget | null>(null)
  // 首次进入（URL 与 localStorage 都没选过项目）时自动选第一个未归档项目；只兜底一次，
  // 之后用户可以切回「全部项目」，不会再被强制选中。
  const autoPicked = useRef(false)

  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: ({ signal }) => fetchProjects(signal),
    staleTime: 60_000,
  })

  const projects = projectsQuery.data?.items

  useEffect(() => {
    if (!projects) return
    if (projectId && !projects.some((project) => project.id === projectId)) {
      // 上次选的项目已被删除：回落到第一个未归档项目，避免后端 404 卡住整页
      autoPicked.current = true
      setProjectId(projects.find((project) => !project.archived_at)?.id ?? null)
      return
    }
    if (!projectId && !autoPicked.current) {
      autoPicked.current = true
      const first = projects.find((project) => !project.archived_at)
      if (first) setProjectId(first.id)
    }
  }, [projectId, projects, setProjectId])

  const resourcesQuery = useQuery({
    queryKey: ['resources', projectId],
    queryFn: ({ signal }) => fetchResources(targetScope, signal, projectId),
    retry: false,
  })

  const syncMutation = useMutation({
    mutationFn: () => syncResources(projectId ? { project_id: projectId } : {}),
    onSuccess: () => resourcesQuery.refetch(),
  })

  const error = resourcesQuery.isError ? describeError(resourcesQuery.error) : null
  const syncError = syncMutation.isError ? describeError(syncMutation.error) : null
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
      key: 'last_seen_at',
      header: '最后在线',
      render: (row) => (
        <span className="muted small">{row.last_seen_at ? fmtDateTime(row.last_seen_at) : DASH}</span>
      ),
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
        actions={
          <PrimaryAction
            label={syncMutation.isPending ? '同步中…' : '同步设备池'}
            icon="plug"
            onClick={() => syncMutation.mutate()}
          />
        }
      />
      <ContextBar
        scope={targetScope}
        onScopeChange={setTargetScope}
        extra={
          <label className="muted small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            项目
            <select
              value={projectId ?? ''}
              onChange={(event) => setProjectId(event.target.value || null)}
              aria-label="项目过滤"
            >
              <option value="">全部项目</option>
              {(projectsQuery.data?.items ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.archived_at ? `${project.name}（已归档）` : project.name}
                </option>
              ))}
            </select>
          </label>
        }
      />

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'资源列表获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      {syncError ? (
        <div className="mb">
          <Notice tone="red" title={'设备同步失败（' + syncError.code + '）'}>
            {syncError.message}
            {syncError.code === 'adb_unavailable'
              ? ' 期望路径与 TESTDOCK_ADB 提示见后端 details。'
              : null}
          </Notice>
        </div>
      ) : null}

      {syncMutation.data ? (
        <div className="mb">
          <Notice tone="blue" title="同步结果">
            <span style={{ whiteSpace: 'pre-line' }}>{summarizeSync(syncMutation.data)}</span>
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
          hint="设备来自 /resources/sync；占用由租约推导"
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
            description="插上设备后点「同步设备池」，这里按可用 / 占用 / 离线 / 待授权展示。"
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
