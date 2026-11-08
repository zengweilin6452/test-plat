# UI 渐进式披露改造与 UX 修复记录

- 日期：2026-11-07 ~ 11-08
- 分支：`feature/ui-ux-polish`（基于 `integration/first-release-closure` + report-inline-view 4 提交；本分支按任务要求**未 commit**，全部改动在工作树）
- 配套截图：`web/docs` 之外放在 `docs/plan/ui-shots/disclosure/{before,after}/`（overview / tasks / reports / perf / apps / task-wizard 各一张 + mobile-nav 验证图）

## 1. 渐进式披露规则（本任务的落地口径）

1. 首屏只留标题 / 状态 / 主操作 / 关键指标；参数、筛选、高级项默认收起
2. 三层结构：概览 → 列表/分组 → 详情抽屉；同一信息不重复
3. 渐进式表单：默认只显必填，高级项折叠并显示已填摘要；校验错误就地提示
4. 折叠区必须有入口与摘要；关键状态不藏进折叠区
5. 危险 / 不可逆操作二次确认，说明后果
6. 空态给下一步动作，不只写「暂无数据」
7. 无障碍：键盘可达、`aria-expanded`/`aria-controls`、对比度 ≥4.5:1；不引入新依赖

与原型的关系：`prototype-alignment-spec.md` D1 以原型为信息结构权威；本任务经用户明确要求降低首屏密度（规格冲突规则「用户明确决定优先」）。所有页面保留了原型的关键动作与入口，仅收敛密度与呈现层级。

## 2. 新增通用组件

| 组件 | 说明 |
| --- | --- |
| `components/Disclosure.tsx` | 折叠区原语：button 入口（键盘可达）+ `aria-expanded`/`aria-controls` + 摘要槽 + 受控/非受控两种模式 |
| 空态动作 | 复用既有 `Empty` 组件的 `actions` 槽（未新建 EmptyState；避免重复抽象） |
| `.scope-chip` / `.choice-row` | tokens.css 新增紧凑选择样式（目标端 chips、向导选择项压缩） |

## 3. 逐页映射（过载点 → 改法 → 收益）

### /apps（收益最大）
- **改前**：新建项目 + 登记应用两个完整表单常驻首屏，项目/应用表在第二屏之外
- **改法**：两个表单折叠为 `Disclosure` 入口（「新建与登记」面板，默认收起，同时只开一个）；项目表成为首屏主体；项目/应用空态加「展开新建/登记」动作
- **顺带修复**：项目表加载中误报「暂无数据」（M2）；两表单缺客户端必填/格式校验 → 字段级 `role=alert` 就地提示 + `aria-invalid`（M3）；创建成功 toast（`success` tone）

### /overview
- **改前**：目标端 3 张静态大卡占黄金横带；首屏只能看到统计卡一半
- **改法**：3 卡压缩为一行 `.scope-chip`（全部/Android/iOS/Web，能力说明收进 chip 小字）；「最近运行」空态加「新建测试任务」主按钮
- **收益**：首屏纵向省约 120px，统计卡 + 运行面板整体上移进首屏

### /tasks（含 TaskWizard）
- **改前**：打开向导立即显示全部必填校验红字（`fieldErrors` 未交互也回显空值错误——bug）；第 1 步 6 张选择大卡占满；设备清单可达数十张卡
- **改法**：
  - 未交互时只提示「格式非法」类错误，必填空值等用户点过下一步再报红
  - 目标端 / 测试模块 6 大卡 → 两行紧凑 chips
  - 应用版本 / 测试场景（可留空）折叠为「高级配置（可选）· 已填 N 项」
  - 固定图像模板折叠为「已选 N 个」；设备清单限高滚动
  - UI 模块不再渲染性能时长/采集项（原先是禁用+灰字占位）
- **收益**：第 1 步一屏收纳、开门不见红；高级项可发现（有摘要）

### /reports
- **改法**：卡片动作重排（「查看报告」为主、「在线查看」为次）；`#/reports?run=<id>` 深链现在会定位并打开该运行的报告（第一页没有时按编号走服务端 `q` 过滤，仍找不到如实提示，不静默）；空态区分「筛选为空 → 清除搜索与筛选」「真空态 → 前往任务中心」
- **保留说明**：ReportDrawer（摘要+证据）与 ReportViewer（内嵌全文）是两个不同视图，按「不删现有功能」纪律两者都保留

### /perf
- **改前**：顶部常驻大段教育性 Notice（门禁结论不在前端计算）
- **改法**：折叠为「为什么结论可能是「未判定」？」单行 Disclosure；运行清单空态加「前往任务中心发起运行」
- **收益**：首屏省约 80px，运行选择 + 判定 + 指标卡成为视觉主体

### 导航与全局
- 面包屑：`/about`、`/legacy-review` 补入 navItems（不在侧栏显示，仅取标题），第二段不再回落成品牌名
- 路由切换重置滚动位置（`ScrollToTop`）
- 移动端导航修复（见 §4 H1）

## 4. 同批完成的 UX bug 修复（两轮审查的全部高/中严重度）

| 级别 | 问题 | 修复 |
| --- | --- | --- |
| H1 | 内联 `display:none` 压过媒体查询，≤760px 导航完全无法打开 | 删内联样式；补桌面默认 `.menu-toggle{display:none}`（修复过程中发现的连带回归） |
| H2 | 原生 `<dialog>` top layer 遮挡 toast，抽屉里的成功/失败提示看不见 | Toast 渲染改为非模态原生 `<dialog>`（`show()` 进 top layer，不阻断交互），多槽位堆叠 |
| H3 | Esc 触发原生 close 后 React `open` 失真，向导提交中按 Esc 后永远打不开 | Dialog 拦截 `cancel` 事件（preventDefault + 交给 onClose 决定） |
| H4 | DebugDrawer window 级 Esc 会连带销毁确认框/输入中的调试会话 | 打开中的 `dialog[open]` 或输入控件聚焦时 Esc 不销毁会话 |
| H5 | `Icon` 的 size prop 被 `.icon{width:19px}` 类规则覆盖，全站图标一律 19px | width/height 改走内联 style |
| M1 | `PrimaryAction` 不支持 busy，同步设备池可连点 | 增加 `busy`/`disabled` props，DevicesPage 接入 |
| M4 | 搜索框每击键写 URL / 发服务端请求 | Toolbar 内置 300ms 防抖（外部值变化仍会同步回输入框） |
| M5 | 路由切换不回滚顶部 | `ScrollToTop` |
| M6 | 旧数据批量操作无二次确认 | 确认 Dialog 列出保留/改名/归档各项数量与后果 |
| M8 | 调试换设备关闭旧会话失败被静默吞掉 | toast 报错并保留原会话 |
| M9 | 导出报告 JSON 链接缺 `download`，可能整页跳离应用 | 两处补 `download` 属性 |
| M10 | Toast 单槽覆盖、无 tone | 多槽位 + info/success/error 三种 tone，全部调用点补 tone |
| M11 | 任务中心点击「查看执行」一次叠开两层抽屉（按钮点击冒泡到表格行，行点击又打开任务详情），用户要连点多次关闭按钮才能关净 | `Table.tsx` 行点击过滤行内交互元素（button/a/input/select/label 等），点按钮不再触发行点击；行空白处点击行为不变（实测：开一层、× 一次关净） |

## 5. 视觉收敛

- **对比度达标（AA 4.5:1）**：`--muted #758094→#5d6b80 (5.41)`、`--muted-strong→#54627a (6.17)`、`--muted-weak→#647186 (4.94)`、`--muted-faint→#66748a (4.74)`、`--nav-label→#66748a`；散落字面灰值（badge.gray、stat-foot、tab、chart 文字、placeholder 等 13 处）全部收敛到 token；9px 字号提升至 11px；`--fs-2xs` 10→11px
- **选中蓝收敛**：新增 `--selected/--selected-bg`，替换 target-card / choice / rev-row.latest / db-entity / locator-option / tree-row.selected 六处离散蓝
- **死代码清理**：删除 `--chart-grid`、`.prototype-tag`（含 430px 断点规则）、`.metric-card.active`、`.pill-tabs`（Tabs 组件 pill 变体一并移除——无调用方）；误导性 `var()` 回退值（--surface-muted/--text/--line/--muted/--green）改为正式定义或直接引用
- **交互态补齐**：`.db-table-btn`/`.target-card`/`.locator-option` 补 hover；`:focus-visible` 选择器覆盖 `[tabindex]`（调试树节点）
- **组件统一**：RunDrawer/InputRegistration 裸 `<pre>` → `code-block`；AboutPage/TemplateLibrary 裸 `<p>` 加载态 → `Empty loading`；Overview/Apps 裸 hash `<a>` → `<Link>`；DatabasePage 裸徽章补 tone；内联 `0 20px` padding → `var(--space-9)`

## 6. 验收证据

- `cd web && npm run typecheck` ✅ 通过
- `npm test` ✅ 85/85（任务书口径「90 个测试」按当前仓库实际为 85 个；无回退）
- `npm run build` ✅ 1.20s 构建成功
- 浏览器走查（1440×900 + 390×844）：
  - 向导打开无红字、Esc 关闭后可重开（实测 `REOPENED OK`）
  - 390px 视口汉堡按钮可见、点击展开侧栏（实测 `SIDEBAR OPEN OK`，见 after/mobile-nav.png）
  - apps 首屏为列表 + 两个折叠入口；overview 目标端为一行 chips；perf 教育性说明折叠
- 无障碍抽查：Disclosure `aria-expanded/aria-controls`；表单错误 `role=alert` + `aria-invalid`；焦点环覆盖 `[tabindex]`；正文灰字 ≥4.5:1

## 7. 未做项与原因

| 项 | 原因 |
| --- | --- |
| RunDrawer 手写时间线复用 `Timeline` 组件 | 两者数据形状不同（事件流 vs 阶段 4 步），重构风险大于收益；留待专项 |
| Tabs 键盘 roving tabindex / aria-controls 完整 WAI-ARIA tabs 模式 | 现有 3 处调用均两枚页签，方向键导航收益低；已保留 `role=tablist/tab/aria-selected` |
| Toast 容器 display 切换的读屏兼容（改 visibility 常驻 DOM） | 已改为 dialog top layer + 每条独立 `role=status aria-live=polite`，结构变化后原建议不再适用 |
| H2 的浏览器实测（在弹层打开时触发 toast） | 需要真实提交/失败路径，避免向共享开发库写数据；修复依据是 dialog top layer 的标准行为，typecheck/测试/构建均通过 |
| 页尾「服务端过滤 ?q=」等开发向提示全部改为面向用户文案 | 部分文案被 `page-states.test.cjs` 钉住（如 GET /api/v1/runs 的加载态说明），按「不改现有测试语义」纪律保留 |
