/**
 * 新建任务向导的三个步骤视图（自 TaskWizard.tsx 迁入，P2-03 分层）。
 *
 * 只做展示与受控交互：所有状态（form / errors / 查询数据 / 登记信号）都由
 * TaskWizard 持有并经 props 传入，本文件不发起请求、不持有状态 —— JSX 逐字
 * 迁移，仅把 query 对象引用换成视图 props，行为与迁移前完全一致。
 */
import type { Dispatch, SetStateAction } from 'react'
import { MODULE_NAMES, TARGET_CATALOG } from '../../constants'
import { DASH } from '../../lib/fmt'
import { PERF_ITEM_OPTIONS, normalizePerfItems, perfItemsLabel } from '../../lib/perfItems'
import type { ApplicationRecord, BuildRecord } from '../../types'
import type { SuiteRecord, SuiteVersionRecord } from '../../api/types'
import { Disclosure } from '../Disclosure'
import { Notice } from '../Notice'
import { BuildRegistration, SuiteRegistration } from '../InputRegistration'
import { TemplatePicker } from '../TemplateLibrary'
import { MODULES, NAME_MAX, PACKAGE_MAX, PLATFORMS } from './wizardModel'
import { isDeviceSelectable, scenarioSummary } from './wizardModel'
import type { WizardErrors, WizardForm } from './wizardModel'

/** 字段下方错误提示：容器 role="alert"，符合「错误提示在字段下方且容器 role=alert」的验收要求 */
function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (!message) return null
  return (
    <div className="field-error" id={id} role="alert">
      {message}
    </div>
  )
}

export function WizardStep1({
  form,
  fieldId,
  fieldErrors,
  update,
  setForm,
  setErrors,
  applications,
  applicationsLoading,
  applicationsError,
}: {
  form: WizardForm
  fieldId: (name: keyof WizardForm) => string
  fieldErrors: WizardErrors
  update: <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => void
  setForm: Dispatch<SetStateAction<WizardForm>>
  setErrors: Dispatch<SetStateAction<WizardErrors>>
  applications: ApplicationRecord[]
  applicationsLoading: boolean
  applicationsError: { code: string; message: string } | null
}) {
  return (
          <div className="form-grid">
            <div className="field">
              <span className="field-label">目标端</span>
              {/* 渐进式披露：选择项压缩为一行 chips（规则 1），行为与原大卡一致 */}
              <div className="choice-row">
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
              <div className="choice-row">
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
                disabled={applicationsLoading}
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
              {!applicationsLoading && !applicationsError && applications.length === 0
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

            {/* 渐进式披露：两个可留空的次级字段默认收起，摘要显示已填项数（规则 3/4） */}
            <Disclosure
              title="高级配置（可选）"
              summary={`已填 ${(form.appVersion.trim() ? 1 : 0) + (form.scenario.trim() ? 1 : 0)} 项`}
            >
              <div className="form-grid two">
                <div className="field">
                  <label htmlFor={fieldId('appVersion')}>应用版本</label>
                  <input
                    id={fieldId('appVersion')}
                    value={form.appVersion}
                    maxLength={40}
                    placeholder="例如 3.8.0-rc.2（示例不会自动提交）"
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
                  <div className="field-hint">请选择可信来源登记套件；自由填写的场景名称不会自动成为套件版本。</div>
                </div>
              </div>
            </Disclosure>
          </div>
  )
}

export function WizardStep2({
  form,
  fieldId,
  fieldErrors,
  update,
  setForm,
  devices,
  resourcesLoading,
  resourcesError,
  builds,
  buildsError,
  suites,
  suitesError,
  suitesPending,
  suiteVersions,
  suiteVersionsError,
  setSuiteRegistrationSignal,
  suiteRegistrationSignal,
  scenarioMismatch,
  selectedScenario,
}: {
  form: WizardForm
  fieldId: (name: keyof WizardForm) => string
  fieldErrors: WizardErrors
  update: <K extends keyof WizardForm>(key: K, value: WizardForm[K]) => void
  setForm: Dispatch<SetStateAction<WizardForm>>
  devices: import('../../types').ResourceRecord[]
  resourcesLoading: boolean
  resourcesError: { code: string; message: string } | null
  builds: BuildRecord[]
  buildsError: boolean
  suites: SuiteRecord[]
  suitesError: boolean
  suitesPending: boolean
  suiteVersions: SuiteVersionRecord[]
  suiteVersionsError: boolean
  setSuiteRegistrationSignal: Dispatch<SetStateAction<number>>
  suiteRegistrationSignal: number
  scenarioMismatch: boolean
  selectedScenario: { duration_s: number | null; items: string[] } | null
}) {
  return (
          <div className="form-grid">
            {form.platform === 'android' ? (
              <div className="field">
                <span className="field-label">执行设备</span>
                {resourcesError ? (
                  <Notice tone="red" title={`设备列表获取失败（${resourcesError.code}）`}>
                    {resourcesError.message}
                  </Notice>
                ) : null}
                {resourcesLoading ? (
                  <div className="muted small">正在请求 /api/v1/resources</div>
                ) : devices.length === 0 && !resourcesError ? (
                  <div className="muted small">当前没有登记在册的 Android 设备。</div>
                ) : (
                  <div className="choice-grid device-list">
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
                    {builds.map((build) => (
                      <option key={build.id} value={build.id}>
                        {build.version}（{build.build_key}）
                      </option>
                    ))}
                  </select>
                  <div className="field-hint">
                    {buildsError
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
                    {suitesError || suiteVersionsError
                      ? '套件清单获取失败：请先在套件来源登记套件版本。'
                      : form.module === 'perf'
                        ? '性能场景版本锁定采集时长与采集项，不执行 UI 用例，也不需要固定代码副本。'
                        : form.module === 'joint'
                          ? '联动版本包含 UI 用例、固定代码副本和性能采集项。'
                          : '验证要求套件版本带用例与固定代码副本。'}
                  </div>
                  {form.module === 'perf'
                  && form.applicationId
                  && !suitesPending
                  && !suitesError
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
            {form.module !== 'perf' ? (
              <Disclosure
                title="固定图像模板（可选）"
                summary={(form.imageTemplates?.length ?? 0) > 0 ? `已选 ${form.imageTemplates!.length} 个` : '未选择'}
              >
                <TemplatePicker value={form.imageTemplates ?? []} onChange={value => update('imageTemplates', value)} />
              </Disclosure>
            ) : null}
            {form.module !== 'ui' ? (
            <div className="form-grid two">
              <div className="field">
                <label htmlFor={fieldId('duration')}>
                  采集时长（秒）<span className="text-red"> *</span>
                </label>
                <input
                  id={fieldId('duration')}
                  value={form.duration}
                  inputMode="numeric"
                  placeholder="300"
                  aria-invalid={Boolean(fieldErrors.duration)}
                  aria-describedby={fieldErrors.duration ? `${fieldId('duration')}-error` : undefined}
                  onChange={(event) => update('duration', event.target.value)}
                />
                <div className="field-hint">整数，10–3600 秒</div>
                <FieldError id={`${fieldId('duration')}-error`} message={fieldErrors.duration} />
              </div>
              <div className="field">
                <span className="field-label">
                  采集指标<span className="text-red"> *</span>
                </span>
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
                <div className="field-hint">门禁阈值由后端基线策略给出，页面不自行判定</div>
              </div>
            </div>
            ) : null}
          </div>
  )
}

export function WizardStep3({
  form,
  devices,
  submitError,
}: {
  form: WizardForm
  devices: import('../../types').ResourceRecord[]
  submitError: { code: string; message: string; requestId: string | null } | null
}) {
  return (
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
                    任务接口返回 404：请确认后端已升级、迁移已执行，且 POST /api/v1/tasks 可访问。
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
  )
}
