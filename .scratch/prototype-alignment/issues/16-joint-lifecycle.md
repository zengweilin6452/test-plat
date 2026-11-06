# 16: joint 生命周期与结果矩阵

**What to build:** 一个运行包含 UI 与性能两个组件，性能采集窗口包围同一次 UI 执行，UI 结束立即停采，超时、失败和取消按结果矩阵收敛。

**Blocked by:** 02、13、15

**Status:** resolved

- [x] AC-JOINT-01：两个可追溯组件共享一次资源独占
- [x] AC-JOINT-02：短 UI 结束立即停采，达到 ui_timeout_s 记超时
- [x] AC-JOINT-03：断言失败、无有效 UI、采集启动失败、采集中错误、取消竞争逐项符合矩阵
- [x] AC-CONTRACT-06：合法 3600 秒执行窗不被总 deadline 截断
- [x] 不静默降级为 UI；无法确认停机时设备不可分配

## Comments

- 实现提交 `d7153b6`（`feat(issue16): joint 生命周期与结果矩阵`）。
- runner 新增 `joint_job`：采集启动 → 一次 UI 执行 → UI 一返回立即停采（时间戳写 report.json 的 collectWindow，测试断言 ui.ended_at <= collect_stopped_at，不补采）；UI 阶段复用 run_ui_job（ponytail 注明：vendor 锁若不可重入再拆内部函数）。
- 组件事实随回报走：complete 带 `[ui, performance]` 组件；fail 也带组件（protocol.fail 扩展 components），`/internal/fail` 透传给 finalize 落 run_components——采集启动失败 → errored/outcome=NULL 且 UI=cancelled"collect_start_failed_ui_not_started"、性能=errored；UI 达 ui_timeout_s → errored 且组件带 ui_timeout 原因（fake 模式用 TESTDOCK_FAKE_PERF / TESTDOCK_FAKE_UI_TIMEOUT 模拟矩阵异常行）。
- AC-CONTRACT-06：`ui_timeout_s` 走独立字段（`domain/joint_policy.clamp_ui_timeout` 10–3600，默认 600，平台与 runner 同一口径）；spawn 对 joint 给总超时 = max(原值, ui_timeout+900) 缓冲，测试断言 3600 秒窗口不被截断。
- 不降级：spawn 的 mode 白名单加 joint，argv 保留 joint（有测试）；断言失败 → completed/failed 且性能组件保留（finalize 路径测试）。
- AC-JOINT-01（共享一次资源独占）是结构性的：joint 只有一次 spawn、一条租约，两个组件挂在同一 run 上（测试断言单运行双组件）。
- 验收（定向）：`test_issue16_joint_lifecycle.py` 8 例 + run_submission / p5_debug / import_and_finalize / runner_contracts / 03_finalize 回归全过；OpenAPI `--check` 通过。全量未跑（按指示）。
- 已知边界：真机 vendor 采集（PerfKit.collect 上下文）尚未实机验证——fake 路径覆盖矩阵与窗口语义，实机联调需要设备授权（spec §"真实验证"清单）；取消与完成并发的原子性由终态迁移乐观锁保证（既有 08 号测试覆盖）。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
