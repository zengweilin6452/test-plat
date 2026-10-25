/**
 * 路由表。9 个页面与导航一一对应（原型 L139 顺序）。
 *
 * 使用 HashRouter（见 main.tsx）：
 * - 与原型 #overview 深链风格一致，静态托管不需要服务器 rewrite；
 * - 目标端 ?scope= 挂在 hash 内部的 query 上，刷新与分享都能还原。
 */
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppsPage } from './pages/AppsPage'
import { DatabasePage } from './pages/DatabasePage'
import { DevicesPage } from './pages/DevicesPage'
import { IntegrationPage } from './pages/IntegrationPage'
import { OverviewPage } from './pages/OverviewPage'
import { PerfPage } from './pages/PerfPage'
import { ReportsPage } from './pages/ReportsPage'
import { TasksPage } from './pages/TasksPage'
import { UiPage } from './pages/UiPage'
import { NotFoundPage } from './pages/NotFoundPage'

export const ROUTES = [
  { path: '/overview', Page: OverviewPage },
  { path: '/apps', Page: AppsPage },
  { path: '/ui', Page: UiPage },
  { path: '/perf', Page: PerfPage },
  { path: '/devices', Page: DevicesPage },
  { path: '/tasks', Page: TasksPage },
  { path: '/reports', Page: ReportsPage },
  { path: '/integration', Page: IntegrationPage },
  { path: '/database', Page: DatabasePage },
] as const

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/overview" replace />} />
      {ROUTES.map(({ path, Page }) => (
        <Route key={path} path={path} element={<Page />} />
      ))}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
