import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RunDrawer } from '../components/RunDrawer'
import { TaskWizard } from '../components/TaskWizard'
/**
 * 工作台（原型 #overview / L141–L185）。
 *
 * 数据源：GET /api/v1/overview（聚合计数，后端唯一口径）+ GET /api/v1/runs（活动运行列表）。
 *
 * 硬约束（frontend-spec.md §8）：
 * - 通过率取后端 pass_rate，分母为 0 时后端返回 null → 前端显示破折号，不显示 0%。
 * - 接口失败时统计卡显示破折号并在 Notice 里给出错误码，绝不用种子数据兜底。
 */
import { useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchOverview, fetchRuns } from '../api/endpoints'
import { useEffectiveContext } from '../store/effectiveContext'
import { Button } from '../components/Button'
import { Panel, PanelHead, PageHeading } from '../components/Card'
import { ContextBar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Icon } from '../components/Icon'
import { Notice } from '../components/Notice'
import { Progress } from '../components/Progress'
import { StatCard } from '../components/StatCard'
import { TargetChipRow } from '../components/TargetCard'
import { moduleName, SCOPE_OPTIONS, TARGET_CATALOG } from '../constants'
import { DASH, fmtDateTime } from '../lib/fmt'
import { displayStatus } from '../lib/display'
import { pagePhase, type PagePhase } from '../lib/pageState'
import { StatusBadge } from '../components/Badge'
import { useTargetScope } from '../store/scope'
import type { OverviewSummary, RunRecord, RunState } from '../types'

/** 执行中的状态集合（与后端 run_running 的统计口径一致） */
export const ACTIVE_STATES: RunState[] = ['queued', 'dispatching', 'running', 'finalizing']

interface EmptyCopy {
  title: string
  description: string
}

/**
 * 统计卡脚注：没有 overview 时区分「正在加载 / 调用失败 / 接口已返回但没数据」。
 * 绝不写成「接口未接入」—— 那会把加载中或网络失败误导成后端没上线。
 */
export function overviewFoot(overview: OverviewSummary | null | undefined, phase: PagePhase): string {
  if (overview) return `执行中 ${overview.run_running} 次 · 已登记应用 ${overview.application_total} 个`
  if (phase === 'loading') return '正在加载概览数据…'
  if (phase === 'error') return '概览接口调用失败，见上方错误码后重试'
  return '接口已连通但尚未返回计数（还没有运行记录）'
}

/** 通过率脚注：口径说明常在，加载/失败时先说清楚当前为什么没有值。 */
export function passRateFoot(overview: OverviewSummary | null | undefined, phase: PagePhase): string {
  if (overview) {
    if (overview.pass_rate === null) return '分母为 0：还没有已判定的运行，不显示 0%'
    return `已通过 ${overview.passed} ÷（已通过 + 未通过 ${overview.failed}）`
  }
  if (phase === 'loading') return '正在加载通过率…'
  if (phase === 'error') return '通过率获取失败，见上方错误码后重试'
  return '口径：已通过 ÷（已通过 + 未通过）；分母为 0 时显示破折号'
}

/** 「执行中的运行」面板占位文案 */
export function activeRunsCopy(phase: PagePhase): EmptyCopy {
  if (phase === 'loading') {
    return {
      title: '正在加载运行记录',
      description: '正在请求 GET /api/v1/runs；返回后只显示排队、下发、执行与收尾中的运行。',
    }
  }
  if (phase === 'error') {
    return {
      title: '运行记录暂不可用',
      description: '接口返回错误（见上方错误码），点「刷新概览」重试；不是「没有执行中的运行」。',
    }
  }
  return {
    title: '当前没有执行中的运行',
    description: '排队、下发、执行与收尾中的运行会出现在这里；已完成的运行见任务中心。',
  }
}

/** 「最近运行」面板占位文案 */
export function recentRunsCopy(phase: PagePhase): EmptyCopy {
  if (phase === 'loading') {
    return { title: '正在加载最近运行', description: '正在请求 GET /api/v1/runs；返回后按创建时间倒序显示。' }
  }
  if (phase === 'error') {
    return { title: '运行记录暂不可用', description: '接口返回错误（见上方错误码），点「刷新」重试。' }
  }
  return { title: '还没有运行记录', description: '提交第一个任务后，运行会出现在这里与任务中心。' }
}

export function OverviewPage() {
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const { targetScope, setTargetScope } = useTargetScope()
  const ctx = useEffectiveContext()

  const overviewQuery = useQuery({
    queryKey: ['overview', targetScope, ctx.projectId],
    queryFn: ({ signal }) => fetchOverview(targetScope === 'all' ? undefined : targetScope, signal, ctx.projectId),
    retry: false,
  })

  const runsQuery = useQuery({
    queryKey: ['runs', 'overview', targetScope, ctx.projectId],
    queryFn: ({ signal }) => fetchRuns(targetScope, 50, signal, { project_id: ctx.projectId }),
    retry: false,
  })

  const overview = overviewQuery.data
  const runs = runsQuery.data?.items ?? []
  const activeRuns = runs.filter((run) => ACTIVE_STATES.includes(run.state))
  // 加载 ≠ 空：四个统计卡与两个面板共用同一套阶段判定
  const overviewPhase = pagePhase({
    isLoading: overviewQuery.isLoading,
    isError: overviewQuery.isError,
    count: overview ? 1 : 0,
  })
  const runsPhase = pagePhase({
    isLoading: runsQuery.isLoading,
    isError: runsQuery.isError,
    count: runs.length,
  })

  const overviewError = overviewQuery.isError ? describeError(overviewQuery.error) : null
  const runsError = runsQuery.isError ? describeError(runsQuery.error) : null
  const scopeLabel = SCOPE_OPTIONS.find((option) => option.value === targetScope)?.label ?? '全部目标端'

  function refresh() {
    void overviewQuery.refetch()
    void runsQuery.refetch()
  }

  return (
    <>
      <RunDrawer key={activeRunId} open={Boolean(activeRunId)} runId={activeRunId} onClose={() => setActiveRunId(null)} />
      <TaskWizard open={wizardOpen} onClose={() => setWizardOpen(false)} onCreated={() => { setWizardOpen(false); refresh() }} initialPlatform={targetScope === 'all' ? 'android' : targetScope} />
      <PageHeading
        title="工作台"
        description="统一管理 Web 与移动应用的测试、执行资源与结果证据。"
        actions={
          <><Button onClick={refresh}>刷新概览</Button><Button kind="primary" icon="plus" onClick={() => setWizardOpen(true)}>新建测试任务</Button></>
        }
      />

      <ContextBar
        scope={targetScope}
        onScopeChange={setTargetScope}
        extra={<span className="muted small">仅展示当前目标端的数据</span>}
      />

      {/* 渐进式披露：目标端从三张大卡压缩为一行 chips，能力说明收进 chip 内 */}
      <div className="mb">
        <div className="between" style={{ marginBottom: 8 }}>
          <h2>目标端</h2>
          <span className="muted small">当前：{scopeLabel}</span>
        </div>
        <TargetChipRow scope={targetScope} onSelect={setTargetScope} />
      </div>

      {overviewError ? (
        <div className="mb">
          <Notice tone="red" title={'概览数据获取失败（' + overviewError.code + '）'}>
            {overviewError.message}
            {overviewError.requestId ? <div className="mono small">request_id: {overviewError.requestId}</div> : null}
          </Notice>
        </div>
      ) : null}

      <div className="stats">
        <StatCard
          label="运行记录"
          value={overview ? overview.run_total : null}
          foot={overviewFoot(overview, overviewPhase)}
        />
        <StatCard
          label="通过率"
          value={overview?.pass_rate ?? null}
          unit="%"
          foot={passRateFoot(overview, overviewPhase)}
        />
        <StatCard
          label="需要关注"
          value={overview ? overview.needs_attention : null}
          foot={overview ? `未通过 ${overview.failed} + 未判定 ${overview.not_tested}` : '未通过 + 未判定'}
          extra={
            <Link className="link-btn" to="/reports" aria-label="查看需要关注的报告">
              查看报告 ›
            </Link>
          }
        />
        <StatCard
          label="执行中"
          value={overview ? overview.run_running : null}
          foot="排队 / 下发 / 执行 / 收尾中的运行"
        />
      </div>

      <div className="grid-2 mb">
        <Panel>
          <PanelHead
            title="执行中的运行"
            hint="进度来自 run_components 的真实完成比例，不是前端模拟"
            actions={
              <Button size="small" onClick={refresh}>
                刷新
              </Button>
            }
          />
          {runsPhase === 'error' ? (
            <Notice tone="red" title={'运行数据获取失败（' + runsError?.code + '）'}>
              {runsError?.message}
            </Notice>
          ) : runsPhase === 'loading' ? (
            <Empty loading title={activeRunsCopy('loading').title} description={activeRunsCopy('loading').description} />
          ) : activeRuns.length === 0 ? (
            <Empty
              icon="pulse"
              title={activeRunsCopy('ready').title}
              description={activeRunsCopy('ready').description}
            />
          ) : (
            <ul className="run-mini-list">
              {activeRuns.map((run) => (
                <li key={run.id}>
                  <div className="between">
                    <Button size="small" onClick={() => setActiveRunId(run.id)}>{run.name}</Button>
                    <StatusBadge status={displayStatus(run.state, run.outcome)} />
                  </div>
                  <div className="task-sub">
                    {run.display_id} · {TARGET_CATALOG[run.platform]?.label ?? run.platform} ·{' '}
                    {moduleName(run.test_type)}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Progress value={run.progress} />
                  </div>
                  <div className="task-sub" style={{ marginTop: 4 }}>
                    {run.resource ?? '未分配资源'} · 进度 {run.progress === null ? DASH : run.progress + '%'}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel>
          <PanelHead title="最近运行" hint="按创建时间倒序，最多 50 条" />
          {runsPhase === 'loading' ? (
            <Empty loading title={recentRunsCopy('loading').title} description={recentRunsCopy('loading').description} />
          ) : runsPhase === 'error' ? (
            // 错误码由左侧「执行中的运行」面板的 Notice 统一展示，这里只说明该面板为什么空
            <Empty title={recentRunsCopy('error').title} description={recentRunsCopy('error').description} />
          ) : runs.length === 0 ? (
            <Empty
              icon="tasks"
              title={recentRunsCopy('empty').title}
              description={recentRunsCopy('empty').description}
              actions={
                <Button kind="primary" icon="plus" onClick={() => setWizardOpen(true)}>
                  新建测试任务
                </Button>
              }
            />
          ) : (
            <ul className="run-mini-list">
              {runs.slice(0, 6).map((run: RunRecord) => (
                <li key={run.id}>
                  <div className="between">
                    <Button size="small" onClick={() => setActiveRunId(run.id)}>{run.name}</Button>
                    <StatusBadge status={displayStatus(run.state, run.outcome)} />
                  </div>
                  <div className="task-sub">
                    {run.display_id} · {fmtDateTime(run.created_at)} · {run.resource ?? '未分配资源'}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="grid-2">
        <Panel>
          <PanelHead title="UI 自动化" hint="进入用例、套件与执行记录" />
          <p className="muted">
            用例失败会保留现场：截图、日志与步骤断言逐条可追溯。
          </p>
          <div className="muted small">
            目标端：Android / iOS / Web · 已接入：Android UI 自动化与性能采集
          </div>
          <Link className="link-btn" to="/ui">进入 UI 自动化 ›</Link>
        </Panel>
        <Panel>
          <PanelHead title="性能测试" hint="门禁判定全部由后端完成" />
          <p className="muted">
            指标与基线可比性随报告给结论，结论来自 gate_evaluations。
          </p>
          <div className="muted small">
            <Icon name="pulse" size={13} /> 指标：内存 / CPU / 帧率 / GPU
          </div>
          <Link className="link-btn" to="/perf">进入性能测试 ›</Link>
        </Panel>
      </div>

      <div className="mt">
        <Panel>
          <PanelHead title="口径说明" />
          <dl className="glossary">
            <dt>通过率</dt>
            <dd>只统计已完成且已判定的运行：已通过 ÷（已通过 + 未通过）。</dd>
            <dt>未判定</dt>
            <dd>样本不足或基线不可比时后端给出 not_tested，不折算为失败。</dd>
            <dt>缺失指标</dt>
            <dd>指标缺失或设备不支持时显示原因，不显示为 0。</dd>
          </dl>
          <div className="muted small">
            数据源：/api/v1/overview · /api/v1/runs · 目标端 {scopeLabel}
          </div>
        </Panel>
      </div>
    </>
  )
}
