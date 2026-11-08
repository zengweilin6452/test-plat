// 07 号工单 Windows 交互与可访问性证据采集（headless Edge + CDP）。
// 产出：evidence/screenshots/*.png + evidence/win-interactions.json
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
const __dirname = path.dirname(fileURLToPath(import.meta.url))

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = 'http://127.0.0.1:5173'
const OUT = path.join(__dirname, 'evidence')
const SHOTS = path.join(OUT, 'screenshots')
fs.mkdirSync(SHOTS, { recursive: true })
const profile = path.join(__dirname, '.edge-profile')
fs.rmSync(profile, { recursive: true, force: true })

const results = { env: {}, pages: {}, keyboard: null, forcedColors: null, dark: null, longName: null }

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = ''
      res.on('data', (c) => (data += c))
      res.on('end', () => { try { resolve(JSON.parse(data)) } catch (e) { reject(e) } })
    }).on('error', reject)
  })
}

async function main() {
  const proc = spawn(EDGE, [
    '--headless=new', '--remote-debugging-port=9333',
    `--user-data-dir=${profile}`, '--no-first-run', '--window-size=1440,900',
    'about:blank',
  ], { stdio: 'ignore' })
  try {
    let target = null
    for (let i = 0; i < 40; i++) {
      try {
        const list = await getJson('http://127.0.0.1:9333/json/list')
        target = list.find((t) => t.type === 'page')
        if (target) break
      } catch {}
      await new Promise((r) => setTimeout(r, 250))
    }
    if (!target) throw new Error('no CDP page target')
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
      const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
      if (r.result?.exceptionDetails) throw new Error('page eval failed: ' + JSON.stringify(r.result.exceptionDetails).slice(0, 300))
      return r.result?.result?.value
    }
    const shot = async (name) => {
      const r = await send('Page.captureScreenshot', { format: 'png' })
      fs.writeFileSync(path.join(SHOTS, name), Buffer.from(r.result.data, 'base64'))
    }
    const goto = async (hash) => {
      await send('Page.navigate', { url: BASE + '/#' + hash })
      await new Promise((r) => setTimeout(r, 1600))
    }
    const metrics = () => evaljs(`(() => {
      const de = document.documentElement, b = document.body
      const overflow = [...document.querySelectorAll('*')].filter(e => {
        const r = e.getBoundingClientRect()
        return r.right > innerWidth + 1 && r.width > 0
      }).length
      return JSON.stringify({ iw: innerWidth, ih: innerHeight, scrollW: Math.max(de.scrollWidth, b.scrollWidth), overflowElems: overflow })
    })()`)

    // 环境信息
    results.env = await evaljs(`JSON.stringify({ ua: navigator.userAgent, dpr: devicePixelRatio, platform: navigator.platform })`).then(JSON.parse)
    const ver = await send('Browser.getVersion')
    results.env.browser = ver.result.product

    // 100% 缩放：三页布局指标 + 截图
    for (const [name, hash] of [['apps', '/apps'], ['tasks', '/tasks'], ['reports', '/reports']]) {
      await goto(hash)
      results.pages[name + '_100'] = JSON.parse(await metrics())
      await shot(`${name}-100.png`)
    }
    // 125% 缩放
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1.25, mobile: false })
    await goto('/apps')
    await new Promise((r) => setTimeout(r, 600))
    results.pages.apps_125 = JSON.parse(await metrics())
    await shot('apps-125.png')
    await send('Emulation.clearDeviceMetricsOverride')

    // 窗口调整：1024×700
    await send('Emulation.setDeviceMetricsOverride', { width: 1024, height: 700, deviceScaleFactor: 1, mobile: false })
    await goto('/apps')
    await new Promise((r) => setTimeout(r, 600))
    results.pages.apps_1024 = JSON.parse(await metrics())
    await shot('apps-1024.png')
    await send('Emulation.clearDeviceMetricsOverride')

    // 键盘焦点：真实 Tab 键 → :focus-visible 与 outline
    await goto('/overview')
    await send('Runtime.evaluate', { expression: 'document.activeElement && document.activeElement.blur()' })
    for (let i = 0; i < 3; i++) {
      await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 })
      await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 })
      await new Promise((r) => setTimeout(r, 120))
    }
    results.keyboard = JSON.parse(await evaljs(`(() => {
      const el = document.activeElement
      const s = getComputedStyle(el)
      return JSON.stringify({ tag: el.tagName, text: (el.textContent || el.ariaLabel || '').trim().slice(0, 24), matchesFocusVisible: el.matches(':focus-visible'), outline: s.outlineStyle + '/' + s.outlineWidth + '/' + s.outlineColor })
    })()`))
    await shot('keyboard-focus.png')

    // 长名称行布局：动作按钮是否在行内可见可达
    results.longName = JSON.parse(await evaljs(`(() => {
      const rows = [...document.querySelectorAll('tr')].filter(r => r.textContent.includes('LONGLABEL'))
      if (!rows.length) return JSON.stringify({ found: false })
      const row = rows[0]
      const btns = [...row.querySelectorAll('button')]
      const rr = row.getBoundingClientRect()
      return JSON.stringify({ found: true, rowWidth: Math.round(rr.width), btnCount: btns.length, allVisible: btns.every(b => { const r = b.getBoundingClientRect(); return r.width > 0 && r.right <= innerWidth + 1 }) })
    })()`))

    // 高对比度（forced-colors）
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'forced-colors', value: 'active' }] })
    await goto('/overview')
    await new Promise((r) => setTimeout(r, 600))
    results.forcedColors = JSON.parse(await evaljs(`(() => {
      const link = document.querySelector('a')
      link.focus()
      const s = getComputedStyle(link)
      const btn = [...document.querySelectorAll('button')][0]
      const bs = getComputedStyle(btn)
      return JSON.stringify({ linkOutline: s.outlineStyle + '/' + s.outlineWidth + '/' + s.outlineColor, btnBorder: bs.borderTopWidth + '/' + bs.borderTopColor, matchesFV: link.matches(':focus-visible') })
    })()`))
    await shot('forced-colors.png')
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'forced-colors', value: 'none' }] })

    // 深色
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] })
    await goto('/overview')
    await new Promise((r) => setTimeout(r, 600))
    results.dark = JSON.parse(await evaljs(`(() => {
      const s = getComputedStyle(document.body)
      return JSON.stringify({ bodyBg: s.backgroundColor, bodyColor: s.color })
    })()`))
    await shot('dark-scheme.png')
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }] })

    ws.close()
    fs.writeFileSync(path.join(OUT, 'win-interactions.json'), JSON.stringify(results, null, 2))
    console.log(JSON.stringify(results, null, 2))
  } finally {
    proc.kill()
  }
}

main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
