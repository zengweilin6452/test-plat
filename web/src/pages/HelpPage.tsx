/** 帮助页：承接接入说明、数据设计、旧帮助深链接与开发者资料入口。 */
import { Link } from 'react-router-dom'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Notice } from '../components/Notice'
import { usePlatform } from '../store/platform'

export function HelpPage() {
  const { capabilities } = usePlatform()
  return (
    <>
      <PageHeading title="帮助" description="接入说明、数据设计与旧数据处理" />
      <div className="mb">
        <Notice tone="blue" title="旧路径仍然可用">
          /integration 与 /database 深链接仍指向原有接入说明和数据设计页面，不需要迁移书签。
        </Notice>
      </div>
      <Panel>
        <PanelHead title="接入与使用" hint="正式产品文案" />
        <div className="panel-pad">
          <ul>
            <li><Link className="link-btn" to="/integration">接入说明</Link>：外部系统如何把测试定义与结果写入平台。</li>
            <li><Link className="link-btn" to="/database">数据设计</Link>：实体关系、字段字典与写入流程。</li>
            <li><Link className="link-btn" to="/onboarding">首次使用引导</Link>：从空库到第一次真实运行。</li>
            <li><Link className="link-btn" to="/legacy-review">旧演示数据预览</Link>：只预览，逐项确认后才执行。</li>
            <li><Link className="link-btn" to="/settings">工作空间设置</Link>：改名与产品版本信息。</li>
          </ul>
          <p className="muted small">
            目标端能力：{capabilities?.platforms.map((p) => `${p.platform}=${p.supported ? '支持' : '未支持'}`).join(' · ') ?? '读取中'}
            。平台支持与设备就绪分别判断；能力读取失败时不显示可执行入口。
          </p>
        </div>
      </Panel>
    </>
  )
}
