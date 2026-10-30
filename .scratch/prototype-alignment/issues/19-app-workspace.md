# 19: 应用工作区与入口

**What to build:** 从应用列表携带应用身份和 scope 进入工作区；iOS/Web 只保存草稿，不伪装真实执行。

**Blocked by:** 06、07

**Status:** ready-for-human

- [x] AC-APP-01：两个同平台不同应用逐个进入，所选应用准确
- [x] 规划平台不能提交真实执行或显示设备就绪
- [x] 登记按钮按批准范围实现，或明确不可用
- [x] 不因本项追加应用 CRUD 范围

## Comments

- 实现提交 ``fdf80bb``（`feat(issue19): 应用工作区入口与应用锚定`）。
- AC-APP-01：应用列表行新增"进入工作区 ›"（#/ui?app=<id>）；新增 `store/app.ts`（与 store/project 同模式：URL ?app= 权威 + localStorage 兜底）；UiPage 读 ?app= 并按 `GET /runs?application_id=` 过滤运行列表，蓝色 Notice 显示当前应用。服务端过滤有测试。
- 规划平台：iOS/Web 修订永远 draft（validate 拒绝）、POST /runs 422 readiness_incomplete（测试覆盖）；工作区 Notice 明示"仅支持保存草稿，不显示设备就绪，不伪装真实执行"。
- 登记按钮：应用页"登记应用"按批准范围保持占位（不追加应用 CRUD）；任务创建仍走 TaskWizard（工单 06/07 通道）。
- 验收（定向）：`test_issue19_app_workspace.py` 2 例；web `tsc --noEmit` 通过；OpenAPI `--check` 通过。逐应用进入的浏览器端到端走查未做（按指示）。
