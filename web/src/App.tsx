/**
 * 应用根组件：外壳（侧栏 + 顶栏）+ 路由出口。
 * 数据 Provider（QueryClientProvider）在 main.tsx 里提供。
 */
import { AppShell } from './components/layout/AppShell'
import { AppRoutes } from './routes'

export default function App() {
  return (
    <AppShell>
      <AppRoutes />
    </AppShell>
  )
}
