/**
 * 报告中心（原型 #reports / L214 一句话结论）。
 *
 * 结论文案映射表照抄原型，但它只用于**展示后端已给出的结论**，不是前端判定：
 *   not_tested → 样本不足，未产生门禁结论
 *   ui   failed → 断言未满足，已保留失败现场
 *   ui   passed → 用例断言通过，执行过程可追溯
 *   perf failed → 性能阈值未满足，查看指标与基线
 *   perf passed → 性能门禁通过，指标与基线可比
 *
 * 数据源：
 *  - 清单：已完成运行（state='completed'）；
 *  - 「查看报告」：GET /runs/{id}/report + GET /runs/{id}/artifacts（ReportDrawer）。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchRuns } from '../api/endpoints'
import { StatusBadge } from '../components/Badge'
import { Button, LinkButton } from '../components/Button'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar, PrimaryAction, Toolbar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { ReportDrawer } from '../components/ReportDrawer'
import { Table, type Column } from '../components/Table'
import { TARGET_CATALOG, isPerformanceType } from '../constants'
import { displayStatus } from '../lib/display'
import { fmtDateTime } from '../lib/fmt'
import { useTargetScope } from '../store/scope'
import type { RunOutcome, RunRecord } from '../types'

/** 原型 L214 的映射表：只做文案映射，不做判定（module 用后端原始枚举） */
export function conclusionText(module: string | null, outcome: RunOutcome | null): string {
  if (outcome === null) return '后端尚未给出结论'
  if (outcome === 'not_tested') return '样本不足，未产生门禁结论'
  if (isPerformanceType(module)) {
    return outcome === 'passed' ? '性能门禁通过，指标与基线可比' : '性能阈值未满足，查看指标与基线'
  }
  return outcome === 'passed' ? '用例断言通过，执行过程可追溯' : '断言未满足，已保留失败现场'
}

export function ReportsPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const [activeRun, setActiveRun] = useState<RunRecord | null>(null)
  // 服务端过滤 + 游标分页（工单 10）：q / module / 页栈变化都重新拉取；
  // 过滤条件变化时页栈清零，旧游标带新过滤条件会被服务端 422 拒掉。
  const [keyword, setKeyword] = useState('')
  const [module, setModule] = useState<'' | 'ui' | 'performance'>('')
  const [pages, setPages] = useState<(string | null)[]>([])
  const cursor = pages.length > 0 ? pages[pages.length - 1] : null

  const runsQuery = useQuery({
    queryKey: ['runs', 'reports', targetScope, keyword, module, cursor],
    queryFn: ({ signal }) =>
      fetchRuns(targetScope, 50, signal, {
        state: 'completed',
        q: keyword.trim() || undefined,
        test_type: module || undefined,
        cursor: cursor ?? undefined,
      }),
    retry: false,
  })

  const error = runsQuery.isError ? describeError(runsQuery.error) : null
  // 只有完成的运行才有报告：completed 过滤在服务端完成，前端不再从
  // 全量列表里筛 —— 第 201 份之后的报告也能靠游标翻到（AC-REP-01）。
  const completed = runsQuery.data?.items ?? []

  const columns: Column<RunRecord>[] = [
    {
      key: 'name',
      header: '报告 / 运行',
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
      header: '结论',
      render: (run) => <StatusBadge status={displayStatus(run.state, run.outcome)} />,
    },
    {
      key: 'conclusion',
      header: '一句话结论',
      wrap: true,
      render: (run) => <span className="muted small">{conclusionText(run.test_type, run.outcome)}</span>,
    },
    {
      key: 'time',
      header: '结束时间',
      render: (run) => <span className="muted small">{fmtDateTime(run.ended_at)}</span>,
    },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: (run) => (
        <LinkButton onClick={() => setActiveRun(run)}>
          查看报告<span aria-hidden="true">›</span>
        </LinkButton>
      ),
    },
  ]

  return (
    <>
      <PageHeading
        title="报告中心"
        description="统一报告视图：结论、证据与可比性说明"
        actions={<PrimaryAction label="导出报告" icon="download" />}
      />
      <ContextBar
        scope={targetScope}
        onScopeChange={(scope) => {
          setTargetScope(scope)
          setPages([])
        }}
      />

      <div className="mb">
        <Toolbar
          search={keyword}
          onSearch={(value) => {
            setKeyword(value)
            setPages([])
          }}
        >
          <select
            value={module}
            onChange={(event) => {
              setModule(event.target.value as '' | 'ui' | 'performance')
              setPages([])
            }}
            aria-label="按模块筛选"
          >
            <option value="">全部模块</option>
            <option value="ui">UI</option>
            <option value="performance">性能</option>
          </select>
          <span className="muted small">
            搜索命中编号 / 任务名 / 应用名，completed 过滤在服务端完成
          </span>
        </Toolbar>
      </div>

      <div className="mb">
        <Notice tone="blue" icon="alert" title="结论只有一种来源">
          报告的通过 / 未通过 / 未判定都来自后端结果与门禁评估；前端只负责展示。
          outcome 为空时按「未判定」呈现，不会显示成失败或通过。
        </Notice>
      </div>

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'报告清单获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      <Panel>
        <PanelHead
          title="报告清单"
          hint="只列出已完成运行；证据链与可比性说明随报告提供（P4 接入）"
        />
        {completed.length === 0 && !error ? (
          <Empty
            icon="report"
            title="还没有已完成的运行"
            description="运行结束后会生成报告，这里按任务列出结论、证据与可比性说明。"
          />
        ) : (
          <Table
            columns={columns}
            rows={completed}
            rowKey={(run) => run.id}
            ariaLabel="报告清单"
            footer={
              <span className="muted small">
                本页 {completed.length} 份
                {runsQuery.data?.has_more ? ` · 还有更多（已翻到第 ${pages.length + 1} 页）` : ''}
              </span>
            }
          />
        )}
        {pages.length > 0 || runsQuery.data?.has_more ? (
          <div className="toolbar mt">
            <Button
              disabled={pages.length === 0}
              onClick={() => setPages((current) => current.slice(0, -1))}
            >
              上一页
            </Button>
            <Button
              disabled={!runsQuery.data?.has_more || !runsQuery.data?.next_cursor}
              onClick={() =>
                setPages((current) => [...current, runsQuery.data?.next_cursor ?? null])
              }
            >
              下一页
            </Button>
          </div>
        ) : null}
      </Panel>

      <div className="result-grid mt">
        <Panel className="report-card">
          <span className="badge gray">
            <i className="dot" />
            待接入
          </span>
          <h3>证据链</h3>
          <p>
            截图、日志、指标快照与门禁检查明细会作为证据挂到报告下，前端按可用性展示
            （available / missing / expired）。
          </p>
          <footer>
            <span className="muted small">—</span>
            <span className="muted small">—</span>
          </footer>
        </Panel>
        <Panel className="report-card">
          <span className="badge gray">
            <i className="dot" />
            待接入
          </span>
          <h3>可比性</h3>
          <p>基线不可比时报告会显式标注原因，不给出差值，也不把缺失值写成 0。</p>
          <footer>
            <span className="muted small">—</span>
            <span className="muted small">—</span>
          </footer>
        </Panel>
      </div>

      <ReportDrawer
        open={Boolean(activeRun)}
        run={activeRun}
        onClose={() => setActiveRun(null)}
      />
    </>
  )
}
