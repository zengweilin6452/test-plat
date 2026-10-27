/**
 * 任务详情抽屉（原型 taskDetail L226）。
 *
 * 三段内容：
 * 1. 最新修订摘要 —— 任务行自带的最新修订（test_type / readiness / revision_id）+ 修订接口里的同号修订详情；
 * 2. 修订历史时间线 —— GET /api/v1/tasks/{id}/revisions，按修订号倒序；
 * 3. 就绪状态与「验证任务」—— POST /api/v1/tasks/{id}/validate，
 *    422 readiness_incomplete 时把 details 里的缺失项原样列出（不自行推导、不伪造通过）。
 *
 * 硬约束：
 * - outcome 为 null 时绝不显示「已通过 / 未通过」，只显示生命周期 / 就绪态；
 * - 后端 P2 端点未就绪（404）时显示 Notice + 错误码，页面不崩；
 * - 缺失字段显示破折号，不显示 0。
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchTaskRevisions, validateTask } from '../api/endpoints'
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

  useEffect(() => {
    if (open) {
      setValidationError(null)
      setLastValidated(null)
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
  const readiness: TaskReadiness | null = lastValidated?.readiness ?? task?.readiness ?? null

  const validate = useMutation({
    mutationFn: (taskId: string) => validateTask(taskId),
    onSuccess: (result) => {
      setValidationError(null)
      setLastValidated(result)
      toast.show('任务已通过验证：修订 readiness = validated')
      // 列表与修订历史都要反映新状态
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      void queryClient.invalidateQueries({ queryKey: ['task-revisions', task?.id] })
    },
    onError: (error) => {
      setValidationError(describeError(error))
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
        disabled={validate.isPending || readiness === 'validated'}
      >
        {validate.isPending ? '验证中…' : readiness === 'validated' ? '已验证' : '验证任务'}
      </Button>
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
                    <span className="rev-no">{revision.revision === null ? DASH : `r${revision.revision}`}</span>
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
