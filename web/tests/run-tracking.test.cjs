const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      fileName: filename, compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    })
    module._compile(outputText, filename)
  }
}
const { fetchRunTracking, isRunTerminal } = require('../src/components/RunDrawer.tsx')
global.window = { location: { origin: 'http://localhost' } }
const event = sequence => ({ sequence, event_type: 'stage', payload: {}, occurred_at: null })
const respond = value => ({ ok: true, status: 200, text: async () => JSON.stringify(value) })

test('recovers multiple event pages and deduplicates overlapping persisted events', async () => {
  const urls = []
  global.fetch = async url => {
    urls.push(url)
    if (!url.includes('/events')) return respond({ id: 'run-1', state: 'completed', last_sequence: 4 })
    const after = Number(new URL(url, 'http://localhost').searchParams.get('after'))
    return respond(after === 1 ? { items: [event(1), event(2), event(3)], next_after: 3, has_more: true } : { items: [event(4)], next_after: 4, has_more: false })
  }
  const result = await fetchRunTracking('run-1', { run: { id: 'run-1' }, events: [event(1)] })
  assert.deepEqual(result.events.map(e => e.sequence), [1, 2, 3, 4])
  assert.equal(urls.length, 3)
  assert.match(urls[1], /after=1/)
  assert.match(urls[2], /after=3/)
})

test('switching runs discards the old cursor; empty recovery is an explicit error', async () => {
  global.fetch = async url => !url.includes('/events') ? respond({ id: 'run-2', last_sequence: 1 }) : respond({ items: [], next_after: 0, has_more: false })
  await assert.rejects(fetchRunTracking('run-2', { run: { id: 'run-1' }, events: [event(10)] }), /运行事件尚未完整返回/)
})

test('temporary read failure preserves prior data and never submits another run', async () => {
  const previous = { run: { id: 'run-1' }, events: [event(1)] }
  const methods = []
  global.fetch = async (url, init) => { methods.push(init.method); throw new Error('offline') }
  await assert.rejects(fetchRunTracking('run-1', previous), /无法连接/)
  assert.deepEqual(previous.events, [event(1)])
  assert.deepEqual(methods, ['GET'])
  assert.equal(isRunTerminal('finalizing'), false)
  for (const state of ['completed', 'errored', 'cancelled']) assert.equal(isRunTerminal(state), true)
})

