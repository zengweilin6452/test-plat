const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')

// 与 task-wizard.test.cjs 同一套：用真实 TypeScript 编译执行源码，不引入测试依赖。
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const source = fs.readFileSync(filename, 'utf8')
    const { outputText } = ts.transpileModule(source, {
      fileName: filename,
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    })
    module._compile(outputText, filename)
  }
}

const { moduleName, isPerformanceType, MODULE_NAMES } = require('../src/constants.ts')
const { conclusionText } = require('../src/pages/ReportsPage.tsx')
const { metricCell, metricMissingReason, junitCounts } = require('../src/components/ReportDrawer.tsx')
const { buildTreeIndex, nodeLabel } = require('../src/components/DebugDrawer.tsx')

test('后端 test_type（ui/performance/joint）都有展示名，不会被当成未指定', () => {
  assert.equal(moduleName('ui'), MODULE_NAMES.ui)
  assert.equal(moduleName('performance'), MODULE_NAMES.perf)
  // 前端向导内部仍用 perf 写法，两种都要认
  assert.equal(moduleName('perf'), MODULE_NAMES.perf)
  assert.equal(moduleName('joint'), MODULE_NAMES.joint)
  assert.equal(moduleName(null), '未指定类型')
})

test('性能类判定覆盖后端 performance 与前端 perf', () => {
  assert.equal(isPerformanceType('performance'), true)
  assert.equal(isPerformanceType('perf'), true)
  assert.equal(isPerformanceType('ui'), false)
  assert.equal(isPerformanceType(null), false)
})

test('报告结论文案用后端原始枚举判定性能类', () => {
  assert.equal(conclusionText('performance', 'passed'), '性能门禁通过，指标与基线可比')
  assert.equal(conclusionText('performance', 'failed'), '性能阈值未满足，查看指标与基线')
  assert.equal(conclusionText('ui', 'passed'), '用例断言通过，执行过程可追溯')
  assert.equal(conclusionText('ui', null), '后端尚未给出结论')
  // not_tested 一律是「样本不足」，不能被性能分支改写成未通过
  assert.equal(conclusionText('performance', 'not_tested'), '样本不足，未产生门禁结论')
})

test('指标缺失显示原因而不是 0', () => {
  assert.equal(metricCell({ median: 20, unit: '%' }), '20 %')
  assert.equal(metricCell({ median: 12.5, unit: 'MB' }), '12.5 MB')
  assert.equal(metricCell({ median: null, unit: 'MB' }), '—')
  assert.equal(metricCell(undefined), '—')
  assert.equal(
    metricMissingReason({ notTested: true, notTestedReason: 'device_unsupported' }),
    'device_unsupported',
  )
  assert.equal(metricMissingReason({ missingReason: 'no_samples' }), 'no_samples')
  assert.equal(metricMissingReason({ median: 1 }), null)
})

test('junit 未产出时计数为 null（不写成 0 个失败）', () => {
  assert.deepEqual(junitCounts({ junit: { present: false } }), {
    tests: null,
    failed: null,
    skipped: null,
  })
  assert.deepEqual(junitCounts({}), { tests: null, failed: null, skipped: null })
  assert.deepEqual(junitCounts({ junit: { present: true, tests: 3, failures: 1, errors: 1, skipped: 0 } }), {
    tests: 3,
    failed: 2,
    skipped: 0,
  })
  // vendor 已经合并好的 failed 字段优先
  assert.deepEqual(junitCounts({ junit: { present: true, tests: 3, failed: 1 } }), {
    tests: 3,
    failed: 1,
    skipped: null,
  })
})

test('层级树按 children 下标还原父子关系', () => {
  const nodes = [
    { index: 0, class_name: 'Root', children: [1, 2] },
    { index: 1, text: '登录', children: [] },
    { index: 2, resource_id: 'com.example:id/ok', children: [3] },
    { index: 3, text: '', content_desc: '确认' },
  ]
  const tree = buildTreeIndex(nodes)
  assert.deepEqual(tree.roots.map((node) => node.index), [0])
  assert.equal(tree.byIndex.size, 4)
  assert.equal(nodeLabel(nodes[1]), '登录')
  assert.equal(nodeLabel(nodes[2]), 'com.example:id/ok')
  assert.equal(nodeLabel(nodes[3]), '确认')
  assert.equal(nodeLabel({ index: 9, class_name: 'Button' }), 'Button')
  assert.equal(nodeLabel({ index: 7 }), '#7')
})
