import { displayName, validDisplayName } from '../lib/formalization'
/** 设置页：工作空间改名、关于信息、旧演示数据入口。 */
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { describeError } from '../api/client'
import { PageHeading, Panel, PanelHead } from '../components/Card'
import { Notice } from '../components/Notice'
import { BRAND, usePlatform } from '../store/platform'

export function SettingsPage() {
  const platform = usePlatform()
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<{ code: string; message: string; requestId: string | null } | null>(null)
  const [saved, setSaved] = useState(false)
  const value = draft ?? platform.workspace?.name ?? ''

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      const updated = await platform.saveWorkspace(displayName(value))
      setDraft(null)
      setSaved(true)
      // 成功后刷新共享来源，侧栏 / 面包屑 / 跨页与刷新都使用新值
      platform.refresh()
      void updated
    } catch (error) {
      // 保存失败保留输入，不显示成功，也不覆盖原工作空间名称
      const info = describeError(error)
      setSaveError({ code: info.code, message: info.message, requestId: info.requestId })
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <PageHeading title="设置" description="本机工作空间设置与产品信息" />
      <Panel>
        <PanelHead title="工作空间名称" hint="去除首尾空白，长度 1–60 字符；保存后全站与刷新后生效" />
        <div className="panel-pad">
          {platform.loading ? (
            <Notice tone="blue" title="正在加载工作空间设置">读取成功前不展示伪造的已配置名称。</Notice>
          ) : platform.error ? (
            <Notice tone="red" title="工作空间读取失败">
              {platform.error}
              {platform.errorDetail ? `（错误码 ${platform.errorDetail.code}${platform.errorDetail.requestId ? ` · 请求 ID ${platform.errorDetail.requestId}` : ''}）` : ''}
              <div><button className="link-btn" type="button" onClick={platform.refresh}>重试</button></div>
            </Notice>
          ) : (
            <form onSubmit={submit} className="form-stack">
              <label className="field">
                <span>名称</span>
                <input
                  value={value}
                  onChange={(event) => { setDraft(event.target.value); setSaved(false) }}
                  maxLength={60}
                  disabled={saving}
                  aria-label="工作空间名称"
                  autoComplete="off"
                />
              </label>
              <div className="flex">
                <button className="btn primary" type="submit" disabled={saving || !validDisplayName(value)}>
                  {saving ? '正在保存…' : '保存名称'}
                </button>
                <Link className="link-btn" to="/legacy-review">旧演示数据预览与处理</Link>
                <Link className="link-btn" to="/about">关于 TestDock</Link>
              </div>
              {saved ? <Notice tone="green" title="名称已保存">侧栏、面包屑与刷新后的页面都将使用这个名称。</Notice> : null}
              {saveError ? (
                <Notice tone="red" title={'保存失败（' + saveError.code + '）'}>
                  {saveError.message}
                  {saveError.requestId ? <div className="small muted">请求 ID：{saveError.requestId}</div> : null}
                  <div className="small muted">输入已保留，服务端设置没有变化；请修改后重试。</div>
                </Notice>
              ) : null}
            </form>
          )}
        </div>
      </Panel>
      <Panel>
        <PanelHead title="产品信息" hint={`${BRAND.name} · ${BRAND.mode}`} />
        <div className="panel-pad">
          <p>版本：{platform.capabilities?.version ?? '读取中'}</p>
          <p>提交标识：{platform.capabilities?.commit ?? '当前构建未提供，标记为不可用'}</p>
          <p>本机模式不表示登录或权限保证；继续保持回环绑定与控制面保护。</p>
        </div>
      </Panel>
    </>
  )
}
