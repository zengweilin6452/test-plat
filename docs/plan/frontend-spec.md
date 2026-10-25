# 前端规格（frontend-spec.md）

> 配套：`docs/platform-prototype/index.html`（332 行，UI 权威）、`docs/plan-input/prototype-ui-spec.md`（492 行选择器级清单）、`docs/plan/api-design.md`。
> 原则：**信息结构与视觉照原型，数据与交互换成真实 API**。原型里的演示数据、模拟推进、硬编码判断全部删除。

## 1. 技术栈与目录

```
web/
├─ src/
│  ├─ main.tsx, App.tsx           # 路由 + 布局（顶栏/侧栏/主区）
│  ├─ api/                        # client.ts + 每域一个 hooks 文件
│  ├─ components/                 # 见 §2
│  ├─ pages/                      # 9 个页面，见 §3
│  ├─ stores/scope.ts             # targetScope + 筛选（持久化到 URL query）
│  ├─ styles/tokens.css           # 从原型抽取：颜色/间距/圆角/字阶/阴影
│  └─ lib/                        # fmt.ts(duration/percent) verdict.ts(三态展示)
├─ index.html, vite.config.ts, tsconfig.json
└─ src/**/*.test.tsx              # vitest + RTL
```

| 依赖 | 用途 |
| --- | --- |
| `react` / `react-dom` / `react-router-dom` | 页面与 `#hash` 路由 |
| `@tanstack/react-query` | 服务端状态 |
| `zustand` | `targetScope` 与列表筛选 |
| `vitest` / `@testing-library/react` / `jsdom` | 单测 |

**不引入**：UI 组件库（外观必须与原型一致）、echarts（趋势图自绘 SVG）、CSS 框架（用 tokens.css + CSS Modules）。

## 2. 组件清单（与原型原语一一对应）

| 组件 | 对应原型 | 关键 props |
| --- | --- | --- |
| `<Heading>` | `heading()` L119 | `title, desc, actions` |
| `<Tabs>` | `tabs()` L120 | `items, active, onChange` |
| `<Empty>` | `empty()` L121 | `title, description` |
| `<StatusBadge>` | `badge()` + `statusMap` L70-71 | `state?, outcome?, lifecycle?, readiness?` → 组合成展示态 |
| `<Icon>` | `icon()` + paths L68-69 | `name`（9 个导航 + 少量操作图标） |
| `<Button>` | `btn()` L118 | `variant, action` |
| `<Toast>` | `toast()` L117 + `#toast` | 全局单例，`role=status aria-live=polite` |
| `<Modal>` / `<Drawer>` | `openModal/closeModal/closeDrawer` L222-225 | 原生 `<dialog>`，保留 ESC/焦点陷阱 |
| `<TaskTable>` | `taskTable()` L186 | `rows, withFilterFooter` |
| `<TargetPicker>` | `targetPicker()` L144 | 编辑态禁选其他端 |
| `<DeviceCard>` | 设备卡 L200 | busy 时只读预览 |
| `<Timeline>` | 4 步 timeline L228 | `stage` 由 `progress` 推导 |
| `<TrendChart>` | `chartMarkup()` L211（手绘 SVG） | `points, baseline, unit, marks, missingRanges` |
| `<MetricCard>` | 指标卡 L207 | `null → 显示 —`，跨档案 → 显示「跨档案，不作对比」 |
| `<GateChecks>` | 门禁试算表 L210 | `checks[], level` |
| `<Notice>` | notice 样式 | `kind: info|warn|danger` |

## 3. 页面 → 组件 → API 矩阵

| 页面 | 主要组件 | API |
| --- | --- | --- |
| 工作台 `overview` | 4 `StatCard` + 2 模块入口卡 + `TaskTable`(6) + `AlertList` + 前 3 `DeviceCard` | `GET /overview?platform=` |
| 项目与应用 `apps` | 3 `TargetCard` + 应用表 + `ScopeHint` | `GET /projects`、`GET /applications?platform=` |
| UI 自动化 `ui` | `Tabs(suites|inspector|templates)` | 套件：`GET /suites`、`GET /suites/{id}/versions`、`POST /tasks`；调试：`POST /debug-sessions`、`WS /ws/debug/{id}`、`POST /locators/validate`、`POST /debug-sessions/{id}/snapshots`；模板：`GET/POST/PUT /templates` |
| 性能测试 `perf` | `RunPicker` + `MetricCard`×4 + `TrendChart` + `ContextList` + `GateChecks` + 基线下拉 | `GET /analyses?run_id=`、`GET /baselines`、`POST /runs/{id}/gate-evaluations`、`GET /runs/{id}/report/export` |
| 基线门禁 / 阈值表单 | `BaselineCard` + `RulesForm` | `GET /baselines`、`GET/PUT /gate-policies/{id}` |
| 执行资源 `devices` | `DeviceFilter` + `DeviceCard`×n + 页脚统计 | `GET /resources`、`POST /resources/sync`、`POST /resources/{id}/readiness` |
| 任务中心 `tasks` | `TaskTable` + 三件套筛选 + 新建向导 + 详情抽屉 | `GET /tasks?…`、`GET /runs?…`、`POST /tasks`、`POST /runs`、`WS /ws/runs/{id}` |
| 报告中心 `reports` | `ReportCard`×n + `ReportDrawer` | `GET /runs?state=completed`、`GET /runs/{id}/report`、`GET /runs/{id}/cases`、`GET /runs/{id}/artifacts` |
| 接入说明 `integration` | 静态内容 + 能力核查表（数据来自 `GET /health`） | `GET /health` |
| 数据设计 `database` | `Tabs(overview|dictionary|flow)` + 搜索 + 7 组筛选 | `GET /schema` |

## 4. 状态与路由

| 项 | 规则 |
| --- | --- |
| 路由 | `#overview` 等 9 个 hash；未知 hash 回落 overview；`document.title = 页面名 + ' · TestDock'` |
| `targetScope` | `all|android|ios|web`；**持久化到 `?scope=`**（修正原型刷新丢失）；切 scope 清空列表筛选 |
| 列表筛选 | `?q=&module=&status=`，刷新后保持 |
| 运行对象 | `useRunLive(runId)`：WS `snapshot` → 本地缓存；`state/event` → 增量；`finished` → invalidate 相关 query 并关闭 WS |
| 展示态推导 | `displayStatus(state, outcome)`：`completed+passed→passed`、`completed+failed→failed`、`completed+not_tested→not_tested`、`queued|dispatching→queued`、`running|finalizing→running`、`errored→failed(带错误标)`、`cancelled→cancelled` |

## 5. 与原型的行为差异（逐页）

| 页面 | 原型 | 平台 |
| --- | --- | --- |
| 工作台 | 硬编码 2 条告警；数字由本地任务算 | 全部由 `/overview` 返回；无告警时显示空态文案 |
| 项目与应用 | `targetCatalog` 写死 | `GET /applications`；非 android 端徽章仍为「规划中」 |
| UI 套件 | 4 行写死 + 本地推进 | `GET /suites`；「运行套件」= `POST /tasks` 建任务后 `POST /runs` |
| UI 调试 | 三栏示意、验证定位返回演示串 | 真 `debug_session` + 预览帧 + 真实匹配坐标与置信度 |
| UI 模板 | 本地数组 | vendor TemplateStore；新版本不改旧版本（响应里带 `version`） |
| 性能 | `metricData` 写死 + `metricForRun` 变换 | `/analyses` 返回真实 median/baseline/sampleCount/series |
| 性能判定 | 前端 `perfVerdict()` 计算 | 后端 `gate_evaluations` 给结论，前端只展示（**前端不再自算判定**） |
| 阈值表单 | 改本地 `rules` | `PUT /gate-policies/{id}`；保存后刷新分析改用 `reanalysis` |
| 执行资源 | `deviceState()` 由任务推导 | `/resources` 的 `busy/holder`；离线/未授权禁用操作 |
| 任务中心 | `mutateTask` 模拟推进 | 状态全部来自后端；`running` 行内进度条来自 WS |
| 新建向导 | 直接塞本地任务 | `POST /tasks` → 201 后跳详情；错误按字段定位到 `role=alert` 区 |
| 报告中心 | `isFinished` 局部判定 | `GET /runs?state=completed`；失败证据图/树来自 `artifacts` 下载 |
| JSON 导出 | `exportReport()` 本地拼 | `GET /report/export`，`prototype:true` 已移除 |
| 数据设计 | `DB_TABLES` 常量 | `GET /schema`（构建期由 `schema.sql` 生成） |

## 6. 验收用例（每页至少 3 条）

| 页面 | 用例 |
| --- | --- |
| 工作台 | ①数字与 `/overview` 一致 ②scope=ios 时显示规划态且资源卡为 0 ③告警点击跳到对应运行 |
| 项目与应用 | ①3 端卡片与徽章正确 ②进入应用工作区带 `?scope=android` ③非 android 端「执行能力」=规划中 |
| UI 自动化 | ①套件 tab 列出真实套件与用例数 ②调试 tab 设备离线时禁用开调试 ③模板新建同名 → 版本 +1 且旧版本图仍在 |
| 性能测试 | ①gpu 不支持显示 `—` 且不参与判定 ②跨档案基线显示「跨档案，不作对比」 ③改阈值产生 trial，original 结论不变 |
| 执行资源 | ①busy 设备显示占用者与排队数 ②offline/unauthorized 操作禁用 ③就绪检查失败给出可读 hint |
| 任务中心 | ①三件套过滤组合正确 ②编号规则（draft=TASK-、其他 RUN-） ③运行中进度条随 WS 更新 |
| 新建向导 | ①包名非法被拦且错误在 `role=alert` 内 ②时长非整数被拦 ③提交成功后跳任务中心并打开详情 |
| 报告中心 | ①只有 `completed` 出现 ②not_tested 的一句话结论正确 ③失败运行能下载截图与 UI 树 |
| 数据设计 | ①24 表全部可见 ②搜索过滤表与字段 ③7 组徽章数量与 `/schema` 一致 |

## 7. 视觉对照方法

1. `scripts/screenshot_compare.mjs`：Playwright 打开原型 `docs/platform-prototype/index.html` 与平台同一页面，截 9 页 PNG 到 `docs/plan/ui-shots/{proto,platform}/`。
2. 人工 diff 清单：导航区、卡片圆角与阴影、状态徽章色、表格行高、抽屉宽度、字体（原型系统字体栈）。
3. P1 结束前完成 9 页首轮对照；之后每期回归一次（截图存档在 repo 便于 review）。

## 8. 前端的硬性禁止

1. 不允许在前端计算门禁结论（必须来自 `gate_evaluations`）。
2. 不允许把 `outcome=null` 显示为「失败」或「通过」。
3. 不允许把缺失指标显示为 `0`。
4. 不允许在 demo 数据缺失时用假数据兜底——必须显示空态或错误态。