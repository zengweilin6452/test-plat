# 14: 历史缺 original 的显式重分析

**What to build:** 已完成且有可用数据的历史运行，即使缺 original，也可显式追加 reanalysis；原始缺失标记持续保留。

**Blocked by:** 13

**Status:** ready-for-human

- [x] AC-GATE-02：只新增 reanalysis，原 outcome 不变
- [x] 报告持续显示 original 缺失，不补造
- [x] 未完成或输入不可用时拒绝并说明缺项
- [x] 重复请求幂等，不追加重复记录
- [x] 未知历史档案不伪造可比来源

## Comments

- 实现提交 `0c4928d`（`feat(issue14): 历史缺 original 的显式重分析`）。
- 语义变更：终态（completed/errored/cancelled）运行经 `POST /runs/{id}/gate-evaluations` 补判定一律落 `mode=reanalysis`——"原始判定"只在 finalizing 事务内产生（runtime 显式传 `run_complete=True`），事后补造 original 等于伪造。`test_perf_gate_api` 两处 mode 断言与"每组件一条 original"断言同步更新（不变量改由部分唯一索引用例直接验证）。
- 未完成的运行外部试算 → 409，detail 带当前状态；幂等重放同 request_key 返回同一行（200）。
- 分析页默认仍指向 original：缺 original 时 `original_missing=true`、verdict null，不兜底到补判定；显式 `evaluation_id` 才能选中。
- 跨档案：显式指定另一档案运行的基线 → 判定照做但 `not_tested + profile_mismatch`，不伪造可比来源。
- 验收（定向）：`test_issue14_historical_reanalysis.py` 4 例 + issue12/13、perf_gate_api、03_finalize、import_and_finalize、run_submission 回归全过；OpenAPI `--check` 通过。全量未跑（按指示）。
