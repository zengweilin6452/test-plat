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

const {
  buildTreeIndex,
  initialOpenTreeSet,
  visibleTreeRows,
  treeNavAction,
} = require('../src/components/debug/debugModel.ts')

// 层级形状（vendor children 存下标）：
//   0 FrameLayout（无标识纯容器，整行跳过）
//     1 设置
//       2 WLAN（无子节点）
//     3 容器 FrameLayout（无标识）
//       4 蓝牙
const nodes = [
  { index: 0, class_name: 'android.widget.FrameLayout', children: [1, 3] },
  { index: 1, text: '设置', children: [2] },
  { index: 2, text: 'WLAN', children: [] },
  { index: 3, class_name: 'android.widget.FrameLayout', children: [4] },
  { index: 4, text: '蓝牙', children: [] },
]
const tree = buildTreeIndex(nodes)

test('buildTreeIndex 输出 child→parent 反查表（键盘回父级需要）', () => {
  assert.equal(tree.parentOf.get(2), 1)
  assert.equal(tree.parentOf.get(4), 3)
  assert.equal(tree.parentOf.get(1), 0)
  assert.equal(tree.parentOf.get(0), undefined)
  assert.equal(tree.roots.length, 1)
})

test('initialOpenTreeSet 默认展开前两层（与原 depth<2 行为一致）', () => {
  const open = initialOpenTreeSet(tree.roots, tree.byIndex)
  assert.ok(open.has(0) && open.has(1) && open.has(3), '第 0/1 层展开')
  assert.ok(!open.has(2), '叶子无需展开标记')
})

test('visibleTreeRows 跳过无标识容器且上移子树，收起子树不产生行', () => {
  const open = initialOpenTreeSet(tree.roots, tree.byIndex)
  assert.deepEqual(
    visibleTreeRows(tree.roots, tree.byIndex, open).map((row) => row.index),
    [1, 2, 4],
    '无标识 0/3 整行跳过，子树原位上移',
  )
  const collapsed = new Set(open)
  collapsed.delete(1)
  assert.deepEqual(
    visibleTreeRows(tree.roots, tree.byIndex, collapsed).map((row) => row.index),
    [1, 4],
    '收起 1 后其子节点 2 不渲染',
  )
})

test('treeNavAction：上下移动 + 边界不动', () => {
  const rows = visibleTreeRows(tree.roots, tree.byIndex, initialOpenTreeSet(tree.roots, tree.byIndex))
  assert.deepEqual(treeNavAction(rows, nodes[1], 'ArrowDown', new Set(), tree.byIndex, tree.parentOf), { focus: 2 })
  assert.deepEqual(treeNavAction(rows, nodes[2], 'ArrowDown', new Set(), tree.byIndex, tree.parentOf), { focus: 4 })
  assert.deepEqual(treeNavAction(rows, nodes[4], 'ArrowDown', new Set(), tree.byIndex, tree.parentOf), { focus: null })
  assert.deepEqual(treeNavAction(rows, nodes[2], 'ArrowUp', new Set(), tree.byIndex, tree.parentOf), { focus: 1 })
  assert.deepEqual(treeNavAction(rows, nodes[1], 'ArrowUp', new Set(), tree.byIndex, tree.parentOf), { focus: null })
})

test('treeNavAction：右键展开/进入子节点，左键收起/回最近可见祖先', () => {
  const closed = new Set()
  const rowsClosed = visibleTreeRows(tree.roots, tree.byIndex, closed)
  // 收起状态下右键 = 展开（焦点不动）
  assert.deepEqual(treeNavAction(rowsClosed, nodes[1], 'ArrowRight', closed, tree.byIndex, tree.parentOf), { focus: null, toggle: 1 })
  // 展开后右键 = 进入第一个子节点
  const open = initialOpenTreeSet(tree.roots, tree.byIndex)
  const rowsOpen = visibleTreeRows(tree.roots, tree.byIndex, open)
  assert.deepEqual(treeNavAction(rowsOpen, nodes[1], 'ArrowRight', open, tree.byIndex, tree.parentOf), { focus: 2 })
  // 展开后左键 = 收起
  assert.deepEqual(treeNavAction(rowsOpen, nodes[1], 'ArrowLeft', open, tree.byIndex, tree.parentOf), { focus: null, toggle: 1 })
  // 收起/叶子状态左键 = 回到最近一个「可见」祖先：2 的父是 1（可见）
  assert.deepEqual(treeNavAction(rowsOpen, nodes[2], 'ArrowLeft', open, tree.byIndex, tree.parentOf), { focus: 1 })
  // 4 的祖先 3/0 都是无标识容器（不渲染行）：没有可见祖先可回，焦点不动
  assert.deepEqual(treeNavAction(rowsOpen, nodes[4], 'ArrowLeft', open, tree.byIndex, tree.parentOf), { focus: null })
})

test('TreeBranch 输出 aria-expanded/aria-level 与 roving tabindex（源码契约，审查 F5）', () => {
  const source = fs.readFileSync('src/components/debug/TreeBranch.tsx', 'utf8')
  assert.ok(source.includes('aria-expanded={expandable ? open : undefined}'), 'treeitem 缺少展开状态输出')
  assert.ok(source.includes('aria-level='), 'treeitem 缺少层级信息')
  assert.ok(source.includes('tabIndex={focusIndex === node.index ? 0 : -1}'), '缺少 roving tabindex')
  assert.ok(source.includes('data-tree-index={node.index}'), '键盘导航需要定位行的 data 属性')
})

test('DebugDrawer 接线树键盘导航（方向键/Enter）', () => {
  const source = fs.readFileSync('src/components/DebugDrawer.tsx', 'utf8')
  assert.ok(source.includes('handleTreeKeyDown'), '树行键盘事件未接线')
  assert.ok(source.includes('treeNavAction('), '方向键导航必须走 treeNavAction 纯函数')
  assert.ok(source.includes('visibleTreeRows('), '可见行列表必须来自 visibleTreeRows')
  assert.ok(/ArrowDown/.test(source), '支持上下方向键')
})
