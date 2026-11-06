import { displayName } from '../lib/formalization'
/**
 * 项目与应用：创建、改名、归档预览 / 归档 / 恢复，以及统一上下文选择。
 *
 * - 身份字段创建后固定：项目编码、应用所属项目 / 目标端 / 标识不可修改；
 * - 归档预览显示关联数量与活动占用，被占用时给出具体阻塞对象；
 * - 归档对象仍可查看历史；正常列表默认排除，管理列表提供归档筛选；
 * - 新应用登记仅开放服务端能力摘要里 supported=true 的 Android。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { describeError } from '../api/client'
import {
  archiveEntity,
  createApplication,
  createProject,
  fetchApplications,
  fetchArchivePreview,
  fetchProjects,
  renameApplication,
  renameProject,
  restoreEntity,
} from '../api/endpoints'
import { Badge } from '../components/Badge'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Dialog } from '../components/Dialog'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { ContextBar } from '../components/PageBits'
import { Table, type Column } from '../components/Table'
import { SCOPE_OPTIONS, TARGET_CATALOG } from '../constants'
import { useEffectiveContext } from '../store/effectiveContext'
import { isPlatformSupported, usePlatform } from '../store/platform'
import { useTargetScope } from '../store/scope'
import type { ApplicationRecord, ProjectRecord } from '../types'

type ActionKind = 'archive' | 'restore' | 'rename'

export function AppsPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const ctx = useEffectiveContext()
  const { capabilities } = usePlatform()
  const queryClient = useQueryClient()
  const [showArchived, setShowArchived] = useState(false)
  const [projectForm, setProjectForm] = useState({ code: '', name: '' })
  const [appForm, setAppForm] = useState({ project_id: '', name: '', identifier: '' })
  const [formError, setFormError] = useState<string | null>(null)
  const [action, setAction] = useState<{
    kind: ActionKind
    entity: 'project' | 'application'
    id: string
    name: string
  } | null>(null)
  const [actionValue, setActionValue] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  const projectsQuery = useQuery({
    queryKey: ['projects', showArchived],
    queryFn: ({ signal }) => fetchProjects(signal, { include_archived: showArchived }),
    retry: false,
  })
  const appsQuery = useQuery({
    queryKey: ['applications', showArchived],
    queryFn: ({ signal }) => fetchApplications(signal, { include_archived: showArchived }),
    retry: false,
  })
  const previewQuery = useQuery({
    queryKey: ['archive-preview', action?.entity, action?.id],
    queryFn: ({ signal }) => fetchArchivePreview(action!.entity, action!.id, signal),
    enabled: action?.kind === 'archive',
    retry: false,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['projects'] })
    void queryClient.invalidateQueries({ queryKey: ['applications'] })
    ctx.refresh()
  }

  const createProjectMutation = useMutation({
    mutationFn: () => createProject({ code: projectForm.code, name: displayName(projectForm.name) }),
    onSuccess: (project) => {
      setProjectForm({ code: '', name: '' })
      setFormError(null)
      invalidate()
      ctx.setProject(project.id)
    },
    onError: (error) => setFormError(describeError(error).message),
  })
  const createAppMutation = useMutation({
    mutationFn: () => createApplication({
      project_id: appForm.project_id || ctx.projectId || '',
      platform: 'android',
      name: displayName(appForm.name),
      identifier: appForm.identifier,
    }),
    onSuccess: (app) => {
      setAppForm({ project_id: '', name: '', identifier: '' })
      setFormError(null)
      invalidate()
      ctx.setApplication(app.id)
    },
    onError: (error) => setFormError(describeError(error).message),
  })
  const actionMutation = useMutation({
    mutationFn: async () => {
      if (!action) throw new Error('没有待执行操作')
      if (action.kind === 'archive') return archiveEntity(action.entity, action.id)
      if (action.kind === 'restore') return restoreEntity(action.entity, action.id)
      if (action.entity === 'project') return renameProject(action.id, displayName(actionValue))
      return renameApplication(action.id, displayName(actionValue))
    },
    onSuccess: () => { setAction(null); setActionError(null); invalidate() },
    onError: (error) => setActionError(describeError(error).message),
  })

  const all = appsQuery.data?.items ?? []
  const rows = all.filter((app) => targetScope === 'all' || app.platform === targetScope)
  const error = appsQuery.isError ? describeError(appsQuery.error) : null
  const scopeLabel = SCOPE_OPTIONS.find((option) => option.value === targetScope)?.label ?? '全部目标端'

  function submitProject(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    createProjectMutation.mutate()
  }
  function submitApp(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    if (!appForm.project_id && !ctx.projectId) {
      setFormError('请先创建或选择一个项目，再登记应用。')
      return
    }
    createAppMutation.mutate()
  }

  const projectColumns: Column<ProjectRecord>[] = [
    { key: 'name', header: '项目名称', render: (row) => <span className="task-name">{row.name}</span> },
    { key: 'code', header: '项目编码（固定）', render: (row) => <span className="mono muted">{row.code}</span> },
    {
      key: 'state',
      header: '状态',
      render: (row) => <Badge tone={row.archived_at ? 'gray' : 'green'}>{row.archived_at ? '已归档' : '使用中'}</Badge>,
    },
    {
      key: 'actions',
      header: '操作',
      render: (row) => (
        <div className="flex">
          <button className="link-btn" type="button" onClick={() => ctx.setProject(row.id)}>设为当前</button>
          <button className="link-btn" type="button" onClick={() => { setAction({ kind: 'rename', entity: 'project', id: row.id, name: row.name }); setActionValue(row.name); setActionError(null) }}>改名</button>
          {row.archived_at ? (
            <button className="link-btn" type="button" onClick={() => { setAction({ kind: 'restore', entity: 'project', id: row.id, name: row.name }); setActionError(null) }}>恢复</button>
          ) : (
            <button className="link-btn" type="button" onClick={() => { setAction({ kind: 'archive', entity: 'project', id: row.id, name: row.name }); setActionError(null) }}>归档预览</button>
          )}
        </div>
      ),
    },
  ]

  const columns: Column<ApplicationRecord>[] = [
    { key: 'name', header: '应用名称', render: (row) => <span className="task-name">{row.name}</span> },
    { key: 'platform', header: '目标端', render: (row) => <span className="module-pill">{TARGET_CATALOG[row.platform]?.label ?? row.platform}</span> },
    { key: 'identifier', header: '标识（固定）', render: (row) => <span className="mono muted">{row.identifier}</span> },
    { key: 'taskCount', header: '关联任务', render: (row) => <span className="muted small">{row.task_count}</span> },
    {
      key: 'capability',
      header: '执行能力',
      render: (row) => (
        <Badge tone={isPlatformSupported(capabilities, row.platform) && !row.archived_at ? 'green' : 'gray'}>
          {row.archived_at
            ? '已归档 · 只读历史'
            : isPlatformSupported(capabilities, row.platform)
              ? '支持执行'
              : capabilities
                ? '尚未支持执行'
                : '能力读取中'}
        </Badge>
      ),
    },
    {
      key: 'actions',
      header: '操作',
      render: (row) => (
        <div className="flex">
          <a className="link-btn" href={`#/ui?app=${row.id}&project=${row.project_id}`} aria-label={`进入 ${row.name} 工作区`}>{row.archived_at ? '查看历史' : '进入工作区'} ›</a>
          <button className="link-btn" type="button" onClick={() => { setAction({ kind: 'rename', entity: 'application', id: row.id, name: row.name }); setActionValue(row.name); setActionError(null) }}>改名</button>
          {row.archived_at ? (
            <button className="link-btn" type="button" onClick={() => { setAction({ kind: 'restore', entity: 'application', id: row.id, name: row.name }); setActionError(null) }}>恢复</button>
          ) : (
            <button className="link-btn" type="button" onClick={() => { setAction({ kind: 'archive', entity: 'application', id: row.id, name: row.name }); setActionError(null) }}>归档预览</button>
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeading
        title="项目与应用"
        description="建立真实项目、登记 Android 应用，维护名称与归档状态；身份创建后固定"
      />
      <ContextBar scope={targetScope} onScopeChange={setTargetScope} extra={
        <label className="flex small">
          <input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />
          显示归档对象
        </label>
      } />
      {ctx.error ? <Notice tone="red" title="上下文无法解析">{ctx.error}</Notice> : null}
      {error ? <Notice tone="red" title={'应用列表读取失败（' + error.code + '）'}>{error.message}</Notice> : null}
      {formError ? <Notice tone="red" title="操作未完成">{formError}</Notice> : null}

      <div className="grid-2 mb">
        <Panel>
          <PanelHead title="新建项目" hint="编码去空白并转小写；1–60 位小写字母、数字、短横线" />
          <form className="panel-pad form-stack" onSubmit={submitProject}>
            <label className="field"><span>项目编码</span>
              <input value={projectForm.code} onChange={(event) => setProjectForm({ ...projectForm, code: event.target.value })} placeholder="例如 mobile-regression" maxLength={60} aria-label="项目编码" />
            </label>
            <label className="field"><span>显示名称</span>
              <input value={projectForm.name} onChange={(event) => setProjectForm({ ...projectForm, name: event.target.value })} placeholder="输入实际项目名称" maxLength={60} aria-label="项目名称" />
            </label>
            <button className="btn primary" type="submit" disabled={createProjectMutation.isPending}>创建项目</button>
            <p className="muted small">编码、稳定 ID 创建后不可修改；填错时请建立正确对象，不迁移历史引用。</p>
          </form>
        </Panel>
        <Panel>
          <PanelHead title="登记 Android 应用" hint="应用标识为线上包名；所属项目 / 目标端 / 标识创建后固定" />
          <form className="panel-pad form-stack" onSubmit={submitApp}>
            <label className="field"><span>所属项目</span>
              <select
                value={appForm.project_id || ctx.projectId || ''}
                onChange={(event) => { setAppForm({ ...appForm, project_id: event.target.value }); ctx.setProject(event.target.value || null) }}
                aria-label="所属项目"
              >
                <option value="">选择项目</option>
                {projectsQuery.data?.items.filter((p) => !p.archived_at).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label className="field"><span>显示名称</span>
              <input value={appForm.name} onChange={(event) => setAppForm({ ...appForm, name: event.target.value })} placeholder="输入实际应用名称" maxLength={60} aria-label="应用名称" />
            </label>
            <label className="field"><span>Android 包名</span>
              <input value={appForm.identifier} onChange={(event) => setAppForm({ ...appForm, identifier: event.target.value })} placeholder="例如 com.example.app（示例不会自动提交）" maxLength={200} aria-label="Android 包名" />
            </label>
            <button className="btn primary" type="submit" disabled={createAppMutation.isPending || !isPlatformSupported(capabilities, 'android')}>
              登记应用
            </button>
            <p className="muted small">当前仅 Android 支持执行；iOS / Web 历史数据保持只读，不提供假执行入口。</p>
          </form>
        </Panel>
      </div>

      <Panel className="mb">
        <PanelHead title="项目" hint="归档项目下应用不可开展新业务；项目恢复不复活单独归档的应用" />
        <Table columns={projectColumns} rows={projectsQuery.data?.items ?? []} rowKey={(row) => row.id} ariaLabel="项目清单" />
      </Panel>

      <Panel>
        <PanelHead title="目标端与应用" hint="同名应用可在不同项目 / 目标端分别登记" />
        {appsQuery.isLoading ? (
          <Empty loading icon="layers" title="正在加载应用清单" description="正在请求 /api/v1/applications；返回前不确定是否已登记应用。" />
        ) : rows.length === 0 && !error ? (
          <Empty icon="layers" title="尚未登记任何应用" description="使用上方表单登记真实 Android 应用；不会自动建立演示数据。" />
        ) : (
          <Table
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            ariaLabel="应用清单"
            footer={<span>共 {rows.length} 个应用 · 当前筛选 {scopeLabel}</span>}
          />
        )}
      </Panel>

      <Dialog open={action !== null} title={action ? `${action.kind === 'archive' ? '归档预览' : action.kind === 'restore' ? '恢复确认' : '修改显示名称'}：${action.name}` : ''} onClose={() => { setAction(null); setActionError(null) }}>
        {action?.kind === 'archive' ? (
          <>
            {previewQuery.isLoading ? <p>正在核对关联记录与活动占用…</p> : null}
            {previewQuery.isError ? <Notice tone="red" title="预览读取失败">{describeError(previewQuery.error).message}</Notice> : null}
            {previewQuery.data ? (
              <>
                <p>关联数量：{Object.entries(previewQuery.data.related_counts).map(([key, value]) => `${key} ${value}`).join(' · ')}</p>
                <p>活动占用：运行中 {previewQuery.data.blockers.active_runs.length} · 调试会话 {previewQuery.data.blockers.open_debug_sessions.length} · 租约 {previewQuery.data.blockers.active_leases.length}</p>
                {previewQuery.data.blockers.active_runs.length || previewQuery.data.blockers.open_debug_sessions.length || previewQuery.data.blockers.active_leases.length ? (
                  <Notice tone="red" title="存在进行中的活动，归档将被服务端拒绝">
                    请先等待运行结束或关闭调试会话，不会自动取消活动。
                    <ul>
                      {previewQuery.data.blockers.active_runs.map((run) => <li key={run.id}><a className="link-btn" href={`#/reports?run=${run.id}`}>查看运行 {run.id}（{run.state}）</a></li>)}
                      {previewQuery.data.blockers.open_debug_sessions.map((s) => <li key={s.id}>调试会话 {s.id}（{s.state}）占用设备 {s.resource_id}</li>)}
                    </ul>
                  </Notice>
                ) : <Notice tone="green" title="当前无活动占用">归档后历史运行、报告与证据仍可读；新业务写入会被服务端拒绝。</Notice>}
              </>
            ) : null}
          </>
        ) : null}
        {action?.kind === 'rename' ? (
          <label className="field"><span>新的显示名称</span>
            <input value={actionValue} onChange={(event) => setActionValue(event.target.value)} maxLength={60} aria-label="新的显示名称" autoFocus />
          </label>
        ) : null}
        {action?.kind === 'restore' ? <p>恢复后可继续开展新业务；单独归档的子应用不会随项目恢复自动复活。</p> : null}
        {actionError ? <Notice tone="red" title="操作未完成">{actionError}</Notice> : null}
        <div className="flex">
          <button
            className="btn primary"
            type="button"
            disabled={actionMutation.isPending || (action?.kind === 'archive' && previewQuery.isLoading)}
            onClick={() => actionMutation.mutate()}
          >
            {action?.kind === 'archive' ? '确认归档' : action?.kind === 'restore' ? '确认恢复' : '保存名称'}
          </button>
          <button className="btn" type="button" onClick={() => setAction(null)}>取消</button>
        </div>
      </Dialog>
    </>
  )
}
