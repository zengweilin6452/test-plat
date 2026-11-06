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
