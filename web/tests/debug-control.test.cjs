const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')

// 与 debug-crop-state.test.cjs 同一套：真实 TypeScript 编译执行源码。
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
  normalizeStagePoint,
  controlAvailability,
  gestureMessage,
  shouldSendGestureMove,
  cropSelectionEnabled,
} = require('../src/components/DebugDrawer.tsx')

test('操控坐标归一化到 [0,1]，框外夹紧', () => {
  const rect = { left: 100, top: 50, width: 200, height: 400 }
  assert.deepEqual(normalizeStagePoint(rect, 100, 50), { nx: 0, ny: 0 })
  assert.deepEqual(normalizeStagePoint(rect, 300, 450), { nx: 1, ny: 1 })
  const middle = normalizeStagePoint(rect, 200, 250)
  assert.ok(Math.abs(middle.nx - 0.5) < 1e-9)
  assert.ok(Math.abs(middle.ny - 0.5) < 1e-9)
  assert.deepEqual(normalizeStagePoint(rect, 0, 9999), { nx: 0, ny: 1 })
})

test('直接操控可用性：每种禁用都有明确原因', () => {
  const base = {
    sessionActive: true,
    wsOpen: true,
    frozen: false,
    inspectMode: 'native',
    hasFrame: true,
    busy: false,
  }
  assert.deepEqual(controlAvailability(base), { enabled: true, reason: null })

  const cases = [
    [{ sessionActive: false }, '调试会话尚未激活'],
    [{ inspectMode: 'image' }, '图像模板框选模式下不可操控'],
    [{ frozen: true }, '冻结快照时不可操控，先恢复预览'],
    [{ wsOpen: false }, '实时画面未连接'],
    [{ hasFrame: false }, '画面尚未就绪'],
    [{ busy: true }, '会话切换中'],
  ]
  for (const [patch, reason] of cases) {
    assert.deepEqual(controlAvailability({ ...base, ...patch }), {
      enabled: false,
      reason,
    })
  }
})

test('手势帧形状与 vendor 契约一致', () => {
  assert.deepEqual(gestureMessage('start', 0.25, 0.75, 1), {
    type: 'start',
    nx: 0.25,
    ny: 0.75,
    seq: 1,
  })
  assert.deepEqual(gestureMessage('move', 0.5, 0.4, 2), {
    type: 'move',
    nx: 0.5,
    ny: 0.4,
    seq: 2,
  })
  assert.equal(gestureMessage('end', 0.5, 0.4, 3).type, 'end')
})

test('move 按 20Hz 节流', () => {
  assert.equal(shouldSendGestureMove(null, 1000), true)
  assert.equal(shouldSendGestureMove(1000, 1010), false)
  assert.equal(shouldSendGestureMove(1000, 1050), true)
  assert.equal(shouldSendGestureMove(1000, 1080), true)
})

test('pointerStart 必须在 openGesture 之后设置（closeGestureSocket 会清空它）', () => {
  const source = fs.readFileSync('src/components/DebugDrawer.tsx', 'utf8')
  const start = source.indexOf('const handleControlPointerDown')
  const end = source.indexOf('const handleControlPointerMove')
  assert.ok(start >= 0 && end > start)
  const body = source.slice(start, end)
  const openAt = body.indexOf('openGesture()')
  const pointerAt = body.indexOf('pointerStartRef.current = {')
  assert.ok(openAt >= 0 && pointerAt >= 0)
  assert.ok(
    openAt < pointerAt,
    'openGesture() 会调用 closeGestureSocket() 并把 pointerStartRef 清空；先设指针会导致 finishControlPointer 直接 return，end 永远不发',
  )
})


test('框选门控：只有图像模板模式允许在设备画面上拖拽', () => {
  assert.equal(cropSelectionEnabled('image'), true)
  assert.equal(cropSelectionEnabled('native'), false)
})

test('原生节点模式的三个拖拽 handler 都必须检查 cropSelectionEnabled', () => {
  const source = fs.readFileSync('src/components/DebugDrawer.tsx', 'utf8')
  for (const name of ['handleStageDown', 'handleStageMove', 'handleStageUp']) {
    const start = source.indexOf(`const ${name}`)
    const next = source.indexOf('\n  const ', start + 5)
    const body = source.slice(start, next === -1 ? undefined : next)
    assert.ok(body.includes('cropSelectionEnabled(inspectMode)'), `${name} 缺少框选门控`)
  }
})

test('直接操控键位于设备画面正下方（在快照信息之前）', () => {
  const source = fs.readFileSync('src/components/DebugDrawer.tsx', 'utf8')
  const bar = source.indexOf('className="debug-control-bar"')
  const meta = source.indexOf("'设备画面未冻结'")
  assert.ok(bar >= 0 && meta > bar, '返回/Home 必须在设备画面之后、快照信息之前')
})
