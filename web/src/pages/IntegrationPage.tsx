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

// 与 docs/contracts/openapi.json 同源（AC-INT-01）：不把 runner 内部协议
//（/internal/*，X-Control-Token）宣传成普通接入 API。
const CAPS: { title: string; desc: string }[] = [
  { title: '测试定义写入', desc: 'POST /api/v1/tasks 创建任务草稿；PATCH /tasks/{id} 与 POST /tasks/{id}/validate 形成修订并验证（幂等键 request_key）。' },
  { title: '构建与套件登记', desc: 'POST /api/v1/builds 登记构建（同 key 同身份复用）；POST /api/v1/suites 登记套件并固定代码副本。' },
  { title: '运行发起与跟踪', desc: 'POST /api/v1/runs 发起运行（幂等键重复提交返回 200 + duplicate）；GET /runs/{id}/events 按序号补拉，WS /ws/runs/{id} 实时跟踪。' },
  { title: '结果与证据', desc: '结果由 runner 经内部协议上报并落库（runs/cases/metrics/gate_evaluations）；浏览器经 GET /runs/{id}/report 与 /artifacts 读取，error/available/expired 分别呈现。' },
  { title: '门禁评估', desc: '阈值评估在后端完成并写入 gate_evaluations；试算经 POST /runs/{id}/gate-evaluations 只新增 reanalysis，不改写原始判定。' },
]

const ERRORS: { code: string; desc: string }[] = [
  { code: 'validation_error', desc: '400 请求体字段缺失、类型不符或改写固定输入' },
  { code: 'readiness_incomplete', desc: '422 修订未验证或缺少显式身份（application_id/task_id）' },
  { code: 'not_found', desc: '404 任务/运行/修订不存在或跨归属引用' },
  { code: 'state_conflict', desc: '409 运行终态不可再改、取消竞争等状态不允许' },
  { code: 'stale_version', desc: '409 任务被他人更新（lock_version CAS 失败），请刷新重试' },
  { code: 'device_busy', desc: '409 目标资源已有活动租约（含占用者信息）' },
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
            <Empty loading icon="check" title="正在检查能力" description="正在请求 /api/v1/health；返回前不判断各项能力是否可用。" />
          ) : health ? (
            <div className="flex wrap" style={{ gap: 8 }}>
              {checks.map((check) => (
                <span
                  key={check.label}
                  className={'badge ' + (check.ok === null ? 'gray' : check.ok ? 'green' : 'red')}
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
            <PanelHead title="一次完整接入" hint="验证任务后发起运行，由执行器管理资源与上报" />
            <div className="panel-pad">
              <div className="flow-box">
                <span className="flow-node">定义</span>
                <span aria-hidden="true">→</span>
                <span className="flow-node">验证</span>
                <span aria-hidden="true">→</span>
                <span className="flow-node">执行</span>
                <span aria-hidden="true">→</span>
                <span className="flow-node">报告</span>
              </div>
              <pre className="code-block">{`POST /api/v1/tasks                       # 创建任务草稿
POST /api/v1/tasks/{id}/validate         # 验证当前修订，取得 revision_id
POST /api/v1/runs                        # 提交 application_id/task_id/revision_id/device
GET  /api/v1/runs/{id}/events             # 跟踪运行
GET  /api/v1/runs/{id}/report             # 读取原始结论与证据
GET  /api/v1/runs/{id}/report/export      # 导出报告 JSON`}</pre>
            </div>
          </Panel>
        </div>
      </div>
    </>
  )
}
