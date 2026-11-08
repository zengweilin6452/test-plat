/**
 * 正式产品导航：业务入口、帮助与开发者入口、设置与首次使用引导。
 * 旧路径 /integration、/database 保留为兼容入口（帮助 / 数据设计文档仍可达）。
 */
import type { IconName } from '../Icon'

export interface NavItem {
  path: string
  label: string
  icon: IconName
  /** 页面标题，也是面包屑第二段 */
  title: string
  description: string
}

export interface NavGroup {
  label: string | null
  items: NavItem[]
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/overview', label: '工作台', icon: 'grid', title: '工作台', description: '测试能力的入口与当前状态概览' },
  { path: '/apps', label: '项目与应用', icon: 'layers', title: '项目与应用', description: '创建项目、登记 Android 应用，维护名称与归档状态' },
  { path: '/ui', label: 'UI 自动化', icon: 'phone', title: 'UI 自动化', description: '用例、套件与执行记录：断言结果可追溯到报告与现场证据' },
  { path: '/perf', label: '性能测试', icon: 'pulse', title: '性能测试', description: '性能指标与门禁结论：阈值由后端评估，页面只做展示' },
  { path: '/devices', label: '执行资源', icon: 'devices', title: '执行资源', description: '设备与浏览器资源池：可用状态、占用情况与授权' },
  { path: '/tasks', label: '任务中心', icon: 'tasks', title: '任务中心', description: '当前项目的测试任务配置、执行与结果入口' },
  { path: '/reports', label: '报告中心', icon: 'report', title: '报告中心', description: '统一报告视图：结论、证据与可比性说明' },
  { path: '/onboarding', label: '首次使用', icon: 'grid', title: '首次使用', description: '按真实数据计算待办，完成第一次真实测试' },
  { path: '/help', label: '帮助', icon: 'plug', title: '帮助', description: '接入说明、数据设计与旧数据处理说明' },
  { path: '/settings', label: '设置', icon: 'layers', title: '设置', description: '工作空间名称、旧演示数据预览与关于信息' },
  // 兼容旧深链接：不在主导航重复显示，findNavItem 仍能找到标题
  { path: '/integration', label: '接入说明', icon: 'plug', title: '接入说明', description: '外部系统如何把测试定义与结果写入平台' },
  { path: '/database', label: '数据设计', icon: 'layers', title: '数据设计', description: '实体关系、字段字典与写入流程' },
  // 非导航页（从顶栏/设置进入）：补标题让面包屑第二段不再回落成品牌名
  { path: '/about', label: '关于', icon: 'plug', title: '关于', description: '产品版本、构建标识与本机使用边界' },
  { path: '/legacy-review', label: '旧数据预览', icon: 'layers', title: '旧数据预览', description: '旧演示数据的逐项处理预览' },
]

export const NAV_GROUPS: NavGroup[] = [
  { label: null, items: NAV_ITEMS.slice(0, 2) },
  { label: '测试能力', items: NAV_ITEMS.slice(2, 4) },
  { label: '共享资源', items: NAV_ITEMS.slice(4, 7) },
  { label: '使用与维护', items: NAV_ITEMS.slice(7, 10) },
]

export function findNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => item.path === pathname)
}
