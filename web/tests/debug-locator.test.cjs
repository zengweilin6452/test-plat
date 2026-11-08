const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')

// 与 debug-control.test.cjs 同一套：真实 TypeScript 编译执行源码。
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

const { locatorValueForNode, preferredLocator } = require('../src/components/DebugDrawer.tsx')

const node = {
  index: 7,
  class_name: 'android.widget.TextView',
  resource_id: null,
  text: 'william101@byd.com Internal use only',
  content_desc: null,
  bounds: [0, 1323, 378, 1543],
}

test('切换定位方式时按节点生成该形态的定位值（u2 selector 必须是白名单 JSON）', () => {
  // text 节点切到 u2 selector：生成 {"text": ...}，而不是沿用原文（vendor 判 InvalidTarget）
  assert.deepEqual(JSON.parse(locatorValueForNode('u2_selector', node)), { text: node.text })
  // resource_id 节点切 u2 selector：resourceId 字段优先
  const withId = { ...node, resource_id: 'com.example:id/title' }
  assert.deepEqual(JSON.parse(locatorValueForNode('u2_selector', withId)), {
    resourceId: 'com.example:id/title',
  })
  // 无 id/text/desc：回落 className（短类名）
  const bare = { ...node, text: null }
  assert.deepEqual(JSON.parse(locatorValueForNode('u2_selector', bare)), {
    className: 'TextView',
  })
})

test('xpath 按短类名 + text 生成表达式；无 text 只给类名', () => {
  assert.equal(locatorValueForNode('xpath', node), "//TextView[@text='william101@byd.com Internal use only']")
  const bare = { ...node, text: null }
  assert.equal(locatorValueForNode('xpath', bare), '//TextView')
})

test('各形态缺值时如实为空，不猜值；text/accessibility_id 直取节点属性', () => {
  const bare = { ...node, text: null, content_desc: null }
  assert.equal(locatorValueForNode('resource_id', node), '')
  assert.equal(locatorValueForNode('accessibility_id', node), '')
  assert.equal(locatorValueForNode('image', node), '')
  assert.equal(locatorValueForNode('accessibility_id', { ...node, content_desc: '首页' }), '首页')
  assert.equal(locatorValueForNode('text', node), node.text)
  assert.equal(locatorValueForNode('text', null), '')
})

test('节点拾取优先级不变：resource-id 优先于 text', () => {
  assert.deepEqual(preferredLocator({ ...node, resource_id: 'a:b' }), {
    by: 'resource_id',
    value: 'a:b',
  })
  assert.deepEqual(preferredLocator(node), { by: 'text', value: node.text })
  assert.equal(preferredLocator({ ...node, text: null }), null)
})
