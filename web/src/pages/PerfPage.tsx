/**
 * 性能测试（原型 #perf / L104–L230）。
 *
 * 重要：原型里 perfVerdict() 是前端算门禁；平台侧**不这么做**。
 * 页面只展示后端 gate_evaluations 给的结论：
 * - 样本不足或基线不可比时后端返回 not_tested，前端原样显示"未判定"；
 * - 指标缺失（如 GPU 不支持）显示原因，不显示 0。
 *
 * P1 可用数据：GET /api/v1/runs 里 test_type='perf' 的运行；
 * 指标与门禁明细接口（/runs/{id}/metrics、/runs/{id}/gate）在 P3 提供。
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchRuns, fetchTasks } from '../api/endpoints'
import { StatusBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PlannedNotice, PrimaryAction } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import { TaskDrawer } from '../components/TaskDrawer'
import { TaskWizard } from '../components/TaskWizard'
import { useToast } from '../components/Toast'
import { TARGET_CATALOG, isImplementedPlatform } from '../constants'
import { displayStatus } from '../lib/display'
import { DASH, fmtDateTime } from '../lib/fmt'
import { useTargetScope } from '../store/scope'
import type { CreateTaskResponse, Platform, RunRecord, TaskRecord } from '../types'

export function PerfPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const planned = !isImplementedPlatform(targetScope)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeTask, setActiveTask] = useState<TaskRecord | null>(null)
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
    () => (runsQuery.data?.items ?? []).filter((run) => run.test_type === 'perf'),
    [runsQuery.data],
  )

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
          title="性能运行"
          hint="指标口径：PSS 内存 / 应用进程 CPU / 帧率 / GPU 占用（明细接口在 P3）"
          actions={
            <Button size="small" icon="download">
              导出指标
            </Button>
          }
        />
        {perfRuns.length === 0 && !error ? (
          <Empty
            icon="pulse"
            title={planned ? '该目标端尚未接入' : '还没有性能运行'}
            description={
              planned
                ? 'iOS / Web 目标端暂无执行能力，接入后按同一套指标口径开通。'
                : '提交性能任务后，运行与门禁结论会出现在这里。'
            }
          />
        ) : (
          <Table
            columns={columns}
            rows={perfRuns}
            rowKey={(run) => run.id}
            ariaLabel="性能运行"
            onRowClick={openTaskOfRun}
            footer={<span>共 {perfRuns.length} 条性能运行</span>}
          />
        )}
      </Panel>

      <div className="mt">
        <Panel>
          <PanelHead title="门禁检查明细" hint="逐项检查来自后端，前端只展示级别、阈值与是否满足" />
          <Empty
            icon="flag"
            title="门禁明细接口尚未接入"
            description="每次性能运行完成后后端写入 gate_evaluations（原始 / 重算两种模式）；明细读接口在 P3 提供。"
          />
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
