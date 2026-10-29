# 12: 性能分析 original 与 reanalysis 选择

**What to build:** 分析默认展示原始判定，用户可用 evaluation_id 显式选择试算；基线关联真实组件与档案；缺策略和缺基线原因分开。

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] AC-PERF-01：真实指标、样本数与缺失原因正确，不补零
- [ ] AC-PERF-02：跨档案显示不可比且 not_tested 原因正确
- [ ] AC-PERF-03：原始阈值与历史报告不被试算覆盖
- [ ] AC-CONTRACT-04：默认 original，显式 evaluation_id 才选 reanalysis
- [ ] 缺 original 时不自动兜底；gate_policy_missing 与 baseline_missing 可区分
