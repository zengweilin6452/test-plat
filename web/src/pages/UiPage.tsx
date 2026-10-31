/**
 * UI 自动化（原型 #ui / L188 起）。
 *
 * 数据源：
 *  - 执行记录：GET /api/v1/runs 里 test_type='ui' 的运行
 *  - 调试 / 模板：平台代理到活动调试会话的 vendor viewer（见 DebugDrawer / TemplatesPanel）
 *  - 套件：GET /api/v1/suites?test_type=ui；用例：GET /api/v1/suites/{id}/versions 里
 *    最新版本的 manifest.cases（schema 没有 cases 表，清单就存在 jsonb 里）
 * 硬约束：断言结果与失败现场都来自后端，接口未接入时只显示空态。
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, describeError } from '../api/client'
import {
  createTemplate,
  fetchResources,
  fetchApplications,
  fetchRuns,
  fetchSuiteVersions,
  fetchSuites,
  fetchTasks,
  fetchTemplates,
  updateTemplate,
} from '../api/endpoints'
import type { ResourceRecord } from '../types'
import type {
  SuiteCaseRecord,
  SuiteRecord,
  SuiteVersionRecord,
  TemplateRecord,
} from '../api/types'
import { DebugDrawer, type DebugTarget } from '../components/DebugDrawer'
import { StatusBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { LinkButton } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PlannedNotice, PrimaryAction, Toolbar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import { TaskDrawer } from '../components/TaskDrawer'
import { TaskWizard } from '../components/TaskWizard'
import { useToast } from '../components/Toast'
import { Tabs, type TabItem } from '../components/Tabs'
import { MODULE_NAMES, TARGET_CATALOG, isImplementedPlatform } from '../constants'
import { displayStatus } from '../lib/display'
import { DASH, fmtDateTime } from '../lib/fmt'
import { useDebugHandoff } from '../store/debugHandoff'
import { useAppScope } from '../store/app'
import type { ApplicationRecord } from '../types'
import { useTargetScope } from '../store/scope'
import type { CreateTaskResponse, Platform, RunRecord, TargetScope, TaskRecord } from '../types'

type UiTab = 'runs' | 'suites' | 'cases' | 'debug' | 'templates'

const TABS: TabItem<UiTab>[] = [
  { value: 'runs', label: '执行记录' },
  { value: 'suites', label: '用例套件' },
  { value: 'cases', label: '用例' },
  { value: 'debug', label: '设备调试' },
  { value: 'templates', label: '模板' },
]

/**
 * 目标端筛选：/suites 只支持 test_type 过滤，platform 过滤在页面做
 * （与设备页按 platform 过滤同一口径，不伪造后端能力）。
 */
export function filterSuites(items: SuiteRecord[], scope: TargetScope): SuiteRecord[] {
  return scope === 'all' ? items : items.filter((item) => item.application.platform === scope)
}

/**
 * 选中的版本：后端按 version 倒序返回；选中的号不存在（换了套件、或新 discover
 * 把版本号推到后面）时回落到最新版本，而不是显示一张空表。
 */
export function pickVersion(
  versions: SuiteVersionRecord[],
  versionNo: number | null,
): SuiteVersionRecord | null {
  if (versions.length === 0) return null
  return versions.find((item) => item.version === versionNo) ?? versions[0]
}

export function UiPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  // 工单 19：工作区携带应用身份；过滤与提交都锚定这个应用（AC-APP-01）
  const { appId } = useAppScope()
  const appsQuery = useQuery({
    queryKey: ['applications'],
    queryFn: ({ signal }) => fetchApplications(signal),
    retry: false,
  })
  const currentApp = (appsQuery.data?.items ?? []).find((app: ApplicationRecord) => app.id === appId) ?? null
  const [tab, setTab] = useState<UiTab>('runs')
  const [keyword, setKeyword] = useState('')
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeTask, setActiveTask] = useState<TaskRecord | null>(null)
  const [debugTarget, setDebugTarget] = useState<DebugTarget | null>(null)
  // 执行资源页「打开调试」跳转进来：落在调试标签并锚定该设备（消费即清空）
  const consumeHandoff = useDebugHandoff((state) => state.consume)
  useEffect(() => {
    const pending = consumeHandoff()
    if (pending) {
      setDebugTarget(pending)
      setTab('debug')
    }
  }, [consumeHandoff])
  // 调试抽屉当前持有的会话 id：模板按调试会话隔离（vendor TemplateStore 绑定
  // session.assets_dir），模板页签的所有请求都必须显式带上它。
  const [debugSessionId, setDebugSessionId] = useState<string | number | null>(null)
  // 调试工作区一旦打开就保持挂载：切到「模板」页签时不能卸载 DebugDrawer，
  // 否则组件卸载兜底会关掉会话，模板页签随即失去 session_id（模板按会话隔离）。
  const [debugEngaged, setDebugEngaged] = useState(false)
  useEffect(() => {
    if (tab === 'debug') setDebugEngaged(true)
  }, [tab])
  // 套件 / 用例页签：选中的套件与版本（versionNo 为 null 表示看最新版本）
  const [suiteId, setSuiteId] = useState<string | null>(null)
  const [versionNo, setVersionNo] = useState<number | null>(null)
  const planned = !isImplementedPlatform(targetScope)
  const queryClient = useQueryClient()
  const toast = useToast()

  const runsQuery = useQuery({
    queryKey: ['runs', 'ui', targetScope],
    queryFn: ({ signal }) =>
      fetchRuns(targetScope, 100, signal, appId ? { application_id: appId } : undefined),
    retry: false,
  })

  // 任务抽屉需要任务对象，而运行记录只带 task_id：按 id 反查任务列表（只读、失败不影响本页表格）
  const tasksQuery = useQuery({
    queryKey: ['tasks', 'by-id'],
    queryFn: ({ signal }) => fetchTasks(undefined, undefined, signal),
    retry: false,
  })
  const taskById = useMemo(() => {
    const map = new Map<string, TaskRecord>()
    for (const task of tasksQuery.data?.items ?? []) map.set(task.id, task)
    return map
  }, [tasksQuery.data])

  function openTaskOfRun(run: RunRecord) {
    const task = run.task_id ? taskById.get(run.task_id) : undefined
    if (task) {
      setActiveTask(task)
      return
    }
    // 找不到对应任务时不伪造一条：明确告诉用户任务详情接口/数据缺失
    toast.show(run.task_id ? '任务 ' + run.task_id + ' 不在当前任务列表中，无法打开详情' : '该运行没有关联任务')
  }

  function handleCreated(created: CreateTaskResponse) {
    toast.show('任务已创建：' + created.display_id + '（编号 ' + created.id + '）')
    setWizardOpen(false)
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    void queryClient.invalidateQueries({ queryKey: ['runs'] })
  }

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

  // ---- 调试 tab：ready 设备清单（与 DevicesPage 同源 /api/v1/resources）----
  const resourcesQuery = useQuery({
    queryKey: ['resources'],
    queryFn: ({ signal }) => fetchResources(targetScope, signal),
    enabled: tab === 'debug',
    retry: false,
  })
  const readyDevices = useMemo(
    () => (resourcesQuery.data?.items ?? []).filter((item) => item.status === 'ready' && !item.busy),
    [resourcesQuery.data],
  )

  // ---- 模板 tab ----
  // 模板端点由平台代理到调试会话的 vendor viewer：模板数据按会话隔离（缺失
  // session_id 后端 422），所以没有活动会话时不发请求，页面如实提示。
  const templatesQuery = useQuery({
    queryKey: ['templates', debugSessionId],
    queryFn: ({ signal }) => fetchTemplates(debugSessionId, signal),
    enabled: tab === 'templates' && debugSessionId !== null,
    retry: false,
  })
  const templatesError = templatesQuery.isError ? describeError(templatesQuery.error) : null
  const templates = templatesQuery.data?.templates ?? []

  // ---- 套件 / 用例 tab ----
  // 后端 P2 起就有 GET /suites 与 /suites/{id}/versions；用例清单不在独立表里，
  // 而是 suite_versions.manifest.cases，所以"用例"页签读的是所选版本。
  const suitesQuery = useQuery({
    queryKey: ['suites', 'ui'],
    queryFn: ({ signal }) => fetchSuites('ui', signal),
    enabled: !planned && (tab === 'suites' || tab === 'cases'),
    retry: false,
  })
  const suites = useMemo(
    () => filterSuites(suitesQuery.data?.items ?? [], targetScope),
    [suitesQuery.data, targetScope],
  )

  // 未点过套件时默认看第一个：切到「用例」页签不需要先回套件页签点一下
  const activeSuiteId = suiteId ?? suites[0]?.id ?? null
  const activeSuite = suites.find((item) => item.id === activeSuiteId) ?? null

  const versionsQuery = useQuery({
    queryKey: ['suite-versions', activeSuiteId],
    queryFn: ({ signal }) => fetchSuiteVersions(activeSuiteId as string, signal),
    enabled: !planned && tab === 'cases' && Boolean(activeSuiteId),
    retry: false,
  })
  const versions = versionsQuery.data?.items ?? []
  const activeVersion = pickVersion(versions, versionNo)
  const suiteCases: SuiteCaseRecord[] = activeVersion?.manifest?.cases ?? []
  const suitesError = suitesQuery.isError ? describeError(suitesQuery.error) : null
  const versionsError = versionsQuery.isError ? describeError(versionsQuery.error) : null

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
      render: (run) => (
        <LinkButton onClick={() => openTaskOfRun(run)}>
          任务详情<span aria-hidden="true">›</span>
        </LinkButton>
      ),
    },
  ]

  /** 打开某个套件的用例（切到「用例」页签并重置版本到最新） */
  function openSuite(suite: SuiteRecord) {
    setSuiteId(suite.id)
    setVersionNo(null)
    setTab('cases')
  }

  const suiteColumns: Column<SuiteRecord>[] = [
    {
      key: 'name',
      header: '套件 / 应用',
      render: (suite) => (
        <>
          <span className="task-name">{suite.name}</span>
          <div className="task-sub">{suite.application.name}</div>
        </>
      ),
    },
    {
      key: 'platform',
      header: '目标端',
      render: (suite) => (
        <span className="module-pill">
          {TARGET_CATALOG[suite.application.platform as Platform]?.label ??
            suite.application.platform}
        </span>
      ),
    },
    {
      key: 'version',
      header: '最新版本',
      render: (suite) =>
        suite.latest_version ? (
          <span className="mono">v{suite.latest_version.version}</span>
        ) : (
          <span className="muted small">未发现</span>
        ),
    },
    {
      key: 'cases',
      header: '用例数',
      align: 'right',
      render: (suite) =>
        suite.latest_version ? (
          <span className="mono">{suite.latest_version.case_count}</span>
        ) : (
          <span className="muted">{DASH}</span>
        ),
    },
    {
      key: 'discovered',
      header: '最近发现',
      render: (suite) => (
        <span className="muted small">
          {suite.latest_version ? fmtDateTime(suite.latest_version.created_at) : DASH}
        </span>
      ),
    },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: (suite) => (
        <LinkButton
          onClick={() => openSuite(suite)}
          disabled={!suite.latest_version}
          title={suite.latest_version ? undefined : '该套件还没有 discover 过，没有用例可看'}
        >
          查看用例<span aria-hidden="true">›</span>
        </LinkButton>
      ),
    },
  ]

  const caseColumns: Column<SuiteCaseRecord>[] = [
    {
      key: 'case',
      header: '用例',
      render: (item) => <span className="mono small">{item.case_key}</span>,
    },
    {
      key: 'file',
      header: '文件',
      render: (item) => <span className="muted small">{item.file ?? DASH}</span>,
    },
    {
      key: 'entry',
      header: '入口',
      render: (item) => <span className="mono small">{item.entry ?? DASH}</span>,
    },
    {
      key: 'tags',
      header: '标签',
      render: (item) =>
        item.tags && item.tags.length > 0 ? (
          <span className="muted small">{item.tags.join(' · ')}</span>
        ) : (
          <span className="muted">{DASH}</span>
        ),
    },
  ]

  return (
    <>
      <PageHeading
        title="UI 自动化"
        description="用例、套件与执行记录：断言结果可追溯到报告与现场证据"
        actions={<PrimaryAction label="新建任务" icon="plus" onClick={() => setWizardOpen(true)} />}
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

      {currentApp ? (
        <div className="mb">
          <Notice tone="blue" title={'当前工作区：' + currentApp.name}>
            运行与任务都锚定该应用（id {currentApp.id.slice(0, 8)}…）；清单已按此应用过滤。
            {currentApp.platform !== 'android'
              ? ' iOS/Web 仅支持保存草稿，不显示设备就绪，也不伪装真实执行。'
              : ''}
          </Notice>
        </div>
      ) : null}

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'执行记录获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      {tab === 'debug' ? null : (
        <Panel>
        <PanelHead
          title={TABS.find((item) => item.value === tab)?.label ?? ''}
          hint={
            tab === 'runs'
              ? '失败运行的现场证据（截图 / 日志 / 步骤断言）随报告提供'
              : tab === 'templates'
                  ? '模板按调试会话隔离，经 vendor TemplateStore 管理（需先建立调试会话）'
                  : tab === 'suites'
                    ? '套件来自 test_suites；用例数取自最新 discover 版本'
                    : '用例清单存在套件版本的 manifest 里，每次 discover 追加新版本'
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
                onRowClick={openTaskOfRun}
                footer={<span>共 {uiRuns.length} 条 UI 运行 · 类型 {MODULE_NAMES.ui}</span>}
              />
            )}
          </>
        ) : tab === 'templates' ? (
          <TemplatesPanel
            sessionId={debugSessionId}
            templates={templates}
            loading={templatesQuery.isLoading}
            error={templatesError}
            onCreated={() => void queryClient.invalidateQueries({ queryKey: ['templates'] })}
          />
        ) : tab === 'suites' ? (
          <>
            {suitesError ? (
              <div className="mb" style={{ padding: '0 20px' }}>
                <Notice tone="red" title={'套件列表获取失败（' + suitesError.code + '）'}>
                  {suitesError.message}
                </Notice>
              </div>
            ) : null}
            <Table
              columns={suiteColumns}
              rows={suites}
              rowKey={(suite) => suite.id}
              ariaLabel="用例套件"
              onRowClick={openSuite}
              empty={
                <Empty
                  icon="layers"
                  title={
                    suitesQuery.isLoading
                      ? '正在加载套件…'
                      : targetScope !== 'all' && (suitesQuery.data?.items.length ?? 0) > 0
                        ? // 套件存在但被目标端筛掉了：别让用户以为库里一个套件都没有
                          TARGET_CATALOG[targetScope].label + ' 还没有登记套件'
                        : '还没有登记任何套件'
                  }
                  description={
                    suitesQuery.isLoading
                      ? 'GET /api/v1/suites?test_type=ui'
                      : '套件由后端登记；每个套件用 POST /api/v1/suites/{id}/discover 收集用例生成版本。'
                  }
                />
              }
              footer={<span>共 {suites.length} 个套件 · 类型 {MODULE_NAMES.ui}</span>}
            />
          </>
        ) : tab === 'cases' ? (
          <>
            {suitesError ? (
              <div className="mb" style={{ padding: '0 20px' }}>
                <Notice tone="red" title={'套件列表获取失败（' + suitesError.code + '）'}>
                  {suitesError.message}
                </Notice>
              </div>
            ) : null}
            {versionsError ? (
              <div className="mb" style={{ padding: '0 20px' }}>
                <Notice tone="red" title={'套件版本获取失败（' + versionsError.code + '）'}>
                  {versionsError.message}
                </Notice>
              </div>
            ) : null}
            {activeSuiteId ? (
              <div style={{ padding: '0 20px' }}>
                <Toolbar>
                  <label className="muted small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    套件
                    <select
                      value={activeSuiteId}
                      onChange={(event) => {
                        setSuiteId(event.target.value || null)
                        setVersionNo(null)
                      }}
                      aria-label="选择套件"
                    >
                      {suites.map((suite) => (
                        <option key={suite.id} value={suite.id}>
                          {suite.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="muted small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    版本
                    <select
                      value={activeVersion ? String(activeVersion.version) : ''}
                      onChange={(event) =>
                        setVersionNo(event.target.value ? Number(event.target.value) : null)
                      }
                      aria-label="选择版本"
                      disabled={versions.length === 0}
                    >
                      {versions.map((version) => (
                        <option key={version.id} value={String(version.version)}>
                          v{version.version} · {version.case_count} 条
                        </option>
                      ))}
                    </select>
                  </label>
                  {activeVersion ? (
                    <span className="muted small">
                      {activeVersion.source_commit ?? 'local'} · 发现于{' '}
                      {fmtDateTime(activeVersion.created_at)}
                      {activeVersion.manifest?.suite_root
                        ? ' · ' + String(activeVersion.manifest.suite_root)
                        : ''}
                    </span>
                  ) : null}
                </Toolbar>
              </div>
            ) : null}
            <Table
              columns={caseColumns}
              rows={suiteCases}
              rowKey={(item, index) => item.case_key + ':' + index}
              ariaLabel="套件用例清单"
              empty={
                <Empty
                  icon="layers"
                  title={
                    !activeSuiteId
                      ? '还没有可查看的套件'
                      : versionsQuery.isLoading
                        ? '正在加载用例…'
                        : activeVersion
                          ? '该版本没有用例清单'
                          : '这个套件还没有 discover 过'
                  }
                  description={
                    !activeSuiteId
                      ? '先在「用例套件」页签登记套件，或在后端用 POST /api/v1/suites/{id}/discover 收集用例。'
                      : activeVersion
                        ? 'manifest.cases 为空：discover 收集到 0 条用例时后端会拒绝写入版本。'
                        : 'POST /api/v1/suites/{id}/discover 会在宿主跑 pytest --collect-only 生成第一个版本。'
                  }
                />
              }
              footer={
                activeVersion ? (
                  <span>
                    共 {suiteCases.length} 条用例 · {activeSuite?.name ?? ''} v{activeVersion.version}
                  </span>
                ) : null
              }
            />
          </>
        ) : null}
        </Panel>
      )}

      {tab === 'debug' || debugEngaged ? (
        <div style={{ display: tab === 'debug' ? undefined : 'none' }}>
          <DebugDrawer
            open={debugEngaged || tab === 'debug'}
            target={
              debugTarget
              ?? (readyDevices[0] ? toDebugTarget(readyDevices[0]) : null)
            }
            devices={readyDevices}
            onTargetChange={(target) => setDebugTarget(target)}
            onClose={() => {
              setDebugTarget(null)
              setDebugEngaged(false)
              // 关闭会话后回到执行记录：停留在调试页签会立刻按 ready 设备重建会话
              setTab('runs')
            }}
            onSessionChange={setDebugSessionId}
          />
        </div>
      ) : null}


      <TaskWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={handleCreated}
        initialPlatform={targetScope === 'all' ? 'android' : (targetScope as Platform)}
      />
      <TaskDrawer open={Boolean(activeTask)} task={activeTask} onClose={() => setActiveTask(null)} />
    </>
  )
}


function toDebugTarget(device: ResourceRecord): DebugTarget {
  const hint = device.lease
    ? device.lease.run_id
      ? '运行 ' + device.lease.run_id.slice(0, 8) + ' 占用中'
      : '调试会话占用中'
    : null
  return { serial: device.resource_key, label: device.name, leaseHint: hint }
}

/**
 * 模板页签：清单 + 登记表单。
 *
 * vendor 契约（viewer/app.py 716-776）：
 *  - 模板只能从**服务端保留的快照**裁剪，不接受浏览器上传图片：
 *    POST /templates {snapshot_id, region:[x,y,w,h], logical}；
 *  - 同名登记 409（DuplicateTemplate）→ 用 PUT /templates/{logical}
 *    {snapshot_id, region, expected_old_sha256} 确认更新；
 *  - 清单返回 {templates:[{logical, version_id, image_sha256}]}。
 * 因此表单要求：逻辑名 + 快照 id + 裁剪区域（四个整数）；快照 id 来自调试抽屉
 * 「采集快照」的响应。模板按调试会话隔离：没有会话时本页不发请求，只提示先开会话。
 */
function TemplatesPanel({
  sessionId,
  templates,
  loading,
  error,
  onCreated,
}: {
  sessionId: string | number | null
  templates: TemplateRecord[]
  loading: boolean
  error: ReturnType<typeof describeError> | null
  onCreated: () => void
}) {
  const toast = useToast()
  const [logical, setLogical] = useState('')
  const [snapshotId, setSnapshotId] = useState('')
  const [region, setRegion] = useState({ x: '', y: '', w: '', h: '' })
  const [expectedSha, setExpectedSha] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  function parseRegion(): [number, number, number, number] | null {
    const values = [region.x, region.y, region.w, region.h].map((raw) => raw.trim())
    if (values.some((raw) => !/^\d+$/.test(raw))) return null
    return values.map(Number) as [number, number, number, number]
  }

  async function submit() {
    setLocalError(null)
    const name = logical.trim()
    if (!name.endsWith('.png') || name.includes('..') || name.startsWith('/') || name.includes('\\')) {
      setLocalError('逻辑名必须是以 .png 结尾的 POSIX 相对路径（不含 ..、不以 / 开头）')
      return
    }
    if (!snapshotId.trim()) {
      setLocalError('需要快照 id：先在「调试」页签采集快照，再填入这里的 snapshot_id')
      return
    }
    if (!sessionId) {
      setLocalError('模板按调试会话隔离：请先在「调试」页签建立会话，再登记模板')
      return
    }
    const box = parseRegion()
    if (!box || box[2] <= 0 || box[3] <= 0) {
      setLocalError('裁剪区域必须是四个非负整数 [x, y, width, height]，且宽高大于 0')
      return
    }
    setPending(true)
    try {
      if (expectedSha.trim()) {
        await updateTemplate(name, {
          snapshot_id: snapshotId.trim(),
          region: box,
          expected_old_sha256: expectedSha.trim(),
        }, sessionId)
        toast.show('模板已更新：' + name)
      } else {
        await createTemplate(sessionId, { logical: name, snapshot_id: snapshotId.trim(), region: box })
        toast.show('模板已登记：' + name)
      }
      onCreated()
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 400) {
        setLocalError('后端要求显式会话 id（模板按调试会话隔离）：请刷新页面重试')
      } else if (cause instanceof ApiError && cause.status === 503) {
        setLocalError('viewer 上游不可达：调试会话可能已退出')
      } else if (cause instanceof ApiError && cause.status === 409) {
        // 同名模板需要确认更新：把当前摘要填进 expected_old_sha256 再提交
        const described = describeError(cause)
        setLocalError(
          '同名模板已存在（' + described.code + '）。确认覆盖请填写当前版本摘要后再次提交：' +
            described.message,
        )
      } else {
        const described = describeError(cause)
        setLocalError('登记失败（' + described.code + '）：' + described.message)
      }
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="panel-pad">
      {error ? (
        <div className="mb">
          <Notice tone="red" title={'模板清单获取失败（' + error.code + '）'}>
            {error.message}
            {error.code === 'debug_session_not_active' ? (
              <div className="small" style={{ marginTop: 6 }}>
                该调试会话已结束：请重新打开调试抽屉建立会话后再查看模板。
              </div>
            ) : null}
          </Notice>
        </div>
      ) : null}

      <div className="mb" style={{ maxWidth: 620, display: 'grid', gap: 8 }}>
        <strong className="small">登记模板（从调试快照裁剪）</strong>
        <label className="small">
          逻辑名（.png）
          <input
            style={{ width: '100%' }}
            value={logical}
            onChange={(event) => setLogical(event.target.value)}
            placeholder="如 buttons/confirm.png"
          />
        </label>
        <label className="small">
          快照 id（调试抽屉「采集快照」返回）
          <input
            style={{ width: '100%' }}
            value={snapshotId}
            onChange={(event) => setSnapshotId(event.target.value)}
            placeholder="snapshot_id"
          />
        </label>
        <div className="form-grid two">
          {([
            ['x', 'x'], ['y', 'y'], ['w', '宽'], ['h', '高'],
          ] as const).map(([key, label]) => (
            <label className="small" key={key}>
              裁剪 {label}
              <input
                style={{ width: '100%' }}
                inputMode="numeric"
                value={region[key]}
                onChange={(event) => setRegion((prev) => ({ ...prev, [key]: event.target.value }))}
              />
            </label>
          ))}
        </div>
        <label className="small">
          期望旧摘要（覆盖同名模板时必填）
          <input
            style={{ width: '100%' }}
            value={expectedSha}
            onChange={(event) => setExpectedSha(event.target.value)}
            placeholder="sha256，可从下方清单复制"
          />
        </label>
        {localError ? <Notice tone="amber">{localError}</Notice> : null}
        <div>
          <Button kind="primary" size="small" icon="plus" onClick={submit} disabled={pending}>
            {pending ? '提交中…' : '登记模板'}
          </Button>
        </div>
        <span className="muted small">
          vendor 不接受浏览器上传的图片：模板由服务端从保留快照按区域裁剪生成；
          同名登记返回 409，确认覆盖需带当前版本摘要（乐观锁）。
        </span>
      </div>

      {sessionId === null ? (
        <Empty
          icon="layers"
          title="尚未建立调试会话"
          description="模板按调试会话隔离（属于该会话的 vendor viewer）：打开「调试」页签建立会话后，这里才会加载并登记该会话的模板。"
        />
      ) : loading ? (
        <Empty icon="layers" title="正在加载模板" description="正在请求 /api/v1/templates" />
      ) : !error && templates.length === 0 ? (
        <Empty icon="layers" title="暂无模板" description="登记模板后在此展示（逻辑名 / 版本 / 摘要）。" />
      ) : templates.length > 0 ? (
        <div className="table-wrap">
          <table className="task-table" aria-label="图像模板清单">
            <thead>
              <tr>
                <th>逻辑名</th>
                <th>版本 id</th>
                <th>图片摘要</th>
              </tr>
            </thead>
            <tbody>
              {templates.map((template) => (
                <tr key={template.logical}>
                  <td className="mono">{template.logical}</td>
                  <td className="mono small">{template.version_id ?? DASH}</td>
                  <td className="mono small">{template.image_sha256 ?? DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
