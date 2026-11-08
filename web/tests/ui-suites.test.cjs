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

const { filterSuites, pickVersion, versionCopyNotice } = require('../src/pages/UiPage.tsx')
const { suiteSourceEmptyHint } = require('../src/components/InputRegistration.tsx')

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

test('缺少固定代码副本的版本要直接要求重新发现', () => {
  // 有副本：不需要提示（V1 必须带副本，正常路径不打扰用户）
  assert.equal(versionCopyNotice({ id: 'v1', suite_id: 's', version: 1, case_count: 3, has_code_copy: true }), null)
  // 旧版本没有副本：执行会被阻断，明确要求重新发现，而不是只标"不可验证"
  const legacy = versionCopyNotice({ id: 'v0', suite_id: 's', version: 0, case_count: 3, has_code_copy: false })
  assert.ok(legacy && legacy.includes('重新发现'), String(legacy))
  // 字段缺失（老接口）不臆断成"已保留"
  assert.equal(versionCopyNotice({ id: 'v2', suite_id: 's', version: 2, case_count: 1 }), null)
})

test('来源为空时提示需要宿主配置，且不提供路径输入', () => {
  const hint = suiteSourceEmptyHint({ items: [], total: 0, hint: '未配置可信套件来源：需要宿主预配置 TESTDOCK_SUITE_SOURCES 后才能登记或发现套件。' })
  assert.ok(hint.includes('宿主配置') || hint.includes('宿主预配置'), hint)
  // 后端没给 hint 时也要有一句兜底说明，不能静默留一个空下拉
  const fallback = suiteSourceEmptyHint({ items: [], total: 0 })
  assert.ok(fallback && fallback.includes('宿主'), String(fallback))
  // 有来源时不提示
  assert.equal(suiteSourceEmptyHint({ items: [{ id: 'a', name: 'A', test_types: ['ui'] }], total: 1 }), null)
})

test('joint 版本发布体必须带 ui_timeout_s（manifest 契约必填）', () => {
  const { jointVersionPayload } = require('../src/components/InputRegistration.tsx')
  const body = jointVersionPayload({ duration_s: 30, items: ['CPU'] }, 'calc-smoke', '600')
  assert.equal(body.source_id, 'calc-smoke')
  assert.equal(body.ui_timeout_s, 600)
  assert.equal(body.scenario.duration_s, 30)
  // 表单值是字符串：Number 归一，非法值会在 valid 门禁里被拦（10–3600）
  assert.equal(jointVersionPayload({ duration_s: 30, items: ['CPU'] }, 's', '45').ui_timeout_s, 45)
})
