/**
 * 正式化改造前端静态行为契约（工单 01/02/03/05/06/07/08/09/10/11）。
 * 不依赖浏览器：验证共享来源、上下文解析规则、范围参数与文案收口的真实代码路径。
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const SRC = path.join(__dirname, '..', 'src')
const read = (relative) => fs.readFileSync(path.join(SRC, relative), 'utf8')

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, out)
    else if (/\.(tsx?|ts)$/.test(entry.name)) out.push(full)
  }
  return out
}

test('运行时源码不再写死虚构身份、阶段标签与研发阶段文案', () => {
  const offenders = []
  for (const file of walk(SRC)) {
    const source = fs.readFileSync(file, 'utf8')
    for (const bad of ['星河工作空间', '测试工程组', 'P1 骨架阶段', 'P6 · 调试与交付就绪', '已有组件基础', 'P2 将提供', '24 张表的实体关系']) {
      if (source.includes(bad)) offenders.push(`${path.basename(file)}: ${bad}`)
    }
  }
  assert.deepEqual(offenders, [])
})

test('品牌、本机模式与工作空间名称来自统一来源', () => {
  const brand = read(path.join('store', 'platform.tsx'))
  assert.match(brand, /name: 'TestDock'/)
  assert.match(brand, /mode: '本机模式'/)
  assert.match(brand, /demoBadge: '演示环境'/)
  assert.match(brand, /无法读取工作空间设置/)
  const sidebar = read(path.join('components', 'layout', 'Sidebar.tsx'))
  assert.match(sidebar, /BRAND\.name/)
  assert.match(sidebar, /workspace\.name/)
  assert.match(sidebar, /usePlatform/)
  const topbar = read(path.join('components', 'layout', 'Topbar.tsx'))
  assert.match(topbar, /breadcrumb-workspace/)
  assert.match(topbar, /usePlatform/)
})

test('设置页区分加载、读取失败、保存失败与成功，失败保留输入', () => {
  const source = read(path.join('pages', 'SettingsPage.tsx'))
  assert.match(source, /platform\.loading/)
  assert.match(source, /platform\.error/)
  assert.match(source, /保存失败保留输入/)
  assert.match(source, /输入已保留，服务端设置没有变化/)
  assert.match(source, /setSaved\(true\)/)
  assert.match(source, /renameWorkspace|saveWorkspace/)
  assert.match(source, /重试/)
})

test('统一上下文：URL 优先、显式全部、仅应用解析项目、冲突拒绝，不只靠缓存', () => {
  const source = read(path.join('store', 'effectiveContext.tsx'))
  assert.match(source, /PROJECT_QUERY_KEY = 'project'/)
  assert.match(source, /APP_QUERY_KEY = 'app'/)
  assert.match(source, /ALL_PROJECTS = 'all'/)
  assert.match(source, /explicitAll/)
  assert.match(source, /CONTEXT_MISMATCH|归属冲突/)
  assert.match(source, /fetchApplication/)
  assert.match(source, /writeStorage\(PROJECT_STORAGE_KEY, explicitAll \? null : resolvedProjectId\)/)
  assert.match(source, /nextParams\.delete\(APP_QUERY_KEY\)/)
  assert.match(source, /testdock\.selection\./)
})

test('全站范围参数与查询缓存键跟随当前项目', () => {
  assert.match(read(path.join('api', 'endpoints.ts')), /project_id: projectId \|\| undefined/)
  assert.match(read(path.join('pages', 'OverviewPage.tsx')), /fetchOverview\(.*ctx\.projectId/)
  assert.match(read(path.join('pages', 'OverviewPage.tsx')), /\['overview', targetScope, ctx\.projectId\]/)
  assert.match(read(path.join('pages', 'TasksPage.tsx')), /ctx\.projectId/)
  assert.match(read(path.join('pages', 'ReportsPage.tsx')), /project_id: ctx\.projectId/)
  assert.match(read(path.join('pages', 'DevicesPage.tsx')), /useEffectiveContext/)
  assert.match(read(path.join('components', 'TaskWizard.tsx')), /project_id: ctx\.projectId/)
  assert.match(read(path.join('store', 'effectiveContext.tsx')), /projectId \?\? 'all'.*appId \?\? 'none'/)
})

test('能力摘要是服务端来源，失败不显示可执行', () => {
  const platform = read(path.join('store', 'platform.tsx'))
  assert.match(platform, /fetchCapabilities/)
  assert.match(platform, /isPlatformSupported/)
  assert.match(platform, /\?\? false/)
  const apps = read(path.join('pages', 'AppsPage.tsx'))
  assert.match(apps, /isPlatformSupported\(capabilities, 'android'\)/)
  assert.match(apps, /能力读取中/)
  assert.match(apps, /尚未支持执行/)
  assert.match(read(path.join('components', 'PageBits.tsx')), /能力信息读取失败/)
})

test('表单示例明确标注、不会自动提交；构建向导保留空真实值', () => {
  const wizard = read(path.join('components', 'TaskWizard.tsx'))
  assert.match(wizard, /例如 3\.8\.0-rc\.2（示例不会自动提交）/)
  assert.doesNotMatch(wizard, /placeholder="3\.8\.0-rc\.2"/)
  assert.match(wizard, /任务接口返回 404：请确认后端已升级/)
  const constants = read('constants.ts')
  assert.match(constants, /BUILD_LABEL_EXAMPLE/)
  assert.doesNotMatch(constants, /DEFAULT_BUILD_LABEL/)
  assert.match(read(path.join('pages', 'AppsPage.tsx')), /例如 com\.example\.app（示例不会自动提交）/)
})

test('首用引导与旧数据预览按真实数据计算，默认不自动写库', () => {
  const onboarding = read(path.join('pages', 'OnboardingPage.tsx'))
  assert.match(onboarding, /fetchOnboardingStatus/)
  assert.match(onboarding, /按真实数据计算待办/)
  assert.match(onboarding, /跳过引导/)
  const legacy = read(path.join('pages', 'LegacyReviewPage.tsx'))
  assert.match(legacy, /默认只预览/)
  assert.match(legacy, /不按名称批量删除/)
  assert.match(legacy, /需人工判断/)
  assert.match(legacy, /applyLegacyActions/)
})

test('归档预览、活动阻塞、改名/恢复与只读历史在页面可见', () => {
  const apps = read(path.join('pages', 'AppsPage.tsx'))
  for (const token of ['fetchArchivePreview', 'archiveEntity', 'restoreEntity', 'renameProject', 'renameApplication', 'active_runs.length', 'open_debug_sessions.length', '查看历史']) {
    assert.ok(apps.includes(token), token)
  }
})

test('帮助与旧深链接兼容，部署配置统一端口', () => {
  const routes = read('routes.tsx')
  for (const route of ['/onboarding', '/help', '/settings', '/about', '/legacy-review', '/integration', '/database']) {
    assert.ok(routes.includes(`'${route}'`), route)
  }
  const vite = fs.readFileSync(path.join(__dirname, '..', 'vite.config.ts'), 'utf8')
  assert.match(vite, /TESTDOCK_API_PORT/)
  assert.match(vite, /TESTDOCK_WEB_PORT/)
  assert.match(vite, /strictPort: true/)
  const up = fs.readFileSync(path.join(__dirname, '..', '..', 'scripts', 'dev_up.ps1'), 'utf8')
  assert.match(up, /TESTDOCK_API_PORT/)
  assert.match(up, /TESTDOCK_WEB_PORT/)
  assert.match(up, /Get-PlatformHealth/)
  assert.match(up, /Save-Pid/)
  const down = fs.readFileSync(path.join(__dirname, '..', '..', 'scripts', 'dev_down.ps1'), 'utf8')
  assert.match(down, /\.pid/)
  assert.doesNotMatch(down, /Name LIKE/)
})

test('帮助示例与保留常量有明确理由', () => {
  const constants = read('constants.ts')
  assert.match(constants, /服务端 \/capabilities 是能力事实来源/)
  assert.match(constants, /帮助示例（仅用于 placeholder，绝不自动提交）/)
  assert.match(read(path.join('pages', 'HelpPage.tsx')), /旧路径仍然可用/)
})
