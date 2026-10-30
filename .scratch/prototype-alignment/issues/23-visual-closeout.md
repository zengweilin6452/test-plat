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
