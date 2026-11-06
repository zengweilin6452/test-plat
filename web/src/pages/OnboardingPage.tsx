import { useState } from 'react'
import { ONBOARDING_SKIP_KEY, onboardingSkipped } from '../lib/formalization'
/** 首次使用引导：完成状态来自服务端真实数据，可跳过并随时返回。 */
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { describeError } from '../api/client'
import { fetchOnboardingStatus } from '../api/endpoints'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Notice } from '../components/Notice'
import { useEffectiveContext } from '../store/effectiveContext'
import { usePlatform } from '../store/platform'



export function OnboardingPage() {
  const { refresh } = useEffectiveContext()
  const { capabilities } = usePlatform()
  const query = useQuery({
    queryKey: ['onboarding-status'],
    queryFn: ({ signal }) => fetchOnboardingStatus(signal),
    retry: false,
  })
  const [skipped, setSkipped] = useState(onboardingSkipped)
  const navigate = useNavigate()
  const error = query.isError ? describeError(query.error) : null

  return (
    <>
      <PageHeading
        title="首次使用"
        description="按真实数据计算待办，不生成演示项目、伪设备或假运行结果"
        actions={
          <button
            className="link-btn"
            type="button"
            onClick={() => {
              setSkipped(true)
              try { window.localStorage.setItem(ONBOARDING_SKIP_KEY, '1') } catch { /* 忽略存储失败 */ }
              navigate('/overview', { replace: true })
            }}
          >
            跳过引导
          </button>
        }
      />
      {capabilities?.demo_mode ? (
        <Notice tone="amber" title="演示环境">当前为显式演示环境；引导中的完成状态仍按真实记录计算。</Notice>
      ) : null}
      {skipped ? <Notice tone="blue" title="引导已跳过">可以随时返回本页，待办状态会按当前数据重新计算。</Notice> : null}
      {error ? (
        <Notice tone="red" title={'待办状态读取失败（' + error.code + '）'}>
          {error.message}
          {error.requestId ? <div className="small muted">请求 ID：{error.requestId}</div> : null}
          <div><button className="link-btn" type="button" onClick={() => query.refetch()}>重试</button></div>
        </Notice>
      ) : null}
      {query.isLoading ? <Notice tone="blue" title="正在核对真实数据">正在读取工作空间、项目、应用、设备与运行记录…</Notice> : null}
      {query.data ? (
        <Panel>
          <PanelHead title="使用待办" hint={query.data.complete ? '全部完成' : '完成状态由真实数据计算'} />
          <div className="panel-pad">
            <ol className="onboarding-list">
              {query.data.steps.map((step) => (
                <li key={step.key} className={step.done ? 'done' : ''}>
                  <strong>{step.done ? '✓ ' : '○ '}{step.title}</strong>
                  <div className="muted small">{step.description} · 当前 {step.count} 项</div>
                  {!step.done && step.target ? (
                    <Link
                      className="link-btn"
                      to={step.target}
                      onClick={() => { refresh(); query.refetch() }}
                    >
                      前往对应页面
                    </Link>
                  ) : null}
                </li>
              ))}
            </ol>
            {!query.data.complete ? (
              <p className="muted small">
                缺少可信来源、设备或性能前置条件时，对应页面会给出准确原因和下一步，不会伪造可用状态。
              </p>
            ) : (
              <p>已具备第一次运行的真实条件；可继续在任务中心创建任务并查看报告与证据。</p>
            )}
          </div>
        </Panel>
      ) : null}
    </>
  )
}
