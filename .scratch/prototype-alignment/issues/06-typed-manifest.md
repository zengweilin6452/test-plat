# 06: 类型化清单与任务验证

**What to build:** UI、performance、joint 各自使用明确的清单形状与就绪规则；空清单失败，性能场景不伪造 pytest 用例。

**Blocked by:** 04、05

**Status:** resolved

- [x] AC-INPUT-03：三种类型分别验证，套件与修订测试类型不匹配失败
- [x] AC-CORE-02：缺构建、缺套件、无效归属、空或不适用清单显示准确 missing/invalid
- [x] 声明式性能场景没有虚假 cases
- [x] joint 缺少 UI 或性能任一部分时验证失败
- [x] 错误可读、可修复，不以占位数据通过验证

## Comments

- 实现提交 `93ebb15`（`feat(issue06): 类型化清单与任务验证`）。
- `domain/suite.py` 新增 `build_typed_manifest` / `validate_manifest`；manifest 带 `test_type`，performance 的 `case_count` 恒为 0、`cases` 为空。
- `POST /suites/{id}/versions` 发布 performance 声明式场景或 joint 组合；UI 版本仍由 discover 产生；performance 套件走 discover 返回 400。
- 登记语义：UI 必须带 source_id；performance/joint 登记阶段不接受来源，首版本由 `/versions` 发布。
- readiness 新增套件/修订类型一致性校验；带 `test_type` 的新清单按 §6.6 逐项校验，旧清单沿用旧口径（UI/joint 需用例与固定副本）。
- 验收：`tests/test_issue06_typed_manifest.py` 10 例；worktree 全量 322 passed / 1 skipped；`export_openapi.py --check` 通过；未新增迁移（head 仍 0004）。
- 已知接线缺口：joint 的实际执行（UI 与采集时间边界）归工单 16；浏览器侧清单展示与类型选择归工单 18/19。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
