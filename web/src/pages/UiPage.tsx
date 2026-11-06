/**
 * UI 自动化（原型 #ui / L188 起）。
 *
 * 数据源：
 *  - 执行记录：GET /api/v1/runs 里 test_type='ui' 的运行
 *  - 调试 / 模板：平台代理到活动调试会话的 vendor viewer（见 DebugDrawer / TemplateLibrary）
 *  - 套件：GET /api/v1/suites?test_type=ui；用例：GET /api/v1/suites/{id}/versions 里
 *    最新版本的 manifest.cases（schema 没有 cases 表，清单就存在 jsonb 里）
 * 硬约束：断言结果与失败现场都来自后端，接口未接入时只显示空态。
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import {
  fetchResources,
  fetchApplications,
  fetchRuns,
  fetchSuiteVersions,
  fetchSuites,
} from '../api/endpoints'
import type { ResourceRecord } from '../types'
import type {
  SuiteCaseRecord,
  SuiteRecord,
  SuiteVersionRecord,
} from '../api/types'
import { SuiteRegistration } from '../components/InputRegistration'
import { TemplateLibrary } from '../components/TemplateLibrary'
import { DebugDrawer, type DebugTarget } from '../components/DebugDrawer'
import { StatusBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { LinkButton } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PlannedNotice, PrimaryAction, Toolbar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import { RunDrawer } from '../components/RunDrawer'
import { TaskWizard } from '../components/TaskWizard'
import { useToast } from '../components/Toast'
import { Tabs, type TabItem } from '../components/Tabs'
import { MODULE_NAMES, TARGET_CATALOG, isImplementedPlatform } from '../constants'
import { displayStatus } from '../lib/display'
import { DASH, fmtDateTime } from '../lib/fmt'
import { pagePhase, type PagePhase } from '../lib/pageState'
import { useDebugHandoff } from '../store/debugHandoff'
import { useEffectiveContext } from '../store/effectiveContext'
import type { ApplicationRecord } from '../types'
import { useTargetScope } from '../store/scope'
import type { CreateTaskResponse, Platform, RunRecord, TargetScope } from '../types'

type UiTab = 'runs' | 'suites' | 'cases' | 'debug' | 'templates'

const TABS: TabItem<UiTab>[] = [
  { value: 'suites', label: '测试套件' },
  { value: 'debug', label: '设备调试' },
  { value: 'templates', label: '图像模板' },
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

/**
 * 版本固定代码副本状态：没有副本的旧版本不能执行，必须要求重新发现。
 * `has_code_copy` 缺失（更老的接口）时不下结论，返回 null 由后端 readiness 兜底。
 */
export function versionCopyNotice(version: SuiteVersionRecord): string | null {
  if (version.has_code_copy !== false) return null
  return '该版本未保留固定代码副本：执行会被阻断，请用「重新发现」创建带副本的新版本。'
}

/**
 * 「执行记录」页签的占位文案：加载中不能说「还没有 UI 自动化运行」，
 * 规划中的目标端（iOS/Web）也不是真实空态，而是执行能力未接入。
 */
export function uiRunsEmptyCopy(
  phase: PagePhase,
  planned: boolean,
): { title: string; description: string } {
  if (phase === 'loading') {
    return {
      title: '正在加载 UI 执行记录',
      description: '正在请求 GET /api/v1/runs；返回前不判断有没有运行。',
    }
  }
  if (phase === 'error') {
    return {
      title: '执行记录暂不可用',
      description: '接口返回错误（见上方错误码），请稍后重试或刷新页面。',
    }
  }
  if (planned) {
    return {
      title: '该目标端尚未接入',
      description: 'iOS / Web 目标端暂无执行能力，接入后按同一套接口开通；当前可切换目标端为 Android。',
    }
  }
  return {
    title: '还没有 UI 自动化运行',
    description: '创建 UI 用例并提交运行后，执行记录会出现在这里。',
  }
}

export function UiPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  // 工单 19：工作区携带应用身份；过滤与提交都锚定这个应用（AC-APP-01）
  const ctx = useEffectiveContext()
  const appId = ctx.appId
  const appsQuery = useQuery({
    queryKey: ['applications', 'all', ctx.projectId],
    queryFn: ({ signal }) => fetchApplications(signal, { include_archived: true }),
    retry: false,
  })
  const currentApp = (appsQuery.data?.items ?? []).find((app: ApplicationRecord) => app.id === appId) ?? null
  const [tab, setTab] = useState<UiTab>('suites')
  const [keyword, setKeyword] = useState('')
  const [runSuite, setRunSuite] = useState<SuiteRecord | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
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
  // 保持调试工作区挂载，切换标签时保留当前会话。
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
    queryKey: ['runs', 'ui', targetScope, appId, ctx.projectId],
    queryFn: ({ signal }) =>
      fetchRuns(targetScope, 100, signal, { application_id: appId || undefined, project_id: ctx.projectId }),
    retry: false,
  })

  function openTaskOfRun(run: RunRecord) { setActiveRunId(run.id) }

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
  const runsPhase = pagePhase({
    isLoading: runsQuery.isLoading,
    isError: runsQuery.isError,
    count: uiRuns.length,
  })
  const runsEmptyCopy = uiRunsEmptyCopy(runsPhase, planned)

  // ---- 调试 tab：ready 设备清单（与 DevicesPage 同源 /api/v1/resources）----
  const resourcesQuery = useQuery({
    queryKey: ['resources', targetScope],
    queryFn: ({ signal }) => fetchResources(targetScope, signal, ctx.projectId),
    enabled: tab === 'debug',
    retry: false,
  })
  const readyDevices = useMemo(
    () => (resourcesQuery.data?.items ?? []).filter((item) => item.status === 'ready' && !item.busy),
    [resourcesQuery.data],
  )
  useEffect(() => {
    if (tab === 'debug' && !debugTarget && readyDevices[0]) setDebugTarget(toDebugTarget(readyDevices[0]))
  }, [tab, debugTarget, readyDevices])

  // ---- 套件 / 用例 tab ----
  // 后端 P2 起就有 GET /suites 与 /suites/{id}/versions；用例清单不在独立表里，
  // 而是 suite_versions.manifest.cases，所以"用例"页签读的是所选版本。
  const suitesQuery = useQuery({
    queryKey: ['suites', 'ui'],
    queryFn: ({ signal }) => fetchSuites('ui', signal, ctx.projectId),
    enabled: !planned && (tab === 'suites' || tab === 'cases'),
    retry: false,
  })
  const suites = useMemo(
    () => filterSuites(suitesQuery.data?.items ?? [], targetScope).filter((suite) => !appId || suite.application.id === appId),
    [suitesQuery.data, targetScope, appId],
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
  // 旧版本没有固定代码副本时不能执行：直接要求重新发现，不显示"未验证"就放行。
  const copyNotice = activeVersion ? versionCopyNotice(activeVersion) : null
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
          运行详情<span aria-hidden="true">›</span>
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
        <div className="flex"><LinkButton
          onClick={() => { setRunSuite(suite); setWizardOpen(true) }}
          disabled={!suite.latest_version}
          title={suite.latest_version ? undefined : '该套件还没有 discover 过，没有可运行的版本'}
        >运行套件</LinkButton><LinkButton
          onClick={() => openSuite(suite)}
          disabled={!suite.latest_version}
          title={suite.latest_version ? undefined : '该套件还没有 discover 过，没有用例可看'}
        >
          查看用例<span aria-hidden="true">›</span>
        </LinkButton></div>
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
        actions={<PrimaryAction label="新建任务" icon="plus" onClick={() => { setRunSuite(null); setWizardOpen(true) }} />}
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

      <div className="between mb"><Button size="small" onClick={() => setTab(tab === 'runs' ? 'suites' : 'runs')}>{tab === 'runs' ? '返回测试套件' : '查看执行记录'}</Button></div>
      <Tabs items={TABS} active={tab === 'cases' || tab === 'runs' ? 'suites' : tab} onChange={setTab} ariaLabel="UI 自动化视图" />

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
                  ? '跨会话管理图像模板与版本'
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
            {runsPhase === 'loading' ? (
              <Empty loading title={runsEmptyCopy.title} description={runsEmptyCopy.description} />
            ) : runsPhase === 'error' ? (
              <Empty title={runsEmptyCopy.title} description={runsEmptyCopy.description} />
            ) : uiRuns.length === 0 ? (
              <Empty
                icon="phone"
                title={runsEmptyCopy.title}
                description={runsEmptyCopy.description}
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
          <TemplateLibrary />
        ) : tab === 'suites' ? (
          <>
            {currentApp ? <div className="panel-pad"><SuiteRegistration key={currentApp.id} applicationId={currentApp.id} testType="ui" onRegistered={(id) => { setSuiteId(id); void queryClient.invalidateQueries({ queryKey: ['suites'] }); void queryClient.invalidateQueries({ queryKey: ['suite-versions'] }) }} /></div> : null}
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
                suitesQuery.isError ? (
                  <Empty
                    icon="layers"
                    title="套件清单暂不可用"
                    description="接口返回错误（见上方错误码），请稍后重试；这不代表没有登记套件。"
                  />
                ) : (
                  <Empty
                    icon="layers"
                    loading={suitesQuery.isLoading}
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
                )
              }
              footer={<span>共 {suites.length} 个套件 · 类型 {MODULE_NAMES.ui}</span>}
            />
          </>
        ) : tab === 'cases' ? (
          <>
            <div className="panel-pad"><Button size="small" onClick={() => setTab('suites')}>返回测试套件</Button></div>
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
                    </span>
                  ) : null}
                </Toolbar>
              </div>
            ) : null}
            {copyNotice ? (
              <div className="mb" style={{ padding: '0 20px' }}>
                <Notice tone="amber" title={'v' + (activeVersion?.version ?? '') + ' 没有固定代码副本'}>
                  {copyNotice}
                </Notice>
              </div>
            ) : null}
            <Table
              columns={caseColumns}
              rows={suiteCases}
              rowKey={(item, index) => item.case_key + ':' + index}
              ariaLabel="套件用例清单"
              empty={
                versionsQuery.isError ? (
                  <Empty
                    icon="layers"
                    title="用例清单暂不可用"
                    description="套件版本接口返回错误（见上方错误码），请稍后重试；这不代表该版本没有用例。"
                  />
                ) : (
                  <Empty
                    icon="layers"
                    loading={versionsQuery.isLoading}
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
                )
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
              // 关闭会话后回到套件：停留在调试页签会立刻按 ready 设备重建会话
              setTab('suites')
            }}
          />
        </div>
      ) : null}


      <TaskWizard
        initialApplicationId={appId ?? undefined}
        initialSuite={runSuite?.latest_version ? { applicationId: runSuite.application.id, suiteId: runSuite.id, suiteVersionId: runSuite.latest_version.id, platform: runSuite.application.platform as Platform, name: runSuite.name } : undefined}
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={handleCreated}
        initialPlatform={targetScope === 'all' ? 'android' : (targetScope as Platform)}
      />
      <RunDrawer key={activeRunId} open={Boolean(activeRunId)} runId={activeRunId} onClose={() => setActiveRunId(null)} />
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
