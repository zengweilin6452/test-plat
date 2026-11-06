# 13: 原始判定冻结与原子收敛

**What to build:** 执行前固定默认策略与同档案基线；finalizing 内完成原始判定、组件聚合与终态，不出现 completed 缺 original。

**Blocked by:** 12、03

**Status:** resolved

- [x] AC-GATE-01：排队期间策略变化不改执行快照
- [x] AC-CONTRACT-05：原始判定、组件结论与终态同事务收敛
- [x] 显式指定版本失效时不偷偷替换
- [x] 无默认同档案基线时记录缺失，不回退跨档案
- [x] 重试幂等，每个性能组件只有一条 original

## Comments

- 实现提交 `c08830f`（`feat(issue13): 排队固定策略快照与同档案基线纪律`）。
- AC-GATE-01：`POST /runs` 排队即把该应用最新策略（id/版本/规则副本）写进 `config_snapshot.gate_policy`；`evaluate_run_original` 无显式 policy_id 时优先用快照版本，排队期间新增 v2 不影响本次判定（有测试：v1 lt 240 判 passed，新运行才用 v2）。
- 显式失效版本：显式 policy_id 查不到 → 404，绝不偷偷替换成最新；快照策略行被删 → not_tested + `gate_policy_missing`（记录事实）。not_tested 行的 policy_id 必须是真实存在的行（先核验策略再谈基线，显式失效 id 不再被引用进判定记录——原先会撞外键）。
- 同档案纪律：`_default_baseline_run_id` 删除"跨档案回退最新基线"，无同档案基线 → `baseline_missing`（工单 12 引入的 reason code）。
- 幂等：同 request_key 重放同一行，且响应从 201 改为 200（`created:false` 之外的显式区分，`test_perf_gate_api` 断言同步）；每组件一条 original 仍由部分唯一索引兜底。
- AC-CONTRACT-05（finalizing 单事务收敛 original+组件+终态）此前已由工单 03 落地，本工单回归覆盖其判定核心路径。
- 验收（定向）：`test_issue13_original_freeze.py` 5 例 + perf_gate_api / gates_logic / run_submission / 03_finalize / import_and_finalize / issue12 回归全过；OpenAPI 重新生成并通过 `--check`。全量未跑（按指示）。
- 已知边界：快照里的 rules 是审计副本，判定仍按 policy_id 读行（gate_policies 行按约定不可变、改动即新增版本）；若未来允许原地改 rules，需要把判定输入改为读快照 rules。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
