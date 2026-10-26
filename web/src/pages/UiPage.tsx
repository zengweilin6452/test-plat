/**
 * UI 自动化（原型 #ui / L188 起）。
 *
 * 数据源（P1 可用部分）：
 *  - 用例套件 / 执行记录：GET /api/v1/runs 里 test_type='ui' 的运行
 *  - 套件清单本身要等 test_suites 的读接口（P2），当前不伪造
 * 硬约束：断言结果与失败现场都来自后端，接口未接入时只显示空态。
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, describeError } from '../api/client'
import { createTemplate, fetchResources, fetchRuns, fetchTasks, fetchTemplates } from '../api/endpoints'
import type { ResourceRecord } from '../types'
import type { TemplateRecord } from '../api/types'
import { DebugDrawer, type DebugTarget } from '../components/DebugDrawer'
import { StatusBadge } from '../components/Badge'
import { Button } from '../components/Button'
import { LinkButton } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PlannedNotice, PrimaryAction, Toolbar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { Table, type Column } from '../components/Table'
import { TaskDrawer } from '../components/TaskDrawer'
import { TaskWizard } from '../components/TaskWizard'
import { useToast } from '../components/Toast'
import { Tabs, type TabItem } from '../components/Tabs'
import { MODULE_NAMES, TARGET_CATALOG, isImplementedPlatform } from '../constants'
import { displayStatus } from '../lib/display'
import { fmtDateTime } from '../lib/fmt'
import { useTargetScope } from '../store/scope'
import type { CreateTaskResponse, Platform, RunRecord, TaskRecord } from '../types'

type UiTab = 'runs' | 'suites' | 'cases' | 'debug' | 'templates'

const TABS: TabItem<UiTab>[] = [
  { value: 'runs', label: '执行记录' },
  { value: 'suites', label: '用例套件' },
  { value: 'cases', label: '用例' },
  { value: 'debug', label: '调试' },
  { value: 'templates', label: '模板' },
]

export function UiPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const [tab, setTab] = useState<UiTab>('runs')
  const [keyword, setKeyword] = useState('')
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeTask, setActiveTask] = useState<TaskRecord | null>(null)
  const [debugTarget, setDebugTarget] = useState<DebugTarget | null>(null)
  const planned = !isImplementedPlatform(targetScope)
  const queryClient = useQueryClient()
  const toast = useToast()

  const runsQuery = useQuery({
    queryKey: ['runs', 'ui', targetScope],
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
    // 找不到对应任务时不伪造一条：明确告诉用户任务详情接口/数据缺失
    toast.show(run.task_id ? '任务 ' + run.task_id + ' 不在当前任务列表中，无法打开详情' : '该运行没有关联任务')
  }

  function handleCreated(created: CreateTaskResponse) {
    toast.show('任务已创建：' + created.display_id + '（编号 ' + created.id + '）')
    setWizardOpen(false)
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    void queryClient.invalidateQueries({ queryKey: ['runs'] })
  }

  const error = runsQuery.isError ? describeError(runsQuery.error) : null
  const uiRuns = useMemo(() => {
    const all = (runsQuery.data?.items ?? []).filter((run) => run.test_type === 'ui')
    const key = keyword.trim().toLowerCase()
    if (!key) return all
    return all.filter(
      (run) =>
        run.name.toLowerCase().includes(key) ||
        run.display_id.toLowerCase().includes(key),
    )
  }, [runsQuery.data, keyword])

  // ---- 调试 tab：ready 设备清单（与 DevicesPage 同源 /api/v1/resources）----
  const resourcesQuery = useQuery({
    queryKey: ['resources'],
    queryFn: ({ signal }) => fetchResources(targetScope, signal),
    enabled: tab === 'debug',
    retry: false,
  })
  const readyDevices = useMemo(
    () => (resourcesQuery.data?.items ?? []).filter((item) => item.status === 'ready' && !item.busy),
    [resourcesQuery.data],
  )

  // ---- 模板 tab ----
  const templatesQuery = useQuery({
    queryKey: ['templates'],
    queryFn: ({ signal }) => fetchTemplates(signal),
    enabled: tab === 'templates',
    retry: false,
  })
  const templatesError = templatesQuery.isError ? describeError(templatesQuery.error) : null
  const templates = (templatesQuery.data?.items ?? []) as TemplateRecord[]

  async function handleTemplateUpload(logicalPath: string, file: File, confidence: number) {
    try {
      const pngBase64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => {
          const result = String(reader.result ?? '')
          const comma = result.indexOf(',')
          resolve(comma >= 0 ? result.slice(comma + 1) : result)
        }
        reader.onerror = () => reject(new Error('读取文件失败'))
        reader.readAsDataURL(file)
      })
      await createTemplate({ logical_path: logicalPath, png_base64: pngBase64, confidence })
      toast.show('模板已上传：' + logicalPath)
      void queryClient.invalidateQueries({ queryKey: ['templates'] })
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 501) {
        toast.show('需要活动调试会话：请先在「调试」页签建立会话')
        return
      }
      const described = describeError(cause)
      toast.show('上传失败（' + described.code + '）：' + described.message)
    }
  }

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
      key: 'status',
      header: '状态',
      render: (run) => <StatusBadge status={displayStatus(run.state, run.outcome)} />,
    },
    {
      key: 'resource',
      header: '资源',
      render: (run) => <span className="muted small">{run.resource ?? '—'}</span>,
    },
    {
      key: 'time',
      header: '创建时间',
      render: (run) => <span className="muted small">{fmtDateTime(run.created_at)}</span>,
    },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: (run) => (
        <LinkButton onClick={() => openTaskOfRun(run)}>
          任务详情<span aria-hidden="true">›</span>
        </LinkButton>
      ),
    },
  ]

  return (
    <>
      <PageHeading
        title="UI 自动化"
        description="用例、套件与执行记录：断言结果可追溯到报告与现场证据"
        actions={<PrimaryAction label="新建任务" icon="plus" onClick={() => setWizardOpen(true)} />}
      />
      <ContextBar
        scope={targetScope}
        onScopeChange={setTargetScope}
        extra={<span className="muted small">断言与现场证据均在后端留存</span>}
      />

      {planned ? (
        <div className="mb">
          <PlannedNotice scope={targetScope} />
        </div>
      ) : null}

      <Tabs items={TABS} active={tab} onChange={setTab} ariaLabel="UI 自动化视图" />

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'执行记录获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      <Panel>
        <PanelHead
          title={TABS.find((item) => item.value === tab)?.label ?? ''}
          hint={
            tab === 'runs'
              ? '失败运行的现场证据（截图 / 日志 / 步骤断言）随报告提供'
              : tab === 'debug'
                ? '调试会话与自动运行竞争同一资源租约；关闭抽屉即释放'
                : tab === 'templates'
                  ? '模板经 vendor TemplateStore 管理，路径校验由后端执行'
                  : '套件与用例的读接口在 P2 提供（test_suites / 用例表）'
          }
          actions={
            <Button kind="soft" size="small" icon="download">
              导出清单
            </Button>
          }
        />
        {tab === 'runs' ? (
          <>
            <div style={{ padding: '0 20px' }}>
              <Toolbar search={keyword} onSearch={setKeyword}>
                <span className="muted small">按运行名称或编号搜索</span>
              </Toolbar>
            </div>
            {uiRuns.length === 0 && !error ? (
              <Empty
                icon="phone"
                title={planned ? '该目标端尚未接入' : '还没有 UI 自动化运行'}
                description={
                  planned
                    ? 'iOS / Web 目标端暂无执行能力，接入后按同一套接口开通。'
                    : '创建 UI 用例并提交运行后，执行记录会出现在这里。'
                }
              />
            ) : (
              <Table
                columns={columns}
                rows={uiRuns}
                rowKey={(run) => run.id}
                ariaLabel="UI 自动化执行记录"
                onRowClick={openTaskOfRun}
                footer={<span>共 {uiRuns.length} 条 UI 运行 · 类型 {MODULE_NAMES.ui}</span>}
              />
            )}
          </>
        ) : tab === 'debug' ? (
          <DebugPanel
            devices={readyDevices}
            devicesLoading={resourcesQuery.isLoading}
            devicesError={resourcesQuery.isError ? describeError(resourcesQuery.error) : null}
            onOpen={(target) => setDebugTarget(target)}
          />
        ) : tab === 'templates' ? (
          <TemplatesPanel
            templates={templates}
            loading={templatesQuery.isLoading}
            error={templatesError}
            onUpload={handleTemplateUpload}
          />
        ) : (
          <Empty
            icon="layers"
            title={tab === 'suites' ? '用例套件尚未接入' : '用例清单尚未接入'}
            description="套件与用例的读接口（test_suites / 用例表）在 P2 提供。当前不展示任何占位数据。"
          />
        )}
      </Panel>

      <DebugDrawer
        open={Boolean(debugTarget)}
        target={debugTarget}
        onClose={() => setDebugTarget(null)}
      />

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


/** 调试页签：选 ready 设备 → 开会话（复用 DebugDrawer） */
function DebugPanel({
  devices,
  devicesLoading,
  devicesError,
  onOpen,
}: {
  devices: ResourceRecord[]
  devicesLoading: boolean
  devicesError: ReturnType<typeof describeError> | null
  onOpen: (target: DebugTarget) => void
}) {
  if (devicesError) {
    return (
      <div className="panel-pad">
        <Notice tone="red" title={'资源列表获取失败（' + devicesError.code + '）'}>
          {devicesError.message}
        </Notice>
      </div>
    )
  }
  if (devicesLoading) {
    return <Empty icon="phone" title="正在加载资源" description="正在请求 /api/v1/resources" />
  }
  if (devices.length === 0) {
    return (
      <Empty
        icon="phone"
        title="没有可调试的设备"
        description="调试会话要求资源 status=ready 且未被运行或调试占用。"
      />
    )
  }
  return (
    <div className="panel-pad">
      <div className="muted small" style={{ marginBottom: 10 }}>
        点击设备打开调试抽屉：创建调试会话后可实时预览画面、浏览快照层级树并验证定位表达式。
      </div>
      <div className="flex wrap" style={{ gap: 8 }}>
        {devices.map((device) => (
          <Button key={device.id} size="small" icon="phone" onClick={() => onOpen(toDebugTarget(device))}>
            {device.name}
            <span className="muted small"> {device.resource_key ?? device.resource_key}</span>
          </Button>
        ))}
      </div>
    </div>
  )
}

function toDebugTarget(device: ResourceRecord): DebugTarget {
  const hint = device.lease
    ? device.lease.run_id
      ? '运行 ' + device.lease.run_id.slice(0, 8) + ' 占用中'
      : '调试会话占用中'
    : null
  return { serial: device.resource_key ?? device.resource_key, label: device.name, leaseHint: hint }
}

/** 模板页签：清单 + 上传表单（logical_path + png 文件 → base64） */
function TemplatesPanel({
  templates,
  loading,
  error,
  onUpload,
}: {
  templates: TemplateRecord[]
  loading: boolean
  error: ReturnType<typeof describeError> | null
  onUpload: (logicalPath: string, file: File, confidence: number) => void
}) {
  const [logicalPath, setLogicalPath] = useState('')
  const [confidence, setConfidence] = useState('0.85')
  const [file, setFile] = useState<File | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)

  function submit() {
    setLocalError(null)
    if (!logicalPath.trim() || logicalPath.includes('..') || logicalPath.startsWith('/')) {
      setLocalError('模板路径必须是不含 .. 与开头 / 的相对逻辑路径')
      return
    }
    if (!file) {
      setLocalError('请选择 png 模板图片')
      return
    }
    const value = Number(confidence)
    if (!Number.isFinite(value) || value <= 0 || value > 1) {
      setLocalError('置信度需要是 0–1 之间的数字')
      return
    }
    onUpload(logicalPath.trim(), file, value)
  }

  return (
    <div className="panel-pad">
      {error ? (
        <div className="mb">
          <Notice tone="red" title={'模板清单获取失败（' + error.code + '）'}>
            {error.message}
            {error.code === 'HTTP_404' || error.code === 'not_found' ? (
              <div className="small" style={{ marginTop: 6 }}>
                GET /api/v1/templates 可能尚未上线，请与后端确认。
              </div>
            ) : null}
          </Notice>
        </div>
      ) : null}

      <div className="mb" style={{ maxWidth: 560, display: 'grid', gap: 8 }}>
        <strong className="small">上传模板</strong>
        <label className="small">
          逻辑路径
          <input
            className="search"
            style={{ width: '100%' }}
            value={logicalPath}
            onChange={(event) => setLogicalPath(event.target.value)}
            placeholder="如 buttons/confirm.png"
          />
        </label>
        <label className="small">
          png 模板图片
          <input
            type="file"
            accept="image/png"
            style={{ display: 'block', marginTop: 4 }}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label className="small">
          置信度（0–1）
          <input
            className="search"
            style={{ width: 120 }}
            value={confidence}
            onChange={(event) => setConfidence(event.target.value)}
          />
        </label>
        {localError ? <Notice tone="amber">{localError}</Notice> : null}
        <div>
          <Button kind="primary" size="small" icon="plus" onClick={submit}>
            上传模板
          </Button>
        </div>
        <span className="muted small">
          上传走 POST /api/v1/templates；后端返回 501 时表示需要活动调试会话。
        </span>
      </div>

      {loading ? (
        <Empty icon="layers" title="正在加载模板" description="正在请求 /api/v1/templates" />
      ) : !error && templates.length === 0 ? (
        <Empty icon="layers" title="暂无模板" description="上传 png 模板后在此展示。" />
      ) : templates.length > 0 ? (
        <div className="table-wrap">
          <table className="task-table" aria-label="图像模板清单">
            <thead>
              <tr>
                <th>逻辑路径</th>
                <th>版本</th>
                <th>置信度</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              {templates.map((template) => (
                <tr key={template.logical_path}>
                  <td className="mono">{template.logical_path}</td>
                  <td>{template.version ?? '—'}</td>
                  <td className="mono">
                    {typeof template.confidence === 'number' ? template.confidence.toFixed(2) : '—'}
                  </td>
                  <td className="muted small">{fmtDateTime(template.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
