/**
 * 新建任务三步向导（原型 newTask L240 / wizardRender L242–L247 / wizardNext L248）。
 *
 * 步骤：① 基本信息 ② 套件与设备 ③ 确认。
 * 校验规则照 api-design.md §2.3 与 prototype-ui-spec §2.6：
 * - name 必填、maxlength 60（trim 后 1–60）；
 * - Android 包名 ^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$，≤120；Web 端用 URL（http/https）；
 * - 采集时长（module != ui）整数 10–3600；
 * - 采集项（module != ui）至少一项，选项来自 mobile-perf 的 SoloPi 采集项。
 * 每步未通过校验不得进入下一步；错误提示渲染在字段下方，容器 role="alert"。
 *
 * 提交纪律：
 * - 写操作带 X-TestDock-Client: web（由 api/client.ts 统一注入）；
 * - request_key 每次「尝试提交」生成一次，网络失败重试复用同一个 key，保证幂等；
 * - 后端 P2 端点未就绪（404）时只显示 Notice + 错误码，不伪造成功、不关窗。
 */
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import {
  createTask,
  fetchApplications,
  fetchBuilds,
  fetchResources,
  fetchSuiteVersions,
  fetchSuites,
} from '../api/endpoints'
import { MODULE_NAMES, TARGET_CATALOG } from '../constants'
import { DASH } from '../lib/fmt'
import {
  DEFAULT_PERF_ITEMS,
  PERF_ITEM_OPTIONS,
  normalizePerfItems,
  perfItemsLabel,
} from '../lib/perfItems'
import type {
  CreateTaskRequest,
  CreateTaskResponse,
  Platform,
  ResourceRecord,
  TestModule,
} from '../types'
import type { SuiteVersionRecord } from '../api/types'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { Notice } from './Notice'
import { BuildRegistration, SuiteRegistration } from './InputRegistration'
import { TemplatePicker, type TemplatePin } from './TemplateLibrary'

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

const PLATFORMS: Platform[] = ['android', 'ios', 'web']
const MODULES: TestModule[] = ['ui', 'perf', 'joint']

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

const STEP_LABELS = ['基本信息', '套件与设备', '确认任务'] as const

/** 字段下方错误提示：容器 role="alert"，符合「错误提示在字段下方且容器 role=alert」的验收要求 */
function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (!message) return null
  return (
    <div className="field-error" id={id} role="alert">
      {message}
    </div>
  )
}

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
function scenarioOfVersion(version: SuiteVersionRecord): {
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
function scenarioSummary(version: SuiteVersionRecord): string {
  const scenario = scenarioOfVersion(version)
  if (!scenario) return ''
  const parts: string[] = []
  if (scenario.duration_s !== null) parts.push(`${scenario.duration_s}s`)
  const items = perfItemsLabel(scenario.items)
  if (items) parts.push(items)
  return parts.length > 0 ? ' · ' + parts.join(' · ') : ''
}

interface TaskWizardProps {
  open: boolean
  onClose: () => void
  /** 创建成功后回调（页面据此 refetch 任务列表 / toast / 打开抽屉） */
  onCreated?: (created: CreateTaskResponse) => void
  /** 初始目标端（跟随页面 context 条的 scope；'all' 时用 android） */
  initialPlatform?: Platform
  initialModule?: TestModule
  initialApplicationId?: string
  initialSuite?: { applicationId: string; suiteId: string; suiteVersionId: string; platform: Platform; name?: string }
}

export function TaskWizard({ open, onClose, onCreated, initialPlatform, initialModule, initialApplicationId, initialSuite }: TaskWizardProps) {
  const uid = useId()
  const [step, setStep] = useState(1)
  const [form, setForm] = useState<WizardForm>(INITIAL_FORM)
  const [errors, setErrors] = useState<WizardErrors>({})
  const [touched, setTouched] = useState(false)
  const [suiteRegistrationSignal, setSuiteRegistrationSignal] = useState(0)
  const requestKeyRef = useRef<string>('')
  const stepsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const body = stepsRef.current?.closest('.dialog-body')
    if (body) body.scrollTop = 0
  }, [step])

  const fieldId = (name: keyof WizardForm) => `${uid}-${name}`
  const presetPlatform = initialSuite?.platform ?? initialPlatform ?? 'android'
  const presetApplicationId = initialSuite?.applicationId ?? initialApplicationId ?? ''
  const presetSuiteId = initialSuite?.suiteId ?? ''
  const presetVersionId = initialSuite?.suiteVersionId ?? ''
  const presetName = initialSuite?.name ?? ''

  // 每次打开重置为初始状态；关闭时清掉请求键
  useEffect(() => {
    if (open) {
      setStep(1)
      setErrors({})
      setTouched(false)
      setSuiteRegistrationSignal(0)
      setForm({ ...INITIAL_FORM, platform: presetPlatform, module: initialModule ?? 'ui',
        applicationId: presetApplicationId, suiteId: presetSuiteId,
        suiteVersionId: presetVersionId, name: presetName })
      requestKeyRef.current = ''
    }
  }, [open, presetPlatform, initialModule, presetApplicationId, presetSuiteId, presetVersionId, presetName])

  const applicationsQuery = useQuery({
    queryKey: ['applications', 'wizard'],
    queryFn: ({ signal }) => fetchApplications(signal),
    enabled: open,
    retry: false,
  })
  const applications = (applicationsQuery.data?.items ?? []).filter(
    (application) => application.platform === form.platform,
  )
  const applicationsError = applicationsQuery.isError ? describeError(applicationsQuery.error) : null
  useEffect(() => {
    const application = applicationsQuery.data?.items.find(app => app.id === form.applicationId)
    if (application) setForm(prev => ({ ...prev, identifier: application.identifier ?? '' }))
  }, [applicationsQuery.data, form.applicationId])

  // 构建与套件版本（validate 的必要绑定）：换应用后重新拉取
  const buildsQuery = useQuery({
    queryKey: ['builds', 'wizard', form.applicationId],
    queryFn: ({ signal }) => fetchBuilds(form.applicationId, signal),
    enabled: open && form.platform === 'android' && Boolean(form.applicationId),
    retry: false,
  })
  const suitesQuery = useQuery({
    queryKey: ['suites', 'wizard', form.module],
    queryFn: ({ signal }) =>
      fetchSuites(form.module === 'perf' ? 'performance' : form.module, signal),
    enabled: open && form.platform === 'android',
    retry: false,
  })
  const suites = (suitesQuery.data?.items ?? []).filter(
    (suite) => suite.application.id === form.applicationId,
  )
  const suiteVersionsQuery = useQuery({
    queryKey: ['suite-versions', 'wizard', form.suiteId],
    queryFn: ({ signal }) => fetchSuiteVersions(form.suiteId, signal),
    enabled: open && form.platform === 'android' && Boolean(form.suiteId),
    retry: false,
  })
  const suiteVersions: SuiteVersionRecord[] = suiteVersionsQuery.data?.items ?? []
  const selectedSuiteVersion =
    suiteVersions.find((version) => version.id === form.suiteVersionId) ?? null

  // 已有性能/联动版本自带场景：选定后把时长与采集项回填到表单，
  // 避免提交时 revision.config.perf 与版本清单冲突。
  useEffect(() => {
    if (form.module === 'ui' || !selectedSuiteVersion) return
    const scenario = scenarioOfVersion(selectedSuiteVersion)
    if (!scenario) return
    const duration =
      scenario.duration_s !== null ? String(scenario.duration_s) : null
    const items = scenario.items
    setForm((prev) => {
      if (prev.suiteVersionId !== selectedSuiteVersion.id) return prev
      const nextDuration = duration ?? prev.duration
      const nextItems = items.length > 0 ? items : prev.perfItems
      if (
        prev.duration === nextDuration &&
        prev.perfItems.length === nextItems.length &&
        prev.perfItems.every((item, index) => item === nextItems[index])
      ) {
        return prev
      }
      return { ...prev, duration: nextDuration, perfItems: nextItems }
    })
  }, [form.module, selectedSuiteVersion?.id, selectedSuiteVersion?.manifest])

  const selectedScenario = selectedSuiteVersion
    ? scenarioOfVersion(selectedSuiteVersion)
    : null
  const scenarioMismatch = Boolean(
    form.module !== 'ui' &&
    selectedScenario &&
    (normalizePerfItems(form.perfItems).join('\u0000') !== selectedScenario.items.join('\u0000') ||
      (selectedScenario.duration_s !== null &&
        Number(form.duration) !== selectedScenario.duration_s)),
  )

  // Android 才需要选设备；其它端不请求资源列表
  const resourcesQuery = useQuery({
    queryKey: ['resources', 'wizard'],
    queryFn: ({ signal }) => fetchResources('android', signal),
    enabled: open && form.platform === 'android',
    retry: false,
  })

  const resourcesError = resourcesQuery.isError ? describeError(resourcesQuery.error) : null
  const devices = useMemo(
    () => (resourcesQuery.data?.items ?? []).filter((item) => item.platform === 'android'
      && item.project_id === applicationsQuery.data?.items.find((app) => app.id === form.applicationId)?.project_id),
    [resourcesQuery.data, applicationsQuery.data, form.applicationId],
  )

  const submit = useMutation({
    mutationFn: (body: CreateTaskRequest) => createTask(body, requestKeyRef.current),
    onSuccess: (created) => {
      // 成功后通知页面：toast + 关闭 + refetch 由调用方统一处理（避免各页各写一份）
      onCreated?.(created)
    },
    onError: () => {
      // 错误在下方 Notice 中展示；这里不吞掉、不重试（避免后端未就绪时刷 404）
    },
  })

  const submitError = submit.isError ? describeError(submit.error) : null

  /**
   * 字段错误展示口径：
   * - 用户已点过「下一步」：展示该步的显式错误（含空值提示）；
   * - 尚未交互：只在格式确实非法时提示（不因为空值就报红）。
   */
  const fieldErrors = useMemo<WizardErrors>(() => {
    const live = validateStep(step, form)
    const shown = touched ? errors : live
    const merged: WizardErrors = { ...live, ...shown }
    for (const key of Object.keys(merged) as (keyof WizardForm)[]) {
      if (!live[key]) delete merged[key]
    }
    return merged
  }, [step, form, touched, errors])

  function update<K extends keyof WizardForm>(key: K, value: WizardForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
    if (touched) setErrors((prev) => ({ ...prev, [key]: undefined }))
  }

  function goNext() {
    const nextErrors = validateStep(step, form)
    setTouched(true)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) return
    setStep((prev) => Math.min(3, prev + 1))
  }

  function goPrev() {
    setTouched(false)
    setErrors({})
    setStep((prev) => Math.max(1, prev - 1))
  }

  function handleSubmit() {
    // 提交前把前两步重跑一遍，任何一步不通过就退回该步（防止绕过）
    const step1 = validateStep1(form)
    if (Object.keys(step1).length > 0) {
      setErrors(step1)
      setTouched(true)
      setStep(1)
      return
    }
    const step2 = validateStep2(form)
    if (Object.keys(step2).length > 0) {
      setErrors(step2)
      setTouched(true)
      setStep(2)
      return
    }
    if (!requestKeyRef.current) requestKeyRef.current = newRequestKey()
    submit.mutate(buildCreateTaskRequest(form))
  }

  function handleClose() {
    if (submit.isPending) return
    onClose()
  }

  /** 字段下方错误提示：容器 role="alert"，符合验收要求 */
  const footer = (
    <>
      <Button onClick={handleClose} disabled={submit.isPending}>
        取消
      </Button>
      {step > 1 ? <Button onClick={goPrev} disabled={submit.isPending}>上一步</Button> : null}
      {step < 3 ? (
        <Button kind="primary" onClick={goNext}>
          下一步
        </Button>
      ) : (
        <Button kind="primary" onClick={handleSubmit} disabled={submit.isPending}>
          {submit.isPending ? '提交中…' : '创建任务'}
        </Button>
      )}
    </>
  )

  const stepLabels = form.module === 'perf'
    ? (['基本信息', '场景与设备', '确认任务'] as const)
    : STEP_LABELS

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="新建测试任务"
      description={`第 ${step} / 3 步 · ${stepLabels[step - 1]}`}
      footer={footer}
      footHint={
        step === 3
          ? '创建后可在此打开任务详情验证就绪状态'
          : '每步校验通过后才能进入下一步'
      }
    >
      <div ref={stepsRef} className="wizard-steps" role="list" aria-label="向导步骤">
        {stepLabels.map((label, index) => {
          const value = index + 1
          return (
            <div key={label} className="flex" role="listitem">
              <span className="wizard-step" aria-current={value === step ? 'step' : undefined}>
                <b>{value}</b>
                {label}
              </span>
              {value < stepLabels.length ? (
                <span className="wizard-arrow" aria-hidden="true">
                  ›
                </span>
              ) : null}
            </div>
          )
        })}
      </div>

      {step === 1 ? (
        <div className="form-grid">
          <div className="field">
            <span className="field-label">目标端</span>
            <div className="choice-grid three">
              {PLATFORMS.map((platform) => (
                <button
                  key={platform}
                  type="button"
                  className="choice"
                  aria-pressed={form.platform === platform}
                  onClick={() => {
                    update('platform', platform)
                    // 换端后设备选择与标识含义都变了，清掉旧值避免误提交
                    setForm((prev) => ({ ...prev, platform, applicationId: '', identifier: '', resourceId: '', buildId: '', suiteId: '', suiteVersionId: '' }))
                    setErrors({})
                  }}
                >
                  <strong>{TARGET_CATALOG[platform].label}</strong>
                  <small>{TARGET_CATALOG[platform].capability}</small>
                </button>
              ))}
            </div>
            {form.platform !== 'android' ? (
              <div className="field-hint">
                {TARGET_CATALOG[form.platform].label} 端尚无执行适配器，创建的修订只能是草稿（readiness 永远 draft）。
              </div>
            ) : null}
          </div>

          <div className="field">
            <span className="field-label">测试模块</span>
            <div className="choice-grid three">
              {MODULES.map((module) => (
                <button
                  key={module}
                  type="button"
                  className="choice"
                  aria-pressed={form.module === module}
                  onClick={() => setForm(prev => ({ ...prev, module, suiteId: '', suiteVersionId: '' }))}
                >
                  <strong>{MODULE_NAMES[module]}</strong>
                  <small>{module === 'ui' ? '不采集性能指标' : '需要填写采集时长'}</small>
                </button>
              ))}
            </div>
            {form.module === 'joint' ? (
              <div className="field-hint">
                联动（UI + 性能）的步骤打标依赖宿主注入设备准入协议，首期只保留配置。
              </div>
            ) : null}
          </div>

          <div className="field">
            <label htmlFor={fieldId('name')}>
              任务名称 <span className="text-red">*</span>
            </label>
            <input
              id={fieldId('name')}
              value={form.name}
              maxLength={NAME_MAX}
              placeholder="例如：首页滑动性能巡检"
              aria-invalid={Boolean(fieldErrors.name)}
              aria-describedby={fieldErrors.name ? `${fieldId('name')}-error` : undefined}
              onChange={(event) => update('name', event.target.value)}
            />
            <div className="field-hint">
              {form.name.trim().length} / {NAME_MAX}
            </div>
            <FieldError id={`${fieldId('name')}-error`} message={fieldErrors.name} />
          </div>

          <div className="field">
            <label htmlFor={fieldId('applicationId')}>已登记应用 <span className="text-red">*</span></label>
            <select
              id={fieldId('applicationId')}
              value={form.applicationId}
              disabled={applicationsQuery.isLoading}
              aria-invalid={Boolean(fieldErrors.applicationId)}
              aria-describedby={`${fieldId('applicationId')}-error`}
              onChange={(event) => {
                const application = applications.find((item) => item.id === event.target.value)
                setForm((prev) => ({ ...prev, applicationId: application?.id ?? '',
                  identifier: application?.identifier ?? '', resourceId: '', buildId: '', suiteId: '', suiteVersionId: '' }))
              }}
            >
              <option value="">请选择已登记应用</option>
              {applications.map((application) => (
                <option key={application.id} value={application.id}>{application.name} · {application.identifier}</option>
              ))}
            </select>
            {applicationsError ? <Notice tone="red" title="应用列表获取失败">{applicationsError.message}</Notice> : null}
            {!applicationsQuery.isLoading && !applicationsError && applications.length === 0
              ? <div className="field-hint">当前目标端没有已登记应用。</div> : null}
            <FieldError id={`${fieldId('applicationId')}-error`} message={fieldErrors.applicationId} />
          </div>

          <div className="field">
            <label htmlFor={fieldId('identifier')}>
              {form.platform === 'android' ? '应用包名' : form.platform === 'web' ? '站点地址（URL）' : 'Bundle ID'}{' '}
              <span className="text-red">*</span>
            </label>
            <input
              id={fieldId('identifier')}
              value={form.identifier}
              maxLength={PACKAGE_MAX}
              placeholder={
                form.platform === 'android'
                  ? 'com.example.xinghe'
                  : form.platform === 'web'
                    ? 'https://staging.example.test'
                    : 'com.example.xinghe.ios'
              }
              aria-invalid={Boolean(fieldErrors.identifier)}
              aria-describedby={fieldErrors.identifier ? `${fieldId('identifier')}-error` : undefined}
              readOnly
            />
            <div className="field-hint">
              {form.platform === 'android'
                ? '包名需符合 ^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$'
                : form.platform === 'web'
                  ? 'Web 端用站点地址标识目标，必须是 http/https URL'
                  : 'iOS 端用 Bundle ID 标识目标'}
            </div>
            <FieldError id={`${fieldId('identifier')}-error`} message={fieldErrors.identifier} />
          </div>

          <div className="form-grid two">
            <div className="field">
              <label htmlFor={fieldId('appVersion')}>应用版本</label>
              <input
                id={fieldId('appVersion')}
                value={form.appVersion}
                maxLength={40}
                placeholder="3.8.0-rc.2"
                aria-invalid={Boolean(fieldErrors.appVersion)}
                aria-describedby={fieldErrors.appVersion ? `${fieldId('appVersion')}-error` : undefined}
                onChange={(event) => update('appVersion', event.target.value)}
              />
              <div className="field-hint">可留空，后端记录实际构建</div>
              <FieldError id={`${fieldId('appVersion')}-error`} message={fieldErrors.appVersion} />
            </div>
            <div className="field">
              <label htmlFor={fieldId('scenario')}>测试套件 / 场景</label>
              <input
                id={fieldId('scenario')}
                value={form.scenario}
                maxLength={120}
                placeholder={form.module === 'perf' ? '首页滑动' : '核心链路回归'}
                onChange={(event) => update('scenario', event.target.value)}
              />
              <div className="field-hint">套件清单读接口在 P2 提供，这里先按名称登记</div>
            </div>
          </div>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="form-grid">
          {form.platform === 'android' ? (
            <div className="field">
              <span className="field-label">执行设备</span>
              {resourcesError ? (
                <Notice tone="red" title={`设备列表获取失败（${resourcesError.code}）`}>
                  {resourcesError.message}
                </Notice>
              ) : null}
              {resourcesQuery.isLoading ? (
                <div className="muted small">正在请求 /api/v1/resources</div>
              ) : devices.length === 0 && !resourcesError ? (
                <div className="muted small">当前没有登记在册的 Android 设备。</div>
              ) : (
                <div className="choice-grid">
                  {devices.map((device) => {
                    const selectable = isDeviceSelectable(device)
                    return (
                      <button
                        key={device.id}
                        type="button"
                        className="choice"
                        aria-pressed={form.resourceId === device.id}
                        disabled={!selectable}
                        title={selectable ? undefined : '设备离线、未授权或维护中，暂不可选；可在「执行资源」同步后重试'}
                        onClick={() => update('resourceId', device.id)}
                      >
                        <strong>{device.name}</strong>
                        <small>
                          {device.profile?.os_name ?? '未知系统'}
                          {device.profile?.os_version ? ` ${device.profile.os_version}` : ''} ·{' '}
                          {device.status === 'ready'
                            ? (device.busy ? '占用中（可排队）' : '可用')
                            : device.status === 'draining'
                              ? '维护中'
                              : device.status === 'offline'
                                ? '离线'
                                : '待授权'}
                        </small>
                        <span className="choice-meta">
                          {device.profile?.screen_resolution ?? '分辨率未登记'} · {device.resource_key}
                          {device.busy ? ' · 当前有租约' : ''}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
              <div className="field-hint">离线、未授权或维护中的设备不可选；在线设备占用中可选择排队。</div>
              <FieldError id={`${fieldId('resourceId')}-error`} message={fieldErrors.resourceId} />
            </div>
          ) : (
            <Notice tone="blue" icon="clock" title="该目标端暂无执行资源">
              {TARGET_CATALOG[form.platform].label} 端尚未接入执行能力，无需选择设备；任务会以草稿保存。
            </Notice>
          )}

          {form.platform === 'android' ? (
            <div className="form-grid two">
              <div className="field">
                <label htmlFor={fieldId('buildId')}>
                  构建版本 <span className="text-red">*</span>
                </label>
                <select
                  id={fieldId('buildId')}
                  value={form.buildId}
                  aria-invalid={Boolean(fieldErrors.buildId)}
                  aria-describedby={fieldErrors.buildId ? `${fieldId('buildId')}-error` : undefined}
                  onChange={(event) => update('buildId', event.target.value)}
                >
                  <option value="">请选择构建…</option>
                  {(buildsQuery.data?.items ?? []).map((build) => (
                    <option key={build.id} value={build.id}>
                      {build.version}（{build.build_key}）
                    </option>
                  ))}
                </select>
                <div className="field-hint">
                  {buildsQuery.isError
                    ? '构建清单获取失败：请先在应用页登记构建。'
                    : '验证（readiness=validated）必须绑定构建。'}
                </div>
                <FieldError id={`${fieldId('buildId')}-error`} message={fieldErrors.buildId} />
              </div>
              <div className="field">
                <label htmlFor={fieldId('suiteVersionId')}>
                  {form.module === 'perf' ? '性能场景版本' : '套件版本'} <span className="text-red">*</span>
                </label>
                <div style={{ display: 'grid', gap: 6 }}>
                  <select
                    id={fieldId('suiteId')}
                    value={form.suiteId}
                    onChange={(event) => {
                      setForm((prev) => ({ ...prev, suiteId: event.target.value, suiteVersionId: '' }))
                    }}
                    aria-label={form.module === 'perf' ? '选择性能场景' : '选择套件'}
                  >
                    <option value="">
                      {form.module === 'perf' ? '请选择性能场景…' : '请选择套件…'}
                    </option>
                    {suites.map((suite) => (
                      <option key={suite.id} value={suite.id}>
                        {suite.name}
                      </option>
                    ))}
                  </select>
                  <select
                    id={fieldId('suiteVersionId')}
                    value={form.suiteVersionId}
                    aria-invalid={Boolean(fieldErrors.suiteVersionId)}
                    aria-describedby={
                      fieldErrors.suiteVersionId ? `${fieldId('suiteVersionId')}-error` : undefined
                    }
                    disabled={!form.suiteId}
                    onChange={(event) => update('suiteVersionId', event.target.value)}
                  >
                    <option value="">
                      {form.suiteId ? '请选择版本…' : '先选择套件…'}
                    </option>
                    {suiteVersions.map((version) => (
                      <option key={version.id} value={version.id}>
                        v{version.version}
                        {form.module === 'ui' ? (
                          <>
                            {typeof version.case_count === 'number' ? ` · ${version.case_count} 用例` : ''}
                            {version.has_code_copy === false ? ' · 无固定代码副本（不可验证）' : ''}
                          </>
                        ) : (
                          <>
                            {form.module === 'joint' && typeof version.case_count === 'number'
                              ? ` · ${version.case_count} 用例`
                              : ''}
                            {form.module === 'joint' && version.has_code_copy === false
                              ? ' · 无固定代码副本（不可验证）'
                              : ''}
                            {scenarioSummary(version)}
                          </>
                        )}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field-hint">
                  {suitesQuery.isError || suiteVersionsQuery.isError
                    ? '套件清单获取失败：请先在套件来源登记套件版本。'
                    : form.module === 'perf'
                      ? '性能场景版本锁定采集时长与采集项，不执行 UI 用例，也不需要固定代码副本。'
                      : form.module === 'joint'
                        ? '联动版本包含 UI 用例、固定代码副本和性能采集项。'
                        : '验证要求套件版本带用例与固定代码副本。'}
                </div>
                {form.module === 'perf'
                && form.applicationId
                && !suitesQuery.isPending
                && !suitesQuery.isError
                && suites.length === 0 ? (
                  <Notice tone="amber" title="还没有性能场景版本">
                    当前应用没有性能套件。请先
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => setSuiteRegistrationSignal((value) => value + 1)}
                    >
                      去登记
                    </button>
                    ，登记后会回填场景与版本。
                  </Notice>
                ) : null}
                <FieldError
                  id={`${fieldId('suiteVersionId')}-error`}
                  message={fieldErrors.suiteVersionId}
                />
              </div>
            </div>
          ) : null}

          {form.platform === 'android' && form.applicationId ? <>
            <BuildRegistration key={`${form.applicationId}-${form.buildId}-${form.resourceId}`} applicationId={form.applicationId} buildId={form.buildId} resourceId={form.resourceId} onRegistered={id => update('buildId', id)} />
            <SuiteRegistration
              key={`${form.applicationId}-${form.module}-${form.suiteId}`}
              applicationId={form.applicationId}
              testType={form.module === 'perf' ? 'performance' : form.module}
              suiteId={form.suiteId}
              duration={form.duration}
              items={form.perfItems}
              expandSignal={suiteRegistrationSignal}
              onRegistered={(id, versionId) => setForm(prev => ({ ...prev, suiteId: id, suiteVersionId: versionId ?? '' }))}
            />
          </> : null}
          {form.module !== 'perf' ? <TemplatePicker value={form.imageTemplates ?? []} onChange={value => update('imageTemplates', value)} /> : null}
          <div className="form-grid two">
            <div className="field">
              <label htmlFor={fieldId('duration')}>
                采集时长（秒）{form.module !== 'ui' ? <span className="text-red"> *</span> : null}
              </label>
              <input
                id={fieldId('duration')}
                value={form.duration}
                inputMode="numeric"
                disabled={form.module === 'ui'}
                placeholder="300"
                aria-invalid={Boolean(fieldErrors.duration)}
                aria-describedby={fieldErrors.duration ? `${fieldId('duration')}-error` : undefined}
                onChange={(event) => update('duration', event.target.value)}
              />
              <div className="field-hint">
                {form.module === 'ui' ? 'UI 自动化不采集性能指标，时长不适用' : '整数，10–3600 秒'}
              </div>
              <FieldError id={`${fieldId('duration')}-error`} message={fieldErrors.duration} />
            </div>
            <div className="field">
              <span className="field-label">
                采集指标{form.module !== 'ui' ? <span className="text-red"> *</span> : null}
              </span>
              {form.module === 'ui' ? (
                <div className="muted small">不采集性能指标</div>
              ) : (
                <>
                  <div role="group" aria-label="采集指标" style={{ display: 'grid', gap: 6 }}>
                    {PERF_ITEM_OPTIONS.map((option) => (
                      <label
                        key={option.value}
                        className="small"
                        style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}
                      >
                        <input
                          type="checkbox"
                          checked={form.perfItems.includes(option.value)}
                          onChange={(event) => {
                            setForm((prev) => {
                              const current = normalizePerfItems(prev.perfItems)
                              const next = event.target.checked
                                ? [...current, option.value]
                                : current.filter((item) => item !== option.value)
                              return { ...prev, perfItems: normalizePerfItems(next) }
                            })
                          }}
                        />
                        <span>
                          {option.label}
                          <span className="muted"> · {option.description}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                  <div className="field-hint">
                    至少选一项。FPS 首次采集可能弹系统告知框；Temperature / GPU 由补采旁路自动采集。
                  </div>
                  {scenarioMismatch && selectedScenario ? (
                    <div className="field-error" role="alert">
                      当前采集配置与所选版本场景不一致（
                      {selectedScenario.duration_s !== null ? `${selectedScenario.duration_s}s · ` : ''}
                      {perfItemsLabel(selectedScenario.items) || '未记录采集项'}）。提交会被拒绝，
                      请改回版本场景或发布新版本。
                    </div>
                  ) : null}
                  <FieldError id={`${fieldId('perfItems')}-error`} message={fieldErrors.perfItems} />
                </>
              )}
              <div className="field-hint">门禁阈值由后端基线策略给出，页面不自行判定</div>
            </div>
          </div>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="form-grid">
          <Notice tone="blue" icon="clock" title="提交后进入任务中心">
            创建会同时生成首个修订（readiness = draft）。需要执行前在任务详情里通过「验证任务」切换到 validated。
          </Notice>
          <dl className="summary-dl">
            <dt>任务名称</dt>
            <dd>{form.name.trim()}</dd>
            <dt>目标端</dt>
            <dd>{TARGET_CATALOG[form.platform].label}</dd>
            <dt>测试模块</dt>
            <dd>{MODULE_NAMES[form.module]}</dd>
            <dt>应用标识</dt>
            <dd className="mono">{form.identifier.trim()}</dd>
            <dt>应用版本</dt>
            <dd className="mono">{form.appVersion.trim() || DASH}</dd>
            <dt>套件 / 场景</dt>
            <dd>{form.scenario.trim() || DASH}</dd>
            <dt>执行设备</dt>
            <dd>
              {form.platform !== 'android'
                ? '该端无执行资源'
                : (devices.find((device) => device.id === form.resourceId)?.name ?? DASH)}
            </dd>
            <dt>采集时长</dt>
            <dd>{form.module === 'ui' ? '不采集性能' : `${form.duration.trim()} 秒`}</dd>
            <dt>采集指标</dt>
            <dd>{form.module === 'ui' ? DASH : perfItemsLabel(form.perfItems) || DASH}</dd>
          </dl>

          {submitError ? (
            <Notice tone="red" title={`创建任务失败（${submitError.code}）`}>
              {submitError.message}
              {submitError.code === 'HTTP_404' || submitError.code === 'not_found' ? (
                <div className="small" style={{ marginTop: 6 }}>
                  后端 P2 任务接口可能尚未上线（404），请联系后端确认 POST /api/v1/tasks 已部署。
                </div>
              ) : null}
              {submitError.requestId ? (
                <div className="small muted" style={{ marginTop: 6 }}>
                  请求号 {submitError.requestId}
                </div>
              ) : null}
            </Notice>
          ) : null}
        </div>
      ) : null}
    </Dialog>
  )
}
