const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')

// 与 report-and-debug.test.cjs 同一套：真实 TypeScript 编译执行源码，不引入测试依赖。
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
  cropVerificationKey,
  resolveCropVerification,
  preferredLocator,
} = require('../src/components/DebugDrawer.tsx')

const REGION = { x: 581, y: 1048, w: 173, h: 173 }
const VALIDATED = {
  count: 1,
  scores: [1],
  matches: [{ x: 581, y: 1048, width: 173, height: 173 }],
  snapshot_id: 'fresh',
  source_snapshot_id: 'frozen',
  region: [581, 1048, 173, 173],
  verification: 'proof-token',
}

test('框选验证凭证绑定会话/快照/框选/阈值，任一改变即失效', () => {
  const base = cropVerificationKey('sess-1', 'frozen', REGION, '0.80')
  assert.equal(base, cropVerificationKey('sess-1', 'frozen', REGION, '0.80'))
  assert.notEqual(base, cropVerificationKey('sess-2', 'frozen', REGION, '0.80'))
  assert.notEqual(base, cropVerificationKey('sess-1', 'other', REGION, '0.80'))
  assert.notEqual(base, cropVerificationKey('sess-1', 'frozen', { ...REGION, x: 1 }, '0.80'))
  assert.notEqual(base, cropVerificationKey('sess-1', 'frozen', REGION, '0.95'))
  assert.notEqual(base, cropVerificationKey('sess-1', 'frozen', null, '0.80'))
})

test('唯一匹配才产生登记依据，且用验证返回的新快照与命中框', () => {
  const key = cropVerificationKey('sess-1', 'frozen', REGION, '0.80')
  const proof = resolveCropVerification(VALIDATED, key)
  assert.deepEqual(proof, {
    key,
    token: 'proof-token',
    snapshotId: 'fresh', // 新快照写回状态，不再用旧冻结快照登记
    region: { x: 581, y: 1048, w: 173, h: 173 },
  })
})

test('零匹配或多匹配不产生登记依据', () => {
  const key = cropVerificationKey('sess-1', 'frozen', REGION, '0.80')
  assert.equal(resolveCropVerification({ ...VALIDATED, count: 0 }, key), null)
  assert.equal(resolveCropVerification({ ...VALIDATED, count: 2 }, key), null)
  // 服务端没给凭证（例如旧响应）时不得凭空认为已验证
  assert.equal(resolveCropVerification({ ...VALIDATED, verification: null }, key), null)
  assert.equal(resolveCropVerification({ ...VALIDATED, region: null }, key), null)
  assert.equal(resolveCropVerification(null, key), null)
})

test('冻结后再采集/切设备后旧验证不可复用（key 不等即失效）', () => {
  const staleKey = cropVerificationKey('sess-1', 'frozen', REGION, '0.80')
  const currentKey = cropVerificationKey('sess-1', 'frozen-2', REGION, '0.80')
  assert.equal(resolveCropVerification(VALIDATED, staleKey) !== null, true)
  // 组件判定用「凭证 key === 当前 key」；对比时必须换 key 重新算
  assert.notEqual(staleKey, currentKey)
})

test('节点拾取优先 resource-id，其次 text，都没有则如实为空', () => {
  assert.deepEqual(
    preferredLocator({ index: 1, resource_id: 'com.miui.home:id/drag_layer', text: '桌面' }),
    { by: 'resource_id', value: 'com.miui.home:id/drag_layer' },
  )
  assert.deepEqual(preferredLocator({ index: 2, text: '确定' }), { by: 'text', value: '确定' })
  assert.equal(preferredLocator({ index: 3, resource_id: '', text: '  ' }), null)
  assert.equal(preferredLocator({ index: 4 }), null)
})

test('冻结快照必须显示同一快照的图片，而不是最后一帧实时画面', () => {
  const source = fs.readFileSync(require.resolve('../src/components/DebugDrawer.tsx'), 'utf8')
  // 一次采集返回 snapshot + tree，树和画面都必须用同一个 snapshot_id 去取
  assert.match(source, /const captured = await captureSnapshot\(id, true\)/)
  assert.match(source, /fetchSnapshotTree\(id, captured\.snapshot_id\)/)
  assert.match(
    source,
    /fetchSnapshotImage\(id, captured\.snapshot_id\)/,
    '冻结画面必须加载该快照的图片；只暂停实时流会展示错帧',
  )
  const freezeAt = source.indexOf('frozenRef.current = true', source.indexOf('const snapshotMutation'))
  const drawAt = source.indexOf('drawSnapshotImage(canvasRef.current, image)', freezeAt)
  assert.ok(freezeAt >= 0 && drawAt > freezeAt, '先冻结再绘制快照，防止解码期间的实时帧覆盖')
  // 实时帧改成异步解码后也要复查冻结标记（P2-03：drawFrame 迁到 debug/debugModel.ts）
  const drawModel = fs.readFileSync(
    require.resolve('../src/components/debug/debugModel.ts'),
    'utf8',
  )
  assert.match(drawModel, /if \(isPaused\?\.\(\)\) return/, '实时帧 onload 必须复查冻结状态')
})

test('快照画面地址与会话/快照 id 对应', () => {
  const { snapshotImagePath } = require('../src/api/endpoints.ts')
  assert.equal(
    snapshotImagePath('s 1', '0123456789abcdef'),
    '/debug-sessions/s%201/snapshots/0123456789abcdef/image',
  )
})

test('刷新/恢复预览清临时状态，但模板清单只来自服务端（不本地删除）', () => {
  const source = fs.readFileSync(
    require.resolve('../src/components/DebugDrawer.tsx'),
    'utf8',
  )
  // 刷新：先清临时选择/验证/颜色框，再从服务端重读已登记模板
  assert.match(source, /clearInspection\(\);\s*void templatesQuery\.refetch\(\)/)
  // 恢复预览同样走 clearInspection（同一个清除路径）
  assert.match(source, /clearInspection\(\)[\s\S]{0,400}恢复预览/)
  // 已登记模板不在前端状态里：没有 setTemplates，也没有删除模板的请求
  assert.ok(!/setTemplates\(/.test(source), '模板清单必须直接来自服务端，不能本地维护/删除')
  assert.ok(!/deleteTemplate|method: 'DELETE'/.test(source), '前端不得删除已登记模板')
})
