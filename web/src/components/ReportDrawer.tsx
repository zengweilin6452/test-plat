/**
 * 报告抽屉：GET /api/v1/runs/{id}/report + GET /api/v1/runs/{id}/artifacts。
 *
 * 硬约束（frontend-spec.md §8）：
 * - verdict 为空时不显示「已通过 / 未通过」，只写「后端尚未给出结论」；
 * - metricsSummary 里 value 缺失时显示 notTestedReason / missingReason，绝不用 0 顶替；
 * - junit 未产出（present=false）时显示破折号，不把「没跑」写成 0 个失败；
 * - 证据下载地址由后端 download_url 给出，前端不自己拼路径。
 */
import { Fragment, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { describeError } from '../api/client'
import { createRun, fetchRunArtifacts, fetchRunReport } from '../api/endpoints'
import type { RunArtifact, RunReport } from '../api/types'
import { StatusBadge } from './Badge'
import { Button, LinkButton } from './Button'
import { Drawer } from './Dialog'
import { Empty } from './Empty'
import { Notice } from './Notice'
import { ReportViewer } from './ReportViewer'
import { useToast } from './Toast'
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

/** 摘要短值：前 12 位，没有就 null（不写 0 或空串） */
function shortHex(value: unknown): string | null {
  const text = asText(value)
  return text ? text.slice(0, 12) : null
}

export interface TraceRow {
  label: string
  value: string
}

/**
 * 报告追溯行（工单 05）：套件版本、固定代码副本摘要、构建、任务修订、资源档案。
 * 缺失一律如实说明，不拿设备 serial / 当前版本冒充（AC-REP-01、AC-REP-02）。
 */
export function traceRows(report: RunReport | undefined): TraceRow[] {
  const revision = report?.revision ?? null
  const build = report?.build ?? null
  const suite = report?.suite ?? null
  const profile = report?.resourceProfile ?? null
  const codeCopy = suite?.code_copy ?? null

  let suiteValue = '未绑定套件版本'
  if (suite) {
    const parts: string[] = []
    const version = asNumber(suite.version)
    parts.push(version === null ? '版本号未记录' : `v${version}`)
    const ref = asText(suite.source_ref)
    if (ref) parts.push(ref)
    const commit = shortHex(suite.source_commit)
    if (commit) parts.push(commit)
    suiteValue = parts.join(' · ')
  }

  let copyValue = '未记录固定代码副本'
  if (codeCopy) {
    const tree = shortHex(codeCopy.tree_sha256)
    if (!tree) {
      copyValue = '副本摘要缺失'
    } else {
      const count = asNumber(codeCopy.file_count)
      copyValue = count === null ? tree : `${tree} · ${count} 个文件`
    }
  }

  let buildValue = '未绑定构建'
  if (build) {
    const parts: string[] = []
    const version = asText(build.version)
    if (version) parts.push(`v${version}`)
    const key = asText(build.build_key)
    if (key) parts.push(key)
    const commit = shortHex(build.source_commit)
    if (commit) parts.push(commit)
    buildValue = parts.length ? parts.join(' · ') : '构建信息未记录'
  }

  const revisionValue = revision
    ? [asText(revision.readiness) ?? '就绪态未记录', asText(revision.test_type) ?? '未指定类型'].join(' · ')
    : '未绑定任务修订'

  const profileValue = profile
    ? [asText(profile.name) ?? asText(profile.id) ?? '档案名未记录', shortHex(profile.fingerprint)]
        .filter((part): part is string => Boolean(part))
        .join(' · ')
    : '未绑定资源档案'

  const currentName = asText(report?.currentNames?.application) ?? asText(report?.target?.name)
  const currentProject = asText(report?.currentNames?.project)
  return [
    // 改名 / 归档后读取同一历史运行：显示名明确标注为「当前名称」，
    // 追溯仍依赖稳定 ID 与原始快照，不把新名称伪装成运行时原始记录。
    ...(currentName ? [{ label: '应用当前名称', value: currentName }] : []),
    ...(currentProject ? [{ label: '项目当前名称', value: currentProject }] : []),
    { label: '套件版本', value: suiteValue },
    { label: '固定副本', value: copyValue },
    { label: '构建', value: buildValue },
    { label: '任务修订', value: revisionValue },
    { label: '资源档案', value: profileValue },
  ]
}

export interface CollectWindowView {
  available: boolean
  note: string | null
  rows: TraceRow[]
}

/**
 * joint 联合采集窗口（真实时间戳）：采集必须包围 UI 执行窗。
 * 后端没给窗口（非 joint / 旧数据 / 被取消）时如实写「无联合采集窗口」，
 * 不编造时间、也不拿耗时冒充窗口。
 */
export function collectWindowRows(report: RunReport | undefined): CollectWindowView {
  const collectWindow = report?.collectWindow ?? null
  if (!collectWindow) {
    return { available: false, note: '无联合采集窗口', rows: [] }
  }
  const ui = collectWindow.ui
  const timeout = asNumber(ui?.timeout_s)
  return {
    available: true,
    note: null,
    rows: [
      { label: '采集起点', value: fmtDateTime(collectWindow.collect_started_at) },
      { label: '采集终点', value: fmtDateTime(collectWindow.collect_stopped_at) },
      { label: 'UI 执行起点', value: fmtDateTime(ui?.started_at) },
      { label: 'UI 执行终点', value: fmtDateTime(ui?.ended_at) },
      { label: 'UI 超时', value: timeout === null ? DASH : `${fmtNumber(timeout, 0)} 秒` },
    ],
  }
}

const AVAILABILITY_LABELS: Record<string, string> = {
  available: '可用',
  missing: '缺失',
  expired: '已过期',
}

const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  file_missing: '文件已不在产物目录',
  retention_expired: '已超过保留期',
  storage_unresolvable: '存储路径无效',
}

export interface EvidenceState {
  label: string
  reason: string | null
  downloadable: boolean
}

/**
 * 证据三态（AC-REP-03）：只有 available 且后端给了 download_url 才算可下载；
 * missing/expired 给出原因，前端不自己拼路径。
 */
export function evidenceState(item: RunArtifact | undefined): EvidenceState {
  const availability = asText(item?.availability) ?? ''
  const reasonCode = asText(item?.unavailable_reason)
  return {
    label: AVAILABILITY_LABELS[availability] ?? (availability || DASH),
    reason: reasonCode ? (UNAVAILABLE_REASON_LABELS[reasonCode] ?? reasonCode) : null,
    downloadable: availability === 'available' && Boolean(asText(item?.download_url)),
  }
}

interface ReportDrawerProps {
  open: boolean
  run: RunRecord | null
  onClose: () => void
}

export function ReportDrawer({ open, run, onClose }: ReportDrawerProps) {
  const runId = run?.id ?? ''
  const toast = useToast()
  const navigate = useNavigate()
  // 在线查看：iframe 直接渲染报告本体（vendor HTML 或平台渲染页）
  const [viewing, setViewing] = useState(false)
  // 抽屉关闭时把查看器一起收掉，避免它残留在顶层
  useEffect(() => {
    if (!open) setViewing(false)
  }, [open])
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
  const collectWindow = collectWindowRows(report)
  const artifacts = artifactsQuery.data?.items ?? []

  // 重跑：POST /runs 引用原输入（同修订/同应用/同任务），parent_run_id 指回原运行；
  // 原记录不改写，历史报告不受影响（AC-REP-04、spec §9.3 重跑语义）。
  const [rerunning, setRerunning] = useState(false)
  async function rerun() {
    if (!run || !report?.revision) return
    setRerunning(true)
    try {
      const created = await createRun({
        application_id: run.application.id,
        task_id: run.task_id ?? '',
        revision_id: report.revision.id,
        platform: run.platform,
        request_key: crypto.randomUUID(),
        parent_run_id: run.id,
      })
      toast.show('重跑已创建：' + created.display_id + '，可在运行页跟踪', 'success')
      onClose()
      navigate('/ui')
    } catch (error) {
      const e = describeError(error)
      toast.show('重跑失败（' + e.code + '）：' + e.message, 'error')
    } finally {
      setRerunning(false)
    }
  }

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
            <Empty loading icon="report" title="正在加载报告" description="正在请求 GET /api/v1/runs/{id}/report" />
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
                <div className="toolbar">
                  <Button disabled={rerunning || !report?.revision} onClick={rerun}>
                    重跑（引用原输入）
                  </Button>
                  <Button disabled={!report?.view_url} onClick={() => setViewing(true)}>
                    在线查看报告
                  </Button>
                  <LinkButton onClick={() => navigate('/perf')}>性能分析 ›</LinkButton>
                  <a className="link-btn" href={`/api/v1/runs/${run.id}/report/export`} download>
                    导出 JSON
                  </a>
                </div>
              </div>

              <div className="drawer-section">
                <h3>追溯</h3>
                <dl className="summary-dl">
                  {traceRows(report).map((row) => (
                    <Fragment key={row.label}>
                      <dt>{row.label}</dt>
                      <dd className="mono">{row.value}</dd>
                    </Fragment>
                  ))}
                </dl>
              </div>

              <div className="drawer-section">
                <h3>采集窗口</h3>
                {collectWindow.available ? (
                  <>
                    <dl className="summary-dl">
                      {collectWindow.rows.map((row) => (
                        <Fragment key={row.label}>
                          <dt>{row.label}</dt>
                          <dd className="mono">{row.value}</dd>
                        </Fragment>
                      ))}
                    </dl>
                    <p className="muted small">
                      采集窗口由 runner 在真实时间上写出；UI 执行窗必须落在采集起止之间。
                    </p>
                  </>
                ) : (
                  <p className="muted small">{collectWindow.note}</p>
                )}
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
                          <th>说明</th>
                          <th>大小</th>
                        </tr>
                      </thead>
                      <tbody>
                        {artifacts.map((item: RunArtifact) => {
                          const state = evidenceState(item)
                          return (
                            <tr key={item.id}>
                              <td className="mono">
                                {state.downloadable && item.download_url ? (
                                  <a href={item.download_url}>{item.logical_key}</a>
                                ) : (
                                  item.logical_key
                                )}
                                {item.view_url ? (
                                  <>
                                    {' '}
                                    <a className="small" href={item.view_url} target="_blank" rel="noreferrer">
                                      在线查看
                                    </a>
                                  </>
                                ) : null}
                              </td>
                              <td className="muted small">{item.kind ?? DASH}</td>
                              <td className="muted small">{state.label}</td>
                              <td className="muted small">{state.reason ?? DASH}</td>
                              <td className="mono">{formatBytes(item.byte_size)}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          ) : null}
        </>
      )}

      <ReportViewer
        open={viewing && Boolean(report?.view_url)}
        viewUrl={report?.view_url ?? null}
        title={run ? `${run.name} · 在线报告` : '在线报告'}
        description={run ? `${run.display_id} · 报告内容由后端渲染，前端不参与判定` : undefined}
        onClose={() => setViewing(false)}
      />
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
