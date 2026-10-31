# 23: 九页视觉与空态收口

**What to build:** 九页的默认入口、页签、卡片/表格、空态和视觉基线完成对齐；所有可见动作都有真实结果或明确不可用状态。

**Blocked by:** 17、18、19、20、21、22

**Status:** ready-for-human

- [x] AC-NAV-01：未知 hash 回工作台，跨页保留 scope 与必要应用上下文
- [x] AC-UX-01：全部可见按钮遍历，无空 onClick 或仅假成功 toast
- [x] AC-VIS-01：同一桌面视口对照原型，仅右侧全高调试面板为已批准布局例外
- [ ] 加载、失败、空态、部分缺失和过期分别呈现
- [ ] 视觉验收记录所用原型内容摘要，不用移动中的文件宣称对齐

## Comments

- 静态部分实现提交 `af0f895`（`feat(issue23): 未开放动作显式禁用与 404 返回入口核对`）。
- AC-NAV-01：`* ` 路由落到 NotFoundPage，带"返回工作台"入口；scope 经 URL query 持久（工单 18/19/20 的 ?scope/?project/?app/?q 系列），跨页保留。
- AC-UX-01：静态扫描 `onClick={() => {}}` 零命中；14 处 toast 均跟在真实 mutation 之后。两个无结果的 PrimaryAction（"登记应用"、"导出报告"）改为 disabled + title"该操作尚未开放"——显式不可用，不再是点了没反应的按钮。
- 加载/失败/空态：Empty/Notice/骨架组件为各页标配（此前工单逐页接齐）。
- **AC-VIS-01 未勾选**：与原型的同视口视觉对照需要浏览器截图走查（九页 × 桌面视口），本轮按指示未做浏览器 QA。空态与交互基线已由上述静态核对覆盖；像素级对齐待人工/浏览器走查后补记。

## Comments（2026-10-31 浏览器走查补记）

- 走查方式：dev 环境（`scripts/dev_up.ps1`，PG 55432 + 后端 8000 + Vite 5174），浏览器桌面视口 1440x900（Browser pane），逐页导航并截图；控制台无错误。
- 九页全部到达并渲染：/overview（目标端卡片 + 4 统计卡 + 双栏面板）、/apps（应用表 + 进入工作区）、/ui（页签：执行记录/套件/用例/调试/模板 + 空态）、/perf、/devices（资源表 + 五状态计数卡 + 打开调试）、/tasks（URL 过滤下拉）、/reports（completed 服务端过滤 + 证据/可比性待接入卡）、/integration（三态能力核查：后端 ok/数据库 ok/vendor present ×2——修复后实测）、/database（七组分组表清单——走查发现"全部落入未分组"缺陷并当场修复，/schema 每表带 group，提交 c0a93ab）。
- 布局基线与原型一致：左侧固定导航、页头 + 主操作、ContextBar（scope 同步地址栏）、卡片/表格/空态组件统一；调试面板例外按批准保留（未展开）。空态（无任务/无报告/无运行）与失败态（早期 /runs 500 → 红色 Notice，迁移 0007 后消失）分别呈现。
- 证据截图存 `.scratch/prototype-alignment/visual-closeout/`（overview / devices / database）。
- 走查附带修复：dev 库从 0002 升级到 0007（alembic upgrade head，历史运行回填 display_no）；`/schema` 分组标注（c0a93ab）。

## Comments（2026-10-31 二次走查：执行资源 + 真机调试按原型返工）

- 反馈：执行资源页与真机调试页与原型不符。返工（提交 be389a8、baa528e、978a77a，合并 fc99a2a/ed214ac 及后续）：
- **执行资源**：表格布局改为原型的 `resource-card` 卡片栅格——设备名+状态徽章、mini-phone 示意图、kv（平台/系统/分辨率/设备编号/当前占用）、打开调试按钮（仅空闲可用）；顶部工具条为状态筛选下拉（含各状态计数）与服务端汇总。
- **真机调试**：右侧抽屉改为原型 `nativeInspectorPage` 的**页面内工作区**（UI 自动化页"调试"标签）：工具条 = 设备下拉 + 连接状态徽章 + 原生节点/图像模板模式切换（inspectMode，图像模式隐藏树与属性列）+ 返回设备池 + 采集检查（primary）；`.inspector` 三栏 = 手机画面（真机 WS 实时预览）| UI 层级树（真实节点）| 元素与定位描述（attribute-list + 定位候选（resource-id 优先候选徽章）+ Target 表达式 + 复制表达式 + 验证定位）。执行资源页"打开调试"= 原型 `go('ui') + uiTab='inspect'`：跳转调试标签并锚定设备（跨页交接 store，消费即清空）。
- 真机实测（749622c9）：进入调试标签自动建会话（已连接）→ 采集检查冻结快照（snapshot 94f23e99…）→ 层级树点击节点 → 属性面板 5 行（text/resource-id/class/clickable/bounds）与表达式实时联动；无标识节点如实显示空候选（不以假表达式冒充）。
- 已知边界：工作区打开期间在下拉里切换设备不会自动重建会话（需先"返回设备池"）——设备切换语义留待下轮；图像识别面板在两种模式都保留（兼做模板库清单）。

## Comments（2026-10-31 全页原型一致性排查）

- 逐页对照原型 index.html 的页面函数（overviewPage/appsPage/tasksPage/uiPage/inspectorPage/templatesPage/androidDevicesPage/perfPage/reportsPage/integrationPage/databasePage），返工两项：
- **报告中心**：清单表格改为原型 `report-card` 卡片栅格（module-pill 平台/模块 + 结论徽章 + 运行名 + RUN 编号/资源 + 一句话结论 + 结束时间 + 查看报告）；页头描述改为原型口径"保留每次运行的原始结论，从结果回到证据。"；工具条提示改"重跑创建新记录，不覆盖历史证据"；移除两个"待接入"占位卡与已禁用的"导出报告"死按钮（证据在报告抽屉，AC-REP-03 已交付）。服务端 completed 过滤、搜索与游标分页保留（工单 10 验收项）。
- **页头描述对齐**：项目与应用 / 测试工作台 / 任务中心三页的描述改为原型原文。
- 排查后判定**有意保留的差异**（规格驱动，非偏差）：接入说明页用真实契约替代原型的"虚构示例"声明（AC-INT-01）；任务中心 run_state 过滤替代原型把 passed/failed 混进状态筛选（工单 20）；通过率空样本显示 null 而非原型的 0%（工单 18）；UI 自动化页的执行记录页签（原型的运行清单在任务中心）。

## Comments（2026-10-31 真机调试页对齐原型 nativeInspectorPage）

- 现象：用户反馈「真机调试页面和原型 UI 不一致」；同视口（2560×1215）浏览器对照确认差异集中在：调试页外层多包 `<Panel>`、三栏是裸 `.debug-section` 没有卡片、切换器挤在 toolbar、设备状态徽章被 WS 状态顶替、图像模式整块在 inspector 下方。
- 本轮改动（`web/src/components/DebugDrawer.tsx`、`web/src/pages/UiPage.tsx`、`web/src/styles/tokens.css`）：
  1. 调试页不再包在 UiPage 的 `<Panel>`+`.panel-head` 内；切换器（原生节点/图像模板，`.btn.soft` 激活态）回到 toolbar 之前独立一行。
  2. 三栏 = `.phone-panel` | `.panel`（UI 层级树） | `.panel`（元素与定位描述）；列宽 280px / `minmax(210px,1fr)` / `minmax(260px,1.1fr)`、gap 18px，标题 h2 14px；层级树改用原型 `.tree-row`（选中高亮、节点计数、底部提示）。
  3. toolbar：设备下拉 `name / os` + 设备状态徽章「可用」+ WS 状态 muted + 返回设备池 + 采集检查/恢复预览单按钮切换（freeze/play 图标）；`leaseHint` 恢复渲染。
  4. 元素与定位描述：属性 5 行 + 定位候选（resource-id 优先）+ `Target(...)` 表达式 + 定位方式/定位值表单 + 验证定位/复制表达式 + 紧凑结果行（原型 `#locator-result` 的位置）；定位结果从左侧栏移入第 3 栏。
  5. 图像模式：第 2、3 栏改为「框选与保存模板」「图像匹配验证」两个 `.panel.panel-pad.image-form`（原型 imagePanel 的切割方式），删除 `.inspector.mode-image` 隐藏列与 inspector 下方全宽模板区；模板匹配仍走真实 vendor 接口，零匹配如实显示。
  6. 真机联调发现并修复：详情轮询在后台标签页被 TanStack Query 暂停，导致 opening→active 永不推进（加 `refetchIntervalInBackground`）；模板坐标改用快照像素尺寸（capture 响应的 width/height），不再拿缩放的实时流尺寸，图像模式坐标范围显示 1080×2400。
  7. 关闭会话后回到「执行记录」页签，避免停在调试页时按 ready 设备立刻重建会话；关闭后无活动会话、无未释放租约。
- 验证：
  - 真机 749622c9：自动建会话 → WS 已连接 → 采集检查（143 节点）→ resource-id `com.miui.home:id/drag_layer` 唯一匹配 → 图像模板匹配返回 vendor 真实「零匹配:目标未出现」→ 关闭会话释放设备。
  - 截图：`.runtime/shots/debug-app-before.png`（改前）、`debug-proto.png`（原型）、`debug-ui-final.png`（改后 native）、`debug-app-image2.png`（改后 image）。
  - 栅格实测：三栏 280 / 586 / 644px，gap 18（与原型 280 / 1fr / 1.1fr 一致）。
  - `npx tsc --noEmit`、`npm run build`、`npm test`（17 例）全过。
- 有意保留：定位验证表单（by/value 是真实 vendor 契约）、结果行的 x/y/尺寸/置信度、关闭会话 footer、跨页签保活、错误/空态；原型演示专属（直接控制、返回/主屏、SNAP-DEMO、模拟分数）未照搬。差异全表见 `.scratch/prototype-alignment/debug-ui-diff.md`。
