import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { EffectiveContextProvider } from './store/effectiveContext'
import { PlatformProvider } from './store/platform'
import './styles/tokens.css'

/**
 * 路由使用 HashRouter：与 #/overview 深链风格一致，静态托管无需服务器 rewrite。
 * 工作空间/能力与有效上下文由 Provider 统一提供，页面不再独立猜测默认项目。
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <PlatformProvider>
          <EffectiveContextProvider>
            <App />
          </EffectiveContextProvider>
        </PlatformProvider>
      </HashRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
