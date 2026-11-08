/**
 * 性能测试（原型 #perf / L104–L230）。
 *
 * 重要：原型里 perfVerdict() 是前端算门禁；平台侧**不这么做**。
 * 页面只展示后端 gate_evaluations 给的结论：
 * - 样本不足或基线不可比时后端返回 not_tested，前端原样显示「未判定」；
 * - 指标缺失（如 GPU 不支持）显示原因，不显示 0。
 *
 * 数据源（routers/analyses.py）：
 * - GET /analyses?run_id= —— 单次运行分析：原始判定、checks、median 指标、基线候选；
 * - POST /runs/{id}/gate-evaluations —— 规则试算：只新增判定行，不改写历史报告；
 * - GET /analyses?run_id=&evaluation_id= —— 切到某条试算判定查看。
 *
 * 后端枚举是 ui / performance / joint，不是前端向导内部的 'perf'；
 * 联动（joint）运行同样产出性能组件与门禁结论，因此一并列出。
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request, describeError } from '../api/client'
import { createGateEvaluation, fetchAnalysis, fetchRuns } from '../api/endpoints'
import { Badge, StatusBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Disclosure } from '../components/Disclosure'
import { ContextBar, PlannedNotice, PrimaryAction } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Tabs } from '../components/Tabs'
import { useEffectiveContext } from '../store/effectiveContext'
import { Table, type Column } from '../components/Table'
import { RunDrawer } from '../components/RunDrawer'
import { TaskWizard, newRequestKey } from '../components/TaskWizard'
import { useToast } from '../components/Toast'
import { TARGET_CATALOG, isImplementedPlatform, isPerformanceType, moduleName } from '../constants'
import { displayStatus } from '../lib/display'
import { DASH, fmtDateTime } from '../lib/fmt'
import { pagePhase, type PagePhase } from '../lib/pageState'
import { useTargetScope } from '../store/scope'
import type {
  AnalysisMetric,
  GateCheck,
  RunAnalysis,
} from '../api/types'
import type { CreateTaskResponse, Platform, RunOutcome, RunRecord } from '../types'

/** 指标口径展示名；未登记的 key 原样显示，不猜单位 */
const METRIC_LABELS: Record<string, string> = {
  mem_pss_mb: 'PSS 内存',
  cpu_process_pct: '进程 CPU',
  fps_frame: '帧率',
  gpu_util_pct: 'GPU 占用',
  gpu_mem_mb: 'GPU 显存',
  temp_battery_c: '电池温度',
  net_rx_total_kb: '网络累计收',
  net_tx_total_kb: '网络累计发',
  net_conn_duration_ms: '连接建立耗时',
  app_cold_start_ms: '冷启动耗时',
  app_warm_start_ms: '热启动耗时',
  page_load_ms: '整页加载耗时',
  api_req_duration_ms: '接口请求耗时',
  api_req_count: '接口请求数',
  api_error_rate_pct: '接口错误率',
  api_payload_kb: '接口载荷',
  app_jank_light_count: '轻微卡顿数',
  app_jank_heavy_count: '重度卡顿数',
  app_jank_severe_count: '严重卡顿数',
  app_frame_p50_ms: '帧耗时 P50',
  app_frame_p90_ms: '帧耗时 P90',
  app_frame_p99_ms: '帧耗时 P99',
  app_frame_jank_ratio_pct: '卡顿帧占比',
  app_frame_count: '帧总数',
}

const OP_TEXT: Record<string, string> = { lt: '<', le: '≤', gt: '>', ge: '≥' }

function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key
}

function verdictText(verdict: string | null | undefined): string {
  if (verdict === 'passed') return '通过'
  if (verdict === 'failed') return '未通过'
  if (verdict === 'not_tested') return '未判定'
  return '尚未判定'
}

function verdictTone(verdict: string | null | undefined): 'green' | 'red' | 'amber' | 'blue' {
  if (verdict === 'passed') return 'green'
  if (verdict === 'failed') return 'red'
  if (verdict === 'not_tested') return 'amber'
  return 'blue'
}

export function PerfPage() {
  const ctx = useEffectiveContext()
  return <ScopedPerfPage key={`${ctx.projectId ?? 'all'}:${ctx.appId ?? 'none'}`} />
}

function ScopedPerfPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const ctx = useEffectiveContext()
  const appId = ctx.appId
  const [tab, setTab] = useState<'analysis' | 'baseline'>('analysis')
  const [policyId, setPolicyId] = useState('')
  const planned = !isImplementedPlatform(targetScope)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  // 分析页状态：选中运行 / 选中的判定（试算后切到那条）/ 试算用基线
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [evaluationId, setEvaluationId] = useState<string | null>(null)
  const [baselineRunId, setBaselineRunId] = useState('')
  const queryClient = useQueryClient()
  const toast = useToast()

  const runsQuery = useQuery({
    queryKey: ['runs', 'perf', targetScope, appId, ctx.projectId],
    queryFn: ({ signal }) => fetchRuns(targetScope, 100, signal, { application_id: appId || undefined, project_id: ctx.projectId }),
    retry: false,
  })

  function openTaskOfRun(run: RunRecord) { setActiveRunId(run.id) }

  function handleCreated(created: CreateTaskResponse) {
    toast.show('任务已创建：' + created.display_id + '（编号 ' + created.id + '）', 'success')
    setWizardOpen(false)
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    void queryClient.invalidateQueries({ queryKey: ['runs'] })
  }

  const error = runsQuery.isError ? describeError(runsQuery.error) : null
  const perfRuns = useMemo(
    () =>
      (runsQuery.data?.items ?? []).filter(
        (run) => isPerformanceType(run.test_type) || run.test_type === 'joint',
      ),
    [runsQuery.data],
  )

  // 默认分析第一条已结束的运行；换了运行就回到原始判定
  const finishedRuns = perfRuns.filter((run) => run.state === 'completed')
  // 加载 ≠ 空：两个区块各自按 runs 查询的阶段渲染
  const runsPhase = pagePhase({
    isLoading: runsQuery.isLoading,
    isError: runsQuery.isError,
    count: perfRuns.length,
  })
  const finishedPhase = pagePhase({
    isLoading: runsQuery.isLoading,
    isError: runsQuery.isError,
    count: finishedRuns.length,
  })
  const analysisEmptyCopy = perfAnalysisEmptyCopy(finishedPhase, planned)
  const runsEmptyCopy = perfRunsEmptyCopy(runsPhase, planned)
  const currentRunId = selectedRunId ?? finishedRuns[0]?.id ?? null
  useEffect(() => {
    setEvaluationId(null)
    setBaselineRunId('')
  }, [currentRunId])

  const analysisQuery = useQuery({
    queryKey: ['analysis', currentRunId, evaluationId],
    queryFn: ({ signal }) => fetchAnalysis(currentRunId!, evaluationId, signal),
    enabled: Boolean(currentRunId),
    retry: false,
  })
  const analysisError = analysisQuery.isError ? describeError(analysisQuery.error) : null
  const analysis: RunAnalysis | null = analysisQuery.data ?? null
  useEffect(() => { setPolicyId('') }, [analysis?.run.application_id])

  const trialMutation = useMutation({
    mutationFn: () =>
      createGateEvaluation(currentRunId!, {
        request_key: newRequestKey(),
        baseline_run_id: baselineRunId || null,
        policy_id: policyId || null,
      }),
    onSuccess: (result) => {
      const id = result.evaluation_id ?? result.id
      setEvaluationId(id)
      toast.show('试算完成：' + verdictText(result.verdict) + '（未改写历史报告）', 'success')
      void queryClient.invalidateQueries({ queryKey: ['analysis', currentRunId] })
    },
    onError: (mutationError) => {
      const described = describeError(mutationError)
      toast.show('试算失败（' + described.code + '）：' + described.message, 'error')
    },
  })

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
      key: 'module',
      header: '类型',
      // 性能页同时列出联动运行（joint）：不标出来会被读成纯性能任务
      render: (run) => <span className="muted small">{moduleName(run.test_type)}</span>,
    },
    {
      key: 'verdict',
      header: '门禁结论',
      render: (run) => <StatusBadge status={displayStatus(run.state, run.outcome)} />,
    },
    {
      key: 'reason',
      header: '原因',
      wrap: true,
      render: (run) => (
        <span className="muted small">
          {run.reason_code ?? run.not_tested_reason ?? DASH}
        </span>
      ),
    },
    {
      key: 'time',
      header: '创建时间',
      render: (run) => <span className="muted small">{fmtDateTime(run.created_at)}</span>,
    },
  ]

  return (
    <>
      <PageHeading
        title="性能测试"
        description="性能指标与门禁结论：阈值由后端评估，页面只做展示"
        actions={<PrimaryAction label="新建任务" icon="plus" onClick={() => setWizardOpen(true)} />}
      />
      <ContextBar
        scope={targetScope}
        onScopeChange={setTargetScope}
        extra={<span className="muted small">门禁结论来自 gate_evaluations</span>}
      />

      {planned ? (
        <div className="mb">
          <PlannedNotice scope={targetScope} />
        </div>
      ) : null}

      {/* 渐进式披露：判定规则的完整说明默认收起，首屏只留一行入口（规则 1/4） */}
      <div className="mb">
        <Disclosure title="为什么结论可能是「未判定」？" summary="判定规则说明">
          <Notice tone="blue" icon="alert" title="门禁结论不在前端计算">
            性能结论由后端根据阈值与基线评估后写入 gate_evaluations。样本不足或基线不可比时结论为「未判定」，
            页面不会把它显示成未通过或已通过；指标缺失会显示具体原因，而不是 0。
          </Notice>
        </Disclosure>
      </div>

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'性能运行获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      <Tabs items={[{ value: 'analysis', label: '运行分析' }, { value: 'baseline', label: '基线与门禁' }]} active={tab} onChange={setTab} ariaLabel="性能测试视图" />
      <div style={{ display: tab === 'baseline' ? undefined : 'none' }}>
        <Panel className="mb"><PanelHead title="基线管理" hint="从已完成的性能或联动运行保存真实指标与设备档案" /><div className="panel-pad"><BaselineManager key={analysis?.run.application_id ?? appId ?? 'none'} applicationId={analysis?.run.application_id ?? appId} runs={finishedRuns} initialRunId={currentRunId} onSelected={setBaselineRunId} /></div></Panel>
        <Panel className="mb"><PanelHead title="门禁策略" hint="保存生成新版本，历史报告仍使用原始策略" /><div className="panel-pad"><PolicyEditor key={analysis?.run.application_id ?? appId ?? 'none'} applicationId={analysis?.run.application_id ?? appId} onSelected={setPolicyId} /></div></Panel>
      </div>
      <Panel>
        <PanelHead
          title={tab === 'analysis' ? '运行分析' : '基线对比与试算'}
          hint="指标取 median；门禁逐项来自后端 checks，试算只新增判定行"
          actions={
            currentRunId ? (
              <a className="link-btn" href={`/api/v1/runs/${currentRunId}/report/export`} download>
                导出报告 JSON
              </a>
            ) : null
          }
        />

        {finishedRuns.length === 0 ? (
          finishedPhase === 'loading' ? (
            <Empty loading title={analysisEmptyCopy.title} description={analysisEmptyCopy.description} />
          ) : (
            <Empty
              title={analysisEmptyCopy.title}
              description={analysisEmptyCopy.description}
            />
          )
        ) : (
          <div style={{ padding: '0 20px 20px' }}>
            <div className="toolbar">
              <select
                aria-label="选择性能运行"
                value={currentRunId ?? ''}
                onChange={(event) => setSelectedRunId(event.target.value || null)}
              >
                {finishedRuns.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.display_id} / {run.name}
                  </option>
                ))}
              </select>
              {analysis?.context?.device_profile ? (
                <Badge tone="gray">{analysis.context.device_profile}</Badge>
              ) : null}
              {evaluationId ? (
                <>
                  <Badge tone="blue" dot>试算判定</Badge>
                  <Button size="small" onClick={() => setEvaluationId(null)}>
                    恢复原始判定
                  </Button>
                </>
              ) : null}
            </div>

            {analysisError ? (
              <Notice tone="red" title={'分析获取失败（' + analysisError.code + '）'}>
                {analysisError.message}
              </Notice>
            ) : analysisQuery.isLoading ? (
              <Empty loading icon="pulse" title="正在加载运行分析" description="正在请求 GET /api/v1/analyses?run_id=" />
            ) : analysis ? (
              <>
                <VerdictNotice analysis={analysis} />
                {tab === 'analysis' ? <><MetricCards analysis={analysis} /><LeakTrendCard analysis={analysis} /><ChecksTable analysis={analysis} /></> : null}
                <div className="content-grid mt">
                  <ContextCard analysis={analysis} />
                  <TrialCard
                    analysis={analysis}
                    baselineRunId={baselineRunId}
                    onBaselineChange={setBaselineRunId}
                    onTrial={() => trialMutation.mutate()}
                    pending={trialMutation.isPending}
                    canTrial={Boolean(currentRunId && policyId && baselineRunId)}
                  />
                </div>
              </>
            ) : null}
          </div>
        )}
      </Panel>

      <div className="mt">
        <Panel>
          <PanelHead
            title="性能运行"
            hint="指标口径：PSS 内存 / 应用进程 CPU / 帧率 / GPU 占用"
          />
          {perfRuns.length === 0 ? (
            runsPhase === 'loading' ? (
              <Empty loading title={runsEmptyCopy.title} description={runsEmptyCopy.description} />
            ) : (
              <Empty
                title={runsEmptyCopy.title}
                description={runsEmptyCopy.description}
                actions={
                  planned ? null : (
                    <Link className="btn" to="/tasks">
                      前往任务中心发起运行
                    </Link>
                  )
                }
              />
            )
          ) : (
            <Table
              columns={columns}
              rows={perfRuns}
              rowKey={(run) => run.id}
              ariaLabel="性能运行"
              onRowClick={openTaskOfRun}
              footer={<span>共 {perfRuns.length} 条性能 / 联动运行</span>}
            />
          )}
        </Panel>
      </div>

      <TaskWizard
        initialModule="perf"
        initialApplicationId={appId ?? undefined}
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={handleCreated}
        initialPlatform={targetScope === 'all' ? 'android' : (targetScope as Platform)}
      />
      <RunDrawer key={activeRunId} open={Boolean(activeRunId)} runId={activeRunId} onClose={() => setActiveRunId(null)} />
    </>
  )
}

/** 原始判定 / 试算判定的结论条：只转述后端结论，不自行判定 */
function VerdictNotice({ analysis }: { analysis: RunAnalysis }) {
  const verdict = analysis.verdict ?? null
  const trial = analysis.mode === 'reanalysis'
  const runOutcome: RunOutcome | null = (analysis.run.outcome as RunOutcome | null) ?? null
  return (
    <Notice
      tone={verdictTone(verdict)}
      title={(trial ? '当前规则试算：' : '门禁结论：') + verdictText(verdict)}
    >
      <div>{analysis.reason_text ?? analysis.reason ?? '后端未给出原因文本'}</div>
      <div className="small muted" style={{ marginTop: 4 }}>
        原始运行结论：{runOutcome ? verdictText(runOutcome) : '后端尚未给出结论'}
        {analysis.original_missing ? '（该运行还没有原始判定行）' : ''}
        {trial ? '。切换基线或规则只影响分析，不改写历史报告。' : ''}
      </div>
    </Notice>
  )
}

/** 指标卡：median 缺失时显示 missing_reason，基线差值取同一条 check 的 baselineValue */
function MetricCards({ analysis }: { analysis: RunAnalysis }) {
  const metrics = analysis.metrics ?? []
  const checkByKey = useMemo(() => {
    const map = new Map<string, GateCheck>()
    for (const check of analysis.checks ?? []) map.set(check.metricKey, check)
    return map
  }, [analysis.checks])

  if (metrics.length === 0) {
    return (
      <div className="mb">
        <Empty
          icon="pulse"
          title="该运行没有性能指标"
          description="后端 metric_summaries 没有该运行的 median 行（可能没有性能组件）。"
        />
      </div>
    )
  }

  return (
    <div className="metric-grid">
      {metrics.map((metric) => {
        const check = checkByKey.get(metric.metric_key)
        return (
          <MetricCard key={metric.metric_key} metric={metric} check={check} />
        )
      })}
    </div>
  )
}

const LEAK_CONFIDENCE_LABELS: Record<string, string> = {
  ok: '可信',
  low: '仅供参考',
  insufficient: '样本不足',
}

/** 泄漏趋势：vendor leak 同口径的平台侧实现（OLS 斜率，只展示不判定门禁） */
function LeakTrendCard({ analysis }: { analysis: RunAnalysis }) {
  const trend = analysis.leakTrend
  if (!trend) return null
  const confidence = typeof trend.confidence === 'string' ? trend.confidence : 'insufficient'
  const label = LEAK_CONFIDENCE_LABELS[confidence] ?? confidence
  const slope = typeof trend.slopeMbPerDay === 'number' ? trend.slopeMbPerDay : null
  return (
    <div className="mb">
      <Notice tone={confidence === 'ok' ? 'blue' : 'amber'} title={`内存泄漏趋势 · ${label}`}>
        {slope !== null ? (
          <>mem_pss_mb 中位数历史序列 OLS 斜率 <strong className="mono">{slope} MB/天</strong>（{trend.runCount} 次运行，跨度 {trend.spanHours} 小时）。</>
        ) : (
          <>{trend.confidenceReason ?? '历史样本不足，无法估计趋势。'}</>
        )}
        {slope !== null && typeof trend.confidenceReason === 'string' ? (
          <div className="muted small">{trend.confidenceReason}</div>
        ) : null}
        <div className="muted small">趋势只做参考展示；门禁结论仍由后端 gate_evaluations 判定，本卡片不参与判定。</div>
      </Notice>
    </div>
  )
}

function MetricCard({ metric, check }: { metric: AnalysisMetric; check?: GateCheck }) {
  const missing = metric.median === null || metric.median === undefined
  const baseline = check?.baselineValue
  const diff =
    !missing && typeof baseline === 'number' && baseline !== 0
      ? ((Number(metric.median) - baseline) / baseline) * 100
      : null
  return (
    <div className="metric-card">
      <span className="small muted">{metricLabel(metric.metric_key)}</span>
      <span className="value">
        {missing ? '—' : metric.median} <small>{metric.unit ?? ''}</small>
      </span>
      <span className={'metric-change ' + (missing ? 'muted' : '')}>
        {missing
          ? metric.missing_reason_text ?? metric.missing_reason ?? '未采集到该指标'
          : diff === null
            ? '无基线参照'
            : (diff >= 0 ? '+' : '') + diff.toFixed(1) + '% 较基线'}
      </span>
    </div>
  )
}

/** 门禁逐项：级别 fail / warn 与是否满足都由后端给出 */
function ChecksTable({ analysis }: { analysis: RunAnalysis }) {
  const checks = analysis.checks ?? []
  return (
    <div className="mt">
      <h3 style={{ fontSize: 14 }}>质量门禁 · 逐项检查</h3>
      {checks.length === 0 ? (
        <div className="muted small mt">
          后端未给出 checks（{analysis.reason_text ?? analysis.reason ?? '未判定'}）。
        </div>
      ) : (
        <div className="table-wrap mt">
          <table className="task-table">
            <thead>
              <tr>
                <th>指标</th>
                <th>中位数</th>
                <th>绝对阈值</th>
                <th>级别</th>
                <th>样本数</th>
                <th>检查结果</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((check) => (
                <tr key={check.metricKey}>
                  <td>
                    {metricLabel(check.metricKey)}
                    <div className="task-sub mono">{check.metricKey}</div>
                  </td>
                  <td>{check.median ?? DASH}</td>
                  <td className="mono">
                    {OP_TEXT[check.op ?? ''] ?? check.op ?? DASH} {check.threshold ?? DASH}
                  </td>
                  <td>{check.level === 'warn' ? '告警' : check.level === 'fail' ? '阻断' : DASH}</td>
                  <td>{check.sampleCount ?? DASH}</td>
                  <td>
                    {check.ok === null || check.ok === undefined ? (
                      <Badge tone="gray">未参与判定</Badge>
                    ) : check.ok ? (
                      <Badge tone="green" dot>满足阈值</Badge>
                    ) : check.level === 'warn' ? (
                      <Badge tone="amber" dot>告警，不阻断</Badge>
                    ) : (
                      <Badge tone="red" dot>阈值未满足</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** 运行上下文：全部来自后端 analysis.run / analysis.context */
function ContextCard({ analysis }: { analysis: RunAnalysis }) {
  const context = analysis.context ?? {}
  return (
    <section className="panel panel-pad">
      <h3 style={{ fontSize: 14 }}>运行上下文</h3>
      <dl className="kv mt">
        <dt>任务</dt>
        <dd>{analysis.run.task_name ?? DASH}</dd>
        <dt>类型</dt>
        <dd>{moduleName(analysis.run.test_type ?? '')}</dd>
        <dt>设备档案</dt>
        <dd>
          {context.device_profile ?? DASH}
          {context.device_profile_error ? (
            <span className="muted small">（{context.device_profile_error}）</span>
          ) : null}
        </dd>
        <dt>窗口</dt>
        <dd>{context.window ?? DASH}</dd>
        <dt>统计口径</dt>
        <dd>{context.statistic ?? DASH}</dd>
        <dt>判定模式</dt>
        <dd>{analysis.mode === 'reanalysis' ? '试算（reanalysis）' : analysis.mode === 'original' ? '原始判定' : DASH}</dd>
      </dl>
    </section>
  )
}

/** 规则试算：选基线 → POST gate-evaluations，只新增判定行 */
function TrialCard({
  analysis,
  baselineRunId,
  onBaselineChange,
  onTrial,
  pending,
  canTrial,
}: {
  analysis: RunAnalysis
  baselineRunId: string
  onBaselineChange: (value: string) => void
  onTrial: () => void
  pending: boolean
  canTrial: boolean
}) {
  const options = analysis.baseline_options ?? []
  return (
    <section className="panel panel-pad">
      <h3 style={{ fontSize: 14 }}>规则试算</h3>
      <p className="small muted" style={{ margin: '8px 0 13px' }}>
        保存后新增一条判定行，用于对比；不修改历史报告或既有原始判定。
      </p>
      <label className="field">
        <span className="field-label">对比基线</span>
        <select
          aria-label="试算基线"
          value={baselineRunId}
          onChange={(event) => onBaselineChange(event.target.value)}
        >
          <option value="">请选择明确的基线</option>
          {baselineRunId && !options.some((option) => option.source_run_id === baselineRunId) ? <option value={baselineRunId}>已选基线来源：{baselineRunId}</option> : null}
          {options.map((option) => (
            <option key={option.id} value={option.source_run_id ?? ''}>
              {option.baseline_name ?? '基线'}
              {option.version !== null && option.version !== undefined ? ` v${option.version}` : ''}
              {option.same_profile ? ' · 同设备档案' : ' · 档案不匹配'}
            </option>
          ))}
        </select>
      </label>
      <div className="mt">
        <Button kind="primary" disabled={!canTrial || pending} title={canTrial ? undefined : '先在「基线与门禁」选择已保存的策略与基线'} onClick={onTrial}>
          {pending ? '试算中…' : '按此基线试算'}
        </Button>
      </div>
      <p className="small muted mt">
        先在「基线与门禁」选择策略与基线，再提交试算。告警级不阻断；具体结论与原因由后端返回。
      </p>
    </section>
  )
}

interface GatePolicyView {
  id: string
  name: string
  version: number
  thresholds: Record<string, [string, number, string]>
  min_samples: number | null
  rules_error?: string | null
}

function PolicyEditor({ applicationId, onSelected }: { applicationId: string | null | undefined; onSelected: (id: string) => void }) {
  const client = useQueryClient()
  const [selected, setSelected] = useState('')
  const [dirty, setDirty] = useState(false)
  const [rows, setRows] = useState<{ key: string; op: string; value: string; level: string }[]>([])
  const [minimum, setMinimum] = useState('10')
  const [name, setName] = useState('default')
  const policies = useQuery({
    queryKey: ['gate-policies', applicationId],
    queryFn: ({ signal }) => request<{ items: GatePolicyView[] }>('/gate-policies', { query: { application_id: applicationId }, signal }),
    enabled: Boolean(applicationId), retry: false,
  })
  function selectPolicy(id: string) {
    setDirty(false)
    setSelected(id)
    onSelected(id)
    const policy = policies.data?.items.find((item) => item.id === id)
    setName(policy?.name ?? 'default')
    setMinimum(String(policy?.min_samples ?? 10))
    setRows(Object.entries(policy?.thresholds ?? {}).map(([key, [op, value, level]]) => ({ key, op, value: String(value), level })))
  }
  const save = useMutation({
    mutationFn: () => request<GatePolicyView>(selected ? `/gate-policies/${encodeURIComponent(selected)}` : '/gate-policies', {
      method: selected ? 'PUT' : 'POST',
      body: { application_id: applicationId, name: name.trim(), rules: { min_samples: Number(minimum), thresholds: rows.map((row) => ({ metric_key: row.key.trim(), op: row.op, threshold: Number(row.value), level: row.level })) } },
    }),
    onSuccess: async (policy) => {
      await client.invalidateQueries({ queryKey: ['gate-policies', applicationId] })
      setSelected(policy.id)
      setDirty(false)
      onSelected(policy.id)
    },
  })
  if (!applicationId) return <div className="muted small">请选择应用工作区或已完成运行，再管理门禁策略。</div>
  const valid = name.trim() && Number.isInteger(Number(minimum)) && Number(minimum) > 0 && rows.length > 0 && rows.every((row) => row.key.trim() && row.value.trim() && Number.isFinite(Number(row.value))) && new Set(rows.map((row) => row.key.trim())).size === rows.length
  return <>
    {policies.isError ? <Notice tone="red" title="策略加载失败">{describeError(policies.error).message}</Notice> : null}
    <label className="field"><span>策略版本</span><select aria-label="选择门禁策略" disabled={save.isPending} value={selected} onChange={(event) => { save.reset(); selectPolicy(event.target.value) }}><option value="">新建策略</option>{policies.data?.items.map((policy) => <option key={policy.id} value={policy.id}>{policy.name} v{policy.version}</option>)}</select></label>
    {dirty ? <p className="small muted" role="status">规则有未保存修改，保存为新版本后才能试算；也可重新选择已保存版本。</p> : null}
    <fieldset disabled={save.isPending} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} onChange={() => { setDirty(true); onSelected(''); save.reset() }}>
    <div className="form-grid mt"><label className="field"><span>策略名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="field"><span>最少样本数</span><input type="number" min="1" step="1" value={minimum} onChange={(event) => setMinimum(event.target.value)} /></label></div>
    {rows.map((row, index) => <div className="toolbar" key={index}>
      <label className="field"><span>指标键</span><input aria-label={`指标键 ${index + 1}`} value={row.key} onChange={(event) => setRows((items) => items.map((item, i) => i === index ? { ...item, key: event.target.value } : item))} /></label>
      <label className="field"><span>比较方式</span><select value={row.op} onChange={(event) => setRows((items) => items.map((item, i) => i === index ? { ...item, op: event.target.value } : item))}>{Object.entries(OP_TEXT).map(([op, text]) => <option key={op} value={op}>{text}</option>)}</select></label>
      <label className="field"><span>阈值</span><input type="number" step="any" aria-label={`阈值 ${index + 1}`} value={row.value} onChange={(event) => setRows((items) => items.map((item, i) => i === index ? { ...item, value: event.target.value } : item))} /></label>
      <label className="field"><span>超标级别</span><select aria-label={`超标级别 ${index + 1}`} value={row.level} onChange={(event) => setRows((items) => items.map((item, i) => i === index ? { ...item, level: event.target.value } : item))}><option value="fail">阻断</option><option value="warn">告警，不阻断</option></select></label>
      <Button size="small" onClick={() => { setDirty(true); onSelected(''); save.reset(); setRows((items) => items.filter((_, i) => i !== index)) }}>移除规则 {index + 1}</Button>
    </div>)}
    <div className="flex mt"><Button onClick={() => { setDirty(true); onSelected(''); save.reset(); setRows((items) => [...items, { key: '', op: 'lt', value: '', level: 'fail' }]) }}>添加阈值</Button><Button kind="primary" disabled={!valid || save.isPending || policies.isError || policies.isLoading} onClick={() => save.mutate()}>{save.isPending ? '保存中…' : '保存为新版本'}</Button></div>
    </fieldset>
    {save.isError ? <Notice tone="red" title="策略保存失败">{describeError(save.error).message}</Notice> : null}
    {save.isSuccess ? <p className="small mt" role="status">已保存 {save.data.name} v{save.data.version}，后续试算使用此版本。</p> : null}
  </>
}

interface BaselineView {
  id: string
  name: string
  version: number
  source_run_id: string | null
  source_component_id: string | null
  profile: string | null
  profile_error: string | null
  created_at: string | null
  created?: boolean
  metrics: { key: string; value?: number | null; median?: number | null; unit?: string | null; missing_reason?: string | null; missing_reason_text?: string | null }[]
}

export function baselineCreatePayload(run: RunRecord | undefined, name: string, requestKey: string) {
  if (!run || run.state !== 'completed' || !(isPerformanceType(run.test_type) || run.test_type === 'joint')) {
    throw new Error('请选择已完成的性能或联动运行')
  }
  if (!name.trim()) throw new Error('请填写基线名称')
  return { request_key: requestKey, run_id: run.id, name: name.trim() }
}

/**
 * 运行分析面板的占位文案：加载中 / 失败 / 规划中目标端 / 真实无已完成运行。
 * 只有最后一种才能说「还没有」。
 */
export function perfAnalysisEmptyCopy(
  phase: PagePhase,
  planned: boolean,
): { title: string; description: string } {
  if (phase === 'loading') {
    return {
      title: '正在加载运行分析',
      description: '正在请求 GET /api/v1/runs 与 /api/v1/analyses；返回前不判断有没有性能结论。',
    }
  }
  if (phase === 'error') {
    return {
      title: '性能运行暂不可用',
      description: '接口返回错误（见上方错误码），请稍后重试；这不代表没有已完成运行。',
    }
  }
  if (planned) {
    return {
      title: '该目标端尚未接入',
      description: 'iOS / Web 目标端暂无执行能力，接入后按同一套指标口径开通；可先切回 Android。',
    }
  }
  return {
    title: '还没有已完成的性能运行',
    description: '性能或联动任务跑完后，这里展示指标、门禁逐项与基线对比。',
  }
}

/** 「性能运行」表格的占位文案（同上：加载中不等于没有运行） */
export function perfRunsEmptyCopy(
  phase: PagePhase,
  planned: boolean,
): { title: string; description: string } {
  if (phase === 'loading') {
    return {
      title: '正在加载性能运行清单',
      description: '正在请求 GET /api/v1/runs；返回前不判断有没有性能运行。',
    }
  }
  if (phase === 'error') {
    return {
      title: '性能运行清单暂不可用',
      description: '接口返回错误（见上方错误码），请稍后重试。',
    }
  }
  if (planned) {
    return {
      title: '该目标端尚未接入',
      description: 'iOS / Web 目标端暂无执行能力，接入后按同一套指标口径开通。',
    }
  }
  return {
    title: '还没有性能运行',
    description: '提交性能或联动任务后，运行与门禁结论会出现在这里。',
  }
}

function BaselineManager({ applicationId, runs, initialRunId, onSelected }: {
  applicationId: string | null | undefined
  runs: RunRecord[]
  initialRunId: string | null
  onSelected: (sourceRunId: string) => void
}) {
  const client = useQueryClient()
  const eligible = runs.filter((run) => run.application.id === applicationId && run.state === 'completed' && (isPerformanceType(run.test_type) || run.test_type === 'joint'))
  const [sourceId, setSourceId] = useState(initialRunId ?? '')
  const [name, setName] = useState('')
  const [requestKey, setRequestKey] = useState(newRequestKey)
  const source = eligible.find((run) => run.id === sourceId)
  const list = useQuery({
    queryKey: ['baselines', applicationId],
    queryFn: ({ signal }) => request<{ items: BaselineView[] }>('/baselines', { query: { application_id: applicationId, limit: 200 }, signal }),
    enabled: Boolean(applicationId), retry: false,
  })
  const save = useMutation({
    mutationFn: () => request<BaselineView>('/baselines', { method: 'POST', body: baselineCreatePayload(source, name, requestKey) }),
    onSuccess: async (baseline) => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['baselines', applicationId] }),
        client.invalidateQueries({ queryKey: ['analysis'] }),
      ])
      if (baseline.source_run_id) onSelected(baseline.source_run_id)
    },
  })
  function edit() { save.reset(); setRequestKey(newRequestKey()) }
  if (!applicationId) return <p className="small muted">请选择应用工作区或已完成运行，再查看基线。</p>
  return <>
    <div className="form-grid">
      <label className="field"><span>来源运行</span><select aria-label="基线来源运行" value={sourceId} disabled={save.isPending} onChange={(event) => { edit(); setSourceId(event.target.value) }}><option value="">选择已完成的性能或联动运行</option>{eligible.map((run) => <option key={run.id} value={run.id}>{run.display_id} / {run.name}</option>)}</select></label>
      <label className="field"><span>基线名称</span><input aria-label="基线名称" value={name} disabled={save.isPending} onChange={(event) => { edit(); setName(event.target.value) }} /></label>
    </div>
    <p className="small muted mt">保留来源组件、指标快照及设备档案；同名基线由后端复用，不覆盖既有快照。需要保留另一份来源时请填写新名称。</p>
    <Button kind="primary" disabled={!source || !name.trim() || save.isPending} title={source && name.trim() ? undefined : '先选择已完成的来源运行并填写基线名称'} onClick={() => save.mutate()}>{save.isPending ? '保存中…' : '从运行创建基线'}</Button>
    {save.isError ? <Notice tone="red" title="基线创建失败">{describeError(save.error).message}</Notice> : null}
    {save.isSuccess ? <p className="small mt" role="status">{save.data.created === false ? '已复用同名基线' : '已创建基线'}：{save.data.name} v{save.data.version}，来源运行 {save.data.source_run_id ?? '未提供'}。</p> : null}
    {list.isError ? <Notice tone="red" title="基线加载失败">{describeError(list.error).message}</Notice> : list.isLoading ? <p className="small muted mt">正在加载基线…</p> : <Table
      rows={list.data?.items ?? []}
      rowKey={(baseline) => baseline.id}
      ariaLabel="已保存基线"
      empty={<Empty icon="pulse" title="当前应用没有基线" description="选择已完成运行，保存真实指标快照作为后续比较来源。" />}
      columns={[
        { key: 'name', header: '基线 / 版本', render: (baseline) => <>{baseline.name}<div className="task-sub">v{baseline.version}</div></> },
        { key: 'source', header: '来源运行 / 组件', render: (baseline) => <span className="small mono">{baseline.source_run_id ?? DASH}<div className="task-sub">{baseline.source_component_id ?? '缺少来源组件'}</div></span> },
        { key: 'profile', header: '设备档案', render: (baseline) => baseline.profile ?? baseline.profile_error ?? '缺少档案' },
        { key: 'metrics', header: '快照指标', render: (baseline) => <div className="small">{(baseline.metrics ?? []).map((metric) => <div key={metric.key}>{metricLabel(metric.key)}：{metric.value ?? metric.median ?? metric.missing_reason_text ?? metric.missing_reason ?? '未采集'} {metric.unit ?? ''}</div>)}</div> },
        { key: 'created', header: '创建时间', render: (baseline) => <span className="small muted">{fmtDateTime(baseline.created_at)}</span> },
        { key: 'select', header: '操作', render: (baseline) => <Button size="small" disabled={!baseline.source_run_id} title={baseline.source_run_id ? undefined : '该基线没有来源运行，不能用于试算'} onClick={() => onSelected(baseline.source_run_id!)}>用于试算</Button> },
      ]}
      footer={<span>本页最多显示最新 200 条基线；可比性与结论由后端核验。</span>}
    />}
  </>
}
