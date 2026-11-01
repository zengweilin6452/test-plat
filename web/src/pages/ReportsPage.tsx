/**
 * 报告中心（原型 #reports / L214 一句话结论）。
 *
 * 结论文案映射表照抄原型，但它只用于**展示后端已给出的结论**，不是前端判定：
 *   not_tested → 未产生门禁结论，具体原因来自运行和原始报告
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
import { PageHeading } from '../components/Card'
import { ContextBar, Toolbar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { ReportDrawer } from '../components/ReportDrawer'
import { TARGET_CATALOG, isPerformanceType } from '../constants'
import { displayStatus } from '../lib/display'
import { fmtDateTime } from '../lib/fmt'
import { pagePhase, type PagePhase } from '../lib/pageState'
import { useTargetScope } from '../store/scope'
import type { RunOutcome, RunRecord } from '../types'

/** 原型 L214 的映射表：只做文案映射，不做判定（module 用后端原始枚举） */
export function conclusionText(module: string | null, outcome: RunOutcome | null): string {
  if (outcome === null) return '后端尚未给出结论'
  if (outcome === 'not_tested') return '未产生门禁结论，查看报告中的具体原因'
  if (module === 'joint') return outcome === 'passed' ? '联动测试通过，查看组件结论与证据' : '联动测试未通过，查看各组件的具体原因'
  if (isPerformanceType(module)) {
    return outcome === 'passed' ? '性能门禁通过，指标与基线可比' : '性能阈值未满足，查看指标与基线'
  }
  return outcome === 'passed' ? '用例断言通过，执行过程可追溯' : '断言未满足，已保留失败现场'
}

/**
 * 报告清单占位文案：加载中 / 失败 / 无任何已完成运行 / 筛选后为空 四种互不冒充。
 * filtered=true 时说明是筛选条件导致空，指引清除筛选，而不是让用户以为平台没跑过。
 */
export function reportsEmptyCopy(phase: PagePhase, filtered: boolean): { title: string; description: string } {
  if (phase === 'loading') {
    return {
      title: '正在加载报告清单',
      description: '正在请求 GET /api/v1/runs?state=completed；返回前不判断有没有报告。',
    }
  }
  if (phase === 'error') {
    return {
      title: '报告清单暂不可用',
      description: '接口返回错误（见上方错误码），请稍后重试；这不代表没有已完成运行。',
    }
  }
  if (filtered) {
    return {
      title: '没有匹配筛选条件的已完成运行',
      description: '清除搜索关键词或把模块切回「全部模块」再看；筛选不影响历史报告留存。',
    }
  }
  return {
    title: '还没有已完成的运行',
    description: '运行结束后会生成报告，这里按任务列出结论、证据与可比性说明。',
  }
}

export function ReportsPage() {
  const { targetScope, setTargetScope } = useTargetScope()
  const [activeRun, setActiveRun] = useState<RunRecord | null>(null)
  // 服务端过滤 + 游标分页（工单 10）：q / module / 页栈变化都重新拉取；
  // 过滤条件变化时页栈清零，旧游标带新过滤条件会被服务端 422 拒掉。
  const [keyword, setKeyword] = useState('')
  const [module, setModule] = useState<'' | 'ui' | 'performance' | 'joint'>('')
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
  const filtered = Boolean(keyword.trim() || module)
  const listPhase = pagePhase({
    isLoading: runsQuery.isLoading,
    isError: runsQuery.isError,
    count: completed.length,
  })
  const emptyCopy = reportsEmptyCopy(listPhase, filtered)
  const nextCursor = runsQuery.data?.next_cursor ?? null
  const pageNo = pages.length + 1


  return (
    <>
      <PageHeading title="报告中心" description="保留每次运行的原始结论，从结果回到证据。" />
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
              setModule(event.target.value as '' | 'ui' | 'performance' | 'joint')
              setPages([])
            }}
            aria-label="按模块筛选"
          >
            <option value="">全部模块</option>
            <option value="ui">UI</option>
            <option value="performance">性能</option>
            <option value="joint">联动</option>
          </select>
          <span className="muted small">重跑创建新记录，不覆盖历史证据</span>
        </Toolbar>
      </div>

      {error ? (
        <div className="mb">
          <Notice tone="red" title={'报告清单获取失败（' + error.code + '）'}>
            {error.message}
          </Notice>
        </div>
      ) : null}

      {listPhase === 'loading' ? (
        <Empty loading title={emptyCopy.title} description={emptyCopy.description} />
      ) : listPhase === 'error' ? (
        <Empty title={emptyCopy.title} description={emptyCopy.description} />
      ) : completed.length === 0 ? (
        <Empty icon="report" title={emptyCopy.title} description={emptyCopy.description} />
      ) : (
        <div className="resource-grid">
          {completed.map((run) => (
            <section key={run.id} className="panel report-card">
              <div className="between">
                <span className="module-pill">
                  {TARGET_CATALOG[run.platform]?.label ?? run.platform} /{' '}
                  {run.test_type === 'performance' ? '性能' : run.test_type === 'joint' ? '联动' : 'UI'}
                </span>
                <StatusBadge status={displayStatus(run.state, run.outcome)} />
              </div>
              <h3>{run.name}</h3>
              <p>
                {run.display_id} / {run.resource ?? '未分配资源'}
              </p>
              <p className="mt">{run.outcome === 'not_tested' && run.not_tested_reason ? run.not_tested_reason : conclusionText(run.test_type, run.outcome)}</p>
              <footer>
                <span className="muted small">{fmtDateTime(run.ended_at)}</span>
                <LinkButton onClick={() => setActiveRun(run)}>
                  查看报告 <span aria-hidden="true">›</span>
                </LinkButton>
              </footer>
            </section>
          ))}
        </div>
      )}

      {completed.length > 0 ? (
        <div className="between mt">
          <span className="muted small">
            第 {pageNo} 页 · 本页 {completed.length} 条
          </span>
          <div className="flex">
            <Button
              disabled={pages.length === 0 || runsQuery.isFetching}
              title={pages.length === 0 ? '已经是第一页' : undefined}
              onClick={() => setPages((stack) => stack.slice(0, -1))}
            >
              上一页
            </Button>
            <Button
              disabled={!nextCursor || runsQuery.isFetching}
              title={!nextCursor ? '后端没有返回下一页游标（已到最后一页）' : undefined}
              onClick={() => setPages((stack) => [...stack, nextCursor])}
            >
              下一页
            </Button>
          </div>
        </div>
      ) : null}

      <ReportDrawer
        open={Boolean(activeRun)}
        run={activeRun}
        onClose={() => setActiveRun(null)}
      />
    </>
  )
}
