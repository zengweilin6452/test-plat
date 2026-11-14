import { defineConfig, loadEnv } from 'vite'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'

// 启动 / 代理 / 健康检查共用 env 配置。dev_up.ps1 负责注入同一组端口；
// 单独运行 `npm run dev` 时读默认值即可。含空格的安装目录由 vite 原生支持。
const rootEnv = loadEnv('', fileURLToPath(new URL('..', import.meta.url)), 'TESTDOCK_')
const env = { ...rootEnv, ...process.env }
const host = env.TESTDOCK_HOST || '127.0.0.1'
const webHost = env.TESTDOCK_WEB_HOST || '127.0.0.1'
const apiPort = Number(env.TESTDOCK_PORT || env.TESTDOCK_API_PORT || 8000)
const webPort = Number(env.TESTDOCK_WEB_PORT || 5173)

// 回环约束（P1-03）：首期服务没有登录认证，Web 与其代理的 API 都只能绑定回环。
// 与 server/app/config.py 的 LOOPBACK_HOSTS 同一份名单 —— 任何一侧放开都必须先
// 设计身份认证、Origin 校验与 CSRF 防护，而不是改这一行。
const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1'])
function assertLoopback(envName: string, value: string): void {
  const normalized = value.trim().toLowerCase().replace(/^\[|\]$/g, '')
  if (!LOOPBACK_HOSTS.has(normalized)) {
    throw new Error(
      `${envName}=${value} 不是回环地址。首期服务没有登录认证，` +
        '只允许绑定 127.0.0.1 / localhost / ::1；如需局域网访问，' +
        '必须先设计身份认证、Origin 校验与 CSRF 防护，不能仅开放 Host。',
    )
  }
}
assertLoopback('TESTDOCK_WEB_HOST', webHost)
assertLoopback('TESTDOCK_HOST', host)

const apiTarget = `http://${host}:${apiPort}`
const wsTarget = `ws://${host}:${apiPort}`

export default defineConfig({
  plugins: [react()],
  server: {
    host: webHost,
    port: webPort,
    strictPort: true, // 端口占用明确失败，不静默换端口
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
      '/ws': { target: wsTarget, ws: true },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
})
