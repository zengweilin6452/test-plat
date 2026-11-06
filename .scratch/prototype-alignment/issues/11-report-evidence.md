# 11: 报告详情、证据与导出

**What to build:** 报告可追溯运行时资源档案、原始阈值和证据；证据的可用、过期、缺失分别呈现；服务端导出与重跑可用。

**Blocked by:** 10

**Status:** resolved

- [x] AC-REP-03：available 可下载，expired/missing 不提供假入口
- [x] AC-REP-04：运行后改变档案或策略，历史报告仍追溯原输入
- [x] 缺字段明确标缺失，不以设备 serial 冒充档案
- [x] 导出内容与报告快照一致，不含凭据或宿主敏感路径
- [x] 重跑创建新运行并保留来源关联

## Comments

- 实现提交 `f42dd41`（`feat(issue11): 报告快照、证据可用性与服务端导出`）。
- 报告重构为 `_report_view`（GET /report 与 GET /report/export 共用同一构建器）：新增 `revision`（id/readiness/test_type）、`build`（version/build_key/source_commit/sha256）、`environmentId`（来自修订，原来硬编码 null）、`resourceProfile`（id/name/fingerprint/spec，读运行时挂在 `test_runs.profile_id` 的档案行）、`components`、`gateEvaluations`、`evidence`、`resourceName`。
- AC-REP-04 成立的结构性原因：`resource_profiles` 是不可变档案（内容变化=新增行），`gate_evaluations` 行不可变；报告读的是这两张表里运行时绑定的行，跑完改策略/新增档案行不改写历史报告（有测试：改 `gate_policies.rules` 后报告逐字段不变）。
- AC-REP-03：evidence 只有 `availability='available'` 才给 `download_url`；missing/expired 为 null，下载端点本身也按可用性 404。`storage_key`（宿主存储路径）不进报告。
- 导出：`GET /runs/{id}/report/export` 用与 GET /report 同一个 `jsonable_encoder` 序列化（逐字段一致，有测试比对），文件名 `TestDock-<display_id>.json`（工单 09 的稳定编号）。
- 前端：报告抽屉加"重跑（引用原输入）"（POST /runs 带 `parent_run_id` + 原修订，成功后跳运行页）、"性能分析"跳转（/perf）、"导出 JSON"直链；`RunReport` 类型补 revision/build/resourceProfile/evidence/gateEvaluations。
- 验收（按指示只跑定向）：`tests/test_issue11_report_evidence.py` 6 例（追溯修订/构建/档案、缺失字段 null 不冒充、改策略不改写原始判定、available 才有下载入口且 missing 下载 404、导出与快照逐字段一致、重跑新运行带 parent_run_id 且原记录一行不改）；web `tsc --noEmit` 通过；OpenAPI 基线重新生成并通过 `--check`。全量套件未跑（按用户指示）。
- 已知边界：`thresholdsAtRun` 目前仍来自 vendor report.json（`runtime.read_report_source`），平台侧"排队时固定策略与阈值快照"（`gate_evaluations` 扩列）归工单 13；`resourceProfile` 的 id/name/fingerprint 已回传，spec 明细是否在抽屉展开展示留给工单 21 的报告页打磨。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
