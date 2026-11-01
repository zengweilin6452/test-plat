import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 验收专用：1440×900 截图指向 HEAD 后端 :8010，不改默认 :8000 配置。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: true, ws: true },
      '/ws': { target: 'ws://127.0.0.1:8010', ws: true },
    },
  },
})
