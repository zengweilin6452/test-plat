# 03: 性能运行与判定闭环 — 验收证据

- 执行时间：2026-11-08 20:50–21:05（本机时间）
- 版本：master @ `d3c2124`；环境同 02（隔离库 `testdock_rr02`、产物根 `.runtime/rr-verify/data`、真机 749622c9）
- 能力背景：mobile_perf 六块能力（启动/整页/网络/接口/整页耗时/泄漏趋势 + p90 + HAR 枚举）已于 2026-11-08
  在 `feature/ui-ux-polish` 真机 E2E 验收（RUN-1032，`docs/plan/perf-capability-e2e.md`），该代码原样并入
  master（`04194a1`），证据继续适用；本轮在 master 上补真实采集与判定链路复核。

## 验收项逐条（measured）

| AC | 结果 | 证据 |
| --- | --- | --- |
| 页面登记固定性能场景与资源，真实采集可追溯 | ✅ | 向导内「登记性能场景 / 发布固定版本」：v1·300s·CPU/Memory/FPS，随后发布 v2·30s·CPU/Memory/FPS——版本只追加，v1 原样保留（不可变载体）；RUN-0003 报告 mode=live、窗口 20:52:58.510→20:53:33.424、durationS=34 |
| 性能前置条件不满足时说明原因 | ✅ | 表单标注「FPS 首次可能弹系统告知框」「Battery 充电时可能降级」「Temperature/GPU 由补采旁路自动采集」「HAR 需宿主安装 mitmproxy，未安装时如实标注未判定」；无门禁策略时判定卡片给出「缺少门禁策略，无法判定」 |
| 缺失指标空值+原因；样本/可比不足如实未判定 | ✅ | RUN-0003 实采 15 项指标全部带 median+p90+sampleCount（cpu_global 61 样本、fps 118、mem_global 4165MB 等），未请求的指标不出现也不写零；泄漏趋势卡「样本不足：同档案历史运行不足 3 次（当前 1 次）」；无基线时全部指标「无基线参照」 |
| 重分析不改原始判定 | ✅ | POST /gate-evaluations（request_key 幂等）落 mode=reanalysis（not_tested/baseline_missing，如实）；报告同时返回 original（not_tested/gate_policy_missing，原样）+ reanalysis 两行，只 INSERT 不 UPDATE |
| 在线报告/图表可读，独立性能不声称执行 UI 业务 | ✅ | 性能页「运行分析」：门禁结论未判定+原因、14 指标卡、逐项检查「未参与判定」、运行上下文（任务/类型/档案/窗口/统计口径 median/判定模式）、试算区明示「只新增判定行」；向导明示「不执行 UI 用例，也不需要固定代码副本」 |
| 复用既有行为测试与真机证据 | ✅ | 复用 RUN-1032 能力面证据 + 本轮 RUN-0003 主链路复核；三态门禁/缺失补零由 `test_perf_gate_api`(22) 等自动化钉住（665 项全量含） |

## 门禁/基线口径

本轮未配置门禁策略与同档基线（与首期口径一致）：性能运行如实 `not_tested(gate_policy_missing / baseline_missing)`，
不伪造判定。基线比较与跨档案不可比由既有自动化覆盖（`test_issue13_original_freeze`、`test_perf_gate_api::test_cross_profile_baseline_is_not_tested_with_profile_mismatch`）。

## 运行身份

- RUN-0003（性能）：completed / not_tested / gate_policy_missing；采集窗口 34s；15 指标 median+p90。
- GPU 占用/显存、电池温度（32.8°C）经补采旁路产出。
