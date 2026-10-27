/**
 * 报告抽屉：GET /api/v1/runs/{id}/report + GET /api/v1/runs/{id}/artifacts。
 *
 * 硬约束（frontend-spec.md §8）：
 * - verdict 为空时不显示「已通过 / 未通过」，只写「后端尚未给出结论」；
 * - metricsSummary 里 value 缺失时显示 notTestedReason / missingReason，绝不用 0 顶替；
 * - junit 未产出（present=false）时显示破折号，不把「没跑」写成 0 个失败；
 * - 证据下载地址由后端 download_url 给出，前端不自己拼路径。
 */
import { useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchRunArtifacts, fetchRunReport } from '../api/endpoints'
import type { RunArtifact, RunReport } from '../api/types'
import { StatusBadge } from './Badge'
import { Drawer } from './Dialog'
import { Empty } from './Empty'
import { Notice } from './Notice'
import { DASH, fmtDateTime, fmtDuration, fmtNumber } from '../lib/fmt'
import { displayStatus } from '../lib/display'
import type { RunRecord, RunState } from '../types'

/** metricsSummary 单条：vendor 直接透传，字段名以实际返回为准 */
interface MetricEntry {
  unit?: unknown
  median?: unknown
  mean?: unknown
  p90?: unknown
  min?: unknown
  max?: unknown
  sampleCount?: unknown
  notTested?: unknown
  notTestedReason?: unknown
  missingReason?: unknown
  labelZh?: unknown
}

function asText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 单条指标的展示值：优先 median，缺失时给出原因（不是 0） */
export function metricCell(entry: MetricEntry | undefined): string {
  if (!entry) return DASH
  const median = asNumber(entry.median)
  if (median !== null) {
    const unit = asText(entry.unit)
    return unit ? `${fmtNumber(median)} ${unit}` : fmtNumber(median)
  }
  return DASH
}

/** 指标缺失原因：notTestedReason（整项未测）优先于 missingReason（单项缺失） */
export function metricMissingReason(entry: MetricEntry | undefined): string | null {
  if (!entry) return null
  return asText(entry.notTestedReason) ?? asText(entry.missingReason)
}

/** junit 计数：present=false 或字段缺失时返回 null（显示破折号，不写 0） */
export function junitCounts(report: RunReport | undefined): {
  tests: number | null
  failed: number | null
  skipped: number | null
} {
  const junit = report?.junit
  if (!junit || junit.present === false) return { tests: null, failed: null, skipped: null }
  const tests = asNumber(junit.tests)
  const failed = asNumber(junit.failed) ?? (
    (asNumber(junit.failures) ?? 0) + (asNumber(junit.errors) ?? 0)
  )
  return { tests, failed, skipped: asNumber(junit.skipped) }
}

interface ReportDrawerProps {
  open: boolean
  run: RunRecord | null
  onClose: () => void
}

export function ReportDrawer({ open, run, onClose }: ReportDrawerProps) {
  const runId = run?.id ?? ''
  const reportQuery = useQuery({
    queryKey: ['run-report', runId],
    queryFn: ({ signal }) => fetchRunReport(runId, signal),
    enabled: open && Boolean(runId),
    retry: false,
  })
  const artifactsQuery = useQuery({
    queryKey: ['run-artifacts', runId],
    queryFn: ({ signal }) => fetchRunArtifacts(runId, signal),
    enabled: open && Boolean(runId),
    retry: false,
  })

  const reportError = reportQuery.isError ? describeError(reportQuery.error) : null
  const artifactsError = artifactsQuery.isError ? describeError(artifactsQuery.error) : null
  const report = reportQuery.data
  const metrics = Object.entries(report?.metricsSummary ?? {})
  const junit = junitCounts(report)
  const artifacts = artifactsQuery.data?.items ?? []

  return (
    <Drawer
      open={open && Boolean(run)}
      onClose={onClose}
      title={run ? `${run.name} · 报告` : '运行报告'}
      description={run ? `${run.display_id} · ${fmtDateTime(run.ended_at)}` : undefined}
      footHint="报告与证据均由后端产出；页面只做展示，不参与判定"
    >
      {!run ? null : (
        <>
          {reportError ? (
            <div className="mb">
              <Notice tone="red" title={'报告获取失败（' + reportError.code + '）'}>
                {reportError.message}
              </Notice>
            </div>
          ) : null}

          {reportQuery.isLoading ? (
            <Empty icon="report" title="正在加载报告" description="正在请求 GET /api/v1/runs/{id}/report" />
          ) : null}

          {report ? (
            <>
              <div className="drawer-section">
                <h3>结论</h3>
                <dl className="summary-dl">
                  <dt>门禁结论</dt>
                  <dd>
                    <StatusBadge
                      status={displayStatus(
                        (report.status ?? run.state) as RunState,
                        report.verdict ?? null,
                      )}
                    />{' '}
                    {report.verdict ? null : (
                      <span className="muted small">后端尚未给出结论</span>
                    )}
                  </dd>
                  <dt>原因</dt>
                  <dd className="mono">{report.reason ?? report.reasonText ?? DASH}</dd>
                  <dt>报告模式</dt>
                  <dd>
                    {report.mode === 'imported'
                      ? '导入补录（imported）'
                      : report.mode === 'live'
                        ? '真跑产物（live）'
                        : (report.mode ?? DASH)}
                  </dd>
                  <dt>用例（junit）</dt>
                  <dd>
                    共 {junit.tests ?? DASH} 个 · 失败 {junit.failed ?? DASH} · 跳过{' '}
                    {junit.skipped ?? DASH}
                  </dd>
                  <dt>耗时</dt>
                  <dd>{fmtDuration(report.durationS ?? null)}</dd>
                  <dt>设备档案</dt>
                  <dd className="mono">{report.deviceProfile ?? DASH}</dd>
                  <dt>判定时间</dt>
                  <dd>{fmtDateTime(report.evaluatedAt ?? run.ended_at)}</dd>
                </dl>
              </div>

              <div className="drawer-section">
                <h3>指标汇总</h3>
                {metrics.length === 0 ? (
                  <Empty
                    icon="pulse"
                    title="报告没有指标数据"
                    description="该运行没有性能组件，或 vendor 未产出 metricsSummary。"
                  />
                ) : (
                  <div className="table-wrap">
                    <table className="task-table" aria-label="报告指标汇总">
                      <thead>
                        <tr>
                          <th>指标</th>
                          <th>中位数</th>
                          <th>样本数</th>
                          <th>说明</th>
                        </tr>
                      </thead>
                      <tbody>
                        {metrics.map(([key, raw]) => {
                          const entry = raw as MetricEntry
                          return (
                            <tr key={key}>
                              <td className="mono">{asText(entry.labelZh) ?? key}</td>
                              <td className="mono">{metricCell(entry)}</td>
                              <td className="mono">{asNumber(entry.sampleCount) ?? DASH}</td>
                              <td className="muted small">{metricMissingReason(entry) ?? DASH}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="drawer-section">
                <h3>证据链</h3>
                {artifactsError ? (
                  <Notice tone="red" title={'证据清单获取失败（' + artifactsError.code + '）'}>
                    {artifactsError.message}
                  </Notice>
                ) : artifactsQuery.isLoading ? (
                  <div className="muted small">正在请求 /api/v1/runs/{run.id}/artifacts</div>
                ) : artifacts.length === 0 ? (
                  <Empty icon="box" title="没有登记产物" description="该运行没有可下载的证据文件。" />
                ) : (
                  <div className="table-wrap">
                    <table className="task-table" aria-label="报告证据">
                      <thead>
                        <tr>
                          <th>产物</th>
                          <th>类型</th>
                          <th>可用性</th>
                          <th>大小</th>
                        </tr>
                      </thead>
                      <tbody>
                        {artifacts.map((item: RunArtifact) => (
                          <tr key={item.id}>
                            <td className="mono">
                              {item.download_url && item.availability !== 'missing' ? (
                                <a href={item.download_url}>{item.logical_key}</a>
                              ) : (
                                item.logical_key
                              )}
                            </td>
                            <td className="muted small">{item.kind ?? DASH}</td>
                            <td className="muted small">{item.availability ?? DASH}</td>
                            <td className="mono">{formatBytes(item.byte_size)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          ) : null}
        </>
      )}
    </Drawer>
  )
}

/** 字节数展示；未知返回破折号 */
function formatBytes(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return DASH
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
