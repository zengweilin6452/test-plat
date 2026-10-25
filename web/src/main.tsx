import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './styles/tokens.css'

/**
 * 路由使用 HashRouter：
 * - 与原型 #overview 的深链风格一致，静态托管无需服务器 rewrite；
 * - 目标端选择器持久化在 hash 内的 query（形如 #/tasks?scope=android），
 *   刷新、复制链接、前进后退都能还原（实现见 src/store/scope.ts）。
 */
const queryClient = new QueryClient({
  defaultOptions: {
    // 骨架阶段：接口未接入时快速失败并展示空态，不做长时间重试
    queries: { retry: false, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <App />
      </HashRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
