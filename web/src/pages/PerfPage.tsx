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
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { createGateEvaluation, fetchAnalysis, fetchRuns, fetchTasks } from '../api/endpoints'
import { Badge, StatusBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PlannedNotice, PrimaryAction } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import { TaskDrawer } from '../components/TaskDrawer'
import { TaskWizard, newRequestKey } from '../components/TaskWizard'
import { useToast } from '../components/Toast'
import { TARGET_CATALOG, isImplementedPlatform, isPerformanceType, moduleName } from '../constants'
import { displayStatus } from '../lib/display'
import { DASH, fmtDateTime } from '../lib/fmt'
import { useTargetScope } from '../store/scope'
import type {
  AnalysisMetric,
  GateCheck,
  RunAnalysis,
} from '../api/types'
import type { CreateTaskResponse, Platform, RunOutcome, RunRecord, TaskRecord } from '../types'

/** 指标口径展示名；未登记的 key 原样显示，不猜单位 */
const METRIC_LABELS: Record<string, string> = {
  mem_pss_mb: 'PSS 内存',
  cpu_process_pct: '进程 CPU',
  fps_frame: '帧率',
  gpu_usage_pct: 'GPU 占用',
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
  const { targetScope, setTargetScope } = useTargetScope()
  const planned = !isImplementedPlatform(targetScope)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeTask, setActiveTask] = useState<TaskRecord | null>(null)
  // 分析页状态：选中运行 / 选中的判定（试算后切到那条）/ 试算用基线
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [evaluationId, setEvaluationId] = useState<string | null>(null)
  const [baselineRunId, setBaselineRunId] = useState('')
  const queryClient = useQueryClient()
  const toast = useToast()

  const runsQuery = useQuery({
    queryKey: ['runs', 'perf', targetScope],
    queryFn: ({ signal }) => fetchRuns(targetScope, 100, signal),
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
    // 找不到对应任务时不伪造一条：明确告诉用户任务详情数据缺失
    toast.show(run.task_id ? '任务 ' + run.task_id + ' 不在当前任务列表中，无法打开详情' : '该运行没有关联任务')
  }

  function handleCreated(created: CreateTaskResponse) {
    toast.show('任务已创建：' + created.display_id + '（编号 ' + created.id + '）')
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

  const trialMutation = useMutation({
    mutationFn: () =>
      createGateEvaluation(currentRunId!, {
        request_key: newRequestKey(),
        baseline_run_id: baselineRunId || null,
      }),
    onSuccess: (result) => {
      const id = result.evaluation_id ?? result.id
      setEvaluationId(id)
      toast.show('试算完成：' + verdictText(result.verdict) + '（未改写历史报告）')
      void queryClient.invalidateQueries({ queryKey: ['analysis', currentRunId] })
    },
    onError: (mutationError) => {
      const described = describeError(mutationError)
      toast.show('试算失败（' + described.code + '）：' + described.message)
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

      <div className="mb">
        <Notice tone="blue" icon="alert" title="门禁结论不在前端计算">
          性能结论由后端根据阈值与基线评估后写入 gate_evaluations。样本不足或基线不可比时结论为「未判定」，
          页面不会把它显示成未通过或已通过；指标缺失会显示具体原因，而不是 0。
        </Notice>
      </div>

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'性能运行获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      <Panel>
        <PanelHead
          title="运行分析"
          hint="指标取 median；门禁逐项来自后端 checks，试算只新增判定行"
          actions={
            currentRunId ? (
              <a className="link-btn" href={`/api/v1/runs/${currentRunId}/report/export`}>
                导出报告 JSON
              </a>
            ) : null
          }
        />

        {finishedRuns.length === 0 ? (
          <Empty
            icon="pulse"
            title={planned ? '该目标端尚未接入' : '还没有已完成的性能运行'}
            description={
              planned
                ? 'iOS / Web 目标端暂无执行能力，接入后按同一套指标口径开通。'
                : '性能或联动任务跑完后，这里展示指标、门禁逐项与基线对比。'
            }
          />
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
              <Empty icon="pulse" title="正在加载运行分析" description="正在请求 GET /api/v1/analyses?run_id=" />
            ) : analysis ? (
              <>
                <VerdictNotice analysis={analysis} />
                <MetricCards analysis={analysis} />
                <ChecksTable analysis={analysis} />
                <div className="content-grid mt">
                  <ContextCard analysis={analysis} />
                  <TrialCard
                    analysis={analysis}
                    baselineRunId={baselineRunId}
                    onBaselineChange={setBaselineRunId}
                    onTrial={() => trialMutation.mutate()}
                    pending={trialMutation.isPending}
                    canTrial={Boolean(currentRunId)}
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
          {perfRuns.length === 0 && !error ? (
            <Empty
              icon="pulse"
              title={planned ? '该目标端尚未接入' : '还没有性能运行'}
              description={
                planned
                  ? 'iOS / Web 目标端暂无执行能力，接入后按同一套指标口径开通。'
                  : '提交性能或联动任务后，运行与门禁结论会出现在这里。'
              }
            />
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
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={handleCreated}
        initialPlatform={targetScope === 'all' ? 'android' : (targetScope as Platform)}
      />
      <TaskDrawer open={Boolean(activeTask)} task={activeTask} onClose={() => setActiveTask(null)} />
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
          <option value="">由平台选择（同档案优先）</option>
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
        <Button kind="primary" disabled={!canTrial || pending} onClick={onTrial}>
          {pending ? '试算中…' : '按此基线试算'}
        </Button>
      </div>
      <p className="small muted mt">
        告警级超标保留 passed；样本不足、缺失指标或基线不可比则返回 not_tested。
      </p>
    </section>
  )
}
