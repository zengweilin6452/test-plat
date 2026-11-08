/** 关于页：真实版本、提交标识不可用说明、帮助入口。 */
import { Link } from 'react-router-dom'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Empty } from '../components/Empty'
import { Notice } from '../components/Notice'
import { BRAND, usePlatform } from '../store/platform'

export function AboutPage() {
  const { capabilities, loading, error } = usePlatform()
  return (
    <>
      <PageHeading title="关于" description={`${BRAND.name} 产品信息与本机使用边界`} />
      <Panel>
        <PanelHead title="版本与构建" hint={BRAND.mode} />
        <div className="panel-pad">
          {loading ? <Empty loading title="正在读取产品版本" description="正在请求平台能力信息…" /> : null}
          {error ? <Notice tone="red" title="产品信息读取失败">{error}</Notice> : null}
          {capabilities ? (
            <>
              <p>产品版本：{capabilities.version}</p>
              <p>
                提交标识：
                {capabilities.commit ?? '当前构建未提供，标记为不可用（不编造交付就绪状态）'}
              </p>
              <p>演示环境：{capabilities.demo_mode ? '是（数据与产物目录独立）' : '否（正式环境）'}</p>
              <p>
                假执行：{capabilities.fake_runner_enabled ? '已启用（仅允许测试或显式演示环境）' : '未启用'}
              </p>
            </>
          ) : null}
        </div>
      </Panel>
      <Panel>
        <PanelHead title="使用边界" hint="无登录 / 单工作空间" />
        <div className="panel-pad">
          <p>本机模式不代表账号、租户或权限隔离；控制面继续保持回环绑定与令牌保护。</p>
          <p><Link className="link-btn" to="/help">查看帮助与开发者资料</Link></p>
          <p><Link className="link-btn" to="/settings">返回设置</Link></p>
        </div>
      </Panel>
    </>
  )
}
