/**
 * 导航项与分组。
 * 顺序、文案、图标照抄原型 L139 navItems；分组边界照抄原型的索引判断
 * （i===2 起「测试能力」、i===4 起「共享资源」、i===7 起「设计依据」）。
 */
import type { IconName } from '../Icon'

export interface NavItem {
  /** 路由 path（HashRouter，对应 #/overview 等） */
  path: string
  label: string
  icon: IconName
  /** 页面标题，也是面包屑第二段 */
  title: string
  /** 页面说明（原型 heading 的第二参数） */
  description: string
}

export interface NavGroup {
  label: string | null
  items: NavItem[]
}

/** 9 项导航，顺序不可改（与原型一一对应） */
export const NAV_ITEMS: NavItem[] = [
  {
    path: '/overview',
    label: '工作台',
    icon: 'grid',
    title: '工作台',
    description: '测试能力的入口与当前状态概览',
  },
  {
    path: '/apps',
    label: '项目与应用',
    icon: 'layers',
    title: '项目与应用',
    description: '登记被测应用与目标端，作为任务的目标引用',
  },
  {
    path: '/ui',
    label: 'UI 自动化',
    icon: 'phone',
    title: 'UI 自动化',
    description: '用例、套件与执行记录：断言结果可追溯到报告与现场证据',
  },
  {
    path: '/perf',
    label: '性能测试',
    icon: 'pulse',
    title: '性能测试',
    description: '性能指标与门禁结论：阈值由后端评估，页面只做展示',
  },
  {
    path: '/devices',
    label: '执行资源',
    icon: 'devices',
    title: '执行资源',
    description: '设备与浏览器资源池：可用状态、占用情况与授权',
  },
  {
    path: '/tasks',
    label: '任务中心',
    icon: 'tasks',
    title: '任务中心',
    description: '全部测试任务的配置、执行与结果入口',
  },
  {
    path: '/reports',
    label: '报告中心',
    icon: 'report',
    title: '报告中心',
    description: '统一报告视图：结论、证据与可比性说明',
  },
  {
    path: '/integration',
    label: '接入说明',
    icon: 'plug',
    title: '接入说明',
    description: '外部系统如何把测试定义与结果写入平台',
  },
  {
    path: '/database',
    label: '数据设计',
    icon: 'layers',
    title: '数据设计',
    description: '24 张表的实体关系、字段字典与写入流程',
  },
]

/** 分组：第一组无标签（工作台/项目与应用），其余三组有标签 */
export const NAV_GROUPS: NavGroup[] = [
  { label: null, items: NAV_ITEMS.slice(0, 2) },
  { label: '测试能力', items: NAV_ITEMS.slice(2, 4) },
  { label: '共享资源', items: NAV_ITEMS.slice(4, 7) },
  { label: '设计依据', items: NAV_ITEMS.slice(7, 9) },
]

export function findNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => item.path === pathname)
}
