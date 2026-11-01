/**
 * 工单 09：页面四类状态（加载 / 失败 / 真实空态 / 部分缺失）的前端契约。
 *
 * 背景缺陷：Overview / Reports / Ui / Perf 把「请求还没回来」渲染成「还没有数据」，
 * 验收时会被误判为真实空态。这里用纯函数 + 静态渲染把「加载 ≠ 空」钉住。
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      fileName: filename,
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    })
    module._compile(outputText, filename)
  }
}

const SRC = path.join(__dirname, '..', 'src')

const { pagePhase } = require(path.join(SRC, 'lib', 'pageState.ts'))
const { Empty } = require(path.join(SRC, 'components', 'Empty.tsx'))
const { overviewFoot, passRateFoot, activeRunsCopy, recentRunsCopy } = require(
  path.join(SRC, 'pages', 'OverviewPage.tsx'),
)
const { reportsEmptyCopy } = require(path.join(SRC, 'pages', 'ReportsPage.tsx'))
const { uiRunsEmptyCopy } = require(path.join(SRC, 'pages', 'UiPage.tsx'))
const { perfAnalysisEmptyCopy, perfRunsEmptyCopy } = require(path.join(SRC, 'pages', 'PerfPage.tsx'))
const { identityCheckNote } = require(path.join(SRC, 'components', 'InputRegistration.tsx'))
const { copyExpression } = require(path.join(SRC, 'components', 'DebugDrawer.tsx'))

function render(element) {
  return renderToStaticMarkup(element)
}

test('pagePhase 先判加载、再判失败、最后才判空', () => {
  assert.equal(pagePhase({ isLoading: true, isError: false, count: 0 }), 'loading')
  assert.equal(pagePhase({ isLoading: true, isError: false, count: 3 }), 'loading')
  assert.equal(pagePhase({ isLoading: false, isError: true, count: 0 }), 'error')
  assert.equal(pagePhase({ isLoading: false, isError: false, count: 0 }), 'empty')
  assert.equal(pagePhase({ isLoading: false, isError: false, count: 2 }), 'ready')
})

test('概览统计卡的脚注区分加载中、失败与已加载，不把加载失败说成「接口未接入」', () => {
  const overview = {
    application_total: 4,
    run_total: 9,
    run_running: 2,
    passed: 5,
    failed: 1,
    not_tested: 3,
    pass_rate: 83.3,
    needs_attention: 4,
    resource_total: 1,
    resource_ready: 1,
  }
  assert.match(overviewFoot(overview, 'ready'), /执行中 2 次/)
  assert.match(overviewFoot(overview, 'ready'), /已登记应用 4 个/)
  assert.match(overviewFoot(null, 'loading'), /正在加载/)
  assert.match(overviewFoot(null, 'error'), /失败/)
  assert.match(overviewFoot(null, 'empty'), /尚未返回/)
  for (const phase of ['loading', 'error', 'empty']) {
    assert.ok(!/接口未接入/.test(overviewFoot(null, phase)), phase + ' 时不能声称接口未接入')
  }
  // 通过率分母为 0 时后端给 null：显示破折号由 StatCard 负责，脚注只解释口径
  assert.match(passRateFoot({ ...overview, pass_rate: null }, 'ready'), /分母为 0/)
  assert.match(passRateFoot(null, 'loading'), /正在加载/)
  assert.match(passRateFoot(null, 'error'), /失败/)
})

test('概览两个运行面板：加载中不写「还没有运行记录」', () => {
  assert.match(activeRunsCopy('loading').title, /正在加载/)
  assert.match(activeRunsCopy('loading').description, /GET \/api\/v1\/runs/)
  assert.match(activeRunsCopy('empty').title, /没有执行中的运行/)
  assert.match(activeRunsCopy('ready').title, /没有执行中的运行/)
  assert.match(recentRunsCopy('loading').title, /正在加载/)
  assert.ok(!/还没有运行记录/.test(recentRunsCopy('loading').title))
  assert.match(recentRunsCopy('empty').title, /还没有运行记录/)
})

test('报告清单：加载中 / 无数据 / 筛选为空 / 失败四种文案互不冒用', () => {
  assert.match(reportsEmptyCopy('loading', false).title, /正在加载/)
  assert.match(reportsEmptyCopy('loading', false).description, /state=completed/)
  assert.ok(!/还没有已完成/.test(reportsEmptyCopy('loading', false).title))
  assert.match(reportsEmptyCopy('empty', false).title, /还没有已完成的运行/)
  assert.match(reportsEmptyCopy('empty', true).title, /没有匹配/)
  assert.match(reportsEmptyCopy('empty', true).description, /清除搜索关键词|全部模块/)
  assert.match(reportsEmptyCopy('error', false).title, /暂不可用/)
})

test('UI 与性能页的运行清单：加载中与规划中目标端都不冒充真实空态', () => {
  assert.match(uiRunsEmptyCopy('loading', false).title, /正在加载/)
  assert.ok(!/还没有 UI/.test(uiRunsEmptyCopy('loading', false).title))
  assert.match(uiRunsEmptyCopy('empty', false).title, /还没有 UI 自动化运行/)
  assert.match(uiRunsEmptyCopy('empty', true).title, /尚未接入/)
  assert.match(uiRunsEmptyCopy('error', false).title, /暂不可用/)

  assert.match(perfAnalysisEmptyCopy('loading', false).title, /正在加载/)
  assert.match(perfAnalysisEmptyCopy('empty', false).title, /还没有已完成的性能运行/)
  assert.match(perfAnalysisEmptyCopy('empty', true).title, /尚未接入/)
  assert.match(perfRunsEmptyCopy('loading', false).title, /正在加载/)
  assert.ok(!/还没有性能运行/.test(perfRunsEmptyCopy('loading', false).title))
  assert.match(perfRunsEmptyCopy('empty', false).title, /还没有性能运行/)
  assert.match(perfRunsEmptyCopy('error', false).title, /暂不可用/)
})

test('加载态在 DOM 上与真实空态可区分（aria-busy / role=status / data-state）', () => {
  const loading = render(React.createElement(Empty, { loading: true, title: '正在加载运行记录' }))
  assert.match(loading, /aria-busy="true"/)
  assert.match(loading, /role="status"/)
  assert.match(loading, /data-state="loading"/)
  assert.match(loading, /正在加载运行记录/)

  const empty = render(React.createElement(Empty, { title: '还没有运行记录' }))
  assert.ok(!/aria-busy/.test(empty), '真实空态不能带 aria-busy')
  assert.match(empty, /data-state="empty"/)
})

test('身份未学习 / 未判定 / 冲突各有说人话的下一步', () => {
  assert.match(identityCheckNote(null), /尚未读取/)
  assert.match(identityCheckNote('unknown'), /未判定/)
  assert.match(identityCheckNote('conflict'), /身份冲突/)
  assert.match(identityCheckNote('match', 'pending'), /尚未学习完成/)
  assert.match(identityCheckNote('match', 'confirmed'), /已固定/)
})

test('配置就绪与设备就绪在任务详情里分开说明', () => {
  const source = fs.readFileSync(path.join(SRC, 'components', 'TaskDrawer.tsx'), 'utf8')
  assert.match(source, /配置就绪/)
  assert.match(source, /设备就绪/)
})

test('复制表达式只在剪贴板真正写入后提示成功，避免假成功 toast', async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  const messages = []
  const show = (message) => messages.push(message)
  const setNavigator = (value) =>
    Object.defineProperty(globalThis, 'navigator', { value, configurable: true })
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0))
  try {
    // 非安全上下文 / 老浏览器：没有 clipboard，不能提示成功
    setNavigator({})
    copyExpression('xpath=//a', show)
    assert.match(messages.at(-1), /复制失败/)
    assert.ok(!messages.includes('表达式已复制'), '没有剪贴板时不能提示复制成功')

    messages.length = 0
    setNavigator({ clipboard: { writeText: () => Promise.resolve() } })
    copyExpression('xpath=//a', show)
    await flush()
    assert.deepEqual(messages, ['表达式已复制'])

    messages.length = 0
    setNavigator({ clipboard: { writeText: () => Promise.reject(new Error('denied')) } })
    copyExpression('xpath=//a', show)
    await flush()
    assert.match(messages.at(-1), /复制失败/)
    assert.ok(!messages.includes('表达式已复制'), '剪贴板拒绝时不能提示复制成功')
  } finally {
    if (original) Object.defineProperty(globalThis, 'navigator', original)
    else delete globalThis.navigator
  }
})

test('九个页面都按 isLoading 分支，不允许再出现「加载即空态」的回归', () => {
  const pages = [
    'OverviewPage',
    'AppsPage',
    'UiPage',
    'PerfPage',
    'DevicesPage',
    'TasksPage',
    'ReportsPage',
    'IntegrationPage',
    'DatabasePage',
  ]
  for (const page of pages) {
    const source = fs.readFileSync(path.join(SRC, 'pages', page + '.tsx'), 'utf8')
    assert.match(source, /isLoading|pagePhase/, page + ' 缺少加载态分支')
  }
  // 已核实的四个缺陷页必须真的用 pagePhase 判阶段，而不是自己拼条件
  for (const page of ['OverviewPage', 'ReportsPage', 'UiPage', 'PerfPage']) {
    const source = fs.readFileSync(path.join(SRC, 'pages', page + '.tsx'), 'utf8')
    assert.match(source, /pagePhase\(/, page + ' 必须用 pagePhase 统一判定加载/失败/空态')
  }
})
