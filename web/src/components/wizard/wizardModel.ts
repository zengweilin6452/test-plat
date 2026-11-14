/**
 * 新建任务向导的表单模型与校验（自 TaskWizard.tsx 迁入，P2-03 分层）。
 *
 * 纯逻辑，不含 JSX：常量、WizardForm 状态形状、分步校验、POST /tasks 请求体
 * 组装、设备可选性与性能场景摘要。校验规则照 api-design.md §2.3 与
 * prototype-ui-spec §2.6。TaskWizard.tsx 再导出本模块全部公开名，
 * 既有消费方（TaskDrawer / AppsPage / PerfPage / 用例）不需要改导入路径。
 */
import type { CreateTaskRequest, Platform, ResourceRecord, TestModule } from '../../types'
import type { SuiteVersionRecord } from '../../api/types'
import type { TemplatePin } from '../TemplateLibrary'
import { DEFAULT_PERF_ITEMS, normalizePerfItems, perfItemsLabel } from '../../lib/perfItems'

/** 任务名称上限（api-design.md §2.3） */
export const NAME_MAX = 60
/** 包名上限（api-design.md §2.3） */
export const PACKAGE_MAX = 120
/** 采集时长上下限（api-design.md §2.3：整数 10–3600） */
export const DURATION_MIN = 10
export const DURATION_MAX = 3600

/** Android 包名：^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$ */
export const PACKAGE_PATTERN = /^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$/

/** Web 站点地址：必须是 http/https 且能被 URL 解析 */
export function isValidSiteUrl(value: string): boolean {
  if (!value.trim()) return false
  try {
    const parsed = new URL(value.trim())
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

export interface WizardForm {
  platform: Platform
  module: TestModule
  name: string
  applicationId: string
  /** Android 包名 / Web 站点地址 */
  identifier: string
  appVersion: string
  scenario: string
  resourceId: string
  duration: string
  /** module 为 perf/joint 时提交的 mobile-perf 采集项（CPU/Memory/FPS/Network/Battery） */
  perfItems: string[]
  buildId: string
  suiteId: string
  suiteVersionId: string
  imageTemplates?: TemplatePin[]
}

export const INITIAL_FORM: WizardForm = {
  platform: 'android',
  module: 'ui',
  name: '',
  applicationId: '',
  identifier: '',
  appVersion: '',
  scenario: '',
  resourceId: '',
  duration: '300',
  perfItems: [...DEFAULT_PERF_ITEMS],
  buildId: '',
  suiteId: '',
  suiteVersionId: '',
  imageTemplates: [],
}

/** 字段级错误：key 与表单字段同名，便于把提示渲染到对应控件下方 */
export type WizardErrors = Partial<Record<keyof WizardForm, string>>

export const PLATFORMS: Platform[] = ['android', 'ios', 'web']
export const MODULES: TestModule[] = ['ui', 'perf', 'joint']

/**
 * 第 1 步校验：平台、模块、名称、标识（包名 / URL）、版本号。
 * 只做纯函数校验，不发请求 —— 便于单测与「未通过不进下一步」的硬约束。
 */
export function validateStep1(form: WizardForm): WizardErrors {
  const errors: WizardErrors = {}
  if (!form.applicationId) errors.applicationId = '请选择已登记应用。'
  const name = form.name.trim()
  if (!name) {
    errors.name = '请填写任务名称。'
  } else if (name.length > NAME_MAX) {
    errors.name = `任务名称最多 ${NAME_MAX} 个字符。`
  }

  const identifier = form.identifier.trim()
  if (!identifier) {
    errors.identifier =
      form.platform === 'android' ? '所选应用未登记包名，请先在应用档案补全。' : form.platform === 'web' ? '所选应用未登记站点地址，请先在应用档案补全。' : '所选应用未登记 Bundle ID，请先在应用档案补全。'
  } else if (form.platform === 'android') {
    if (!PACKAGE_PATTERN.test(identifier)) {
      errors.identifier = '所选应用登记的包名不合法（应形如 com.example.app），请在应用档案修正。'
    } else if (identifier.length > PACKAGE_MAX) {
      errors.identifier = `包名最多 ${PACKAGE_MAX} 个字符。`
    }
  } else if (form.platform === 'web') {
    if (!isValidSiteUrl(identifier)) {
      errors.identifier = '所选应用登记的站点地址不合法（需 http/https URL），请在应用档案修正。'
    } else if (identifier.length > PACKAGE_MAX) {
      errors.identifier = `站点地址最多 ${PACKAGE_MAX} 个字符。`
    }
  } else if (identifier.length > PACKAGE_MAX) {
    errors.identifier = `Bundle ID 最多 ${PACKAGE_MAX} 个字符。`
  }

  if (form.appVersion.trim().length > 40) {
    errors.appVersion = '应用版本最多 40 个字符。'
  }

  return errors
}

/** 第 2 步校验：设备（Android 必选）、采集时长与采集项（module != ui 必填） */
export function validateStep2(form: WizardForm): WizardErrors {
  const errors: WizardErrors = {}
  if (form.platform === 'android' && !form.resourceId) {
    errors.resourceId = '请选择已授权在线的设备。'
  }
  // 验证（readiness=validated）的 DB CHECK 要求 build_id 与 suite_version_id
  // 都非空；向导里选好，"配置 → 验证 → 执行"才走得通。
  if (form.platform === 'android') {
    if (!form.buildId) errors.buildId = '请选择构建版本。'
    if (!form.suiteVersionId) errors.suiteVersionId = '请选择套件版本。'
  }
  if (form.module !== 'ui') {
    const raw = form.duration.trim()
    if (!raw) {
      errors.duration = '请填写采集时长。'
    } else if (!/^\d+$/.test(raw)) {
      errors.duration = '采集时长需要是 10–3600 之间的整数秒。'
    } else {
      const value = Number(raw)
      if (value < DURATION_MIN || value > DURATION_MAX) {
        errors.duration = '采集时长需要是 10–3600 之间的整数秒。'
      }
    }
    if (normalizePerfItems(form.perfItems).length === 0) {
      errors.perfItems = '至少选择一个采集项。'
    }
  }
  return errors
}

/** 按当前步骤取校验结果（1 / 2 步有表单校验，3 步为确认页） */
export function validateStep(step: number, form: WizardForm): WizardErrors {
  if (step === 1) return validateStep1(form)
  if (step === 2) return validateStep2(form)
  return {}
}

export const STEP_LABELS = ['基本信息', '套件与设备', '确认任务'] as const

/** 生成 UUIDv4 作幂等键（crypto.randomUUID 不可用时降级到 getRandomValues） */
export function newRequestKey(): string {
  const cryptoObj = window.crypto
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') return cryptoObj.randomUUID()
  const bytes = new Uint8Array(16)
  cryptoObj.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/** 组装 POST /tasks 请求体：只发契约字段，不塞前端自造字段 */
export function buildCreateTaskRequest(form: WizardForm): CreateTaskRequest {
  const body: CreateTaskRequest = {
    name: form.name.trim(),
    test_type: form.module === 'perf' ? 'performance' : form.module,
    platform: form.platform,
    application_id: form.applicationId,
    config: {
      ...(form.imageTemplates?.length ? { image_templates: form.imageTemplates } : {}),
      ...(form.platform === 'android'
        ? { package_name: form.identifier.trim() }
        : { identifier: form.identifier.trim() }),
      app_version: form.appVersion.trim() || null,
      scenario: form.scenario.trim() || null,
      device: form.platform === 'android' && form.resourceId
        ? { resource_id: form.resourceId, allow_busy_queue: true } : null,
      ...(form.module === 'ui' ? {} : {
        perf: {
          duration_s: Number(form.duration.trim()),
          items: normalizePerfItems(form.perfItems ?? DEFAULT_PERF_ITEMS),
        },
      }),
    },
  }
  // 验证与首次执行的必要绑定：validate 要求 build + 套件版本，运行只引用
  // validated 修订——创建时不带上，「配置 → 验证 → 执行」链路就断在 validate。
  // 没选就不写这个键：undefined 在 JSON 里会消失，留着只会让请求体与契约对不上。
  if (form.buildId) body.build_id = form.buildId
  if (form.suiteVersionId) body.suite_version_id = form.suiteVersionId
  return body
}

/** 设备可选性：offline / unauthorized 不可选（原型 §2.6 第 2 步） */
export function isDeviceSelectable(resource: ResourceRecord): boolean {
  return resource.status === 'ready'
}

/** 性能/联动版本的场景（performance 在 manifest.scenario，joint 在 manifest.performance）。 */
export function scenarioOfVersion(version: SuiteVersionRecord): {
  duration_s: number | null
  items: string[]
} | null {
  const manifest = version.manifest
  const raw = (manifest?.scenario ?? manifest?.performance) as unknown
  if (!raw || typeof raw !== 'object') return null
  const scenario = raw as { duration_s?: unknown; items?: unknown }
  const duration_s =
    typeof scenario.duration_s === 'number' && Number.isInteger(scenario.duration_s)
      ? scenario.duration_s
      : null
  const items = Array.isArray(scenario.items)
    ? normalizePerfItems(scenario.items.map((item) => String(item)))
    : []
  if (duration_s === null && items.length === 0) return null
  return { duration_s, items }
}

/** 版本清单里展示性能场景摘要；旧版本没有 manifest 时返回空串。 */
export function scenarioSummary(version: SuiteVersionRecord): string {
  const scenario = scenarioOfVersion(version)
  if (!scenario) return ''
  const parts: string[] = []
  if (scenario.duration_s !== null) parts.push(`${scenario.duration_s}s`)
  const items = perfItemsLabel(scenario.items)
  if (items) parts.push(items)
  return parts.length > 0 ? ' · ' + parts.join(' · ') : ''
}
