# TestDock 首期核心流程与交付验收记录

- 记录时间：2026-11-01 12:26–13:00（本机时间，Windows 10.0.26200.9711）
- 依据：`spec.md`（31 条 User Stories + Integration/Testing Decisions）、工单 01–09 的实现与 Comments、`GLOSSARY.md` 领域术语
- 工单：[10: 首期交付验收记录](issues/10-acceptance-record.md)
- 记录方式：在集成分支最终 HEAD 上**重新执行**验证；工单 Comments 里的数字只作为历史证据引用，并标注日期，不代替本次结果。
- 本工作区（`worktree-frc-10`，基于 `cf9f799`）除本文件外未改动任何产品代码、工单或证据文件。
- 附节 §7 记录验收之后的代码评审修复与复跑（代码 HEAD 已从 `cf9f799` 前进），§2 的逐条状态判定不变，真机/来源/像素核对仍未执行。

## 状态口径

| 状态 | 含义 |
| --- | --- |
| 已通过 | 当前 HEAD 上本次重跑的自动化/契约测试或可直接观测的环境事实，覆盖了该条的用户可见行为（可使用受控夹具、fake 适配器） |
| 已实现待验 | 实现存在且本次自动化通过，但该条的验收场景需要真机或真实可信来源，本轮条件不具备，真实条件验证未执行 |
| 未完成 | 未实现或缺证据 |
| 受阻 | 环境条件缺失导致该条在本次无法验证（实现可能存在） |

## 1. 版本与范围

| 项 | 值 | 来源 |
| --- | --- | --- |
| 集成分支 | `integration/first-release-closure`，tip `cf9f799` | `git log -1 integration/first-release-closure`（本次） |
| 验收 HEAD | `cf9f799f8ab8017ce139a5f262b17a0a6cbab2e5`（`docs(issue09): 记录四态修复、九页 DOM 证据与视觉待验项并标记 resolved`） | 本次 `git rev-parse HEAD` |
| 验收工作区 | `D:\workspace\claudecode-test\testplat-auto\.claude\worktrees\frc-10`，分支 `worktree-frc-10` | 本次 |
| 数据库迁移 head | `0008 (head)` | 本次 `alembic heads`（server 目录、未设 `TESTDOCK_DATABASE_URL`，只读） |
| 原型参考 | `docs/platform-prototype/index.html`，sha256 `576d5402238a198ef6a64ae3e92f8f76e7cbe883f91712643d57e90134ed4d5f`，180445 bytes | 本次重算 `sha256sum` / `wc -c`，与工单 09 记录一致 |
| Python | 3.12.10（`D:\python312\python.exe`） | 本次 |
| Node / npm | Node v24.14.0 / npm 11.9.0 | 本次 |
| 操作系统 | Windows 10.0.26200.9711 | 本次 |
| 测试库 | `testdock_frc10`（专用，`alembic_version=0008`）；隔离库 `testdock_frc01`…`testdock_frc10` 均存在 | 本次 `select current_database()` / `pg_database` |
| 共享库 | `testdock` 的 `test_runs` 总行数 0、近 6 小时新增 0 → 本次未向共享库写入任何测试运行 | 本次只读 SQL |
| 设备 | `749622c9` 在线可用；其余 7 台离线（共 8 台） | `evidence/05-devices.json`（2026-11-01，主代理采集）+ 本次未占用设备 |
| 可信套件来源 | 未配置：`GET /api/v1/suite-sources` → `{"items":[],"total":0}` | 本次 `curl http://localhost:8000/api/v1/suite-sources`（2026-11-01 12:58） |
| 常驻服务 | `:8000` 为分支之前的旧进程（同一端点响应缺工单 02 的 `hint` 字段），**不作为本次验收依据**；`:5173` 由 Vite 直接读盘，已反映 HEAD 前端 | 本次 `curl`（8000 返回体无 `hint`；5173 返回 200） |

范围：单工作空间、同机 Android 首期。out-of-scope 见 `spec.md`：多用户/组织/权限、Web/iOS 真实执行、跨机器调度、实时性能曲线、对象存储、应用 CRUD/上传/安装、设备自动修复、调试触控、修改 `vendor/`。

## 2. 逐项验收表

### 2.1 31 条 User Stories

| # | 用户故事（简） | 状态 | 证据（本次执行优先） | 条件与备注 |
| --- | --- | --- | --- | --- |
| 1 | 看到可用的可信套件来源 | 受阻 | 现场：`GET /api/v1/suite-sources` → `{"items":[],"total":0}`；来源机制与空态由 `test_issue05_suite_sources.py`(9)、`test_issue02_source_lifecycle.py`(3) 钉住 | 需宿主配置 `TESTDOCK_SUITE_SOURCES` 指向受控目录；本轮无可用来源，不伪造 |
| 2 | 没有来源时看到明确提示 | 已通过 | `test_issue02_source_lifecycle.py::test_empty_sources_are_explicit_and_path_free`；`web/tests/ui-suites.test.cjs::来源为空时提示需要宿主配置，且不提供路径输入` | 提示由后端 `hint` + 前端 `suiteSourceEmptyHint` 给出；未配置来源即为当前真实状态 |
| 3 | 来源由宿主预配置，浏览器不能指定宿主路径 | 已通过 | `test_issue02_source_lifecycle.py::test_host_path_field_is_rejected_without_echo`；`test_issue05_suite_sources.py::test_suite_sources_hides_host_paths`；`test_error_contract.py`(7) | 校验错误信封只留 `type/loc/msg`，不回显路径 |
| 4 | 登记套件并发现用例 | 已实现待验 | `test_issue05_suite_sources.py::test_create_suite_publishes_v1_with_code_copy`、`test_issue02_source_lifecycle.py::test_failed_collect_keeps_copy_but_publishes_no_version`（受控夹具目录） | 真实来源登记/发现未执行（来源为空） |
| 5 | 每次发现生成固定套件版本 | 已通过 | `test_issue05_suite_sources.py::test_old_version_keeps_v1_after_source_changes`、`test_create_suite_publishes_v1_with_code_copy`；`test_issue05_report_traceability.py::test_rediscovery_new_suite_version_does_not_rewrite_history` | 重新发现只追加新版本，旧版本 manifest/摘要不变 |
| 6 | 版本固定代码快照，来源变化仍执行原内容 | 已通过 | `test_issue01_execution_copy.py::test_pytest_runs_inside_copy_after_live_source_is_broken`（不同标记副本 vs 已改来源） | 副本即执行内容；来源变更不影响既有版本 |
| 7 | 缺失或损坏快照阻断执行 | 已通过 | `test_issue01_execution_copy.py::test_missing_suite_root_blocks_without_running_pytest`、`test_suite_root_that_is_not_a_directory_is_blocked`、`test_out_of_bounds_targets_are_blocked`、`test_absolute_target_inside_copy_is_still_rejected`；`test_issue05_suite_sources.py::test_corrupted_copy_blocks_execution`、`test_legacy_version_without_copy_is_marked_and_blocked`；`test_issue24_execution_wiring.py::test_dispatch_blocked_when_copy_content_tampered` | 缺失→`execution_copy_unavailable`、越界→`suite_path_out_of_bounds`，不回退来源目录 |
| 8 | 选择应用和构建版本 | 已通过 | `test_issue04_builds.py`(14)（含 `test_register_build_enforces_application_scope_and_sha256`）；`web/tests/task-wizard.test.cjs`(9)（未选登记应用不能继续） | 构建登记与向导字段一致 |
| 9 | 核对设备已安装应用的身份 | 已实现待验 | `test_issue04_builds.py::test_identity_check_is_read_only_and_records_expected_observed`、`test_busy_device_is_not_probed`；`test_issue24_execution_wiring.py::test_dispatch_happy_path_passes_suite_root_and_verifies_identity` | 自动化用 fake adb；真机 `749622c9` 上的身份复核实测未执行 |
| 10 | 确认首次识别的身份基准 | 已通过 | `test_issue04_builds.py::test_confirm_identity_fixes_baseline_and_is_idempotent`、`test_version_name_conflict_rejects_confirmation`、`test_confirmed_build_is_not_relearned_from_another_device` | 只有用户明确确认才 `pending → confirmed` |
| 11 | 看到身份不可读取或不一致的原因 | 已通过 | `test_issue04_builds.py::test_unreadable_identity_fields_block`、`test_uninstalled_package_is_conflict`；`test_issue24_execution_wiring.py::test_identity_mismatch_blocks_dispatch`、`test_identity_unreadable_blocks_dispatch_with_readable_reason`；`web/tests/task-wizard.test.cjs`（原因可读、可修正后重试） | unreadable 与 mismatch 均阻断；事件 payload 标 `apk_digest_verified=false` |
| 12 | 创建并验证任务修订 | 已通过 | `test_issue04_run_lifecycle.py::test_task_edit_appends_immutable_revision_and_validation_is_explicit`、`test_task_name_conflict_and_idempotency_key_semantics` | 修订不可变；`readiness=validated` 只能由显式验证产生 |
| 13 | 从已验证修订启动运行并跟踪状态/进度/事件 | 已实现待验 | `test_issue04_run_lifecycle.py::test_draft_revision_cannot_start_run_and_validated_revision_enqueues`、`test_terminal_run_is_immutable_and_outcome_only_on_completed`、`test_events_replay_by_sequence_and_duplicate_delivery_adds_no_rows`；`web/tests/run-tracking.test.cjs`(3) | 需真实 UI 套件+真机才有完整端到端运行；本轮无真实运行 id |
| 14 | 取消运行并看到最终状态 | 已实现待验 | `test_issue04_run_lifecycle.py::test_cancel_running_run_kills_process_tree_releases_lease_and_frees_device`、`test_runner_exit_after_accepted_cancel_converges_to_cancelled_not_errored` | 自动化含双 pid 进程树终止与设备再领取；真机 adb/vendor 锁释放时延未观测 |
| 15 | 设备被占用时排队或拒绝 | 已通过 | `test_issue04_run_lifecycle.py::test_busy_requested_device_never_runs_two_runs_concurrently`、`test_requested_device_unavailable_converges_with_its_own_reason`；`test_issue16_joint_lifecycle.py::test_joint_dispatch_holds_one_lease_for_both_components`；`web/tests/task-wizard.test.cjs`（在线占用可排队，离线不可选） | 租约在 DB 层生效，与设备型号无关 |
| 16 | 查看失败截图、日志和断言 | 已实现待验 | `test_issue05_report_traceability.py::test_failed_run_report_locates_screenshot_log_and_assertions`；`web/tests/report-and-debug.test.cjs`(8)；`evidence/07-reports.json`（真实空态文案） | 真机失败产物（截图/junit）未产生；报告定位能力由夹具运行覆盖 |
| 17 | 报告追溯构建、修订、套件版本、资源档案与证据 | 已通过 | `test_issue05_report_traceability.py`(11)，含 `test_report_includes_suite_version_and_code_copy`、`test_report_marks_absent_suite_and_code_copy_as_null`、`test_paginated_search_still_opens_full_report`；`web/tests/report-and-debug.test.cjs::报告追溯行展示套件版本、副本摘要、构建、修订与档案，缺失如实` | 缺失为 null，不用别的版本冒充；导出与页面同源 |
| 18 | 独立性能运行采集指定指标和时长 | 已实现待验 | `test_issue06_perf_scenario.py`(34)（10–3600 整数秒、items 非空双向锁死）；`test_issue06_perf_dispatch.py::test_performance_run_dispatches_without_code_copy`、`test_performance_run_report_claims_no_ui_execution` | 真机性能采集未执行，不伪造指标 |
| 19 | 样本或可比条件不足时看到未判定及原因 | 已通过 | `test_perf_gate_api.py::test_sample_below_minimum_is_not_tested_with_actual_sample_count`、`test_gate_policy_missing_is_not_tested`、`test_metrics_endpoint_returns_missing_metrics_as_null`、`test_metric_summaries_check_rejects_zero_for_missing_metric`；`test_issue12_analysis_selection.py::test_analysis_reports_real_metrics_without_zero_fill` | 缺失指标 NULL + `missing_reason`，不补零 |
| 20 | 基线按应用和资源档案比较 | 已通过 | `test_issue13_original_freeze.py::test_no_same_profile_baseline_records_missing_not_cross_profile`、`test_same_profile_baseline_is_used_and_retry_is_idempotent`；`test_perf_gate_api.py::test_cross_profile_baseline_is_not_tested_with_profile_mismatch`；`test_profiles.py` 归一化用例（全量运行内） | 档案不匹配给出具体原因 |
| 21 | 规则试算保留原始判定和历史报告 | 已通过 | `test_perf_gate_api.py::test_threshold_change_only_adds_reanalysis_and_keeps_original`、`test_evaluation_request_key_is_idempotent`；`test_issue14_historical_reanalysis.py::test_completed_run_without_original_gets_reanalysis_not_fabricated_original`；`test_issue12_analysis_selection.py::test_analysis_defaults_to_original_verdict` | original 与 reanalysis 分表保留，按 id 可查 |
| 22 | 联动运行在同一次 UI 执行期间采集性能 | 已实现待验 | `test_issue16_joint_lifecycle.py::test_joint_ui_window_caps_ui_execution_deadline`、`test_joint_real_ui_timeout_finalizes_collect_scope`、`test_joint_ui_timeout_stops_collection_and_records_window`、`test_dispatch_joint_merges_manifest_ui_timeout` | 窗口/超时/收口逻辑已通过；真机联动运行未执行 |
| 23 | 联动分别展示 UI 和性能结果及异常原因 | 已通过 | `test_issue16_joint_lifecycle.py::test_joint_job_reports_two_components_with_real_collect_window`、`test_report_exposes_collect_window`、`test_ui_timeout_failure_still_registers_collect_window`、`test_matrix_ui_assertion_failure_is_completed_failed`、`test_matrix_collect_start_failure_is_errored_with_cancelled_ui`、`test_matrix_cancelled_joint_keeps_components_without_outcome` | 非 completed 组件 outcome 为 NULL；失败矩阵按实际状态 |
| 24 | 调试会话显示实际设备、实时画面和连接状态 | 已实现待验 | `test_issue17_debug_templates.py`、`test_p5_debug_api.py`(11)（会话创建/关闭、WS 状态）；`web/tests/debug-crop-state.test.cjs`(7) | 本轮未占用真机；历史真机调试记录为 2026-10-31（旧版，不能代表当前 HEAD） |
| 25 | 冻结同一次画面和节点树 | 已通过 | `test_frc08_debug_registration.py::test_verification_is_bound_to_the_fresh_capture_and_matched_box`；commit `e673983`（冻结快照同源测试）；`test_issue17_debug_templates.py` | 采集时刻同源由自动化钉住；真机冻结未重跑 |
| 26 | 框选后先验证真实匹配再登记模板版本 | 已通过 | `test_frc08_debug_registration.py`(10)，含 `test_registration_without_verification_is_rejected`、`test_failed_match_issues_no_verification_and_blocks_registration`、`test_verification_is_single_use`；`test_crop_validation.py::test_real_vendor_match_accepts_crop_and_rejects_absent_crop` | 服务端一次性凭证（TTL 120s），前端禁用只是体验层 |
| 27 | 刷新或恢复预览后清除旧匹配和颜色框 | 已通过 | `test_frc08_debug_registration.py::test_verification_is_invalidated_by_region_snapshot_or_threshold`、`test_verification_expires`；`web/tests/debug-crop-state.test.cjs`(7) | 清除临时态但不删除已登记模板 |
| 28 | 模板跨会话可查并能在修订中固定版本 | 已通过 | `test_frc08_template_library.py`(4)，含 `test_registered_template_survives_new_session_and_reload`、`test_pins_sha256_mismatch_blocks_dispatch`；`test_issue25_template_library.py`、`test_template_library_read.py`(3) | 共享根 `server/assets`；pin 不符 → `template_pin_mismatch` |
| 29 | 异常、空态和不可用操作有明确说明 | 已通过 | `web/tests/page-states.test.cjs`(10)，含 `pagePhase 先判加载…`、`加载态在 DOM 上与真实空态可区分`、`九个页面都按 isLoading 分支…`、`复制表达式只在剪贴板真正写入后提示成功`；本次 `npm test` 47 passed；九页 DOM 证据 `evidence/01-overview.txt`…`09-database.json` | 视觉像素核对未做（见 §5），不宣称视觉对齐 |
| 30 | 每项结论记录版本、条件和证据 | 已通过 | 本文件 §1–§3（HEAD、迁移 head、原型哈希、库/设备/来源条件、本次命令与结果） | 本次执行与历史证据分开标注 |
| 31 | 外部服务或设备不可用时记录阻塞原因，不把未执行记为通过 | 已通过 | 本文件 §3 未执行项与 §5、§6；US1 标「受阻」、真机相关标「已实现待验」 | 无「未执行却写成已通过」的条目 |

### 2.2 Integration / Testing Decisions 核对

| 决策 | 状态 | 证据与说明 |
| --- | --- | --- |
| 以页面到真实后端的完整流程为最高层验收入口 | 已实现待验 | 九页 DOM/可访问树核查（2026-11-01，主代理）22 个 XHR 全 200、无 console error，见证 `evidence/`；但页面数据来自 **旧 :8000 进程**，且真机流程未执行 |
| 隔离数据库、受控套件、临时产物目录，不覆盖共享库 | 已通过 | 本次在 `testdock_frc10` 全量运行；`testdock` 共享库 `test_runs` 总计 0、近 6h 新增 0 |
| 用不同标记副本与后续修改的来源验证发现/执行/报告同一版本 | 已通过 | `test_issue01_execution_copy.py`(17)；`test_issue05_suite_sources.py::test_old_version_keeps_v1_after_source_changes` |
| 覆盖副本缺失、篡改、越界、依赖与相对导入 | 已通过 | `test_issue01_execution_copy.py` 同上 + `test_dispatch_blocked_when_copy_content_tampered`；`test_execution_leaves_copy_tree_unchanged`（执行前后文件集合与 sha256 不变） |
| 通过页面或真实接口验证构建身份、任务验证、运行跟踪、取消与释放 | 已通过（接口层） | `test_issue24_execution_wiring.py`(9)、`test_issue04_run_lifecycle.py`(9)；页面侧 `task-wizard` / `run-tracking` 前端测试。真机条件未执行 |
| 在可用真机上分别验证 UI、独立性能和联动 | 受阻 | 本轮不占用 `749622c9`：来源为空、`:8000` 调度器为旧代码。模拟矩阵已覆盖失败矩阵，不作真机结论 |
| 验证原始判定/试算分离、基线可比、缺失指标与未判定原因 | 已通过 | `test_issue12/13/14`、`test_perf_gate_api.py`(22)、`test_profiles.py`（全量） |
| 调试交互：设备选择、关闭释放、冻结、节点拾取、框选验证、登记、刷新与恢复预览 | 已实现待验 | `test_frc08_*`(14)、`test_crop_validation.py`(3)、`web/tests/debug-crop-state.test.cjs`(7)；真机调试会话未重跑 |
| 执行前端构建/相关测试与后端回归 | 已通过 | §3 的 tsc / npm test / npm run build / 后端全量 |

### 2.3 状态计数

| 状态 | 条数 | 条目 |
| --- | --- | --- |
| 已通过 | 22 | 2,3,5,6,7,8,10,11,12,15,17,19,20,21,23,25,26,27,28,29,30,31 |
| 已实现待验 | 8 | 4,9,13,14,16,18,22,24 |
| 未完成 | 0 | — |
| 受阻 | 1 | 1 |
| 合计 | 31 | — |

## 3. 本次实际执行的验证

全部在 HEAD `cf9f799`、工作区 `frc-10`、库 `testdock_frc10`（0008）上执行。

| # | 命令（工作目录） | 时间 | 结果 | 判定方式 |
| --- | --- | --- | --- | --- |
| 1 | `TESTDOCK_TEST_DATABASE_URL=…/testdock_frc10 D:/python312/python.exe -m pytest tests/ -q`（`server/`） | 12:27–12:47 | **退出码 0**；进度到 `[100%]`；无 FAILED、无 ERROR；唯一 `s`=1 | 该项目 `pyproject.toml` 有 `addopts = "-q"`，命令行再传 `-q` 等于 `-qq`，**不打印 `N passed` 收尾行**（历史记忆里"日志无 passed"即此原因）。故以「退出码 0 + 进度 100% + 无 F/E + skip 计数」判定；另用 `--collect-only` 统计用例总数为 **544**，进度行共 544 个字符、其中 `s` 1 个 → **543 passed / 1 skipped / 0 failed** |
| 2 | 定向子集：`pytest -o addopts="" -q -rs` 运行 01/02/03/04/05/06/07/08 相关 19 个文件（见下） | 12:48–12:54 | **`200 passed, 1 warning in 239.26s`，退出码 0** | 覆盖 `addopts` 后恢复收尾行，得到确定计数；warning 为 `PytestAssertRewriteWarning`（插件重复导入，非失败） |
| 3 | `alembic heads`（`server/`，未设 `TESTDOCK_DATABASE_URL`） | 12:27 | **`0008 (head)`**，退出码 0 | 只读执行，不连业务库 |
| 4 | `npx tsc -p tsconfig.json --noEmit`（`web/`） | 12:35 | 无输出，**退出码 0** | 类型检查 |
| 5 | `npm test`（`web/`） | 12:35 | **47 pass / 0 fail / 0 skipped**（`tests 47`，duration 1440ms） | `node --test`，文件：contract 1、debug-crop-state 7、page-alignment 3、page-states 10、report-and-debug 8、run-tracking 3、task-wizard 9、ui-static 2、ui-suites 4 |
| 6 | `npm run build`（`web/`） | 12:36 | **退出码 0**：`tsc -b && vite build`，128 modules，`dist/assets/index-DnSIoJcW.css` 34.62 kB、`index-BeGlwnDd.js` 368.41 kB | 生产构建产物生成 |
| 7 | 契约检查 | 12:48–12:54 | 含在定向子集内：`test_contract_openapi.py`(7)、`test_error_contract.py`(7) 全通过 | `docs/contracts/openapi.json` 基线与代码一致、错误信封字段完整、内部协议不外露 |
| 8 | 库隔离核查（只读 SQL） | 12:44 | `current_database()=testdock_frc10`、`alembic_version=0008`；`pg_database` 含 `testdock`、`testdock_audit`、`testdock_frc01…frc10`；共享 `testdock`.`test_runs` 总 0 / 近 6h 0 | 证明未向共享库写入测试运行 |
| 9 | 原型哈希重算 | 12:40 | `576d5402…34ed4d5f`，180445 bytes | 与工单 09 一致 |
| 10 | 服务探测 | 12:58 | `:8000/api/v1/suite-sources` → `{"items":[],"total":0}`（无 `hint`，旧代码）；`:5173/` → 200 | 确认来源为空，且常驻 API 不代表 HEAD |

定向子集（#2）文件与用例数（`--collect-only` 实测）：`test_issue01_execution_copy.py` 17、`test_issue02_source_lifecycle.py` 3、`test_issue05_suite_sources.py` 9、`test_issue04_builds.py` 14、`test_issue24_execution_wiring.py` 9、`test_issue04_run_lifecycle.py` 9、`test_issue05_report_traceability.py` 11、`test_issue06_perf_dispatch.py` 7、`test_issue06_perf_scenario.py` 34、`test_issue16_joint_lifecycle.py` 21、`test_issue12_analysis_selection.py` 4、`test_issue13_original_freeze.py` 5、`test_issue14_historical_reanalysis.py` 4、`test_perf_gate_api.py` 22、`test_frc08_debug_registration.py` 10、`test_frc08_template_library.py` 4、`test_crop_validation.py` 3、`test_contract_openapi.py` 7、`test_error_contract.py` 7（合计 200）。

全量运行中唯一的 skip：`tests/test_03_code_copy.py:119`「当前环境不能创建文件符号链接」——Windows 权限能力限制，与本次验收结论无关（同一文件其余 17 项通过）。

### 3.1 本轮未执行项

| 未执行项 | 原因 | 解除条件（需谁提供什么） |
| --- | --- | --- |
| 真机 UI 运行（749622c9）— US13/16、决策「真机 UI」 | 可信套件来源为空，无可登记套件；`:8000` 常驻调度器为分支前旧代码，用它派发不能代表 HEAD | 宿主配置 `TESTDOCK_SUITE_SOURCES` 指向受控套件目录并以 HEAD 启动后端；用户授权占用 `749622c9` |
| 真机独立性能采集 — US18 | 同上（需真实构建/设备与授权） | 同上 + 登记真实构建版本与资源档案 |
| 真机联动运行 — US22 | 同上；联动需要 UI 副本 + 同一独占期 | 同上 |
| 真机调试会话（实时画面、冻结、框选、登记）— US24 | 本轮不占用设备；2026-10-31 的历史记录早于 08 的验证门与共享模板库改动 | 用户授权占用 `749622c9`，后端以 HEAD 启动后重跑 `test_issue17` 对应手工流程 |
| 真实来源下的套件登记/发现 — US1/4 | 来源为空属环境事实 | 宿主配置来源后按 `test_issue05_suite_sources.py` 的口径复核 |
| 1440×900 像素级视觉核对 — US29 备注 | 内置浏览器无可见视口（`NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`，证据文件里 4 份 `viewport 0×0`，另 4 份为 1145×1145），截图不可得；`agent-browser` 启动挂起 | 提供可截图的浏览器视口（或允许启动独立浏览器），按 1440×900 重采 |
| 页面 ↔ HEAD 后端的同版数据证据 | `:8000` 为旧进程（响应缺 `hint`） | 以 HEAD 重启后端后，重跑九页 XHR/DOM 采集 |
| 证据「过期」态的自然出现 | `TESTDOCK_ARTIFACT_RETENTION_DAYS` 默认 0（未启用保留期） | 宿主配置保留天数，或待产物被清理 |
| 真实 APK 字节摘要验证 | 不在首期范围（规格只要求核对安装包字段） | 不在解除清单 |

## 4. 发现并修复的范围内缺陷

均为本次验收前在 01–09 中修复并合入集成分支；「本次复验」列是本轮 HEAD 上的重跑结果（历史为 2026-11-01 实现时的记录，仅供对照）。

| 工单 | 缺陷（已修复） | 实现提交 | 合并 / 记录提交 | 本次复验（HEAD `cf9f799`） |
| --- | --- | --- | --- | --- |
| 01 | 派发把固定副本写进 spawn 配置，但 runner 不读：`cwd` 仍为 `server/`、目标默认 `tests/`，来源被改后执行的不是副本内容；assets/artifacts 相对路径会写进副本 | `60ecbe1`、`5484f0c` | 合并 `428df88`；记录 `e919ddf` | `test_issue01_execution_copy.py` 17 项通过（含来源破坏后仍跑副本、越界拒绝、副本树摘要不变、joint 同接线）；`test_issue24_execution_wiring.py::test_spawn_config_carries_suite_version_and_tree_digest` |
| 02 | 空来源静默留空下拉；校验错误回显请求值（含宿主路径）；旧版本无副本时未要求重新发现 | `5ec2416` | 合并 `cda1893`；记录 `019492f` | `test_issue02_source_lifecycle.py` 3 项 + `test_issue05_suite_sources.py` 9 项通过；`web/tests/ui-suites.test.cjs` 4 项通过 |
| 03 | adb 不可读被当成"无从复核"继续执行；包名未白名单校验；复核结论未落事件；页面不显示阻断原因 | `0801718` | 合并 `2b8430f`；记录 `e8a9b0f` | `test_issue04_builds.py` 14 项 + `test_issue24_execution_wiring.py` 9 项通过（mismatch/unreadable/pending 三态与租约释放） |
| 04 | 取消 running 的 run 只写 `cancel_requested_at`，不终止进程树，设备可能被占至超时 | `b464319` | 合并 `efd8683`；记录 `b2d4185` | `test_issue04_run_lifecycle.py` 9 项通过（含双 pid 死亡、租约释放、设备再领、事件重放去重） |
| 05 | 报告缺套件版本与副本摘要；证据只有 `available`，missing/expired 生产不可达 | `974bc2b` | 合并 `5d42a3d`；记录 `d242a31` | `test_issue05_report_traceability.py` 11 项通过（三态、过期原因、失败产物定位、历史不被改写） |
| 06 | 独立性能被误判 `execution_copy_missing`；性能场景 10–3600 未校验；修订与清单两份场景声明会漂移 | `d744aab`、`aeb96a7` | 合并 `a8733db`（含 `bb87079` `56e4620`）；记录 `8c68484` | `test_issue06_perf_dispatch.py` 7 项 + `test_issue06_perf_scenario.py` 34 项通过（runner 与平台窗口双向锁死） |
| 07 | `ui_timeout_s` 只是装饰；UI 超时不停采不写 report；清单 `ui_timeout_s` 不参与派发；`collectWindow` 被报告丢弃 | `c9bfc8e` | 合并 `631d41d`；记录 `8b8328c` | `test_issue16_joint_lifecycle.py` 21 项通过（窗口覆盖、超时收口、矩阵终态、报告透出） |
| 08 | 模板登记只有前端 disabled 一道防线，服务端可被绕过；验证返回的新快照未被登记使用；模板库存储口径矛盾 | `e7c35a2`、`e673983` | 合并 `7d322b3`；记录 `959b8bf` | `test_frc08_debug_registration.py` 10 项 + `test_frc08_template_library.py` 4 项 + `test_crop_validation.py` 3 项通过 |
| 09 | 四处把加载态当空态；Overview 脚注把加载失败写成"接口未接入"；剪贴板失败仍提示成功；disabled 动作无原因 | `ee15159`、`289b5c8` | 合并 `223eaad`（含测试 `2a5a934`、`f3f84b9`）；记录 `cf9f799` | `web/tests/page-states.test.cjs` 10 项通过；`npm test` 47 passed；`tsc --noEmit`、`npm run build` 通过 |

历史对照（2026-11-01，非本次）：工单 04 记录代理全量 465 passed / 1 skipped；工单 07 记录 543 passed / 1 skipped；工单 08 记录定向 26 passed、前端 35 通过。本次 HEAD 全量为 543 passed / 1 skipped（用例总数已增至 544）。

## 5. 已知边界与后续

1. **真机证据缺项**：UI、独立性能、联动、调试会话四类真机运行本轮全部未执行（来源为空 + 常驻后端为旧代码），因此首期"真实设备端到端"结论只到自动化与契约层。
2. **可信来源未配置**：真实来源下的登记/发现/真实副本执行无法验收；来源列表为空是当前环境事实，不是缺陷。
3. **常驻进程版本错配**：`:8000` 启动早于本分支，`/suite-sources` 缺 `hint` 等 02 改动；页面数据核查基于旧后端（`:5173` 前端为 HEAD）。需要以 HEAD 重启后端才能取得"同版页面↔后端"证据。
4. **视觉核对未完成**：九页 DOM/可访问树证据齐全（2026-11-01 主代理核查：22 个 XHR 全 200、无 console error，见证 `evidence/`），但 1440×900 像素级比对因内置浏览器无可见视口（证据中 4 份 `viewport 0×0`、另 4 份 1145×1145；截图接口 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`，`agent-browser` 启动挂起）未取得，标「已实现待验」，不宣称视觉对齐。
5. **证据过期态不可自然出现**：`TESTDOCK_ARTIFACT_RETENTION_DAYS` 默认 0；三态中 `expired` 需宿主配置保留期或产物被清理才可观测（工单 05 遗留）。
6. **框选验证凭证存进程内**：多 worker 部署需共享存储（工单 08 遗留）；阈值成为登记必填字段。
7. **联动 `ui_timeout_s` 以套件清单为准**：修订中的冲突值被版本快照覆盖（工单 07 遗留）；`collectWindow` 的报告页展示已由评审修复补齐（见 §7），不再留待后续。
8. **环境能力限制**：`test_03_code_copy.py:119` 因 Windows 权限无法创建文件符号链接而跳过（1 项），与产品行为无关。
9. **out-of-scope**（`spec.md`）：多用户登录/组织/权限、Web/iOS 真实执行、跨机器调度、实时性能曲线、对象存储、应用 CRUD/上传/自动安装、设备自动修复、调试触控、修改 `vendor/`。

## 6. 结论

- **自动化与契约层面：满足。** HEAD `cf9f799` 上后端全量 544 项（543 passed / 1 skipped / 0 failed，退出码 0）、定向验收子集 200 passed、前端 47 passed、`tsc --noEmit` 与 `npm run build` 通过、`alembic heads` 为 `0008`、契约基线一致；31 条用户故事中 22 条已在本次重跑中获得通过依据。
- **首期交付验收：有条件通过（未完全满足）。** 「来源 → 固定版本/副本 → 任务修订 → 运行/取消/独占 → 报告 → 独立性能/联动 → 调试 → 页面四态」这条链路在代码、自动化与页面状态层已被证据覆盖，但**真机执行**与**真实可信来源**两类必需证据本轮缺失，不能记为通过。
- **不满足点（须在解除条件满足后补验，方可视为首期交付完成）：**
  1. 真机 UI 运行（749622c9）未执行：无运行 id、报告与失败证据。
  2. 真机独立性能采集未执行：无真实指标与未判定样例。
  3. 真机联动运行未执行：无真实采集窗口与双组件结果。
  4. 真机调试会话（实时画面、冻结、框选验证、登记）未重跑：仅有 2026-10-31 的旧版历史记录。
  5. 真实可信套件来源未配置：US1 受阻，US4 待验，真实副本执行的"来源变更仍执行原内容"缺少真实来源侧的观测。
  6. 1440×900 像素级视觉核对与"页面 ↔ HEAD 后端"同版数据证据缺失。
- 未执行项一律标注原因与解除条件（§3.1），本记录不把任何未执行项写成已通过。

## 7. 代码评审与修复（验收之后）

- 触发：在集成分支上执行 `code-review` 两轴评审（Standards / Spec），固定点 `9756484`（`integration/prototype-alignment` 起点），评审范围 46 commits / 86 files。
- 评审提出 14 条：采纳并修复 8 组；驳回 1 条（"取消会覆盖已 completed 的运行"——`runtime.finalize_run` 对终态短路，取消不会改写完成态，经代码与测试证伪）；其余为本地工单约定、风格判断或有意保留的范围，明确不改。
- 修复内容与复验：

| 组 | 缺陷（评审发现） | 修复要点 | 复验测试 |
| --- | --- | --- | --- |
| 1 | 取消收敛不登记已落盘产物，报告页丢失同一次运行写出的 `report.json` / 采集窗口 | `cancel_run` 收敛时传 `artifacts_dir`（与 `spawn._finalize_after_exit` 同口径） | `test_issue04_run_lifecycle.py::test_cancel_running_run_registers_artifacts_already_on_disk` |
| 2 | `terminate_run_process` 无条件返回 True，`runner_terminated` 谎报已终止 | 按 taskkill 退出码 + 是否观测到进程退出判定；没有 pid 或杀不掉时为 False | `test_issue04_run_lifecycle.py::test_terminate_run_process_reports_whether_a_process_was_really_killed` |
| 3 | 派发事务提交与 spawn 之间取消已受理，仍会拉起"幽灵 runner" | spawn 前只读复查 `cancel_requested_at` / state，终态与租约交给取消路径收敛 | `test_issue24_execution_wiring.py::test_cancel_requested_in_dispatch_window_blocks_spawn` |
| 4 | 客户端 `snapshot_id` 原样拼进 vendor URL（路径穿越 / 查询串） | 只放行 vendor 真实 id 空间（`uuid4().hex[:16]`），validate-crop 与 image/tree 代理一致 | `test_frc08_debug_registration.py` 的非法 id 参数组（9 项）+ `test_proxy_snapshot_id_endpoints_reject_illegal_snapshot_id` |
| 5 | 调试会话关闭后框选验证凭证仍可用到 TTL 结束 | 会话关闭（DELETE / spawn 失败）按 session 清理该会话全部凭证，TTL 仅兜底 | `test_frc08_debug_registration.py::test_closing_debug_session_drops_its_crop_verifications` |
| 6 | 报告页不展示 `collectWindow` | `ReportDrawer` 增加「采集窗口」段；无窗口时如实写「无联合采集窗口」，不编造时间 | `web/tests/report-and-debug.test.cjs`（采集窗口用例） |
| 7 | 契约文档未跟上新枚举与语义 | `docs/plan/api-design.md`、`docs/plan/data-model.md` 补：取消主动终止与 `runner_terminated`、取消/失败登记产物、`crop_not_verified`、快照 id 规则、`collectWindow`、运行级 `reason_code` 表 | 逐条与代码核对 |
| 8 | 死代码 | 删除未使用的 `_scenario_problems` 别名与 `effective_availability(now=)` 参数 | 全量回归 |

- 提交：修复 `cba314a`、测试 `f810806`、契约文档 `57f9cd5`，合并 `4b4fea2`；随后文档措辞修正 `96c6bec`（调试会话没有"runner 退出兜底"清理路径，改为 DELETE / spawn 失败 + TTL 兜底）。
- 本次复跑（评审修复后的 HEAD，库 `testdock_frc10`，迁移仍 `0008`）：
  - 后端全量：**559 项，558 passed / 1 skipped / 0 failed，退出码 0**（skip 仍为 `test_03_code_copy.py:119` 的 Windows 符号链接权限；计数方式同 §3 #1：进度行共 559 个字符，`.`×558、`s`×1，无 F/E）。
  - 定向子集（运行生命周期 / 执行接线 / 调试登记 / 框选 / 报告追溯 / 性能场景与派发 / 联动）：**119 passed**。
  - 前端：`tsc --noEmit` 退出码 0；`npm test` **48 passed**（新增采集窗口用例）；`npm run build` 成功（128 modules，`index-Dn4VK9xr.js` 369.31 kB）。
- 边界不变：评审修复不改变真机执行、可信来源、1440×900 像素核对三类未执行项的结论（§3.1、§5、§6）；§5 第 7 条的 `collectWindow` 展示缺口已关闭。

## 8. 真机验收执行记录（2026-11-01 下午）

用户连接真机后，在 HEAD 的独立实例上补做 UI / 独立性能 / 联动 / 调试四类真机验证。为避免影响常驻开发环境，**未启动/停止 `:8000` 与 `:5173`**，而是用同一份 HEAD 代码在 `127.0.0.1:8010` 起独立后端，使用隔离库 `testdock_real`（迁移 `0008`），数据与产物根为 `.runtime/real-verify/data`；共享库 `testdock` 未写入。

### 8.1 环境与前置

| 项 | 值 |
| --- | --- |
| 后端 | HEAD 代码，`http://127.0.0.1:8010`（`:8000` 旧进程未动），库 `testdock_real` |
| 设备 | serial `749622c9`，Xiaomi 2206123SC，Android 14，1080×2400；同步后状态 ready，自动档案 "Xiaomi 2206123SC / Android 14 / 1080x2400" |
| 被测应用 | `com.miui.calculator`，versionName `15.0.14`，versionCode `315000014`（设备已安装；未安装/升级/推送任何 APK） |
| 构建 | `com.miui.calculator@15.0.14`，登记后做了真实身份核对（package/versionName match，versionCode 为观测值），再显式确认基准（`confirmed`，baseline versionCode=315000014） |
| 可信来源 | `TESTDOCK_SUITE_SOURCES` 指向 `.scratch/first-release-closure/real-suite`（**宿主配置的受控验收套件，不是客户生产套件**；内容为真机冒烟 pytest 用例，真实冷启动应用并截帧） |
| 套件版本 | UI v1（2 用例）、v2（3 用例，含 15s 前台停留）、v3（4 用例，含故意失败）；joint v1/v2 均锁定对应 UI 代码副本 |
| 设备占用 | 所有运行串行；调试会话关闭与每次运行结束后活动租约均为 0 |

### 8.2 执行结果

| 运行 | 类型 | 终态 / 结论 | 真机证据 |
| --- | --- | --- | --- |
| RUN-0001 | UI v1 | completed / passed | pytest 2 passed；cwd 为固定副本 `code-copies/<id>`；run_events 含 `lease_acquired(serial=749622c9)`、`identity_verified`、`suite_copy`、`pytest: 2 passed`；junit 2/0/0 |
| RUN-0002 | 独立性能 | completed / not_tested(`gate_policy_missing`) | SoloPi 真实采集：CPU（全局/进程）、PSS/PrivateDirty/全局内存、电池温度共 7 类指标，CPU 样本 22 个；未配置门禁策略，如实未判定，不补零 |
| RUN-0003/0005 | 联动（修复前） | completed / not_tested(`baseline_missing`) | 采集窗口存在但指标为空；由此发现"采集作用域未启动"缺陷（见 §8.3） |
| RUN-0004 | UI v2 | completed / passed | pytest 3 passed（含 15.04s 前台停留用例）；固定副本摘要与 v2 一致 |
| RUN-0006 | 联动（修复采集后） | completed / not_tested(`baseline_missing`) | 7 类真实指标；`collectWindow` 因报告选择缺陷暂为 null，修复后可读到 |
| RUN-0007 | 联动（全部修复后） | completed / not_tested(`baseline_missing`) | UI passed + 性能 7 类指标；`collectWindow` 23.2s 包围 UI 19.5s；UI 与 performance 两个组件分别保留；无同档基线，性能如实未判定 |
| RUN-0008 | UI v3（故意失败） | completed / failed(`case_failure`) | junit 4 用例 1 failure（断言消息可见）；真实失败证据 `failure-frame.png`（212,795 bytes，PNG 486×1080）、`ui-tree.xml`（22,363 bytes）、`meta.json`、`run-manifest.jsonl` 均 available 且可下载 |
| RUN-0009 | UI v2 + 取消 | cancelled / outcome NULL | 运行 4s 后取消：响应 `state=cancelled`、`runner_terminated=true`；终态 `cancelled/cancel_requested`；活动租约 0 |

调试会话（真实设备）：

1. `POST /debug-sessions` → 会话 `72458232-6539-4853-a2fe-ebcbd7f74cd2`，viewer `http://127.0.0.1:13650`，状态 active。
2. 快照 `9cd79d88265f4089`（1080×2400）；带树快照 `131ffa6d643148e7` / `9cd79d88265f4089`，`tree_captured_at == captured_at`、`consistent=true`（冻结画面与节点树同源）。
3. 框选计算器隐私弹窗"同意"按钮（bounds → region `[556,2142,447,137]`），`POST /templates/validate-crop` 用**新捕获画面**验证：唯一命中 `count=1`、`score=1.0`，服务端发放一次性 `verification`（TTL 120s）。
4. 凭该凭证登记模板 `acceptance/calculator-consent-agree.png`：version `8e67584b626e4534a3a76d7db6f079d8`，sha256 `0bd150c1…33cc2d`；磁盘 `server/assets/versions/8e675…/image.png` 实测同哈希；`GET /templates` 可查。
5. `DELETE /debug-sessions/{id}` → 会话 closed；会话凭证按会话清除；活动租约 0。

### 8.3 真机验收新发现并修复的缺陷

| # | 缺陷（真机实证） | 修复 | 复验 |
| --- | --- | --- | --- |
| 1 | **联动性能采集从未启动**：`_start_perf_collect` 只调用 `kit.collect()` 构造作用域，没有 `__enter__`；UI 跑完后 finalize 在 `_session=None` 上报 `'NoneType' object has no attribute 'stop'`。报告仍把 performance 记成 completed，属于"没执行却像执行了" | `2295877`：显式进入作用域，启动失败按既有矩阵收敛（UI cancelled / performance errored） | `test_issue16_joint_lifecycle.py::test_perf_collect_scope_is_entered_before_ui_runs`；RUN-0007 采到 7 类真实指标 |
| 2 | **run 级报告被嵌套报告挤掉**：采集真正启动后多出 `perf-runs/<run>/report.json`，平台按 logical_key 取第一个 report.json，导致 `collectWindow` 经 `/report` 变 null | `837e671`：run 级（`logical_key == "report.json"`）优先，其余按路径最短回退 | `test_report_prefers_run_level_report_over_nested_perf_report`；RUN-0007 `collectWindow` 可读且覆盖 UI |
| 3 | **指定 node_id 同步设备 500**：SQL 未取 `execution_nodes.status` 却读取 `fixed_node.status`（真机同步传 node_id 时直接 AttributeError） | `4adf7ca`：补上列并加回归 | `test_p7_device_sync.py::test_sync_with_explicit_node_id_does_not_crash` |

### 8.4 真机后的状态更新（相对 §2.1）

| 用户故事 | 原状态 | 现状态 | 依据 |
| --- | --- | --- | --- |
| 1 可信套件来源可见 | 受阻 | **已通过（受控来源）** | `GET /suite-sources` 返回宿主配置的 `calculator-smoke`（受控验收套件，非客户套件）；来源为空时的 `hint` 行为仍由既有测试覆盖 |
| 4 登记套件并发现用例 | 已实现待验 | **已通过（受控来源）** | 真实目录 → 固定副本 → pytest collect-only 发布 v1（2 用例），v2/v3 追加版本 |
| 9/10 安装身份核对与基准确认 | 已实现待验 | **已通过** | 真机 `dumpsys` 核对 match，确认后 baseline 固定（versionCode=315000014） |
| 13 启动运行并跟踪状态/事件 | 已实现待验 | **已通过** | RUN-0001/0004：排队→派发→运行→完成；事件含租约、身份、副本、pytest 进度；报告可查 |
| 14 取消运行并释放设备 | 已实现待验 | **已通过** | RUN-0009：cancelled/outcome NULL、`runner_terminated=true`、活动租约 0 |
| 16 失败截图/日志/断言 | 已实现待验 | **已通过** | RUN-0008：真实 212KB 截图、UI 树、junit 断言消息、运行清单 |
| 18 独立性能采集 | 已实现待验 | **已通过** | RUN-0002：真实 7 类指标与样本数；无策略时如实 `not_tested` |
| 22 联动同一次 UI 执行采性能 | 已实现待验 | **已通过（修复后）** | RUN-0007：单租约、窗口包围 UI、UI/性能分别落结论；采集中断缺陷已修 |
| 24 调试会话实时画面/连接状态 | 已实现待验 | **已通过** | 真机会话 active、viewer 就绪、快照/树/框选/登记/关闭全链路 |
| 25/26/28 冻结同源、验证后登记、跨会话可查 | 已通过（夹具） | **已通过（真机补证）** | 快照与树同时刻 consistent；新画面唯一命中后凭证登记；模板库可查且 sha256 与磁盘一致 |

未改变：US27 的"刷新/恢复预览清旧匹配"仍由前端测试覆盖，本轮真机只验证了服务端凭证失效与会话关闭清理；US20 无同档基线，性能如实未判定。

### 8.5 仍未执行 / 边界

1. **客户真实套件**：本轮来源是宿主配置的受控验收套件，证明来源→副本→发现→执行链路在真机可用，但不代表任何客户既有套件已通过。
2. **1440×900 像素级视觉核对**：仍未执行（内置浏览器无可见视口，见 §5 第 4 条）。
3. **页面 ↔ HEAD 后端同版数据**：`:8000` 仍是旧进程、`:5173` 仍代理它；本轮真机证据全部走 `:8010` HEAD，不宣称页面数据已同版。
4. **门禁/基线结论**：本轮未配置门禁策略与同档基线，性能运行如实 `not_tested(gate_policy_missing / baseline_missing)`，不伪造判定。
5. **模板资产**：真机登记会在共享模板根 `server/assets/versions/<version_id>/` 落下模板版本（本轮 `8e67584b…`），属真实登记结果；如需清理应按模板版本管理，不直接删目录。
6. **数据与环境**：隔离库 `testdock_real`、产物根 `.runtime/real-verify/data`、证据文件 `.scratch/first-release-closure/real-verify/evidence/`；未写共享库 `testdock`，未占用设备超过单次运行期。

### 8.6 真机修复后的复跑

- 后端全量（`testdock_frc10`，迁移 `0008`）：**562 项，561 passed / 1 skipped / 0 failed，退出码 0**（计数方式同 §3 #1：进度行共 562 个字符，`.`×561、`s`×1，无 F/E；唯一 skip 仍是 Windows 符号链接权限）。
- 定向：`test_issue16_joint_lifecycle.py` 23 passed；`test_issue16 + test_p7_device_sync + test_issue06_perf_dispatch + test_issue06_perf_scenario` 77 passed。
- 前端本轮未改动，§7 的 `tsc --noEmit` / `npm test` 48 passed / `npm run build` 结果仍适用。
- 本轮代码提交：`2295877`（joint 采集作用域）、`4adf7ca`（node_id 同步）、`837e671`（run 级报告优先）；验收记录与证据随本节提交。
- 证据文件：`.scratch/first-release-closure/real-verify/evidence/real-device-2026-11-01.json`（9 次运行与调试会话摘要）、`evidence/failure-frame.png`（真实失败截图）、`crop_validation.json`、`snapshot_tree.json`；运行产物在 `.runtime/real-verify/data/artifacts/<run_id>/`。

## 9. 客户真实套件与 1440×900 像素核对（2026-11-01 下午）

本节补做首期验收中最后两项未执行项：客户真实套件、1440×900 像素级核对。两者都使用 HEAD 的独立实例（`:8010` + 隔离库 `testdock_real`），未动 `:8000` / `:5173`。

### 9.1 客户真实套件（Beta Academy）

| 项 | 值 |
| --- | --- |
| 客户仓库 | `D:/workspace/claudecode-test/moblie-auto`，HEAD `f0d2ce0c37b6434f519b87ce7fc6c48e436753bc` |
| 套件来源 | `examples/beta_academy`（Beta Academy 1.9.77 真机导航套件，5 个测试文件 / 12 用例） |
| 宿主副本 | `.scratch/first-release-closure/beta-academy-suite`：7 个 `.py` 逐字复制（SHA256 见 `FILES.sha256`），**仅新增** `pytest.ini`（`asyncio_mode = auto`，原配置在客户仓库 `pyproject.toml`）；未复制 `local.toml`，设备/应用身份由平台生成的 mobile-config 注入 |
| 被测应用 | `com.sinosoft.trainapp`，versionName `1.9.77-20261020`，versionCode `416`（设备已安装；未安装/升级/推送任何 APK） |
| 身份核对 | 真机 `dumpsys`：package/versionName match、versionCode 观测为 416，显式确认后 baseline 固定 |
| 套件版本 | `00701632-374c-4687-814f-7dfd8f3d7d7d`（v1），固定副本树摘要 `d21f438c9027b97c…`，12 用例 |

**集成过程中发现并修复的平台缺陷**：

| # | 缺陷 | 修复 |
| --- | --- | --- |
| 1 | 平台生成的 `mobile-config.toml` 只有 assets/artifacts；套件自带 `mobile_session` 时 `load_config(--mobile-config)` 丢掉设备 serial 与应用身份，无法冷启动 | `976b8d5`：配置写入 `device_serial/app_package/app_activity`，并加回归 |
| 2 | 平台插件与套件 conftest 都注册 `--mobile-config`，pytest 加载 conftest 时 `ArgumentError`（RUN-0010 → errored/pytest_error） | `6941ab2`：检测到套件自带 `mobile_session` / `--mobile-config` 时不再注入平台会话插件；普通套件行为不变 |

**执行结果**（RUN-0010 → 修复 → RUN-0011）：

| 运行 | 终态 | 结果 |
| --- | --- | --- |
| RUN-0010 | errored / `pytest_error` | 选项冲突，未执行任何用例（集成缺陷，已修复） |
| RUN-0011 | completed / `failed` | **12 用例：7 passed / 3 skipped / 2 failed**；junit 与两份失败证据齐全 |

- 7 passed：冷启动直达首页、我的页学习统计、课程与动态端点、页签往返、知识库入口计数、平台身份注入、Android 驱动截图。
- 3 skipped：2 个 web 专属用例（本示例环境无 browser 驱动）+ 1 个"当前会话有效直达首页"分支（登录页判据不适用）。
- 2 failed（均为真实失败，不是平台执行链故障）：
  1. `test_kb_list_scroll_keeps_items`：`AttributeError: 'UpstreamChannel' object has no attribute 'touch_down'`。平台 vendor 快照记录 `mobile_auto@24a1daa`，其 `UpstreamChannel` 只有 `touch()`，而同快照的 `core/device_ops.py` 已调用 `channel.touch_down`（内部不一致）；客户仓库 HEAD `f0d2ce0` 的 `UpstreamChannel` 已提供 `touch_down`。滑动手势在旧 vendor 上不可用。**需先同步 vendor 才能全绿**；本轮按约束不改 `vendor/`。
  2. `test_feedback_opens_webview`：点击"问题反馈"后立即断言 WebView，真机失败截图仍是加载中 spinner（无 WebView 节点）——套件缺少等待，属套件自身时序问题。
- 证据：`evidence/beta-junit.xml`、`evidence/beta-evidence_4cbdd5f1…_failure-frame.png`（知识库页）、`evidence/beta-evidence_e41ce612…_failure-frame.png`（问题反馈加载中）、运行产物 `.runtime/real-verify/data/artifacts/0b3f0bf9-…/`。
- 结论：客户套件已经通过 TestDock 的固定副本、身份基准、证据与报告链路**真实执行**；但**不能记为客户套件全绿**——2 个失败分别指向 vendor 快照版本落后与套件自身时序。

### 9.2 1440×900 像素核对

| 项 | 值 |
| --- | --- |
| 参考版本 | `docs/platform-prototype/index.html`，sha256 `576d5402238a198ef6a64ae3e92f8f76e7cbe883f91712643d57e90134ed4d5f`，180445 bytes（与 §1 一致） |
| 页面环境 | HEAD 后端 `:8010`（隔离库 `testdock_real`，真实数据）；Vite 验收实例 `:5174` 反代 `:8010`；默认 `:5173 → :8000` 未动 |
| 截图通道 | Edge headless + CDP `Emulation.setDeviceMetricsOverride(1440×900, deviceScaleFactor=1)`；Page.captureScreenshot |
| 采集 | 九页实现截图 + 九页原型截图，均为 1440×900 PNG；每页同时记录布局指标 |
| 证据 | `evidence/visual-1440/`（18 张 PNG）+ `evidence/visual-1440/layout-metrics.json` |

布局指标（九页一致）：

| 指标 | 实测 |
| --- | --- |
| CSS 视口 | `innerWidth=1440`、`innerHeight=900` |
| 文档宽度 | `documentElement.scrollWidth=1440`、`body.scrollWidth=1440`（无横向溢出） |
| 固定侧栏 | 218 px（内容区左边界 218 px） |
| 越界元素 | 九页均为 0（`right > 1440+1` 的元素计数） |

逐页核对（实现 vs 原型）：

- **一致的骨架**：左侧固定导航（218px）+ 顶栏（面包屑/状态/日期）+ 页面标题与说明 + 目标端上下文条 + 卡片/表格网格 + 相同的设计令牌（主色 `#4263eb`、圆角、间距、字号、状态色与徽标）。
- **概览**：实现为「目标端卡片 + 4 指标卡 + 运行列表」；原型为「指标卡 + 两大能力卡 + 任务/设备两列」。属已批准规格的页面结构差异。
- **UI 页**：实现表格增加「应用/目标端/最新版本/最近发现」与「查看执行记录」；原型的「覆盖范围」列不适用于真实发现数据。
- **设备页**：实现增加平台字段、设备池统计与「同步设备池」；不可用设备按状态禁用「打开调试」。
- **报告页**：实现展示真实运行与真实原因（未通过/未判定），与 §2 判定口径一致。
- **工作空间与日期**：实现使用「星河工作空间 / 2026-11-01」，原型为演示项目与演示日期。
- 未发现裁切、错位、横向滚动条或状态色误用；九页在 1440×900 下均完整呈现。

结论：1440×900 九页按参考版本完成像素级视觉核对，无布局缺陷；实现与原型的信息架构差异均为已批准的数据/规格调整，**不宣称与原型逐像素相同**。原 §5 第 4 条与 §8.5 第 2、3 条（页面 ↔ HEAD 后端同版数据）已由本节关闭。

### 9.3 仍未执行 / 边界

1. **客户套件全绿**：需同步 vendor 到客户兼容版本（`UpstreamChannel.touch_down`）并修复套件自身的 WebView 等待；本轮不改 `vendor/`、不改客户套件代码。
2. **逐像素 diff 百分比**：实现与原型存在已批准的信息架构差异，本轮以「同尺寸截图 + 布局指标 + 逐页核对」为准，不输出无意义的 diff 比例。
3. 其余真机/来源边界见 §3.1、§5、§8.5；客户真实来源的“客户生产套件”内容仍以本节 Beta Academy 为准（客户仓库示例套件）。

### 9.4 最终回归与环境收尾

- 最终 HEAD 全量后端回归（`testdock_frc10`，迁移 `0008`）：**564 项，563 passed / 1 skipped / 0 failed，退出码 0**（计数方式同 §3 #1；新增 2 项为 mobile-config 身份与套件自有会话让位的回归）。前端本轮未改产品代码，§7 的 `tsc --noEmit` / `npm test` 48 passed / `npm run build` 结果仍适用。
- 收尾：验收用的 `:8010`（HEAD 后端）与 `:5174`（Vite 反代）已停止；`testdock_real` 活动租约 0、无未关闭调试会话；设备 `749622c9` 仍在线；常驻 `:8000` / `:5173` 均 200，未被重启或改写。
- 本轮提交：`976b8d5`（mobile-config 身份）、`6941ab2`（套件自有会话让位）、`90918d8`（客户套件 + 1440 证据与 §9）。未 push。

## 10. Vendor 同步与客户套件收口（2026-11-01 傍晚）

用户授权后进行 `mobile_auto` vendor 同步与套件 WebView 修复，目标是把 §9.1 的两个失败收敛掉。

### 10.1 Vendor 同步

| 项 | 值 |
| --- | --- |
| 同步命令 | `python scripts/vendor_sync.py sync mobile_auto`（只同步 mobile_auto；mobile_perf 未动） |
| mobile_auto | `24a1daa…` → **`f0d2ce0c37b6434f519b87ce7fc6c48e436753bc`**，132 文件 / 14.8 MiB |
| mobile_perf | 保持 `8df850f31ec08850e02d0b8a24b9c9eb01bbbae1`（217 文件） |
| 锁文件校验 | `vendor_sync.py check` → **OK：349 文件 / 42.6 MiB 与锁文件逐字节一致** |
| 代码变更规模 | 33 文件修改，+3353 / −383；新增 journal、videostream、video_player.js 及 12 个测试文件 |
| 清理 | 删除早期性能运行在 `vendor/mobile_perf/data/mobile_perf.db` 留下的运行时 DB，以及 `__pycache__/.pytest_cache`（均为未登记产物，无产品文件被删） |

为什么能修 §9.1 的滑动失败：同步后的 `stream/upstream.py` 的 `UpstreamChannel` 已提供 `touch_down/touch_move/touch_up`（`592` 行），与 `core/device_ops.py` 的调用一致。

验证：

- **vendor 自身回归**（pathonly，`PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8`）：mobile_auto unit + contract **663 项 = 662 passed / 1 skipped / 0 failed**。未加 `PYTHONIOENCODING` 时出现 5 个失败，均为 pytester 读取 GBK 子进程输出的 `UnicodeDecodeError`，与同步代码无关。
- **平台相关回归**（`testdock_frc10`）：调试/框选/模板/运行/联动/性能/runner 契约等 147 项通过。
- **平台全量回归**：564 项 = 563 passed / 1 skipped / 0 failed，退出码 0（与同步前相同）。
- **真机调试冒烟**（新 vendor）：会话 active → 快照 1080×2400 + UI 树 59 节点、`consistent=true` → 关闭；活动租约 0。

### 10.2 套件 WebView 修复

- 宿主副本 `.scratch/first-release-closure/beta-academy-suite/test_settings_webview.py` 在点击「问题反馈」后增加 `wait_for(WEBVIEW_NODE, timeout=10)`，再执行原有的 `find_elements` 断言；**断言强度不变**（仍要求 WebView 容器存在）。
- 客户仓库 `moblie-auto` **未修改**；`PROVENANCE.md` 与 `FILES.sha256` 已更新，明确这是宿主适配的 1 处差异，其余文件逐字复制。

### 10.3 客户套件复跑（RUN-0012）

| 项 | 值 |
| --- | --- |
| 套件版本 | v2 `15a9a3a5-11b5-4ca7-87e0-027f0f5bc844`，固定副本树 `fe99dd342b345eef…`，12 用例 |
| 终态 | **completed / passed** |
| 结果 | **12 用例：9 passed / 3 skipped / 0 failed**（`pytest: 9 passed, 3 skipped in 37.53s`） |
| 跳过 | 2 个 web 专属（本环境无 browser 驱动）+ 1 个「会话有效直达首页」分支 |
| 覆盖 | 冷启动首页、我的/课程/动态端点、页签往返、知识库入口、**知识库滚动**、平台身份、Android 驱动截图、**问题反馈 WebView** |
| 证据 | `evidence/beta-v2-result.json`、`evidence/beta-v2-junit.xml`；运行产物 `.runtime/real-verify/data/artifacts/6ec3b1d0-…/` |

历史 RUN-0011（同步前 7 passed / 3 skipped / 2 failed）保留在 §9.1，作为两个缺陷的现场证据；§9.3 第 1 条（客户套件全绿）**已由本节关闭**。

### 10.4 最终状态

- 工单 01–10 全部 `resolved`；集成分支 `integration/first-release-closure`。
- 客户真实套件经 TestDock 真机执行全绿（9 passed / 3 skipped / 0 failed），平台 vendor 已同步并逐字节校验；平台全量 564 项通过。
- 原 §5/§8.5/§9.3 的“客户套件全绿、像素核对、页面↔HEAD 数据”三项均已关闭；其余边界（多用户/跨机器/对象存储、保留期 `expired` 态、多 worker 凭证共享、客户仓库自身代码未改）仍按 spec 或约束保留。
- 收尾：验收用 `:8010` 已停止（本轮复跑后），`8000/5173` 未动；租约 0；设备在线；未 push。

## 11. Phase 1 直接操控交付记录（2026-11-01 晚）

在调试工作区增加真机直接操控：点击/拖动/长按画面与 Back/Home，复用 mobile-auto 的单操作者控制权与连续手势 WS。工作分支 `feat/debug-direct-control`，未 push。

### 11.1 实现

| 层 | 内容 |
| --- | --- |
| 平台 API | `POST /debug-sessions/{id}/control`（领取/释放）、`POST .../control/heartbeat`、`POST .../input/key`；token 只存服务端 `_CONTROL_TOKENS`，响应剔除；409 `control-busy` / `control_not_enabled` / `control_expired` |
| 手势代理 | `WS /api/v1/ws/debug/{id}/gesture`：平台向 vendor 发 `{token}` hello，带严格 `Origin: http://127.0.0.1:<viewer_port>`，双向透传 `start/move/end`；每会话最多一条 |
| 前端 | 工具栏「直接操控」+ 确认 Dialog + 「操控中」Badge；pointer 捕获、归一化坐标、20Hz MOVE 节流、触点提示、返回/Home；冻结/图像模式/会话失效自动退出；心跳 2s |
| 关闭 | `_close_session` 尽力释放 vendor 控制权并清 token/手势计数 |
| 文档/契约 | api-design §2.7 新端点与语义；OpenAPI 基线重生成；错误码登记 |

### 11.2 自动化验证

- 后端：`test_debug_control.py` **10 passed**（领取/剥离 token、他人持有 409、续期、TTL 失效映射、按键门控、关闭释放、手势 WS 的 Origin/hello/透传、无控制权 4403）。
- 定向：控制 + P5 调试 + 模板/框选 + 契约 **66 passed**；契约与错误码基线重新生成后 24 passed。
- 前端：`tsc --noEmit` 通过；`npm test` **52 passed**（新增坐标归一化、可用性原因、手势帧形状、20Hz 节流）；`npm run build` 成功。
- 新增错误码：`control_not_enabled`、`control_expired`、`viewer_bad_response`。

### 11.3 真机验证（749622c9）

| 项 | 结果 |
| --- | --- |
| 控制权 | 平台领取 → 响应无 token；第二个客户端直接向 vendor 领取 → 409 control-busy |
| 手势 | 平台 WS 透传 start/end → vendor `ack down` / `ack end` / `ended`；UI 点在「我的」标签后设备树出现「学员/学习统计/学习时长」 |
| 按键 | UI Home → `topResumedActivity` 变为 `com.miui.home/.launcher.Launcher` |
| 收尾 | 退出操控 + 关闭会话 → active leases 0、active debug sessions 0、无 runner 进程 |

证据：`.scratch/first-release-closure/real-verify/evidence/direct-control-2026-11-01.json`。

### 11.4 边界

1. **后台标签页心跳节流**：浏览器切后台时 2s 心跳可能被节流，vendor 5s TTL 到期即撤权；UI 会显示 `control_expired` 并要求重新启用（不静默续权）。当前不引入服务端自动续权：那会让“单操作者/5s 失联释放”的 vendor 语义失效。
2. **多 worker**：`_CONTROL_TOKENS`/手势计数在进程内，与 `_READY_PORTS`、框选凭证同边界；多 worker 部署需共享存储。
3. **H.264 预览**：按已批准计划作为 Phase 2，不在本节范围；不改变控制语义。
4. 未做文字输入、多指/捏合、录制回放（vendor 当前未提供对等端点）。
5. 最终全量回归结果见 §11.5。

### 11.5 最终回归

- 全量后端（`testdock_frc10`，迁移 `0008`）：**574 项，573 passed / 1 skipped / 0 failed，退出码 0**（计数方式同 §3 #1；新增 10 项为直接操控的控制权/手势 WS/按键回归）。
- 定向：控制 + P5 调试 + 模板/框选 + 契约 **66 passed**；前端 `tsc --noEmit`、`npm test` **52 passed**、`npm run build` 成功。
- 真机验收见 §11.3；收尾时活动租约 0、活动调试会话 0、无 runner 进程。
- 分支：`feat/debug-direct-control`，提交 `5aad752`；按计划合并回集成分支后进入 Phase 2（H.264）。


## 12. Phase 2 H.264 预览交付记录（2026-11-01 晚）

在调试页增加 H.264 优先预览，JPEG 保留为回退。分支 `feat/debug-h264-preview`，未 push。

### 12.1 实现

| 层 | 内容 |
| --- | --- |
| 平台代理 | `WS /api/v1/ws/debug/{id}/video`：严格 `Origin: http://127.0.0.1:<viewer_port>` + `{"proto":1}` hello；只下行转发 ready/error 与 27 字节头二进制帧；浏览器消息忽略；每会话最多一条 |
| 前端播放器 | `web/src/lib/h264Preview.ts`：27 字节头/SPS→codec 解析、VideoDecoder、config+首关键帧合并、积压丢 delta、8s 无画面失败、canvas 绘制；冻结时暂停绘制 |
| DebugDrawer | 预览模式 `h264 | jpeg`；页头显示 `H.264 · Nfps` 或 `JPEG 回退`；回退原因 Notice；冻结/恢复、控制覆盖层、坐标归一化不变；无 WebCodecs 时直接回退 |
| 文档 | api-design 增加 video WS 与回退语义；无新依赖、无迁移 |

### 12.2 自动化验证

- 后端：`test_debug_preview_video.py` **3 passed**（Origin/hello/ready/二进制透传；未知 4404；非 active 4403）；控制 + 契约定向 **27 passed**。
- 前端：`tsc --noEmit` 通过；`npm test` **57 passed**（新增包头解析、SPS→codec、积压丢帧、传输选择）；`npm run build` 成功。
- 全量回归结果见 §12.4。

### 12.3 真机验证（749622c9）

| 项 | 结果 |
| --- | --- |
| H.264 | 调试页显示 `H.264 · 25fps`，canvas 486×1080（vendor 码流分辨率），WS `/video` accepted |
| 冻结/恢复 | 采集检查后冻结，恢复预览后 H.264 继续出帧（2.5s 窗口 11fps） |
| 回退 | 隐藏 `window.VideoDecoder` 后重新打开调试：页面显示「预览已回退 JPEG / 浏览器不支持 WebCodecs，已回退 JPEG」，JPEG 链路正常 |
| 控制 | 预览切换不影响「直接操控」按钮与 Phase 1 控制链路 |
| 收尾 | 关闭会话后 active leases 0、active debug sessions 0、无 runner 进程 |

### 12.4 边界与结论

1. **码流分辨率低于设备**：H.264 实测 486×1080；精确节点拾取、框选与模板仍以 1080×2400 快照为准，不影响 Phase 1 精度。
2. **回退粘性**：一旦本会话回退 JPEG，不反复重试 H.264；重开调试会话再尝试。
3. **不并行**：同一会话只开一条预览流（video 或 JPEG），避免 vendor 客户端上限与双重解码开销。
4. **依赖**：需 WebCodecs 与 vendor `stream_backend=upstream`（默认）；否则如实回退并显示原因。
5. **不改变控制**：Phase 1 的控制权/手势 WS 与坐标归一化不受预览传输影响。

全量回归（`testdock_frc10`，迁移 `0008`）：**577 项，576 passed / 1 skipped / 0 failed，退出码 0**（新增 3 项视频代理测试；计数方式同 §3 #1）。分支 `feat/debug-h264-preview`，提交 `b48a9e6`；按计划合并回集成分支。

## 13. 直接操控点击延迟修复（2026-11-01 晚）

**症状**：直接操控点击后约 0.5–2 秒设备才响应。

**根因**：`handleControlPointerDown` 先设置 `pointerStartRef`，再调用 `openGesture()`；而 `openGesture()` 会调用 `closeGestureSocket()`，后者把 `pointerStartRef` 清空。`finishControlPointer` 因此直接 return，手势 `end` 从未发送；vendor 只能等 2s 空闲超时（或下一条手势断连）自己补 UP。Android 应用通常在 ACTION_UP 才完成点击，所以表现为点击延迟。

**证据**：
- 修复前 UI 会话 `3ba8f0be…/actions.jsonl`：`viewer.gesture.down seq:1` 后 `up seq:1`，间隔 0.5–2.0s，且 up 的 `duration_ms:0`（超时/断连清理，不是客户端 end）。
- 对照 API 直发手势 `de7238e5…/actions.jsonl`：`down seq:1`、`up seq:2`，间隔 2ms。
- vendor 空闲阈值 `_GESTURE_IDLE_TIMEOUT_SECONDS = 2.0`。

**修复**：把 `openGesture()` 移到 `pointerStartRef.current = ...` 之前（`DebugDrawer.tsx:988-989`）；`closeGestureSocket` 仍保留 reset/disable 的清理职责。前端新增源码顺序回归测试（旧顺序失败，新顺序通过）。

**复验**（真机 749622c9，H.264 预览）：
- 新会话 `439a5196…/actions.jsonl`：`down seq:1` 于 `09:51:04.738`（注入 156ms），`up seq:2` 于 `09:51:04.740`（2ms 后）——end 已即时送达。
- 同一次点击后设备树出现「学员/学习统计/学习时长」，页面真实切换。
- 前端 58 项测试、`tsc --noEmit`、`npm run build` 通过；活动租约/会话收尾为 0。

**剩余观察**：单次 DOWN 注入约 156ms；若仍感觉慢，下一步应量化 H.264 呈现延迟（本次只修了 2s 的根因，未改预览传输）。

## 14. H.264 呈现延迟量化（2026-11-01 晚）

**方法**：真机 749622c9、H.264 预览（486×1080）；用 vendor 控制权发送 Home（`press_key`），以 HTTP ack 为 t0；浏览器在 canvas 的 `drawImage` 后对 48×106 缩略帧做差分，首次平均绝对差 >3 记为 t1；延迟 = t1 - t0。样本 3 次，每次先把计算器切到前台再发 Home。

| 样本 | 延迟 |
| --- | --- |
| 1 | 177.9 ms |
| 2 | 128.6 ms |
| 3 | 150.8 ms |
| 中位 / 均值 | **150.8 / 152.4 ms** |
| 范围 | 128.6–177.9 ms |

**拆分**：
- 输入侧（修复后）：手势 DOWN 注入约 156ms，UP ack 约 2ms。
- 呈现侧：约 129–178ms（含 launcher 过渡起始与 canvas 绘制；不含合成器上屏约 1 帧）。
- 用户一次点击到画面变化的总量级约 **300–340ms**，不再是之前的 2s。
- 之前的 2s 延迟根因是 `end` 未发送，vendor 2s 空闲超时补 UP；与 H.264 无关（§13）。

**边界**：该数字是 Home 过渡的首次画面变化，包含应用过渡起始，不是纯 codec 基准；浏览器在后台标签页时合成器上屏可能再多一帧。测量期间计算器数字键的 tap 未改变显示（独立问题，未用于本次测量；如需排查另开工单）。

证据：`evidence/h264-presentation-latency.json`。

## 15. 调试页框选与控制键布局修复（2026-11-01 晚）

### 15.1 原生节点模式误触框选

**现象**：原生节点模式下在设备画面拖拽也会生成橙色选择框，并一直留在画面上。

**根因**：`handleStageDown/Move/Up` 只判断了 `controlEnabled`，没有判断 `inspectMode`；选择框 overlay 也无条件渲染。框选本应只属于图像模板模式。

**修复**：
- 新增 `cropSelectionEnabled(inspectMode)`（仅 `image` 为真）；三个拖拽 handler 与 overlay 统一用它门控。
- 切回「原生节点」时清空 `dragging/region/cropVerification`，旧框立即消失。

**验证**（浏览器 DOM 几何）：
- 原生节点模式拖拽：`.debug-box.pick` 数量 **0**。
- 切到图像模板后拖拽：数量 **1**（功能保留）。
- 再切回原生节点：数量 **0**（旧框清除）。
- 回归测试：`web/tests/debug-control.test.cjs` 新增门控纯函数 + 三个 handler 的源码级检查。

### 15.2 返回键/Home 位置

**现象**：两个按键在设备下方的信息/图例之后，离设备较远。

**修复**：控制条移到 `.debug-stage` 之后、快照信息之前；CSS `justify-content:center` 居中。

**验证**（浏览器 DOM 几何）：控制条 top 距 stage bottom **8px**，水平中心与 phone panel 中心偏差 **<3px**，DOM 顺序在「设备画面未冻结」信息之前；按钮为「返回键 / Home」。

### 15.3 回归

- 前端 `tsc --noEmit` 通过；`npm test` **61 passed**；`npm run build` 成功。
- 无后端/数据库/契约改动；收尾租约与调试会话均为 0。

### 15.4 控制键常驻（2026-11-01 晚补）

**现象**：未启用「直接操控」时，设备下方看不到返回/Home，误以为布局没生效。

**根因**：控制条整体包在 `controlEnabled ? ... : null` 里，只在操控中渲染。

**修复**：控制条改为常驻设备正下方；未启用时显示「直接操控未启用 · 先在工具栏点「直接操控」」，两个按键 disabled 且 title 说明原因；启用后解除禁用并显示「直接操控中」。

**验证**：浏览器 DOM 实测——未启用：bar 存在、按钮均 disabled；启用后：按钮均 enabled、提示切换为「直接操控中」。`tsc --noEmit`、`npm test` 61 passed、`npm run build` 通过。
