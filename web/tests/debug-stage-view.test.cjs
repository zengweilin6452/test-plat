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

const { stageViewBadge, nodeOverlayRegion } = require('../src/components/debug/debugModel.ts')

// 审查 F1：断线/终态后的旧截图一律不得再标「实时画面」。
test('画面徽标状态机：断线后的旧图标记过期，不再冒充实时', () => {
  // 正常实时
  assert.deepEqual(
    stageViewBadge({ frozen: false, sessionClosed: false, wsOpen: true, hasFrame: true, liveFrameSeen: true }),
    { tone: 'green', label: '实时画面', stale: false, staleNote: null },
  )
  // 连接断开（会话还在）：最后一帧必须标记过期
  const dropped = stageViewBadge({ frozen: false, sessionClosed: false, wsOpen: false, hasFrame: true, liveFrameSeen: true })
  assert.equal(dropped.stale, true)
  assert.equal(dropped.tone, 'red')
  assert.ok(dropped.label.includes('已断开'))
  assert.ok(!dropped.label.includes('实时画面'))
  // 会话终态 + 未冻结：同样过期
  const closed = stageViewBadge({ frozen: false, sessionClosed: true, wsOpen: false, hasFrame: true, liveFrameSeen: true })
  assert.equal(closed.stale, true)
  assert.ok(closed.label.includes('最后一帧'))
  // 会话终态 + 冻结：保留检查快照的语义，且恢复实时被禁用（见源码断言）
  const closedFrozen = stageViewBadge({ frozen: true, sessionClosed: true, wsOpen: false, hasFrame: true, liveFrameSeen: true })
  assert.equal(closedFrozen.stale, true)
  assert.ok(closedFrozen.label.includes('保留检查快照'))
  // 冻结（会话正常）：检查快照，不是故障
  const frozen = stageViewBadge({ frozen: true, sessionClosed: false, wsOpen: true, hasFrame: true, liveFrameSeen: true })
  assert.equal(frozen.tone, 'amber')
  assert.equal(frozen.stale, false)
  assert.equal(frozen.label, '检查快照')
  // 已连接但还没画出新帧（JPEG 回退恢复/重连窗口）：不标实时
  const waiting = stageViewBadge({ frozen: false, sessionClosed: false, wsOpen: true, hasFrame: true, liveFrameSeen: false })
  assert.equal(waiting.label, '等待新帧…')
  assert.equal(waiting.stale, false)
  // 无帧：未连接
  assert.equal(stageViewBadge({ frozen: false, sessionClosed: false, wsOpen: true, hasFrame: false, liveFrameSeen: false }).label, '未连接')
})

test('终态禁用恢复实时 + 过期画面有覆盖提示（源码契约）', () => {
  const source = fs.readFileSync('src/components/DebugDrawer.tsx', 'utf8')
  const restore = source.indexOf('恢复实时\n')
  assert.ok(restore > 0, '恢复按钮存在')
  const buttonStart = source.lastIndexOf('<Button', restore)
  const buttonBody = source.slice(buttonStart, restore)
  assert.ok(
    /disabled=\{[^}]*sessionClosed/.test(buttonBody),
    '终态会话必须禁用「恢复实时」',
  )
  assert.ok(source.includes('debug-stage-stale'), '过期画面需要覆盖提示层')
  assert.ok(source.includes('stageViewBadge('), '徽标必须来自 stageViewBadge 状态机')
})

// 审查 F5：选中节点也要在画面上有边框，且与定位命中绿框语义区分。
test('选中节点边框：bounds 换算成区域，缺 bounds/越界如实为 null', () => {
  assert.deepEqual(
    nodeOverlayRegion({ index: 3, bounds: [76, 1803, 278, 1988] }),
    { x: 76, y: 1803, w: 202, h: 185 },
  )
  assert.equal(nodeOverlayRegion({ index: 1 }), null, '无 bounds 不画框')
  assert.equal(nodeOverlayRegion({ index: 1, bounds: [10, 10, 10, 40] }), null, '零宽不画框')
  assert.equal(nodeOverlayRegion({ index: 1, bounds: [10, 10, 8, 40] }), null, '反向 bounds 不画框')
  assert.equal(nodeOverlayRegion({ index: 1, bounds: ['a', 2, 3, 4] }), null, '非数值不画框')
  assert.equal(nodeOverlayRegion(null), null)
})
