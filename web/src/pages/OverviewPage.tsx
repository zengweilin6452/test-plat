import { useState } from 'react'
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
import { Button } from '../components/Button'
import { Panel, PanelHead, PageHeading } from '../components/Card'
import { ContextBar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Icon } from '../components/Icon'
import { Notice } from '../components/Notice'
import { Progress } from '../components/Progress'
import { StatCard } from '../components/StatCard'
import { TargetCardGrid } from '../components/TargetCard'
import { moduleName, SCOPE_OPTIONS, TARGET_CATALOG } from '../constants'
import { DASH, fmtDateTime } from '../lib/fmt'
import { displayStatus } from '../lib/display'
import { StatusBadge } from '../components/Badge'
import { useTargetScope } from '../store/scope'
import type { RunRecord, RunState } from '../types'

/** 执行中的状态集合（与后端 run_running 的统计口径一致） */
export const ACTIVE_STATES: RunState[] = ['queued', 'dispatching', 'running', 'finalizing']

export function OverviewPage() {
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const { targetScope, setTargetScope } = useTargetScope()

  const overviewQuery = useQuery({
    queryKey: ['overview', targetScope],
    queryFn: ({ signal }) => fetchOverview(targetScope === 'all' ? undefined : targetScope, signal),
    retry: false,
  })

  const runsQuery = useQuery({
    queryKey: ['runs', 'overview', targetScope],
    queryFn: ({ signal }) => fetchRuns(targetScope, 50, signal),
    retry: false,
  })

  const overview = overviewQuery.data
  const runs = runsQuery.data?.items ?? []
  const activeRuns = runs.filter((run) => ACTIVE_STATES.includes(run.state))

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

      <div className="mb">
        <div className="between" style={{ marginBottom: 12 }}>
          <h2>目标端</h2>
          <span className="muted small">当前：{scopeLabel}</span>
        </div>
        <TargetCardGrid scope={targetScope} onSelect={setTargetScope} />
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
          foot={overview ? `执行中 ${overview.run_running} 次 · 已登记应用 ${overview.application_total} 个` : '接口未接入'}
        />
        <StatCard
          label="通过率"
          value={overview?.pass_rate ?? null}
          unit="%"
          foot={overview ? `已通过 ${overview.passed} ÷（已通过 + 未通过 ${overview.failed}）` : '口径：已通过 ÷（已通过 + 未通过）'}
        />
        <StatCard
          label="需要关注"
          value={overview ? overview.needs_attention : null}
          foot={overview ? `未通过 ${overview.failed} + 未判定 ${overview.not_tested}` : '未通过 + 未判定'}
          extra={
            <a className="link-btn" href="#/reports" aria-label="查看需要关注的报告">
              查看报告 ›
            </a>
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
          {runsError ? (
            <Notice tone="red" title={'运行数据获取失败（' + runsError.code + '）'}>
              {runsError.message}
            </Notice>
          ) : activeRuns.length === 0 ? (
            <Empty
              icon="pulse"
              title="当前没有执行中的运行"
              description="排队、下发、执行与收尾中的运行会出现在这里；已完成的运行见任务中心。"
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
          {runs.length === 0 && !runsError ? (
            <Empty
              icon="tasks"
              title="还没有运行记录"
              description="提交第一个任务后，运行会出现在这里与任务中心。"
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
            目标端：Android / iOS / Web · 已接入：{TARGET_CATALOG.android.capability}
          </div>
          <a className="link-btn" href="#/ui">进入 UI 自动化 ›</a>
        </Panel>
        <Panel>
          <PanelHead title="性能测试" hint="门禁判定全部由后端完成" />
          <p className="muted">
            指标与基线可比性随报告给结论，结论来自 gate_evaluations。
          </p>
          <div className="muted small">
            <Icon name="pulse" size={13} /> 指标：内存 / CPU / 帧率 / GPU
          </div>
          <a className="link-btn" href="#/perf">进入性能测试 ›</a>
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
