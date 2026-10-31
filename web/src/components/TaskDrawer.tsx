/**
 * 任务详情抽屉（原型 taskDetail L226）。
 *
 * 三段内容：
 * 1. 最新修订摘要 —— 任务行自带的最新修订（test_type / readiness / revision_id）+ 修订接口里的同号修订详情；
 * 2. 修订历史时间线 —— GET /api/v1/tasks/{id}/revisions，按修订号倒序；
 * 3. 就绪状态与「验证任务」—— POST /api/v1/tasks/{id}/validate，
 *    422 readiness_incomplete 时把 details 里的缺失项原样列出（不自行推导、不伪造通过）；
 * 4. 绑定构建与套件版本 —— PATCH /api/v1/tasks/{id}（lock_version 做 CAS），
 *    补齐后端验证要求的 build_id / suite_version_id，之后才能验证与首次启动运行。
 *
 * 硬约束：
 * - outcome 为 null 时绝不显示「已通过 / 未通过」，只显示生命周期 / 就绪态；
 * - 后端 P2 端点未就绪（404）时显示 Notice + 错误码，页面不崩；
 * - 缺失字段显示破折号，不显示 0。
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import {
  createRun,
  fetchBuilds,
  fetchSuiteVersions,
  fetchSuites,
  fetchTaskRevisions,
  patchTask,
  validateTask,
} from '../api/endpoints'
import { moduleName, TARGET_CATALOG } from '../constants'
import { displayStatus, displayTaskStatus } from '../lib/display'
import { DASH, fmtDateTime } from '../lib/fmt'
import type {
  ReadinessIncompleteDetails,
  TaskReadiness,
  TaskRecord,
  TaskRevisionRecord,
  TaskValidateResponse,
} from '../types'
import { StatusBadge } from './Badge'
import { Button } from './Button'
import { Drawer } from './Dialog'
import { Empty } from './Empty'
import { Notice } from './Notice'
import { useToast } from './Toast'
import { newRequestKey } from './TaskWizard'

/** 后端可能返回 revisions 为数组或 { items } —— 两种都接住，缺失时返回空数组而不是假数据 */
function readRevisions(payload: unknown): TaskRevisionRecord[] {
  if (Array.isArray(payload)) return payload as TaskRevisionRecord[]
  if (payload && typeof payload === 'object') {
    const items = (payload as { items?: unknown }).items
    if (Array.isArray(items)) return items as TaskRevisionRecord[]
  }
  return []
}

/** 缺失项字段名兼容 missing / missing_checks / items —— 都从 details 里取，缺失就返回空 */
export function readMissingItems(details: unknown): string[] {
  if (!details || typeof details !== 'object') return []
  const bag = details as ReadinessIncompleteDetails
  const raw = bag.missing ?? bag.missing_checks ?? bag.items
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    if (typeof item === 'string') return item
    if (item && typeof item === 'object') {
      const record = item as Record<string, unknown>
      const label = record.label ?? record.name ?? record.field ?? record.code
      if (typeof label === 'string') {
        const hint = record.hint ?? record.detail ?? record.message
        return typeof hint === 'string' && hint ? `${label}（${hint}）` : label
      }
      return JSON.stringify(item)
    }
    return String(item)
  })
}

const READINESS_LABEL: Record<TaskReadiness, string> = {
  draft: '未验证',
  validated: '已验证',
}

function ReadinessBadge({ readiness }: { readiness: TaskReadiness | null | undefined }) {
  if (!readiness) return <span className="muted small">{DASH}</span>
  return (
    <span className={'badge ' + (readiness === 'validated' ? 'green' : 'amber')}>
      <i className="dot" />
      {READINESS_LABEL[readiness] ?? readiness}
    </span>
  )
}

interface TaskDrawerProps {
  open: boolean
  /** 被点击的任务行；为空时抽屉不渲染内容 */
  task: TaskRecord | null
  onClose: () => void
}

export function TaskDrawer({ open, task, onClose }: TaskDrawerProps) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [validationError, setValidationError] = useState<ReturnType<typeof describeError> | null>(null)
  const [lastValidated, setLastValidated] = useState<TaskValidateResponse | null>(null)
  // 绑定表单：套件选择驱动版本列表；构建默认取最新修订已绑定的值
  const [suiteId, setSuiteId] = useState('')
  const [suiteVersionId, setSuiteVersionId] = useState('')
  const [buildId, setBuildId] = useState('')
  // 抽屉拿到的 task 是列表快照：验证 / 绑定都会 bump lock_version，
  // 这里跟着响应更新，避免第二次保存拿着旧版本号撞 409 stale_version
  const [lockVersion, setLockVersion] = useState<number | null>(null)
  // 绑定会追加一条 draft 修订：本地 readiness 跟着回落，不能继续显示"已验证"
  const [readinessOverride, setReadinessOverride] = useState<TaskReadiness | null>(null)

  useEffect(() => {
    if (open) {
      setValidationError(null)
      setLastValidated(null)
      setSuiteId('')
      setSuiteVersionId('')
      setBuildId('')
      setLockVersion(task?.lock_version ?? null)
      setReadinessOverride(null)
    }
  }, [open, task?.id])

  const revisionsQuery = useQuery({
    queryKey: ['task-revisions', task?.id],
    queryFn: ({ signal }) => fetchTaskRevisions(task!.id, signal),
    enabled: open && Boolean(task?.id),
    retry: false,
  })

  const revisionsError = revisionsQuery.isError ? describeError(revisionsQuery.error) : null
  const revisions = useMemo(() => {
    const items = readRevisions(revisionsQuery.data)
    return [...items].sort((a, b) => (b.revision ?? 0) - (a.revision ?? 0))
  }, [revisionsQuery.data])

  /** 最新修订：优先用修订接口的第 1 条；接口不可用时退回任务行字段（并明确标注来源） */
  const latestRevision = revisions[0] ?? null
  const readiness: TaskReadiness | null =
    readinessOverride ?? lastValidated?.readiness ?? task?.readiness ?? null
  const testType = latestRevision?.test_type ?? task?.test_type ?? null
  const boundBuildId = latestRevision?.build_id ?? null
  const boundSuiteVersionId = latestRevision?.suite_version_id ?? null

  const buildsQuery = useQuery({
    queryKey: ['builds', task?.application.id],
    queryFn: ({ signal }) => fetchBuilds(task!.application.id, signal),
    enabled: open && Boolean(task?.application.id),
    retry: false,
  })
  const suitesQuery = useQuery({
    queryKey: ['suites', testType],
    queryFn: ({ signal }) => fetchSuites(testType ?? undefined, signal),
    enabled: open && Boolean(testType),
    retry: false,
  })
  const versionsQuery = useQuery({
    queryKey: ['suite-versions', suiteId],
    queryFn: ({ signal }) => fetchSuiteVersions(suiteId, signal),
    enabled: open && Boolean(suiteId),
    retry: false,
  })

  // 只列本应用的构建与本类型的套件（/suites 不支持按应用过滤，前端筛）
  const builds = useMemo(
    () => (buildsQuery.data?.items ?? []).filter((item) => item.application_id === task?.application.id),
    [buildsQuery.data, task?.application.id],
  )
  const suites = useMemo(
    () => (suitesQuery.data?.items ?? []).filter((item) => item.application.id === task?.application.id),
    [suitesQuery.data, task?.application.id],
  )
  const versions = versionsQuery.data?.items ?? []

  const validate = useMutation({
    mutationFn: (taskId: string) => validateTask(taskId),
    onSuccess: (result) => {
      setValidationError(null)
      setLastValidated(result)
      const nextLock = (result as { lock_version?: number }).lock_version
      if (typeof nextLock === 'number') setLockVersion(nextLock)
      toast.show('任务已通过验证：修订 readiness = validated')
      // 列表与修订历史都要反映新状态
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      void queryClient.invalidateQueries({ queryKey: ['task-revisions', task?.id] })
    },
    onError: (error) => {
      setValidationError(describeError(error))
    },
  })

  // 补齐草稿的构建 / 套件版本绑定（CAS：lock_version）
  const bindMutation = useMutation({
    mutationFn: (body: { build_id?: string; suite_version_id?: string }) =>
      patchTask(task!.id, { lock_version: lockVersion ?? task!.lock_version, ...body }),
    onSuccess: (updated) => {
      setValidationError(null)
      setLastValidated(null)
      setReadinessOverride(updated?.readiness ?? 'draft')
      if (typeof updated?.lock_version === 'number') setLockVersion(updated.lock_version)
      toast.show('已保存绑定，可执行验证。')
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      void queryClient.invalidateQueries({ queryKey: ['task-revisions', task?.id] })
    },
    onError: (error) => {
      const described = describeError(error)
      if (described.code === 'stale_version') {
        setValidationError(described)
        toast.show('任务已被他人更新，请关闭抽屉后重新打开再试。')
      } else {
        setValidationError(described)
      }
    },
  })

  // 只有选出了与当前绑定不同的值才允许保存，避免空 PATCH 追加无意义修订
  const bindDirty =
    (Boolean(buildId) && buildId !== (boundBuildId ?? '')) ||
    (Boolean(suiteVersionId) && suiteVersionId !== (boundSuiteVersionId ?? ''))

  const runMutation = useMutation({
    mutationFn: (revisionId: string) =>
      createRun({
        application_id: task!.application.id,
        task_id: task!.id,
        revision_id: revisionId,
        platform: task!.platform,
        request_key: newRequestKey(),
      }),
    onSuccess: (created) => {
      toast.show('运行已发起：' + created.display_id + '，可在 UI 自动化页跟踪')
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (error) => {
      const described = describeError(error)
      toast.show('发起运行失败（' + described.code + '）：' + described.message)
    },
  })

  const missingItems = useMemo(
    () => (validationError?.code === 'readiness_incomplete' ? readMissingItems(validationError.details) : []),
    [validationError],
  )

  const footer = task ? (
    <>
      <Button onClick={onClose}>关闭</Button>
      <Button
        kind="primary"
        icon="check"
        onClick={() => validate.mutate(task.id)}
        disabled={validate.isPending || readiness === 'validated' || runMutation.isPending}
      >
        {validate.isPending ? '验证中…' : readiness === 'validated' ? '已验证' : '验证任务'}
      </Button>
      {readiness === 'validated' && (lastValidated?.revision?.id ?? task.revision_id) ? (
        <Button
          kind="primary"
          icon="play"
          disabled={runMutation.isPending}
          onClick={() => runMutation.mutate((lastValidated?.revision?.id ?? task.revision_id)!)}
        >
          {runMutation.isPending ? '发起中…' : '启动运行'}
        </Button>
      ) : null}
    </>
  ) : null

  return (
    <Drawer
      open={open && Boolean(task)}
      onClose={onClose}
      title={task ? task.name : '任务详情'}
      description={
        task
          ? `${task.display_id} · ${TARGET_CATALOG[task.platform]?.label ?? task.platform} · ${moduleName(task.test_type)}`
          : undefined
      }
      footer={footer}
      footHint={task ? '验证会把最新修订从 draft 推到 validated；已绑定运行的修订不可再改' : undefined}
    >
      {!task ? null : (
        <>
          <div className="drawer-section">
            <h3>就绪状态</h3>
            <dl className="summary-dl">
              <dt>任务生命周期</dt>
              <dd>
                <StatusBadge status={displayTaskStatus(task.lifecycle, readiness)} />{' '}
                <span className="muted small">{task.lifecycle}</span>
              </dd>
              <dt>修订 readiness</dt>
              <dd>
                <ReadinessBadge readiness={readiness} />
              </dd>
              <dt>最近一次运行</dt>
              <dd>
                {task.run ? (
                  <>
                    <StatusBadge status={displayStatus(task.run.state, task.run.outcome)} />{' '}
                    {task.run.outcome === null && task.run.state === 'completed' ? (
                      <span className="muted small">后端未给出结论</span>
                    ) : null}
                  </>
                ) : (
                  <span className="muted small">尚未产生运行（草稿不计入通过率）</span>
                )}
              </dd>
              <dt>修订总数</dt>
              <dd>{task.revision_count}</dd>
            </dl>

            {validate.isPending ? (
              <div className="mt">
                <Notice tone="blue" icon="clock" title="正在验证任务">
                  正在调用 POST /api/v1/tasks/{task.id}/validate
                </Notice>
              </div>
            ) : null}

            {validationError ? (
              <div className="mt">
                <Notice
                  tone={validationError.code === 'readiness_incomplete' ? 'amber' : 'red'}
                  title={
                    (validationError.code === 'readiness_incomplete'
                      ? '修订尚不可用（readiness_incomplete）'
                      : '验证失败（' + validationError.code + '）')
                  }
                >
                  <div>{validationError.message}</div>
                  {missingItems.length > 0 ? (
                    <>
                      <div style={{ marginTop: 6 }}>后端给出的缺失项：</div>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                        {missingItems.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  ) : validationError.code === 'readiness_incomplete' ? (
                    <div className="small" style={{ marginTop: 6 }}>
                      后端未在 details 中给出缺失项明细。
                    </div>
                  ) : null}
                  {validationError.code === 'HTTP_404' || validationError.code === 'not_found' ? (
                    <div className="small" style={{ marginTop: 6 }}>
                      验证接口可能尚未上线（404）或该任务不存在，请与后端确认。
                    </div>
                  ) : null}
                  {validationError.requestId ? (
                    <div className="small muted" style={{ marginTop: 6 }}>
                      请求号 {validationError.requestId}
                    </div>
                  ) : null}
                </Notice>
              </div>
            ) : null}

            {lastValidated && !validationError ? (
              <div className="mt">
                <Notice tone="green" title="验证通过">
                  修订 readiness = {READINESS_LABEL[lastValidated.readiness] ?? lastValidated.readiness}
                  {lastValidated.revision?.id ? `（revision ${lastValidated.revision.id}）` : ''}
                </Notice>
              </div>
            ) : null}
          </div>

          <div className="drawer-section">
            <h3>绑定构建与套件版本</h3>
            <p className="muted small">
              验证要求修订同时绑定构建与套件版本；保存会追加一条新的 draft 修订，需要重新验证。
            </p>
            <dl className="summary-dl">
              <dt>当前绑定</dt>
              <dd className="mono">
                {boundBuildId ?? DASH} / {boundSuiteVersionId ?? DASH}
              </dd>
            </dl>

            {buildsQuery.isError || suitesQuery.isError ? (
              <Notice
                tone="red"
                title={
                  '绑定选项获取失败（' +
                  describeError(buildsQuery.error ?? suitesQuery.error).code +
                  '）'
                }
              >
                {describeError(buildsQuery.error ?? suitesQuery.error).message}
              </Notice>
            ) : (
              <>
                <div className="field">
                  <label htmlFor={`bind-build-${task.id}`}>构建版本</label>
                  <select
                    id={`bind-build-${task.id}`}
                    value={buildId || boundBuildId || ''}
                    onChange={(event) => setBuildId(event.target.value)}
                  >
                    <option value="">选择构建…</option>
                    {builds.map((build) => (
                      <option key={build.id} value={build.id}>
                        {build.version}
                        {build.build_key ? ` · ${build.build_key}` : ''}
                      </option>
                    ))}
                  </select>
                  {builds.length === 0 && !buildsQuery.isLoading ? (
                    <div className="field-hint">该应用还没有登记构建，先在应用页上传或登记构建。</div>
                  ) : null}
                </div>

                <div className="field">
                  <label htmlFor={`bind-suite-${task.id}`}>套件</label>
                  <select
                    id={`bind-suite-${task.id}`}
                    value={suiteId}
                    onChange={(event) => {
                      setSuiteId(event.target.value)
                      setSuiteVersionId('')
                    }}
                  >
                    <option value="">选择套件…</option>
                    {suites.map((suite) => (
                      <option key={suite.id} value={suite.id}>
                        {suite.name}
                        {suite.latest_version ? ` · v${suite.latest_version.version}` : ''}
                      </option>
                    ))}
                  </select>
                  {suites.length === 0 && !suitesQuery.isLoading ? (
                    <div className="field-hint">该应用还没有 {moduleName(testType)} 套件。</div>
                  ) : null}
                </div>

                <div className="field">
                  <label htmlFor={`bind-suite-version-${task.id}`}>套件版本</label>
                  <select
                    id={`bind-suite-version-${task.id}`}
                    value={suiteVersionId}
                    disabled={!suiteId}
                    onChange={(event) => setSuiteVersionId(event.target.value)}
                  >
                    <option value="">
                      {suiteId ? (versionsQuery.isLoading ? '加载中…' : '选择版本…') : '先选套件'}
                    </option>
                    {versions.map((version) => (
                      <option key={version.id} value={version.id}>
                        v{version.version}
                        {version.case_count !== undefined ? ` · ${version.case_count} 用例` : ''}
                      </option>
                    ))}
                  </select>
                  {versionsQuery.isError ? (
                    <div className="field-hint">版本清单获取失败：{describeError(versionsQuery.error).message}</div>
                  ) : null}
                </div>

                <div className="mt">
                  <Button
                    kind="primary"
                    disabled={bindMutation.isPending || !bindDirty}
                    onClick={() => {
                      const body: { build_id?: string; suite_version_id?: string } = {}
                      if (buildId && buildId !== boundBuildId) body.build_id = buildId
                      if (suiteVersionId && suiteVersionId !== boundSuiteVersionId) {
                        body.suite_version_id = suiteVersionId
                      }
                      bindMutation.mutate(body)
                    }}
                  >
                    {bindMutation.isPending ? '保存中…' : '保存绑定'}
                  </Button>
                  {!bindDirty ? (
                    <span className="muted small" style={{ marginLeft: 8 }}>
                      未修改
                    </span>
                  ) : null}
                </div>
              </>
            )}
          </div>

          <div className="drawer-section">
            <h3>最新修订摘要</h3>
            <dl className="summary-dl">
              <dt>应用</dt>
              <dd>
                {task.application.name} <span className="muted small">（{task.platform}）</span>
              </dd>
              <dt>测试类型</dt>
              <dd>
                {moduleName(latestRevision?.test_type ?? task.test_type)}
              </dd>
              <dt>修订号</dt>
              <dd className="mono">
                {latestRevision?.revision !== undefined && latestRevision?.revision !== null
                  ? `r${latestRevision.revision}`
                  : DASH}{' '}
                <span className="muted small mono">{latestRevision?.id ?? task.revision_id ?? DASH}</span>
              </dd>
              <dt>创建时间</dt>
              <dd>{revisionsError ? DASH : fmtDateTime(latestRevision?.created_at)}</dd>
              <dt>构建 / 套件</dt>
              <dd className="mono">
                {latestRevision?.build_id ?? DASH} / {latestRevision?.suite_version_id ?? DASH}
              </dd>
              <dt>created_by</dt>
              <dd>{latestRevision?.created_by ?? DASH}</dd>
            </dl>
            {!latestRevision && !revisionsQuery.isLoading && !revisionsError ? (
              <div className="muted small" style={{ marginTop: 8 }}>
                修订接口未返回该任务的修订记录；以上仅包含任务行自身字段。
              </div>
            ) : null}
          </div>

          <div className="drawer-section">
            <h3>修订历史</h3>
            {revisionsError ? (
              <Notice tone="red" title={'修订历史获取失败（' + revisionsError.code + '）'}>
                {revisionsError.message}
                {revisionsError.code === 'HTTP_404' || revisionsError.code === 'not_found' ? (
                  <div className="small" style={{ marginTop: 6 }}>
                    GET /api/v1/tasks/{task.id}/revisions 可能尚未上线，修订历史暂不可用。
                  </div>
                ) : null}
              </Notice>
            ) : revisionsQuery.isLoading ? (
              <Empty icon="tasks" title="正在加载修订历史" description="正在请求 /api/v1/tasks/{id}/revisions" />
            ) : revisions.length === 0 ? (
              <Empty icon="tasks" title="暂无修订记录" description="该任务还没有可展示的修订。" />
            ) : (
              <div className="rev-list">
                {revisions.map((revision, index) => (
                  <div key={revision.id} className={'rev-row' + (index === 0 ? ' latest' : '')}>
                    <span className="rev-no">{`r${revision.revision}`}</span>
                    <div className="grow">
                      <div className="flex" style={{ gap: 8 }}>
                        <ReadinessBadge readiness={revision.readiness} />
                        <span className="muted small">
                          {moduleName(revision.test_type)}
                        </span>
                        {index === 0 ? <span className="muted small">最新</span> : null}
                      </div>
                      <div className="rev-meta">
                        {fmtDateTime(revision.created_at)} · {revision.created_by ?? DASH}
                        {revision.bound_run_id ? ' · 已绑定运行，不可修改' : ''}
                      </div>
                      {revision.note ? <div className="rev-meta">{revision.note}</div> : null}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Drawer>
  )
}
