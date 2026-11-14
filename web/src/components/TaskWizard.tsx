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
 * - 读接口失败时只显示 Notice + 错误码，不伪造成功、不关窗。
 */
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { describeError } from '../api/client'
import type { SuiteVersionRecord } from '../api/types'
import {
  createTask,
  fetchApplications,
  fetchBuilds,
  fetchResources,
  fetchSuiteVersions,
  fetchSuites,
} from '../api/endpoints'
import { useEffectiveContext } from '../store/effectiveContext'
import { normalizePerfItems } from '../lib/perfItems'
import type { CreateTaskRequest, CreateTaskResponse, Platform, TestModule } from '../types'
import { Button } from './Button'
import { Dialog } from './Dialog'
import {
  STEP_LABELS,
  buildCreateTaskRequest,
  INITIAL_FORM,
  newRequestKey,
  scenarioOfVersion,
  validateStep,
  validateStep1,
  validateStep2,
  type WizardErrors,
  type WizardForm,
} from './wizard/wizardModel'
import { WizardStep1, WizardStep2, WizardStep3 } from './wizard/wizardSteps'

// P2-03：模型与校验在 wizard/wizardModel.ts、步骤视图在 wizard/wizardSteps.tsx。
// 这里再导出全部公开名，既有消费方（TaskDrawer / AppsPage / PerfPage / 用例）
// 的导入路径不需要任何变化。
export {
  DURATION_MAX,
  DURATION_MIN,
  INITIAL_FORM,
  NAME_MAX,
  PACKAGE_MAX,
  PACKAGE_PATTERN,
  buildCreateTaskRequest,
  isDeviceSelectable,
  isValidSiteUrl,
  newRequestKey,
  scenarioOfVersion,
  scenarioSummary,
  validateStep,
  validateStep1,
  validateStep2,
} from './wizard/wizardModel'
export type { WizardErrors, WizardForm } from './wizard/wizardModel'


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
  const ctx = useEffectiveContext()
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
    queryKey: ['applications', 'wizard', ctx.projectId],
    queryFn: ({ signal }) => fetchApplications(signal, { project_id: ctx.projectId }),
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
    queryKey: ['suites', 'wizard', form.module, ctx.projectId],
    queryFn: ({ signal }) =>
      fetchSuites(form.module === 'perf' ? 'performance' : form.module, signal, ctx.projectId),
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
    queryKey: ['resources', 'wizard', ctx.projectId],
    queryFn: ({ signal }) => fetchResources('android', signal, ctx.projectId),
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
    if (touched) {
      // 已交互：展示该步的显式校验结果（含空值提示）
      const merged: WizardErrors = { ...live, ...errors }
      for (const key of Object.keys(merged) as (keyof WizardForm)[]) {
        if (!live[key]) delete merged[key]
      }
      return merged
    }
    // 未交互时不因必填项为空就报红（渐进式披露：错误就地提示，但等用户动手后）；
    // 格式确实非法的（如已填但包名不合法）仍然提示。
    const filtered: WizardErrors = {}
    for (const key of Object.keys(live) as (keyof WizardForm)[]) {
      const value = form[key]
      const isEmpty =
        typeof value === 'string'
          ? value.trim() === ''
          : Array.isArray(value)
            ? value.length === 0
            : value == null
      if (!isEmpty && live[key]) filtered[key] = live[key]
    }
    return filtered
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
        <WizardStep1
          form={form}
          fieldId={fieldId}
          fieldErrors={fieldErrors}
          update={update}
          setForm={setForm}
          setErrors={setErrors}
          applications={applications}
          applicationsLoading={applicationsQuery.isLoading}
          applicationsError={applicationsError}
        />
      ) : null}

      {step === 2 ? (
        <WizardStep2
          form={form}
          fieldId={fieldId}
          fieldErrors={fieldErrors}
          update={update}
          setForm={setForm}
          devices={devices}
          resourcesLoading={resourcesQuery.isLoading}
          resourcesError={resourcesError}
          builds={buildsQuery.data?.items ?? []}
          buildsError={Boolean(buildsQuery.isError)}
          suites={suites}
          suitesError={Boolean(suitesQuery.isError)}
          suitesPending={suitesQuery.isPending}
          suiteVersions={suiteVersions}
          suiteVersionsError={Boolean(suiteVersionsQuery.isError)}
          setSuiteRegistrationSignal={setSuiteRegistrationSignal}
          suiteRegistrationSignal={suiteRegistrationSignal}
          scenarioMismatch={scenarioMismatch}
          selectedScenario={selectedScenario}
        />
      ) : null}

      {step === 3 ? (
        <WizardStep3 form={form} devices={devices} submitError={submitError} />
      ) : null}
    </Dialog>
  )
}
