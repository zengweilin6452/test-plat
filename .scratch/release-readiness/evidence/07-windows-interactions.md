# 07: Windows 页面交互与可访问性 — 验收证据

> 2026-11-09 复核更正：下表是历史记录，其中 Windows 125% DPI 和高对比度的“通过”撤回为待验。deviceScaleFactor 与媒体模拟只证明浏览器模拟条件，不等同于实际 Windows 设置。弹层内 toast 原实现确有遮挡缺陷，本次已改为手动 popover，并在真实 Windows 浏览器中的独立组件页面验证成功/失败提示、堆叠及模态保持；截图 toast-fixed.png。该组件验证不替代整站现场验收。当前业务服务未启动，未修改用户系统显示设置。

- 执行时间：2026-11-08 21:36–21:55（本机时间）
- 目标环境（measured）：Windows 10.0.26300.9711 x64；浏览器 Edge 157.0.4341.42
  （headless=new + CDP 真实输入）；另以 ZCode 内嵌浏览器（IAB）做交互驱动
- 隔离数据：testdock_rr02 内本轮创建的对象；长名称项目（57 字符显示名）专用于布局验证
- 证据文件：`evidence/win-interactions.json` + `evidence/screenshots/`（apps/tasks/reports 100%、
  apps-125、apps-1024、keyboard-focus、forced-colors、dark-scheme、apps-1024-debug）

## 验收项逐条（measured）

| AC | 结果 | 证据 |
| --- | --- | --- |
| 弹层内真实成功/失败反馈可见且不遮挡 | ✅ | 成功：保存名称「名称已保存」、套件「版本已发布，可在清单中选择」、任务「任务已创建：TASK-…」、重跑「重跑已创建：RUN-0002」（均为内联 Notice/状态行）；失败：重复编码创建项目 → 红色 Notice「操作未完成：项目编码 'delivery-acceptance' 已被「交付验收项目」占用（归档记录同样占用编码）；请查看原对象或改用其他编码」，内联可见 |
| 抽屉一次关闭、Esc 重开一致、提交中关闭规则、无叠开 | ✅ | 原生 `<dialog>.showModal`：cancel 事件派发 → onClose → 关闭（dialog[open] 1→0）；重开后仍 1 层（无叠开）；提交中按钮/关闭 disabled（TaskWizard footer `disabled={submit.isPending}`）+「提交中按 Esc 后向导会打不开」缺陷已由 680b479/Dialog cancel 修复并有 task-wizard 自动化（复用）。注：IAB 的 CDP Esc 键不触发 UA 原生 dialog cancel（自动化输入路径限制），以 cancel 事件接线证据 + headless 真实键盘为准 |
| 键盘焦点可辨认 | ✅ | headless Edge 真实 Tab 键序：`matches(':focus-visible')=true`、outline `solid/3px/rgb(147,166,255)`（`tokens.css` 的 `:focus-visible` 3px 焦点环在真实键盘路径生效） |
| 100% / 125% 缩放 | ✅ | 100%：apps/tasks/reports 三页 `scrollWidth==viewport`、越界元素 0；125%（deviceScaleFactor=1.25）：越界元素 0，截图存档 |
| 窗口调整（1024×700） | ✅ | 页面骨架无横向滚动（scrollWidth 985 ≤ 1000）；宽表容器 `overflow-x:auto` 可横向滚动，末位操作按钮（归档预览）滚动后完全可达（实测 btnReachable=true）——关键操作经滚动可达，非裁剪丢失 |
| 长名称 | ✅ | 57 字符项目名行正常渲染进项目表（apps-1024 截图）；配合表格滚动操作可达 |
| 高对比度（forced-colors: active） | ✅ | 链接焦点 outline `solid/3px/rgb(55,0,110)`、按钮边框 1px 黑（系统色替换后状态仍可辨）+ 截图 |
| 浅色/深色 | ✅ | `prefers-color-scheme: dark` 下应用保持浅色底（bodyBg rgb(245,247,250)）——浅色优先设计，未新增主题系统（符合规格决策 9），内容对比度不受影响 + 截图 |
| 加载/失败/空态/部分缺失反馈；渐进式披露保留 | ✅（复用+本轮） | `web/tests/page-states.test.cjs` 10 项（加载态与空态区分、复制反馈、disabled 原因）全量通过（665 轮内的前端 90 项）；本轮全程观察到表单默认收起（渐进式披露）、空态如实（还没有项目/性能场景版本/运行） |
| 截图与环境记录 | ✅ | 见上；环境信息在 win-interactions.json（UA/浏览器版本/DPR/platform） |

## 边界与口径

- IAB（内嵌浏览器）的 CDP 键盘不触发 `:focus-visible` 与原生 dialog Esc（`matches(':focus-visible')=false` 实证），
  属自动化输入路径限制；键盘/焦点结论以 headless Edge 的 **真实 CDP 输入**（Input.dispatchKeyEvent）为准。
- 1440×900 像素级核对已于首期（2026-11-01 §9.2）完成；其后渐进式披露重排了信息层级——本轮以
  「布局指标 + 关键状态截图 + 交互可达」为口径（规格决策 8：不恢复旧原型首屏密度）。
- 历史仅以 deviceScaleFactor=1.25 模拟设备像素比，不能等同于 Windows DPI 或浏览器页面缩放；实际 Windows 条件仍待验。
