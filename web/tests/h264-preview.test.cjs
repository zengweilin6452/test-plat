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

const {
  parseRelayHeader,
  relayPayload,
  codecFromAnnexB,
  shouldDropDelta,
  choosePreviewTransport,
} = require('../src/lib/h264Preview.ts')

function packet({ kind = 3, version = 1, generation = 7, sequence = 9, ptsUs = 123456n, key = true, width = 1080, height = 2400, payload = [1, 2, 3, 4] } = {}) {
  const header = new ArrayBuffer(27)
  const view = new DataView(header)
  view.setUint8(0, version)
  view.setUint8(1, kind)
  view.setUint32(2, generation)
  view.setUint32(6, sequence)
  view.setBigUint64(10, ptsUs)
  view.setUint8(18, key ? 1 : 0)
  view.setUint16(19, width)
  view.setUint16(21, height)
  view.setUint32(23, payload.length)
  const out = new Uint8Array(27 + payload.length)
  out.set(new Uint8Array(header), 0)
  out.set(payload, 27)
  return out.buffer
}

test('解析 27 字节包头与载荷', () => {
  const header = parseRelayHeader(packet())
  assert.deepEqual(header, {
    version: 1,
    kind: 3,
    generation: 7,
    sequence: 9,
    ptsUs: 123456n,
    key: true,
    width: 1080,
    height: 2400,
    payloadLength: 4,
  })
  const payload = relayPayload(packet(), header)
  assert.deepEqual([...payload], [1, 2, 3, 4])
})

test('包头异常一律拒绝', () => {
  const badVersion = packet({ version: 2 })
  const badKind = packet({ kind: 9 })
  const short = new Uint8Array(10).buffer
  const incomplete = packet().slice(0, 28)
  const oversized = packet({ payload: [] })
  new DataView(oversized).setUint32(23, 2 * 1024 * 1024 + 1)

  for (const buffer of [badVersion, badKind, short, incomplete, oversized]) {
    assert.throws(() => parseRelayHeader(buffer))
  }
})

test('从 Annex B SPS 生成 WebCodecs codec 串', () => {
  const sps = new Uint8Array([0, 0, 0, 1, 0x67, 0x42, 0xe0, 0x1f, 0xaa])
  assert.equal(codecFromAnnexB(sps), 'avc1.42e01f')
  assert.equal(codecFromAnnexB(new Uint8Array([1, 2, 3])), null)
})

test('解码积压时丢 delta，保关键帧', () => {
  assert.equal(shouldDropDelta(9, false), true)
  assert.equal(shouldDropDelta(9, true), false)
  assert.equal(shouldDropDelta(8, false), false)
})

test('预览传输选择：无 WebCodecs 时明确回退 JPEG', () => {
  assert.deepEqual(choosePreviewTransport(true), { mode: 'h264', reason: null })
  assert.deepEqual(choosePreviewTransport(false), {
    mode: 'jpeg',
    reason: '浏览器不支持 WebCodecs，已回退 JPEG',
  })
})
