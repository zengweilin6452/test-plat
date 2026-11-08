import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, describeError } from '../api/client'
import { Button } from './Button'
import { Notice } from './Notice'
import { DEFAULT_PERF_ITEMS, normalizePerfItems, perfItemsLabel } from '../lib/perfItems'

type TestType = 'ui' | 'performance' | 'joint'
interface Build { id: string; version: string; build_key: string; identity_state: 'pending' | 'confirmed'; verification_note: string }
interface IdentityCheck {
  check_id: string; result: 'match' | 'conflict' | 'unknown'; identity_state: 'pending' | 'confirmed'
  checked_at: string; observed: Record<string, unknown>; expected: Record<string, unknown>
  blocking: { check: string; reason: string }[]; verification_note: string
}
interface Suite { id: string; created_version?: { id: string } | null }
interface Source { id: string; name: string; test_types: string[] }
interface SourceList { items: Source[]; total?: number; hint?: string | null }

/** 来源为空时的提示：来源只能由宿主预配置，页面不提供任意路径输入。 */
export function suiteSourceEmptyHint(payload: SourceList | undefined): string | null {
  if (!payload || payload.items.length > 0) return null
  const hint = (payload.hint ?? '').trim()
  if (hint) return hint
  return '未配置可信套件来源：需要宿主预配置来源后才能登记或发现套件；浏览器不能指定宿主路径。'
}

function Failure({ error }: { error: unknown }) {
  if (!error) return null
  const detail = describeError(error)
  return <div role="alert">{detail.message} ({detail.code}){detail.requestId ? ` · ${detail.requestId}` : ''}
    {detail.details != null ? <pre className="code-block">{JSON.stringify(detail.details, null, 2)}</pre> : null}</div>
}

export function canConfirmIdentity(check: IdentityCheck | null): boolean {
  return Boolean(check && check.result === 'match' && check.identity_state === 'pending' && check.blocking.length === 0)
}

/**
 * joint 版本发布体：契约要求 manifest 顶层带 ui_timeout_s（10–3600 秒，默认 600），
 * 派发时以版本快照为 UI 执行期限。2026-11-08 联动验收发现页面漏发该字段，
 * 服务端以 validation_error（joint 清单缺少 ui_timeout_s）拒绝——这里收口为纯函数并锁死形状。
 */
export function jointVersionPayload(
  scenario: Record<string, unknown>,
  sourceId: string,
  uiTimeout: string,
): Record<string, unknown> {
  return { scenario, source_id: sourceId, ui_timeout_s: Number(uiTimeout) }
}

/** 后端 blocking.reason -> 可读说明；未知原因码保留原文，不吞信息。 */
const IDENTITY_BLOCKING_TEXT: Record<string, string> = {
  version_name_mismatch: '设备上的 versionName 与构建声明的版本不一致',
  version_code_mismatch: '设备上的 versionCode 与已固定基准不一致',
  package_name_mismatch: '设备上未找到构建声明的包名',
  package_not_installed: '设备上没有安装该应用（包名与构建声明不符）',
  identity_unreadable: '读取不到安装包的版本信息（dumpsys 未返回 versionName/versionCode）',
  adb_unavailable: '无法调用 adb（adb 工具不可用），请检查设备连接后重试',
  adb_probe_failed: 'adb 读取设备失败，请重试',
  identity_read_failed: '读取设备安装身份失败，请重试',
  invalid_package_name: '构建声明的包名不是合法 Android 包名，请修正应用登记后重试',
  checker_error: '身份核对过程出错，请重试',
}

export function describeIdentityBlocking(blocking: { check: string; reason: string }[] = []): string[] {
  return blocking.map(item => IDENTITY_BLOCKING_TEXT[item.reason] ?? `${item.check}：${item.reason}`)
}

/**
 * 身份核对结果的一句话说明（工单 09：身份未学习 / 未判定必须如实显示，且给下一步）。
 * match + pending 时是「待确认」，match + confirmed 是「基准已固定」，
 * unknown 是本次读取没拿到可比对的身份（未学习），conflict 由阻断原因列表展开。
 */
export function identityCheckNote(result: IdentityCheck['result'] | null | undefined, state?: IdentityCheck['identity_state']): string | null {
  if (!result) return '尚未读取设备安装身份：选择构建与空闲设备后点「读取设备安装身份」。'
  if (result === 'unknown') return '本次未判定：没读到可比较的安装身份，请确认设备已连接并重试读取。'
  if (result === 'conflict') return '身份冲突：设备上的安装包与构建声明不一致，按下方阻断原因修正后重试。'
  return state === 'confirmed'
    ? '身份基准已固定：后续运行会按此复核，本设备不会改写基准。'
    : '身份尚未学习完成：与构建声明一致但未确认，确认后才会固定基准并用于运行前复核。'
}

/** 观测/预期字段的空值说明：读不到就写「未读取到」，不冒充有值。 */
function showValue(value: unknown, empty = '未读取到'): string {
  return value === null || value === undefined || value === '' ? empty : String(value)
}

export function BuildRegistration({ applicationId, buildId, resourceId, onRegistered }: {
  applicationId: string; buildId: string; resourceId: string; onRegistered: (id: string) => void
}) {
  const cache = useQueryClient()
  const [version, setVersion] = useState('')
  const [key, setKey] = useState('')
  const [sha, setSha] = useState('')
  const [commit, setCommit] = useState('')
  const [check, setCheck] = useState<IdentityCheck | null>(null)
  const refresh = () => cache.invalidateQueries({ queryKey: ['builds'] })
  const register = useMutation({ mutationFn: () => api.post<Build>('/builds', {
    application_id: applicationId, version: version.trim(), build_key: key.trim(),
    source_commit: commit.trim() || null, sha256: sha.trim() || null,
  }), onSuccess: (build) => { onRegistered(build.id); void refresh() } })
  const identity = useMutation({ mutationFn: () => api.post<IdentityCheck>(`/builds/${buildId}/identity-checks`, { resource_id: resourceId }),
    onMutate: () => setCheck(null), onSuccess: setCheck })
  const confirm = useMutation({ mutationFn: () => api.post<Build>(`/builds/${buildId}/confirm-identity`, { check_id: check?.check_id }),
    onSuccess: () => { setCheck(null); void refresh() } })
  const busy = register.isPending || identity.isPending || confirm.isPending
  return <details><summary>登记构建 / 核对安装身份</summary>
    <div className="form-grid">
      <label>业务版本<input value={version} onChange={e => setVersion(e.target.value)} /></label>
      <label>构建号<input value={key} onChange={e => setKey(e.target.value)} /></label>
      <label>来源提交（可选）<input value={commit} onChange={e => setCommit(e.target.value)} /></label>
      <label>APK SHA256（登记声明值，平台不校验字节）<input value={sha} onChange={e => setSha(e.target.value)} /></label>
      {sha && !/^[0-9a-f]{64}$/.test(sha.trim()) ? <div role="alert">SHA256 需为 64 位小写十六进制。</div> : null}
      <Button disabled={busy || !applicationId || !version.trim() || !key.trim() || Boolean(sha && !/^[0-9a-f]{64}$/.test(sha.trim()))} onClick={() => register.mutate()}>登记构建</Button>
      {register.isSuccess ? <p role="status">构建已登记，可在清单中选择。</p> : null}
      <p>选择构建与空闲设备后读取安装身份。只核对设备上已安装包的包名 / versionName / versionCode，不验证 APK 字节摘要；上面填写的 SHA256 仅为登记声明。</p>
      <Button disabled={busy || !buildId || !resourceId} onClick={() => identity.mutate()}>读取设备安装身份</Button>
      {check ? <div role="status"><p>{check.checked_at} · {check.result}</p>
        <p className="muted small">{identityCheckNote(check.result, check.identity_state)}</p>
        <dl className="summary-dl">
          <dt>包名</dt><dd>{showValue(check.observed.package_name)}（构建声明 {showValue(check.expected.package_name)}）</dd>
          <dt>versionName</dt><dd>{showValue(check.observed.version_name)}（构建声明 {showValue(check.expected.version_name)}）</dd>
          <dt>versionCode</dt><dd>{showValue(check.observed.version_code)}（固定基准 {showValue(check.expected.version_code, '未固定')}）</dd>
        </dl>
        {check.blocking.length ? <Notice tone="red" title="身份核对未通过，不能固定基准">
          <ul>{describeIdentityBlocking(check.blocking).map(text => <li key={text}>{text}</li>)}</ul>
          <p>请修正设备上的安装版本或改用正确的设备，然后重新点击「读取设备安装身份」。</p>
        </Notice> : null}
        {check.result === 'match' ? <p>{check.identity_state === 'pending'
          ? '与构建声明一致。确认后固定基准，运行前按此复核；未确认的构建不会被运行前复核。'
          : '与已固定基准一致，本设备不会改写基准。'}</p> : null}
        <p>{check.verification_note}</p>
        <details><summary>原始核对记录</summary><pre className="code-block">{JSON.stringify({ expected: check.expected, observed: check.observed, blocking: check.blocking }, null, 2)}</pre></details>
        <Button disabled={busy || !canConfirmIdentity(check)} onClick={() => confirm.mutate()}>确认以上身份并固定基准</Button>
      </div> : null}
      {confirm.isSuccess ? <p role="status">身份基准已固定。</p> : null}
      <Failure error={register.error || identity.error || confirm.error} />
    </div>
  </details>
}

/** 解析页面打标输入：每行 `页面名@秒`；无法解析的行原样返回（就地提示，不静默丢弃） */
function parsePageMarks(text: string): { marks: { page: string; at_s: number }[]; invalid: string[] } {
  const marks: { page: string; at_s: number }[] = []
  const invalid: string[] = []
  for (const raw of text.split('\n').map(line => line.trim()).filter(Boolean)) {
    const match = /^(.+?)@(\d+(?:\.\d+)?)$/.exec(raw)
    if (match) marks.push({ page: match[1].trim(), at_s: Number(match[2]) })
    else invalid.push(raw)
  }
  return { marks, invalid }
}

export function SuiteRegistration({ applicationId, testType, suiteId = '', duration, items, expandSignal = 0, onRegistered }: {
  applicationId: string
  testType: TestType
  suiteId?: string
  /** 向导已有采集时长/采集项时传入，避免登记的场景与修订配置不一致 */
  duration?: string
  items?: readonly string[]
  /** 父级空态「去登记」：值变化时展开并滚动到登记区 */
  expandSignal?: number
  onRegistered: (id: string, versionId?: string) => void
}) {
  const cache = useQueryClient()
  const detailsRef = useRef<HTMLDetailsElement>(null)
  const [name, setName] = useState('')
  const [source, setSource] = useState('')
  const [createdId, setCreatedId] = useState('')
  const [ownDuration, setOwnDuration] = useState('300')
  const effectiveDuration = duration ?? ownDuration
  const effectiveItems = normalizePerfItems(items ?? DEFAULT_PERF_ITEMS)
  const scenarioLabel = testType === 'performance' ? '性能场景' : '套件'
  // 能力字段（可选，缺省即不启用）：启动编排 / 网络剖面 / HAR / 逐帧 / 页面打标。
  // 注意 net_mitmdump 是宿主可执行路径，浏览器不传（spec §9.2），由运维通过
  // MOBILE_PERF_MITMDUMP 环境变量提供。
  const [startMode, setStartMode] = useState('')
  const [netProfile, setNetProfile] = useState('')
  const [netTier, setNetTier] = useState('')
  const [captureHar, setCaptureHar] = useState(false)
  const [framePoll, setFramePoll] = useState(false)
  const [pageMarksText, setPageMarksText] = useState('')
  // joint 版本的 UI 执行超时（契约必填：manifest.ui_timeout_s，10–3600，默认 600）；
  // 2026-11-08 联动验收发现页面发布载荷漏发该字段，服务端 validation_error 拒绝。
  const [uiTimeout, setUiTimeout] = useState('600')
  const parsedPageMarks = parsePageMarks(pageMarksText)

  /** 已启用的高级能力 -> scenario 可选字段（未启用的不写键，保持形状干净） */
  const capabilityScenarioFields = () => ({
    ...(startMode ? { start_mode: startMode } : {}),
    ...(netProfile ? { net_profile: netProfile } : {}),
    ...(netTier ? { net_tier: netTier } : {}),
    ...(captureHar ? { capture_har: true } : {}),
    ...(framePoll ? { frame_poll: true } : {}),
    ...(parsedPageMarks.marks.length ? { page_marks: parsedPageMarks.marks } : {}),
  })
  const capabilitySummary = () => {
    const parts: string[] = []
    if (startMode) parts.push(startMode === 'cold' ? '冷启动' : '热启动')
    if (netProfile) parts.push(`网络 ${netProfile}`)
    if (captureHar) parts.push('HAR')
    if (framePoll) parts.push('逐帧')
    if (parsedPageMarks.marks.length) parts.push(`打标 ${parsedPageMarks.marks.length} 页`)
    return parts.join(' · ')
  }

  useEffect(() => {
    if (!expandSignal) return
    if (detailsRef.current) {
      detailsRef.current.open = true
      detailsRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [expandSignal])

  const sources = useQuery({ queryKey: ['suite-sources'], queryFn: () => api.get<SourceList>('/suite-sources'), retry: false })
  const allowed = (sources.data?.items ?? []).filter(s => s.test_types.includes(testType))
  const validSource = allowed.some(s => s.id === source)
  // 空来源 / 无适用来源：只说"需要宿主配置"，不给出可填任意路径的入口
  const noSourceHint = sources.isPending || sources.error ? null : (allowed.length ? null : (suiteSourceEmptyHint(sources.data) ?? '未配置适用于该套件类型的来源，请联系管理员配置可信来源。'))
  const refresh = async () => { await cache.invalidateQueries({ queryKey: ['suites'] }); await cache.invalidateQueries({ queryKey: ['suite-versions'] }) }
  const save = useMutation({ mutationFn: async (discover: boolean) => {
    let id = discover ? suiteId : createdId
    if (!id) {
      const suite = await api.post<Suite>('/suites', { application_id: applicationId, name: name.trim(), test_type: testType, ...(testType === 'ui' ? { source_id: source } : {}) })
      id = suite.id
      setCreatedId(id)
      if (testType === 'ui') return { id, versionId: suite.created_version?.id }
    }
    const version = await api.post<{ id: string }>(`/suites/${id}/${testType === 'ui' ? 'discover' : 'versions'}`, testType === 'ui'
      ? { source_id: source }
      : (testType === 'joint'
          ? jointVersionPayload(
              { duration_s: Number(effectiveDuration), items: effectiveItems, ...capabilityScenarioFields() },
              source,
              uiTimeout,
            )
          : { scenario: { duration_s: Number(effectiveDuration), items: effectiveItems, ...capabilityScenarioFields() } }))
    return { id, versionId: version.id }
  }, onSuccess: result => { onRegistered(result.id, result.versionId); setCreatedId(''); void refresh() } })
  const capabilityValid = parsedPageMarks.invalid.length === 0
  const uiTimeoutValid = testType !== 'joint' || (/^\d+$/.test(uiTimeout) && Number(uiTimeout) >= 10 && Number(uiTimeout) <= 3600)
  const valid = (testType === 'performance' || validSource)
    && capabilityValid
    && uiTimeoutValid
    && (testType === 'ui' || (/^\d+$/.test(effectiveDuration) && Number(effectiveDuration) >= 10 && Number(effectiveDuration) <= 3600 && effectiveItems.length > 0))
  return <details ref={detailsRef}><summary>登记{scenarioLabel} / 发布固定版本</summary><div className="form-grid">
    <label>新{scenarioLabel}名称<input maxLength={200} disabled={Boolean(createdId)} value={name} onChange={e => setName(e.target.value)} /></label>
    {testType !== 'performance' ? <label>预配置代码来源<select value={source} onChange={e => setSource(e.target.value)}><option value="">请选择来源</option>{allowed.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label> : null}
    {testType !== 'performance' && noSourceHint ? <p role="status">{noSourceHint}</p> : null}
    {testType !== 'ui' ? (
      duration === undefined ? (
        <label>固定采集时长（秒，10 至 3600）<input type="number" min={10} max={3600} value={ownDuration} onChange={e => setOwnDuration(e.target.value)} />采集项：{perfItemsLabel(effectiveItems) || '未选择'}</label>
      ) : (
        <p className="muted small">将发布场景：{effectiveDuration} 秒 · {perfItemsLabel(effectiveItems) || '未选择采集项'}（与上方采集配置一致）{capabilitySummary() ? ` · ${capabilitySummary()}` : ''}</p>
      )
    ) : null}
    {testType !== 'ui' ? (
      <fieldset className="mb">
        <legend>高级能力（可选，缺省不启用）</legend>
        <div className="form-grid">
          <label>启动编排<select value={startMode} onChange={e => setStartMode(e.target.value)}>
            <option value="">不编排启动</option>
            <option value="cold">冷启动（force-stop 后拉起并计时）</option>
            <option value="warm">热启动（退后台后拉起并计时）</option>
          </select></label>
          <label>网络档位<select value={netProfile} onChange={e => setNetProfile(e.target.value)}>
            <option value="">不动网络</option>
            <option value="none">none（代理直通对照）</option>
            <option value="4g">4G</option>
            <option value="3g">3G</option>
            <option value="weak">弱网</option>
          </select></label>
          <label>代理模式<select value={netTier} onChange={e => setNetTier(e.target.value)}>
            <option value="">自动（抓 HAR 用解密，其余直通）</option>
            <option value="passthrough">passthrough（不解密）</option>
            <option value="decrypt">decrypt（需设备信任代理 CA）</option>
          </select></label>
          {testType === 'joint' ? (
            <label>UI 执行超时（秒，10–3600，默认 600）<input
              type="number"
              min={10}
              max={3600}
              value={uiTimeout}
              onChange={e => setUiTimeout(e.target.value)}
            />
              <span className="field-hint">锁定该版本的 UI 部分执行期限，派发时以此为准</span>
            </label>
          ) : null}
          <label className="muted small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={captureHar} onChange={e => setCaptureHar(e.target.checked)} />
            抓取 HAR 文件（需宿主安装 mitmproxy，未安装时如实标注未判定）
          </label>
          <label className="muted small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={framePoll} onChange={e => setFramePoll(e.target.checked)} />
            逐帧统计（P50 / P90 / P99 帧耗时与卡顿帧占比）
          </label>
          <label>页面打标（每行一条：页面名@秒，如 home@5）<textarea
            rows={3}
            value={pageMarksText}
            onChange={e => setPageMarksText(e.target.value)}
            placeholder={'home@5\ndetail@20'}
          />
            {parsedPageMarks.invalid.length > 0 ? <span className="field-error" role="alert">无法解析：{parsedPageMarks.invalid.join('；')}（格式 页面名@秒）</span> : null}
          </label>
        </div>
      </fieldset>
    ) : null}
    <Button disabled={save.isPending || !applicationId || !name.trim() || !valid} onClick={() => save.mutate(false)}>{createdId ? '重试发布已登记套件的版本' : `登记${scenarioLabel}并发布版本`}</Button>
    <Button disabled={save.isPending || !suiteId || !valid} onClick={() => save.mutate(true)}>{testType === 'ui' ? '为所选套件重新发现并发布版本' : `为所选${scenarioLabel}发布版本`}</Button>
    {save.isSuccess ? <p role="status">版本已发布，可在清单中选择。</p> : null}
    <Failure error={sources.error || save.error} />
  </div></details>
}
