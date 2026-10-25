/**
 * 任务中心（原型 #tasks / L186 taskTable）。
 *
 * 数据源：GET /api/v1/tasks（主表）+ 每行最近一次运行。
 * 任务与运行是两层：草稿任务用 TASK- 前缀，已产生运行的用 RUN- 前缀（display_id 由后端给）。
 *
 * 硬约束：state 与 outcome 分开呈现；outcome 为空时不显示通过/未通过。
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchTasks } from '../api/endpoints'
import { StatusBadge } from '../components/Badge'
import { LinkButton } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PrimaryAction, Toolbar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import { TaskDrawer } from '../components/TaskDrawer'
import { TaskWizard } from '../components/TaskWizard'
import { useToast } from '../components/Toast'
import { MODULE_NAMES, TARGET_CATALOG } from '../constants'
import { displayStatus, displayTaskStatus } from '../lib/display'
import { DASH, fmtDateTime } from '../lib/fmt'
import { useTargetScope } from '../store/scope'
import type { CreateTaskResponse, Platform, TaskRecord } from '../types'

export function TasksPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const [keyword, setKeyword] = useState('')
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeTask, setActiveTask] = useState<TaskRecord | null>(null)
  const queryClient = useQueryClient()
  const toast = useToast()

  const tasksQuery = useQuery({
    queryKey: ['tasks', keyword],
    queryFn: ({ signal }) => fetchTasks(undefined, keyword || undefined, signal),
    retry: false,
  })

  /**
   * 创建成功：Toast 提示（带后端给的编号）→ 关闭向导 → refetch 任务列表。
   * 不在这里乐观插入行 —— 列表口径以后端为准。
   */
  function handleCreated(created: CreateTaskResponse) {
    toast.show('任务已创建：' + created.display_id + '（编号 ' + created.id + '）')
    setWizardOpen(false)
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
  }

  const error = tasksQuery.isError ? describeError(tasksQuery.error) : null
  const all = tasksQuery.data?.items ?? []
  // 目标端过滤在前端做：/tasks 目前只支持 test_type 与 q 两个参数
  const rows = useMemo(
    () => all.filter((task) => targetScope === 'all' || task.platform === targetScope),
    [all, targetScope],
  )

  const columns: Column<TaskRecord>[] = [
    {
      key: 'name',
      header: '任务名称 / 编号',
      render: (task) => (
        <>
          <span className="task-name">{task.name}</span>
          <div className="task-sub">
            {task.display_id} · 修订 {task.revision_count} 版
          </div>
        </>
      ),
    },
    {
      key: 'target',
      header: '目标端 / 类型',
      render: (task) => (
        <>
          <span className="module-pill">{TARGET_CATALOG[task.platform]?.label ?? task.platform}</span>{' '}
          <span className="muted small">{task.test_type ? MODULE_NAMES[task.test_type] : '未指定类型'}</span>
          <div className="task-sub">{task.application.name}</div>
        </>
      ),
    },
    {
      key: 'status',
      header: '状态',
      render: (task) => {
        // 还没有运行 → 展示任务生命周期态（草稿/已验证）；有运行 → 展示运行态
        if (!task.run) {
          return <StatusBadge status={displayTaskStatus(task.lifecycle, task.readiness)} />
        }
        return (
          <div>
            <StatusBadge status={displayStatus(task.run.state, task.run.outcome)} />
            {task.run.outcome === null && task.run.state === 'completed' ? (
              <div className="task-sub">后端未给出结论</div>
            ) : null}
          </div>
        )
      },
    },
    {
      key: 'resource',
      header: '组件 / 时间',
      render: (task) => (
        <span className="muted small">
          {task.run?.component_total === null || task.run?.component_total === undefined
            ? '无组件'
            : task.run.component_total + ' 个组件'}
          <div className="task-sub">{fmtDateTime(task.run?.created_at)}</div>
        </span>
      ),
    },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: (task) => (
        <LinkButton onClick={() => setActiveTask(task)}>
          {task.run ? '查看执行' : '查看配置'}
          <span aria-hidden="true">›</span>
        </LinkButton>
      ),
    },
  ]

  return (
    <>
      <PageHeading
        title="任务中心"
        description="全部测试任务的配置、执行与结果入口"
        actions={<PrimaryAction label="新建任务" icon="plus" onClick={() => setWizardOpen(true)} />}
      />
      <ContextBar
        scope={targetScope}
        onScopeChange={setTargetScope}
        extra={<span className="muted small">草稿编号以 TASK- 开头，其余为 RUN-</span>}
      />

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'任务列表获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      <Panel>
        <PanelHead
          title="任务列表"
          hint="每行展示最新修订与最近一次运行；点击可查看执行详情"
        />
        <div style={{ padding: '0 20px' }}>
          <Toolbar search={keyword} onSearch={setKeyword}>
            <span className="muted small">按任务名称或编号搜索（服务端过滤 ?q=）</span>
          </Toolbar>
        </div>
        {tasksQuery.isLoading ? (
          <Empty icon="tasks" title="正在加载任务" description="正在请求 /api/v1/tasks" />
        ) : rows.length === 0 && !error ? (
          <Empty
            icon="tasks"
            title="还没有测试任务"
            description="任务创建与提交流程在 P2 提供；当前展示数据库中已有的任务。"
          />
        ) : (
          <Table
            columns={columns}
            rows={rows}
            rowKey={(task) => task.id}
            ariaLabel="任务列表"
            onRowClick={(task) => setActiveTask(task)}
            footer={<span>共 {rows.length} 个任务 · 当前筛选 {targetScope === 'all' ? '全部目标端' : TARGET_CATALOG[targetScope].label}</span>}
          />
        )}
      </Panel>

      <div className="mt muted small">
        运行编号与任务编号由后端生成：草稿 {DASH} 无运行，提交后产生 RUN- 编号。
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
