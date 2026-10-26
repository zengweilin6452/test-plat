/**
 * 接入说明（原型 #integration）。
 * 说明外部系统（CI、脚本、测试框架）如何把测试定义与结果写入平台。
 * 内容是接口约定，不是业务数据，因此可以静态呈现。
 */
import { useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import { fetchHealth } from '../api/endpoints'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar } from '../components/PageBits'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { useTargetScope } from '../store/scope'

const CAPS: { title: string; desc: string }[] = [
  { title: '测试定义写入', desc: '用例、套件与任务草稿经 POST /api/v1/tasks 写入，草稿编号以 TASK- 开头。' },
  { title: '执行资源申请', desc: '执行前向后端申请租约（lease），成功后资源状态变为占用中。' },
  { title: '执行结果上报', desc: '结果经 POST /api/v1/runs/{id}/results 上报，包含断言、日志与产物引用。' },
  { title: '性能指标上报', desc: '指标样本写入 run_metrics，统计口径由后端统一计算（中位数 / P95 等）。' },
  { title: '门禁评估', desc: '阈值评估在后端完成并写入 gate_evaluations，接入方不需要也不应该自行判定。' },
]

const ERRORS: { code: string; desc: string }[] = [
  { code: 'VALIDATION_FAILED', desc: '请求体字段缺失或类型不符' },
  { code: 'RESOURCE_UNAVAILABLE', desc: '目标资源无租约可发放' },
  { code: 'TASK_NOT_FOUND', desc: '任务编号不存在或已归档' },
  { code: 'GATE_NOT_EVALUATED', desc: '该运行尚无门禁结论（样本不足或仍在执行）' },
]

export function IntegrationPage() {
  const { targetScope, setTargetScope } = useTargetScope()

  // 能力核查表（动态）：GET /api/v1/health。未上线/失败时只提示，不造假数据。
  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => fetchHealth(signal),
    retry: false,
    refetchInterval: 30_000,
  })
  const health = healthQuery.data ?? null
  const healthError = healthQuery.isError ? describeError(healthQuery.error) : null

  // 能力核查只渲染 /health 实际返回的字段；缺失的字段不显示 0 或假状态（领域规则）。
  const checks: { label: string; ok: boolean | null; detail: string }[] = [
    { label: '后端服务', ok: health ? health.status === 'ok' : null, detail: health?.status ?? '—' },
    ...(health?.db != null
      ? [{ label: '数据库', ok: health.db === 'ok', detail: String(health.db) }]
      : []),
    ...(health?.vendor?.mobile_auto != null
      ? [{ label: 'mobile_auto vendor', ok: Boolean(health.vendor.mobile_auto), detail: String(health.vendor.mobile_auto) }]
      : []),
    ...(health?.vendor?.mobile_perf != null
      ? [{ label: 'mobile_perf vendor', ok: Boolean(health.vendor.mobile_perf), detail: String(health.vendor.mobile_perf) }]
      : []),
    ...(health?.runners?.active != null
      ? [{ label: '执行器', ok: health.runners.active >= 0, detail: '活跃 runner × ' + String(health.runners.active) }]
      : []),
    ...(health?.database_target != null
      ? [{ label: '数据库目标', ok: null, detail: String(health.database_target) }]
      : []),
  ]

  return (
    <>
      <PageHeading
        title="接入说明"
        description="外部系统如何把测试定义与结果写入平台"
      />
      <ContextBar scope={targetScope} onScopeChange={setTargetScope} extra={<span className="muted small">接口基址 /api/v1</span>} />

      <Panel className="mb">
        <PanelHead title="能力核查" hint="来自 GET /api/v1/health，30s 自动刷新" />
        <div className="panel-pad" style={{ paddingTop: 4 }}>
          {healthError ? (
            <Notice tone="red" title={'健康检查失败（' + healthError.code + '）'}>
              {healthError.message}
              {healthError.code === 'HTTP_404' || healthError.code === 'not_found' ? (
                <div className="small" style={{ marginTop: 6 }}>
                  GET /api/v1/health 可能尚未上线，端点就绪后此核查表自动生效。
                </div>
              ) : null}
            </Notice>
          ) : healthQuery.isLoading ? (
            <Empty icon="check" title="正在检查能力" description="正在请求 /api/v1/health" />
          ) : health ? (
            <div className="flex wrap" style={{ gap: 8 }}>
              {checks.map((check) => (
                <span
                  key={check.label}
                  className={'badge ' + (check.ok ? 'green' : 'red')}
                  title={check.label + '：' + check.detail}
                >
                  <i className="dot" />
                  {check.label} · {check.detail}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </Panel>

      <div className="mb">
        <Notice tone="amber" icon="alert" title="鉴权与幂等">
          接入方需要携带访问凭据；写接口均应带幂等键，重试不会产生重复记录。
          凭据只放在服务端，前端页面永远不直连数据库。
        </Notice>
      </div>

      <div className="integration-grid">
        <Panel>
          <PanelHead title="平台能力" hint="外部系统可以使用的写入与查询能力" />
          <div className="panel-pad" style={{ paddingTop: 4 }}>
            {CAPS.map((cap) => (
              <div className="cap-row" key={cap.title}>
                <span>{cap.title}</span>
                <p>{cap.desc}</p>
              </div>
            ))}
          </div>
        </Panel>

        <div className="stack">
          <Panel>
            <PanelHead title="错误码" hint="统一错误信封 { code, message, request_id }" />
            <div className="panel-pad" style={{ paddingTop: 4 }}>
              {ERRORS.map((item) => (
                <div className="cap-row" key={item.code}>
                  <span className="mono">{item.code}</span>
                  <p>{item.desc}</p>
                </div>
              ))}
            </div>
          </Panel>

          <Panel>
            <PanelHead title="一次完整接入" hint="四步走通：定义 → 申请 → 执行 → 上报" />
            <div className="panel-pad">
              <div className="flow-box">
                <span className="flow-node">定义</span>
                <span aria-hidden="true">→</span>
                <span className="flow-node">租约</span>
                <span aria-hidden="true">→</span>
                <span className="flow-node">执行</span>
                <span aria-hidden="true">→</span>
                <span className="flow-node">上报</span>
              </div>
              <pre className="code-block">{`POST /api/v1/tasks                       # 写入任务草稿（TASK-）
POST /api/v1/resources/{id}/lease         # 申请执行资源
POST /api/v1/runs/{id}/results            # 上报断言与产物
GET  /api/v1/runs/{id}/gate               # 读取门禁结论`}</pre>
            </div>
          </Panel>
        </div>
      </div>
    </>
  )
}
