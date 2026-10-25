/**
 * 接入说明（原型 #integration）。
 * 说明外部系统（CI、脚本、测试框架）如何把测试定义与结果写入平台。
 * 内容是接口约定，不是业务数据，因此可以静态呈现。
 */
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { ContextBar } from '../components/PageBits'
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

  return (
    <>
      <PageHeading
        title="接入说明"
        description="外部系统如何把测试定义与结果写入平台"
      />
      <ContextBar scope={targetScope} onScopeChange={setTargetScope} extra={<span className="muted small">接口基址 /api/v1</span>} />

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
