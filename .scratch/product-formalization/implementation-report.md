# TestDock 正式化改造实现与验收报告

- 日期：2026-11-04
- 分支：`integration/first-release-closure`（未 commit、未 push、未创建 PR）
- 基线：`7511fc0`；规格：`.scratch/product-formalization/spec.md`，工单 `issues/01–12`
- 术语：`GLOSSARY.md`；身份决策：`docs/adr/0001-stable-project-application-identity.md`
- 硬编码处理清单：`.scratch/product-formalization/hardcoded-inventory.md`

## 1. 实现范围与顺序

按 Blocked by 依赖分批实现：01/02/06/07/11 → 03/04 → 05/09 → 08/10 → 12。所有代码改动留在工作区，保留用户已有的 `GLOSSARY.md`、`.scratch/product-formalization/`、`docs/adr/`、`web/vite.verify.config.ts` 等未提交/未跟踪内容。

### 工单状态

| 工单 | 状态 | 核心实现 |
| --- | --- | --- |
| 01 工作空间设置与品牌 | 已实现并自测 | `0009` 单行工作空间设置；`GET/PATCH /workspace`；`PlatformProvider`；侧栏/顶栏/关于页取真实名称与版本；加载/读取失败/保存失败状态分离 |
| 02 项目/应用创建改名 | 已实现并自测 | `POST/PATCH /projects`、`POST/PATCH /applications`；项目编码规范化与唯一性、Android 包名校验、身份创建后固定、归档记录仍占用唯一键、冲突返回 `existing_id` |
| 03 统一上下文 | 已实现并自测 | `EffectiveContextProvider`：URL 优先、显式 `project=all`、服务端对象有效性校验、仅 app 解析项目、冲突拒绝、切项目清不兼容选择与缓存键 |
| 04 归档恢复 | 已实现并自测 | 归档预览（关联数量 + 具体阻塞对象）、活动占用拒绝、父子状态规则、幂等归档/恢复、`FOR UPDATE` 归档守卫接入所有业务写入入口 |
| 05 全站范围一致 | 已实现并自测 | `/overview`、`/runs`、`/tasks`、`/suites`、`/baselines` 增加 `project_id`；前端请求与查询缓存键跟随当前项目；工作台/设备/任务/报告/向导统一接入 |
| 06 能力与不可用状态 | 已实现并自测 | `GET /capabilities` 服务端能力摘要；平台支持与设备就绪分开；能力读取失败不显示可执行；删除「已有组件基础」等过时文案；示例明确标注且不自动提交 |
| 07 正式/演示初始化隔离 | 已实现并自测 | 0009 只建立必要系统设置；`seed_demo.py` 需 `--demo` + 独立库并拒绝正式默认库；新导入数据标 `origin='demo_seed'`，不倒填旧数据；`formal_start_blocker()` 拒绝正式假执行 |
| 08 首次真实运行 | 已实现（真机部分受阻） | `GET /onboarding/status` 按真实数据计算；欢迎/引导页可跳过返回；本机节点由既有 `sync_resources` 幂等 upsert；构建/套件/任务/运行复用既有流程并带正确范围 |
| 09 旧演示数据预览处理 | 已实现并自测 | `GET /legacy-review` 按固定 ID/原字段/关联识别，不按名称判定；`POST /legacy-review/apply` 逐项 keep/rename/archive，预览 token 重校验，设备/节点只保留并说明，不物理删除 |
| 10 导航帮助文案 | 已实现并自测 | 正式导航 + `/onboarding`、`/help`、`/settings`、`/about`、`/legacy-review`；旧 `/integration`、`/database` 深链接兼容；清除运行时写死的星河/假团队/P1/P6；动态表数量读 `/schema` |
| 11 可迁移 Windows 部署 | 已实现并自测 | `.env.example`；`dev_up.ps1`/`dev_down.ps1` PID 文件与统一端口；Vite 代理共用 `TESTDOCK_PORT`；端口占用明确失败、平台健康检查识别自身；`vendor_sync.py` 移除个人绝对路径 |
| 12 集成验收 | 部分完成 | 隔离数据库行为测试、前端行为/静态测试、类型检查、构建、契约检查；AC 逐项状态见第 5 节；Windows 浏览器与真机验收受阻项如实标注 |

## 2. 追加迁移

`server/alembic/versions/0009_formalization_workspace.py`（`down_revision = "0008"`，只追加，历史迁移未修改）：

- 新表 `workspace_settings`：单行（id=1），名称去空白 1–60 字符 CHECK，默认「默认工作空间」，`customized_at` 记录显式改名时间。
- `projects.origin` / `applications.origin`：仅用于以后显式演示导入的可信来源标记（`manual` / `demo_seed`）；存量行保持 NULL，不倒填「已确认演示」。
- 既有唯一约束（`projects.code`、`uq_applications_project_id_platform_identifier`）已覆盖归档记录仍占用唯一键的要求，无需新增约束。
- `scripts/gen_schema_doc.py` 把 `workspace_settings` 纳入表分组；`server/app/static_data/schema_doc.json` 重新生成（27 张表，含中文注释）。

## 3. 主要改动文件

**后端**：`server/app/config.py`、`errors.py`、`main.py`、`domain/identity.py`（新）、`domain/workspace.py`（新）、`routers/workspace.py`（新）、`routers/onboarding.py`（新）、`routers/legacy_review.py`（新）、`routers/projects.py`、`applications.py`、`overview.py`、`runs.py`、`tasks.py`、`suites.py`、`builds.py`、`baselines.py`、`gate_policies.py`、`debug.py`、`resources.py`、`services/suites.py`、`static_data/schema_doc.json`、`alembic/versions/0009_*.py`。

**前端**：`web/src/store/effectiveContext.tsx`（新）、`store/platform.tsx`（新）、`main.tsx`、`routes.tsx`、`constants.ts`、`api/endpoints.ts`、`api/types.ts`、`types.ts`、`components/layout/{Sidebar,Topbar,navItems}.tsx/ts`、`components/{PageBits,TaskWizard,TaskDrawer,ReportDrawer}.tsx`、`pages/{AppsPage,SettingsPage,AboutPage,OnboardingPage,HelpPage,LegacyReviewPage,OverviewPage,DevicesPage,TasksPage,ReportsPage,UiPage,PerfPage}.tsx`、`styles/tokens.css`、`vite.config.ts`。

**脚本/文档**：`scripts/{dev_up,dev_down}.ps1`、`scripts/seed_demo.py`、`scripts/vendor_sync.py`、`scripts/gen_schema_doc.py`、`README.md`、`.env.example`、`docs/contracts/openapi.json`、`server/tests/test_formalization.py`（新）、`server/tests/test_p6_schema_api.py`、`web/tests/formalization.test.cjs`（新）、`.scratch/product-formalization/hardcoded-inventory.md`（新）。

## 4. 测试与验证

所有后端测试使用 `conftest.py` 自动建立的**独立临时 PostgreSQL 实例**（随机端口、进程私有数据目录），不接触 `127.0.0.1:55432` 正式库或用户已有服务。前端测试不连接外部服务。

| 命令 | 结果 |
| --- | --- |
| `cd server && python -m pytest tests/test_formalization.py -q` | 通过（正式化新增行为测试，含工作空间、能力、身份、归档、范围、旧数据、迁移重复部署） |
| `cd server && python -m pytest tests/test_migration_append_only.py tests/test_migration_structure.py -q` | 通过 |
| `cd server && python -m pytest tests/test_contract_openapi.py -q` | 通过（已用 `scripts/export_openapi.py` 重新导出基线） |
| `cd server && python -m pytest tests/test_import_and_finalize.py tests/test_issue04_run_lifecycle.py tests/test_issue05_report_traceability.py tests/test_issue06_perf_dispatch.py tests/test_issue16_joint_lifecycle.py -q` | 通过（63 项，报告/产物/联动组合） |
| `cd server && python -m pytest tests -q` | 见下方「全套运行说明」 |
| `cd web && npm run typecheck` | 通过 |
| `cd web && npm test` | 通过，77 项 |
| `cd web && npm run build` | 通过 |
| `python scripts/gen_schema_doc.py` | 通过，27 张表 / 265 列 |
| `python scripts/seed_demo.py --dry-run` 及正式库保护 | 通过：无 `--demo` 返回 2；正式默认库返回 2；独立演示库 dry-run 返回 0 |
| PowerShell 解析检查 `dev_up.ps1` / `dev_down.ps1` | 通过 |
| `python -m py_compile` 脚本 | 通过 |

**全套最终结果**：`cd server && python -m pytest tests -q` 通过（exit code 0，进度输出无 `F`，1 项 skip，3 项 DeprecationWarning）。中途曾出现 9 个报告/产物历史测试在完整顺序下失败，根因是本轮新增用例里 `importlib.reload(app.config)` 使 `artifacts.py` 动态读取的 `settings` 与历史用例 monkeypatch 的对象不一致；已移除 reload 并改为纯环境变量断言，最终全套恢复全绿。

## 5. AC-01 ~ AC-16 逐项状态

| 编号 | 状态 | 证据 / 说明 |
| --- | --- | --- |
| AC-01 | 已通过（隔离库） | `0009` 迁移后仅 1 行工作空间设置、无演示业务记录；`test_capabilities_and_onboarding_are_real`、`test_migration_is_append_only_and_can_be_reapplied`；`seed_demo.py` 默认拒绝执行 |
| AC-02 | 已通过（隔离库 + 静态/构建） | 改名、去空白、1–60 校验、保存失败保留输入、刷新读取、侧栏/顶栏统一来源；`test_workspace_default_rename_validation_and_persistence`；前端 `formalization.test.cjs` |
| AC-03 | 已通过（隔离库） | 创建/改名/重复冲突/非法输入/身份不可改/仅 Android；`test_project_application_identity_and_rename` |
| AC-04 | 已通过（隔离库） | queued 运行占用时 409 `archive_blocked` 并列出具体运行 ID，不取消活动；`test_archive_blocks_active_runs_and_rejects_business_writes` |
| AC-05 | 已通过（隔离库） | 归档后 6 类直接写入 409；父子恢复规则、重复归档/恢复幂等；同上用例 |
| AC-06 | 已通过（隔离库，普通并发） | 归档与运行提交共用 `FOR UPDATE` 身份行锁；归档后 `assert_scope_active` 返回 `object_archived`；`test_archive_and_new_run_share_row_level_lock` |
| AC-07 | 已通过（隔离库 API 层） | 双项目同名应用；`/overview`、`/tasks`、`/runs`、`/suites` 项目过滤生效；`test_project_scope_filters_are_served_by_api` |
| AC-08 | 已通过（前端静态 + 服务端校验） | URL/缓存/显式全部/仅 app 解析/冲突/深链接规则；`EffectiveContextProvider` 与 `formalization.test.cjs`；浏览器跨页交互未在本机实际执行 |
| AC-09 | 已通过（服务端契约 + 前端类型/渲染） | 改名只改显示名，ID/编码/标识不变；报告快照新增 `currentNames` 与 `nameSource`，追溯行标「应用/项目当前名称」，不改写修订/结论/证据 |
| AC-10 | 已通过（隔离旧库副本） | 原始 seed / 改名 seed / 真实同名项目区分；不按名称删除；预览过期拒绝；重复执行稳定；`test_legacy_review_*` |
| AC-11 | 已通过（隔离/静态） | 正式拒绝假执行、演示需独立库与独立产物目录、页面持续显示演示标识；能力响应不泄露连接串；`test_formal_start_rejects_fake_runner`、`test_seed_demo_refuses_formal_default_database`、`PlatformProvider` |
| AC-12 | 已通过（服务端响应 + 前端静态） | `/capabilities` 区分平台支持与设备就绪，读取失败不显示可执行；来源未配置/无设备/未支持平台有明确提示；表单示例不自动提交、缺失指标不补零由既有测试覆盖 |
| AC-13 | 已通过（配置/脚本静态） | 统一端口 `TESTDOCK_PORT`（Vite 兼容 `TESTDOCK_API_PORT`）、`TESTDOCK_WEB_PORT`、含空格路径、PID 文件停止、平台健康检查识别自身、`vendor_sync` 显式源；**未在真实另一 Windows 目录实际启停** |
| AC-14 | 已通过（源码/静态 + 构建） | 运行时无写死星河/假团队/P1/P6；旧帮助深链接可达；动态表数量读 `/schema`；长名称 CSS 与较窄窗口响应式规则已加；**100%/125% 缩放与高对比度浏览器实测未执行** |
| AC-15 | 受阻（无可用真机） | 欢迎页到报告/证据的页面流程已接通，设备同步由既有幂等本机节点机制完成；但本环境没有可用 Android 真机与可信套件来源，未执行页面→真机→报告的实际闭环，按规格标为受阻，不用模拟结果冒充 |
| AC-16 | 已通过（隔离库） | 0009 只追加、0001 哈希未变；重复 `alembic upgrade head` 不灌 seed、不改写旧身份；README 有备份/恢复与升级说明 |

## 6. 已知缺口与未执行范围

1. **真机与 Windows 浏览器实测**：AC-15 因无可用 Android 设备未执行；AC-13 的「另一含空格安装目录实际启停」、AC-14 的 100%/125% 缩放/高对比度键盘焦点实测未执行。相关代码与配置已就绪，需在有设备与桌面会话的环境补验。
2. **历史测试隔离问题**：`artifacts.py` 在函数内动态 `from ..config import settings`，历史用例又 monkeypatch 模块级 `settings`；任何对 `app.config` 的 reload 都会放大该不一致。本轮已删除自身 reload，最终全套通过；历史用例对 `settings` 的共享写法仍建议后续单独整理，不列入本轮范围。
3. **浏览器页面流程**：本轮通过前端单元测试、静态契约、类型检查与构建验证；`preview_start` 的自动安全分类器在本环境暂时不可用，未能打开 Browser 面板做实际交互录屏。仓库内保留了隔离 mock API 辅助脚本 `.scratch/product-formalization/preview_mock_api.py`（不连库、不写文件、不接触用户服务），编排方可用它在 8010 端口配合 `web/vite.verify.config.ts` 检查长中文名称、能力摘要、上下文与错误态；真实服务端行为已由独立 PG 测试覆盖。
4. **历史收尾问题**（规格 §10 明确另列）：联动空异常漏判、vendor 缓存校验、远程 CI 实跑不在本轮范围，未宣称解决。
5. 未 commit / push / 创建 PR / 发布 / 安装新依赖 / 修改 vendor 源码；未清理或覆盖用户已有文件与数据。

## 7. 交付物位置

- 规格与工单：`.scratch/product-formalization/`
- 硬编码清单：`.scratch/product-formalization/hardcoded-inventory.md`
- 实现报告：`.scratch/product-formalization/implementation-report.md`
- 配置示例：`.env.example`
- 正式安装/升级/备份/演示说明：`README.md`
- 契约基线：`docs/contracts/openapi.json`
- 数据设计字典：`server/app/static_data/schema_doc.json`
