import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { fetchOnboardingStatus } from './api/endpoints'
import { onboardingDestination, onboardingSkipped } from './lib/formalization'
/**
 * 路由表：正式产品页面 + 旧帮助/数据设计深链接兼容。
 */
import { Navigate, Route, Routes } from 'react-router-dom'
import { AboutPage } from './pages/AboutPage'
import { AppsPage } from './pages/AppsPage'
import { DatabasePage } from './pages/DatabasePage'
import { DevicesPage } from './pages/DevicesPage'
import { HelpPage } from './pages/HelpPage'
import { IntegrationPage } from './pages/IntegrationPage'
import { LegacyReviewPage } from './pages/LegacyReviewPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { OnboardingPage } from './pages/OnboardingPage'
import { OverviewPage } from './pages/OverviewPage'
import { PerfPage } from './pages/PerfPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage } from './pages/SettingsPage'
import { TasksPage } from './pages/TasksPage'
import { UiPage } from './pages/UiPage'

export const ROUTES = [
  { path: '/overview', Page: OverviewPage },
  { path: '/apps', Page: AppsPage },
  { path: '/ui', Page: UiPage },
  { path: '/perf', Page: PerfPage },
  { path: '/devices', Page: DevicesPage },
  { path: '/tasks', Page: TasksPage },
  { path: '/reports', Page: ReportsPage },
  { path: '/onboarding', Page: OnboardingPage },
  { path: '/help', Page: HelpPage },
  { path: '/settings', Page: SettingsPage },
  { path: '/about', Page: AboutPage },
  { path: '/legacy-review', Page: LegacyReviewPage },
  // 兼容旧深链接
  { path: '/integration', Page: IntegrationPage },
  { path: '/database', Page: DatabasePage },
] as const

function InitialRoute() {
  const location = useLocation()
  const query = useQuery({ queryKey: ['onboarding-status'], queryFn: ({ signal }) => fetchOnboardingStatus(signal), retry: false })
  if (query.isLoading) return <p role="status">正在核对首次使用状态…</p>
  if (query.isError) return <div role="alert">首次使用状态读取失败。<button onClick={() => query.refetch()}>重试</button></div>
  if (!query.data) return null
  return <Navigate to={{ pathname: onboardingDestination(query.data.complete, onboardingSkipped()), search: location.search }} replace />
}

/** 路由切换时回到页面顶部：长页切页不再停留在上一次的滚动位置 */
function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

export function AppRoutes() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<InitialRoute />} />
        {ROUTES.map(({ path, Page }) => (
          <Route key={path} path={path} element={<Page />} />
        ))}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  )
}
