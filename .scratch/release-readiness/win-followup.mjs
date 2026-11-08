import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
const __dirname = path.dirname(fileURLToPath(import.meta.url))

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = 'http://127.0.0.1:5173'
const SHOTS = path.join(__dirname, 'evidence', 'screenshots')
const profile = path.join(__dirname, '.edge-profile2')
fs.rmSync(profile, { recursive: true, force: true })

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = ''
      res.on('data', (c) => (data += c))
      res.on('end', () => { try { resolve(JSON.parse(data)) } catch (e) { reject(e) } })
    }).on('error', reject)
  })
}

const proc = spawn(EDGE, [
  '--headless=new', '--remote-debugging-port=9334',
  `--user-data-dir=${profile}`, '--no-first-run', '--window-size=1024,700',
  'about:blank',
], { stdio: 'ignore' })

try {
  let target = null
  for (let i = 0; i < 40; i++) {
    try {
      const list = await getJson('http://127.0.0.1:9334/json/list')
      target = list.find((t) => t.type === 'page')
      if (target) break
    } catch {}
    await new Promise((r) => setTimeout(r, 250))
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
  let seq = 0
  const pending = new Map()
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
  }
  const send = (method, params = {}) => new Promise((res) => {
    const id = ++seq
    pending.set(id, res)
    ws.send(JSON.stringify({ id, method, params }))
  })
  const evaljs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true })
    return r.result?.result?.value
  }
  await send('Page.navigate', { url: BASE + '/#/apps' })
  await new Promise((r) => setTimeout(r, 2000))
  const overflow = await evaljs(`(() => {
    const bad = [...document.querySelectorAll('*')].filter(e => {
      const r = e.getBoundingClientRect()
      return r.right > innerWidth + 1 && r.width > 0
    }).slice(0, 8).map(e => ({ tag: e.tagName, cls: (e.className || '').toString().slice(0, 40), text: (e.textContent || '').trim().slice(0, 40), right: Math.round(e.getBoundingClientRect().right) }))
    const longRow = [...document.querySelectorAll('tr')].map(r => r.textContent.trim().slice(0, 60)).filter(t => t.includes('长显示') || t.includes('LONGLABEL'))
    const projRows = [...document.querySelectorAll('tr')].length
    return JSON.stringify({ bad, longRow, projRows, bodySample: document.body.innerText.slice(0, 200) })
  })()`)
  console.log(overflow)
  const r = await send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(path.join(SHOTS, 'apps-1024-debug.png'), Buffer.from(r.result.data, 'base64'))
  ws.close()
} finally {
  proc.kill()
}
