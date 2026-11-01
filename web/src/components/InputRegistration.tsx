import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, describeError } from '../api/client'
import { Button } from './Button'
import { Notice } from './Notice'

type TestType = 'ui' | 'performance' | 'joint'
interface Build { id: string; version: string; build_key: string; identity_state: 'pending' | 'confirmed'; verification_note: string }
interface IdentityCheck {
  check_id: string; result: 'match' | 'conflict' | 'unknown'; identity_state: 'pending' | 'confirmed'
  checked_at: string; observed: Record<string, unknown>; expected: Record<string, unknown>
  blocking: { check: string; reason: string }[]; verification_note: string
}
interface Suite { id: string; created_version?: { id: string } | null }
interface Source { id: string; name: string; test_types: string[] }

function Failure({ error }: { error: unknown }) {
  if (!error) return null
  const detail = describeError(error)
  return <div role="alert">{detail.message} ({detail.code}){detail.requestId ? ` · ${detail.requestId}` : ''}
    {detail.details != null ? <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(detail.details, null, 2)}</pre> : null}</div>
}

export function canConfirmIdentity(check: IdentityCheck | null): boolean {
  return Boolean(check && check.result === 'match' && check.identity_state === 'pending' && check.blocking.length === 0)
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
        <details><summary>原始核对记录</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify({ expected: check.expected, observed: check.observed, blocking: check.blocking }, null, 2)}</pre></details>
        <Button disabled={busy || !canConfirmIdentity(check)} onClick={() => confirm.mutate()}>确认以上身份并固定基准</Button>
      </div> : null}
      {confirm.isSuccess ? <p role="status">身份基准已固定。</p> : null}
      <Failure error={register.error || identity.error || confirm.error} />
    </div>
  </details>
}

export function SuiteRegistration({ applicationId, testType, suiteId = '', onRegistered }: {
  applicationId: string; testType: TestType; suiteId?: string; onRegistered: (id: string, versionId?: string) => void
}) {
  const cache = useQueryClient()
  const [name, setName] = useState('')
  const [source, setSource] = useState('')
  const [createdId, setCreatedId] = useState('')
  const [duration, setDuration] = useState('300')
  const sources = useQuery({ queryKey: ['suite-sources'], queryFn: () => api.get<{ items: Source[] }>('/suite-sources'), retry: false })
  const allowed = (sources.data?.items ?? []).filter(s => s.test_types.includes(testType))
  const validSource = allowed.some(s => s.id === source)
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
      : { scenario: { duration_s: Number(duration), items: ['CPU', 'Memory', 'FPS'] }, ...(testType === 'joint' ? { source_id: source } : {}) })
    return { id, versionId: version.id }
  }, onSuccess: result => { onRegistered(result.id, result.versionId); setCreatedId(''); void refresh() } })
  const valid = (testType === 'performance' || validSource) && (testType === 'ui' || (/^\d+$/.test(duration) && Number(duration) >= 10 && Number(duration) <= 3600))
  return <details><summary>登记套件 / 发布固定版本</summary><div className="form-grid">
    <label>新套件名称<input maxLength={200} disabled={Boolean(createdId)} value={name} onChange={e => setName(e.target.value)} /></label>
    {testType !== 'performance' ? <label>预配置代码来源<select value={source} onChange={e => setSource(e.target.value)}><option value="">请选择来源</option>{allowed.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label> : null}
    {testType !== 'performance' && !sources.isPending && !sources.error && !allowed.length ? <p>未配置适用来源，请联系管理员配置可信来源。</p> : null}
    {testType !== 'ui' ? <label>固定采集时长（秒，10 至 3600）<input type="number" min={10} max={3600} value={duration} onChange={e => setDuration(e.target.value)} />CPU / Memory / FPS</label> : null}
    <Button disabled={save.isPending || !applicationId || !name.trim() || !valid} onClick={() => save.mutate(false)}>{createdId ? '重试发布已登记套件的版本' : '登记套件并发布版本'}</Button>
    <Button disabled={save.isPending || !suiteId || !valid} onClick={() => save.mutate(true)}>{testType === 'ui' ? '为所选套件重新发现并发布版本' : '为所选套件发布版本'}</Button>
    {save.isSuccess ? <p role="status">版本已发布，可在清单中选择。</p> : null}
    <Failure error={sources.error || save.error} />
  </div></details>
}
