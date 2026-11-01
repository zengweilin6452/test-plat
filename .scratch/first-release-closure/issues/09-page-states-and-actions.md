# 09: 页面状态与可见动作收口

**What to build:** 核对九个页面在真实数据下的加载、空态、错误、部分缺失与不可用状态；所有可见动作都有真实结果或明确禁用原因；按当前原型与已批准规格注明参考版本。

**Blocked by:** 05, 06, 07, 08

**Status:** resolved

## 现状指针

- 页面：`web/src/pages/*.tsx`（Overview / Apps / Ui / Perf / Devices / Tasks / Reports / Integration / Database）。
- 通用组件：`web/src/components/{Empty,Notice,Button,PageBits,...}.tsx`。
- 原型：`docs/platform-prototype/index.html`（验收时记录文件哈希作为参考版本）。
- 历史走查：`.scratch/prototype-alignment/issues/23-visual-closeout.md`、`debug-ui-diff.md`。
- 运行环境：Vite `http://localhost:5173`（仅 IPv6 回环，不要用 127.0.0.1）。

## 实现要点

1. 逐页核对四类状态：加载、失败（API 错误）、空态（真实无数据）、部分缺失/过期（如证据、身份未学习、来源为空）。
2. 核对可见动作：按钮要么触发真实 mutation 并有结果反馈，要么 disabled 且 title 说明「尚未开放」；不允许空 onClick 或假成功 toast。
3. 核对页面文案与领域术语（运行状态 vs 运行结论、配置就绪 vs 设备就绪、未判定原因）。
4. 核对参考版本：记录原型文件哈希与视口（桌面 1440×900 或用户指定尺寸），不以移动中的文件宣称对齐。
5. 发现缺陷修复并补前端测试；不改后端契约（若必须，回到对应工单）。
6. 明确记录真机/来源为空等不可用项，不伪造数据。

## 验收标准

- [ ] 每页的加载/失败/空态/部分缺失均有可见呈现，且文案能指引下一步。
- [ ] 所有可见按钮无空 onClick；无假成功 toast。
- [ ] 来源为空、身份未学习、证据过期、未判定等状态分别如实显示。
- [ ] 九页按参考版本核对并记录证据（截图路径或 DOM 证据）。
- [ ] `npx tsc --noEmit`、`npm run build`、`npm test` 通过。
- [ ] 有意保留的差异（规格驱动）在工单 Comments 列明原因。

## 验证命令（建议）

```powershell
cd web
npx tsc -p tsconfig.json --noEmit
npm test
npm run build
```

## 已核实缺陷（探索笔记）

- 四处把加载态当空态：`OverviewPage.tsx:53/145/177`、`ReportsPage.tsx:68/118`、`UiPage.tsx:399`、`PerfPage.tsx:247/317/384` 缺 `isLoading` 分支。
- `OverviewPage.tsx:104` 在没有 overview 数据时写「接口未接入」，会把加载失败/加载中误报成未接入。
- 当前没有任何 loading-state 测试。原型参考 sha256：`576d5402…ed4d5f`（180445 bytes）。
- 详细笔记：`C:\Users\williamzeng\AppData\Local\Temp\testdock-frc-notes\09-pages.md`

## 约束

- 不修改 `vendor/`、不安装依赖、不 push。
- 浏览器验收使用 `http://localhost:5173`；若需真机数据，先确认设备空闲。

## Comments

- 2026-11-01 修复：新增 `web/src/lib/pageState.ts`，统一「加载 → 失败 → 空 → 就绪」阶段；Overview / Reports / Ui / Perf 补齐 `isLoading` 分支，加载中显示 `aria-busy`/`role=status` 的占位（`Empty loading`），不再把加载态冒充真实空态。
- Overview 脚注不再写「接口未接入」：按阶段分别显示「正在加载概览数据…」「概览接口调用失败，见上方错误码后重试」「接口已连通但尚未返回计数」。
- 无造假动作：DebugDrawer 复制表达式只在剪贴板写入成功后提示，失败给出真实错误；Ui 套件未 discover 时「运行套件 / 查看用例」disabled 且 title 说明原因；离线设备「打开调试」disabled 且 title 说明。
- 身份未学习、来源为空、证据过期、未判定文案分别由 `InputRegistration.identityCheckNote` / `suiteSourceEmptyHint` / `evidenceState` / `not_tested` 呈现。
- 提交：`ee15159`、`2a5a934`、`289b5c8`、`f3f84b9`，合入 `223eaad`。
- 验证：`tsc -p tsconfig.json --noEmit` 通过；`npm test` 47 passed；`npm run build` 成功。
- 九页浏览器核查（2026-11-01，`http://localhost:5173`，真实 8000 API）：Overview/Apps/Ui/Perf/Devices/Tasks/Reports/Integration/Database 均返回真实数据或真实空态；22 个 XHR 全部 200，无 console error；DOM/可访问树证据存于 `.scratch/first-release-closure/evidence/01-overview.txt`、`02-apps.json` … `09-database.json`。
- 未执行：1440×900 视口下的像素级截图核对——内置浏览器 `visibility=hidden`、viewport 0×0，截图接口报 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`；`agent-browser` 启动挂起。该项在 10 中记为「已实现待验」，不宣称已视觉对齐。
- 有意保留差异：iOS/Web 目标端仍按 `planned` 展示「规划中」而非空态（规格驱动）；Reports 的筛选无结果单独成文案。
