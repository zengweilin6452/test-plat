/**
 * UI 页「用例套件 / 用例」两个页签的纯逻辑（P2 suites 读接口）。
 *
 * 与 report-and-debug.test.cjs 同一套：用真实 TypeScript 编译执行源码，不引入测试依赖。
 * 这里只测纯函数——表格渲染、请求编排在浏览器里验证，不在 node 里假装跑一遍。
 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')

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

const { filterSuites, pickVersion } = require('../src/pages/UiPage.tsx')

const suite = (id, platform) => ({
  id,
  project_id: 'p',
  name: 'suite-' + id,
  test_type: 'ui',
  application: { id: 'a', name: 'app', platform },
  version_count: 0,
  latest_version: null,
})

test('套件按目标端过滤；all 时原样返回', () => {
  const items = [suite('1', 'android'), suite('2', 'ios'), suite('3', 'android')]
  assert.deepEqual(filterSuites(items, 'all').map((s) => s.id), ['1', '2', '3'])
  assert.deepEqual(filterSuites(items, 'android').map((s) => s.id), ['1', '3'])
  // 没有对应目标端的套件时返回空数组，由页面显示空态（不伪造行）
  assert.deepEqual(filterSuites(items, 'web'), [])
})

test('选中的版本号不存在时回落到最新版本（items 已是倒序）', () => {
  const versions = [
    { id: 'v3', suite_id: 's', version: 3, case_count: 5 },
    { id: 'v2', suite_id: 's', version: 2, case_count: 4 },
  ]
  assert.equal(pickVersion(versions, null).version, 3)
  assert.equal(pickVersion(versions, 2).version, 2)
  // 换了套件后残留的旧版本号（9）不能被当成"没有版本"
  assert.equal(pickVersion(versions, 9).version, 3)
  // 没有版本时返回 null，页面显示"还没有 discover 过"
  assert.equal(pickVersion([], 1), null)
})
