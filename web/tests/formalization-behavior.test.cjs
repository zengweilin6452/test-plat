const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      fileName: filename, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    })
    module._compile(outputText, filename)
  }
}
const { requestedContext } = require('../src/store/effectiveContext.tsx')
const { displayName, validDisplayName, onboardingDestination, onboardingSkipped } = require('../src/lib/formalization.ts')
const A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
test('explicit URL app ignores both cached selections; project can be derived from its real application', () => {
  assert.deepEqual(requestedContext(null, B, A, A), { requestedProject: null, requestedApp: B })
})
test('explicit URL project clears cached app, and all clears both cached selections', () => {
  assert.deepEqual(requestedContext(B, null, A, A), { requestedProject: B, requestedApp: null })
  assert.deepEqual(requestedContext('all', null, A, A), { requestedProject: null, requestedApp: null })
  assert.deepEqual(requestedContext('all', B, A, A), { requestedProject: null, requestedApp: null })
})
test('explicit conflicting URL identities survive for validation; absent URL uses cached choices', () => {
  assert.deepEqual(requestedContext(B, A, A, B), { requestedProject: B, requestedApp: A })
  assert.deepEqual(requestedContext(null, null, A, B), { requestedProject: A, requestedApp: B })
})
test('names trim, accept 1 to 60 Unicode characters and reject empty or longer values before requests', () => {
  assert.equal(displayName('  项目  '), '项目')
  assert.equal(validDisplayName('名'.repeat(60)), true)
  assert.equal(validDisplayName('😀'.repeat(60)), true)
  for (const name of ['', '   ', '名'.repeat(61)]) assert.throws(() => displayName(name), /1–60/)
})
test('first entry chooses welcome only when incomplete and unskipped, skip storage updates immediately', () => {
  for (const complete of [true, false]) for (const skipped of [true, false]) {
    assert.equal(onboardingDestination(complete, skipped), !complete && !skipped ? '/onboarding' : '/overview')
  }
  const storage = new Map()
  global.window = { localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) } }
  assert.equal(onboardingSkipped(), false)
  window.localStorage.setItem('testdock.onboarding.skipped', '1')
  assert.equal(onboardingSkipped(), true)
  delete global.window
})
test('performance scope key remounts editors and selected run state when project or app changes', () => {
  const { PerfPage } = require('../src/pages/PerfPage.tsx')
  const contextModule = require('../src/store/effectiveContext.tsx')
  let ctx = { projectId: A, appId: A }
  const original = contextModule.useEffectiveContext
  contextModule.useEffectiveContext = () => ctx
  try {
    const first = PerfPage()
    ctx = { projectId: B, appId: A }
    const second = PerfPage()
    ctx = { projectId: B, appId: B }
    const third = PerfPage()
    assert.notEqual(first.key, second.key)
    assert.notEqual(second.key, third.key)
    assert.equal(first.type, third.type)
  } finally { contextModule.useEffectiveContext = original }
})
