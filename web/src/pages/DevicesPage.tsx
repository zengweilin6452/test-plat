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
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchProjects, fetchResources, syncResources } from '../api/endpoints'
import { ResourceStatusBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { PageHeading } from '../components/Card'
import { ContextBar, PrimaryAction } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { TARGET_CATALOG } from '../constants'
import { DASH } from '../lib/fmt'
import { toWorkspaceTarget } from '../components/DebugDrawer'
import { useDebugHandoff } from '../store/debugHandoff'
import { useTargetScope } from '../store/scope'
import { useEffectiveContext } from '../store/effectiveContext'
import type { ResourceRecord, ResourceSyncResponse } from '../types'

/** 把一轮同步结果压成一行人话；没有可说的节点返回 null */
function summarizeSync(result: ResourceSyncResponse): string {
  const parts = result.nodes.map((node) => {
    if (node.status === 'unreachable') return `${node.node_name}：节点不可达`
    const bits = [`新增 ${node.created}`, `更新 ${node.updated}`, `离线 ${node.offlined}`]
    if (node.busy_skipped.length) bits.push(`占用跳过 ${node.busy_skipped.join('、')}`)
    const label = node.project_name ? `${node.node_name} · ${node.project_name}` : node.node_name
    return `${label}：${bits.join(' / ')}`
  })
  return `同步完成（${result.duration_ms}ms，adb: ${result.adb_path}）\n` + parts.join('\n')
}

export function DevicesPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const ctx = useEffectiveContext()
  const projectId = ctx.projectId
  const setProjectId = ctx.setProject
  const navigate = useNavigate()
  const setPending = useDebugHandoff((state) => state.setPending)

  const projectsQuery = useQuery({
    queryKey: ['projects', 'all'],
    queryFn: ({ signal }) => fetchProjects(signal, { include_archived: true }),
    staleTime: 60_000,
  })


  const resourcesQuery = useQuery({
    queryKey: ['resources', projectId, targetScope],
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

  // 原型 androidDevicesPage：状态筛选 + resource-card 栅格（工单 23 对齐原型）
  type DeviceState = 'idle' | 'busy' | 'offline' | 'unauthorized' | 'draining'
  function deviceState(item: ResourceRecord): DeviceState {
    if (item.status !== 'ready') return item.status as DeviceState
    return item.busy ? 'busy' : 'idle'
  }
  const [deviceFilter, setDeviceFilter] = useState<'all' | DeviceState>('all')
  const filtered = rows.filter((item) => deviceFilter === 'all' || deviceState(item) === deviceFilter)
  const stateCount = (state: DeviceState) => rows.filter((item) => deviceState(item) === state).length

  function openDebug(row: ResourceRecord) {
    // 原型：打开调试 = go('ui') + uiTab='inspect'；调试工作区在 UI 自动化页内
    setPending(toWorkspaceTarget(row))
    navigate('/ui')
  }

  return (
    <>
      <PageHeading
        title="执行资源"
        description="设备与浏览器资源池：可用状态、占用情况与授权"
        actions={
          <PrimaryAction
            label={syncMutation.isPending ? '同步中…' : '同步设备池'}
            icon="plug"
            busy={syncMutation.isPending}
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

      <div className="toolbar mb">
        <select
          value={deviceFilter}
          onChange={(event) => setDeviceFilter(event.target.value as 'all' | DeviceState)}
          aria-label="设备状态筛选"
        >
          <option value="all">全部设备（{rows.length}）</option>
          <option value="idle">空闲（{stateCount('idle')}）</option>
          <option value="busy">占用中（{stateCount('busy')}）</option>
          <option value="offline">离线（{stateCount('offline')}）</option>
          <option value="unauthorized">待授权（{stateCount('unauthorized')}）</option>
          <option value="draining">退役中（{stateCount('draining')}）</option>
        </select>
        <span className="spacer" />
        <span className="small muted">
          {resourcesQuery.data?.summary ?? '占用由未释放租约实时推导'}
        </span>
      </div>

      {resourcesQuery.isLoading ? (
        <Empty loading icon="devices" title="正在加载资源池" description="正在请求 /api/v1/resources；返回前不判断有没有设备。" />
      ) : filtered.length === 0 && !error ? (
        <Empty
          icon="devices"
          title="当前没有此状态的设备"
          description="切换其他状态查看设备；插上真机后点「同步设备池」。"
        />
      ) : (
        <div className="resource-grid">
          {filtered.map((row) => {
            const state = deviceState(row)
            const busy = state === 'busy'
            const profile = row.profile
            const os = profile?.os_name
              ? `${profile.os_name} ${profile.os_version ?? ''}`.trim()
              : DASH
            return (
              <section key={row.id} className="panel resource-card">
                <div className="between">
                  <h3>{row.name}</h3>
                  <ResourceStatusBadge status={row.status} />
                </div>
                <div className="device-art">
                  <div className="mini-phone">
                    <div className="mini-line" />
                    <div className="mini-block">
                      {state === 'idle' ? '可调试' : busy ? '占用中' : '未连接'}
                    </div>
                    <div className="mini-line" />
                  </div>
                </div>
                <dl className="kv">
                  <dt>平台</dt>
                  <dd>{TARGET_CATALOG[row.platform]?.label ?? row.platform}</dd>
                  <dt>系统</dt>
                  <dd>{os === DASH ? DASH : os}</dd>
                  <dt>分辨率</dt>
                  <dd>{profile?.screen_resolution ?? DASH}</dd>
                  <dt>设备编号</dt>
                  <dd className="mono">{row.resource_key}</dd>
                  <dt>所属项目</dt>
                  <dd>{row.project_name ?? DASH}</dd>
                  <dt>当前占用</dt>
                  <dd>
                    {row.lease?.run_id
                      ? 'run ' + row.lease.run_id.slice(0, 8)
                      : row.lease?.debug_session_id
                        ? '调试会话'
                        : state === 'unauthorized'
                          ? '等待 USB 调试授权'
                          : state === 'offline'
                            ? '检查连接与设备状态'
                            : row.busy ? '占用中' : '无占用'}
                  </dd>
                </dl>
                <div className="resource-actions">
                  <Button
                    size="small"
                    kind={state === 'idle' ? 'primary' : 'default'}
                    disabled={state !== 'idle'}
                    title={
                      state !== 'idle'
                        ? busy
                          ? '设备占用中，暂不支持打开调试'
                          : '设备当前不可调试'
                        : undefined
                    }
                    onClick={() => openDebug(row)}
                  >
                    {busy ? '占用中' : '打开调试'}
                  </Button>
                </div>
              </section>
            )
          })}
        </div>
      )}

      <div className="notice blue mt">
        设备占用状态与 UI、性能任务共用；接入时由宿主协调设备租约与短事务准入。平台不执行连接、安装或授权操作。
      </div>

    </>
  )
}
