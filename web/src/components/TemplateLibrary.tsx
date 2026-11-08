import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, describeError } from '../api/client'
import { Button } from './Button'
import { Empty } from './Empty'
import { Notice } from './Notice'

export interface TemplatePin { logical: string; version_id: string; sha256: string }
interface LibraryVersion {
  logical: string; version_id: string; image_sha256: string; current: boolean
  width?: number; height?: number; source_width?: number; source_height?: number
  capture_time?: string
}

function useLibrary() {
  return useQuery({ queryKey: ['template-library'], queryFn: ({ signal }) =>
    api.get<{ templates: LibraryVersion[] }>('/template-library', undefined, signal), retry: false })
}

export function TemplatePicker({ value, onChange }: { value: TemplatePin[]; onChange: (pins: TemplatePin[]) => void }) {
  const query = useLibrary()
  const current = (query.data?.templates ?? []).filter((item) => item.current)
  return <fieldset className="mb"><legend>固定图像模板（可选）</legend>
    {query.isError ? <Notice tone="amber">模板库读取失败：{describeError(query.error).message}</Notice> : null}
    {query.isLoading ? <Empty loading title="正在读取模板库" description="正在请求已登记的图像模板…" /> : null}
    {!query.isLoading && !query.isError && !current.length ? <p className="muted small">模板库为空，可先在设备调试中登记。</p> : null}
    {current.map((item) => <label key={item.logical} style={{ display: 'block' }}>
      <input type="checkbox" checked={value.some((pin) => pin.logical === item.logical)} onChange={(event) =>
        onChange(event.target.checked ? [...value.filter((pin) => pin.logical !== item.logical),
          { logical: item.logical, version_id: item.version_id, sha256: item.image_sha256 }]
          : value.filter((pin) => pin.logical !== item.logical))} /> {item.logical} · {item.version_id.slice(0, 8)}
    </label>)}
    <p className="muted small">选择后固定当前版本和摘要；执行前版本变化会阻断运行，请重新绑定后验证。</p>
  </fieldset>
}

export function TemplateLibrary() {
  const query = useLibrary()
  const [search, setSearch] = useState('')
  const [history, setHistory] = useState(false)
  const [copyMessage, setCopyMessage] = useState('')
  const items = (query.data?.templates ?? []).filter((item) => (history || item.current) && item.logical.toLowerCase().includes(search.trim().toLowerCase()))
  return <div className="panel-pad">
    <div className="toolbar">
      <label>搜索模板 <input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <label><input type="checkbox" checked={history} onChange={(event) => setHistory(event.target.checked)} /> 显示历史版本</label>
      <Button onClick={() => void query.refetch()} disabled={query.isFetching}>刷新模板库</Button>
    </div>
    <p className="muted small mb">模板跨调试会话保留。新建或重新匹配模板请进入设备调试；查看和复制表达式不锁定版本。</p>
    {query.isError ? <Notice tone="red">模板库读取失败：{describeError(query.error).message}</Notice> : null}
    {query.isLoading ? <Empty loading title="正在读取模板库" description="正在请求已登记的图像模板…" /> : !query.isError && !items.length ? <Empty icon="layers" title="没有匹配的模板" description="可在设备调试中冻结画面并保存图像模板。" /> : null}
    <div className="table-wrap"><table className="task-table"><thead><tr><th>逻辑名</th><th>版本</th><th>模板 / 来源尺寸</th><th>摘要</th><th>操作</th></tr></thead>
      <tbody>{items.map((item) => <tr key={item.version_id}>
        <td>{item.logical}</td><td>{item.current ? '当前' : '历史'} · {item.version_id}</td>
        <td>{item.width ?? '—'} × {item.height ?? '—'} / {item.source_width ?? '—'} × {item.source_height ?? '—'}</td>
        <td style={{ overflowWrap: 'anywhere' }}>{item.image_sha256}</td>
        <td><Button size="small" onClick={async () => {
          try { await navigator.clipboard.writeText(`Target(Locator.IMAGE, ${JSON.stringify(item.logical)})`); setCopyMessage('已复制表达式，匹配时按逻辑名读取当前版本') }
          catch { setCopyMessage('复制失败，请手动复制逻辑名：' + item.logical) }
        }}>复制表达式</Button></td>
      </tr>)}</tbody></table></div>
    <p role="status">{copyMessage}</p>
  </div>
}
