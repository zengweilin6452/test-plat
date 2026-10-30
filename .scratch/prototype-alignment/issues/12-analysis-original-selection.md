# 12: 性能分析 original 与 reanalysis 选择

**What to build:** 分析默认展示原始判定，用户可用 evaluation_id 显式选择试算；基线关联真实组件与档案；缺策略和缺基线原因分开。

**Blocked by:** 08

**Status:** ready-for-human

- [x] AC-PERF-01：真实指标、样本数与缺失原因正确，不补零
- [x] AC-PERF-02：跨档案显示不可比且 not_tested 原因正确
- [x] AC-PERF-03：原始阈值与历史报告不被试算覆盖
- [x] AC-CONTRACT-04：默认 original，显式 evaluation_id 才选 reanalysis
- [x] 缺 original 时不自动兜底；gate_policy_missing 与 baseline_missing 可区分

## Comments

- 实现提交 `4de735e`（`feat(issue12): 分析默认原始判定与缺失原因拆分`）。
- AC-CONTRACT-04：`_analysis_for_run` 不再 `latest_reanalysis or original`——默认固定取 original，只有 `GET /analyses?run_id=…&evaluation_id=…` 显式点名才切换；evaluation_id 不属于该运行返回 404。响应新增 `original_missing` 与 `selected_evaluation_id`。
- 缺 original 不兜底：只有 reanalysis 时 verdict/mode 保持 null，`original_missing=true` 让前端明确呈现"还没有原始判定"。
- 缺策略与缺基线拆分：`evaluate_run_original` 先判策略（`gate_policy_missing`），再判基线（新增 reason code `baseline_missing`，`domain/gates.py` 枚举与 `test_gates_logic` 枚举断言同步）；占位策略与 not_tested 语义不变。
- AC-PERF-01/02 复核：既有 `test_perf_gate_api.py` 已覆盖缺失指标不补零、device_unsupported、跨档案 not_tested；本工单测试再验一遍 `GET /analyses` 侧的 metrics 投影。
- 验收（定向）：`test_issue12_analysis_selection.py` 5 例 + `test_gates_logic.py`、`test_perf_gate_api.py`、`test_03_finalize_atomic.py` 回归全过；OpenAPI 重新生成并通过 `--check`（/analyses 新增 evaluation_id 参数）。全量未跑（按指示）。
