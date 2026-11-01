const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      fileName: filename,
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    })
    module._compile(outputText, filename)
  }
}
const { filterSchemaTables } = require('../src/pages/DatabasePage.tsx')
const { conclusionText } = require('../src/pages/ReportsPage.tsx')
test('dictionary search matches Chinese descriptions and intersects the selected group', () => {
  const tables = [
    { name: 'builds', group: '应用', note: '构建身份', fields: [{ field: 'version', note: '安装版本' }] },
    { name: 'runs', group: '运行', fields: [{ field: 'revision_id', note: '任务修订' }] },
  ]
  assert.deepEqual(filterSchemaTables(tables, '安装版本', '应用').map((x) => x.name), ['builds'])
  assert.deepEqual(filterSchemaTables(tables, '构建身份', '').map((x) => x.name), ['builds'])
  assert.deepEqual(filterSchemaTables(tables, 'REVISION', '运行').map((x) => x.name), ['runs'])
  assert.deepEqual(filterSchemaTables(tables, '安装版本', '运行'), [])
  assert.deepEqual(filterSchemaTables(tables, '不存在', ''), [])
})
test('not_tested report summary does not invent a sample shortage cause', () => {
  for (const type of ['ui', 'performance', 'joint']) {
    assert.equal(conclusionText(type, 'not_tested'), '未产生门禁结论，查看报告中的具体原因')
  }
  assert.equal(conclusionText('joint', 'failed'), '联动测试未通过，查看各组件的具体原因')
})

const { baselineCreatePayload } = require('../src/pages/PerfPage.tsx')
test('baseline creation carries the selected completed performance source and stable request key', () => {
  const run = { id: 'run-123', state: 'completed', test_type: 'performance' }
  assert.deepEqual(baselineCreatePayload(run, '  release baseline  ', 'retry-key'), {
    request_key: 'retry-key', run_id: 'run-123', name: 'release baseline',
  })
  assert.deepEqual(baselineCreatePayload({ ...run, test_type: 'joint' }, 'joint', 'retry-key').run_id, 'run-123')
  assert.throws(() => baselineCreatePayload({ ...run, state: 'running' }, 'baseline', 'key'), /已完成/)
  assert.throws(() => baselineCreatePayload({ ...run, test_type: 'ui' }, 'baseline', 'key'), /性能或联动/)
  assert.throws(() => baselineCreatePayload(run, '  ', 'key'), /名称/)
})
