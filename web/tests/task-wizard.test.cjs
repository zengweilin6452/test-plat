const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const ts = require('typescript')

// 使用现有 TypeScript 编译器执行真实表单和客户端模块，不引入测试依赖。
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

const { INITIAL_FORM, buildCreateTaskRequest, validateStep1, validateStep2, isDeviceSelectable } =
  require('../src/components/TaskWizard.tsx')
const { createTask } = require('../src/api/endpoints.ts')
const { canConfirmIdentity } = require('../src/components/InputRegistration.tsx')
const applicationId = '11111111-1111-4111-8111-111111111111'
const resourceId = '22222222-2222-4222-8222-222222222222'
const buildId = '33333333-3333-4333-8333-333333333333'
const suiteVersionId = '44444444-4444-4444-8444-444444444444'
const form = {
  ...INITIAL_FORM,
  applicationId,
  name: '  登录冒烟  ',
  identifier: 'com.example.acceptance',
  appVersion: '1.2.3',
  scenario: 'login',
  resourceId,
  // 后端 validate 要求 build_id + suite_version_id：向导必须能带上它们
  buildId,
  suiteVersionId,
}

test('UI 向导使用后端任务模型并保留配置', () => {
  const body = buildCreateTaskRequest(form)
  assert.deepEqual(body, {
    name: '登录冒烟',
    test_type: 'ui',
    platform: 'android',
    application_id: applicationId,
    build_id: buildId,
    suite_version_id: suiteVersionId,
    config: {
      package_name: 'com.example.acceptance',
      app_version: '1.2.3',
      scenario: 'login',
      device: { resource_id: resourceId, allow_busy_queue: true },
    },
  })
})

test('性能向导映射 performance 并保留采集配置', () => {
  const body = buildCreateTaskRequest({ ...form, module: 'perf', duration: '120' })
  assert.equal(body.test_type, 'performance')
  assert.deepEqual(body.config.perf, { duration_s: 120, items: ['CPU', 'Memory', 'FPS'] })
})

test('only an unblocked matching pending identity can be explicitly confirmed', () => {
  const check = { result: 'match', identity_state: 'pending', blocking: [] }
  assert.equal(canConfirmIdentity(check), true)
  assert.equal(canConfirmIdentity(null), false)
  for (const result of ['conflict', 'unknown']) assert.equal(canConfirmIdentity({ ...check, result }), false)
  assert.equal(canConfirmIdentity({ ...check, blocking: [{ reason: 'missing' }] }), false)
  assert.equal(canConfirmIdentity({ ...check, identity_state: 'confirmed' }), false)
})

test('wizard carries only selected immutable image template pins', () => {
  const pins = [{ logical: 'login', version_id: 'template-v1', sha256: 'abc' }]
  assert.deepEqual(buildCreateTaskRequest({ ...form, imageTemplates: pins }).config.image_templates, pins)
  assert.equal(Object.hasOwn(buildCreateTaskRequest(form).config, 'image_templates'), false)
})

test('未选择登记应用时不能继续；包名与时长校验仍生效', () => {
  assert.ok(validateStep1({ ...form, applicationId: '' }).applicationId)
  assert.ok(validateStep1({ ...form, identifier: 'invalid-package' }).identifier)
  assert.ok(validateStep2({ ...form, module: 'perf', duration: '9' }).duration)
  assert.deepEqual(validateStep1(form), {})
  assert.deepEqual(validateStep2(form), {})
  // 构建 / 套件版本是 validate 的必要条件，缺了就不能进第 3 步
  assert.ok(validateStep2({ ...form, buildId: '' }).buildId)
  assert.ok(validateStep2({ ...form, suiteVersionId: '' }).suiteVersionId)
})

test('在线占用设备可排队，离线、未授权和维护设备不可选', () => {
  assert.equal(isDeviceSelectable({ status: 'ready', busy: true }), true)
  for (const status of ['offline', 'unauthorized', 'draining']) {
    assert.equal(isDeviceSelectable({ status }), false)
  }
})

test('Web 草稿保留登记标识且不伪造 Android 设备配置', () => {
  const body = buildCreateTaskRequest({ ...form, platform: 'web', identifier: 'https://example.test' })
  assert.equal(body.config.identifier, 'https://example.test')
  assert.equal(body.config.device, null)
  assert.equal(Object.hasOwn(body.config, 'package_name'), false)
})

test('客户端用请求头携带幂等键，JSON 仅包含后端字段', async (t) => {
  const originalFetch = global.fetch
  const originalWindow = global.window
  t.after(() => {
    global.fetch = originalFetch
    if (originalWindow === undefined) delete global.window
    else global.window = originalWindow
  })
  global.window = { location: { origin: 'http://localhost:5173' } }
  let captured
  global.fetch = async (url, init) => {
    captured = { url, init }
    return new Response(JSON.stringify({ id: 'created-task', revision: { readiness: 'draft' } }), {
      status: 201,
    })
  }
  const body = buildCreateTaskRequest(form)
  const result = await createTask(body, 'wizard-retry-key')
  assert.equal(result.id, 'created-task')
  assert.equal(captured.url, '/api/v1/tasks')
  assert.equal(captured.init.headers['Idempotency-Key'], 'wizard-retry-key')
  assert.equal(captured.init.headers['X-TestDock-Client'], 'web')
  assert.deepEqual(JSON.parse(captured.init.body), body)
})
