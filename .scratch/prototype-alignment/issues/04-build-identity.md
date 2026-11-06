# 04: 构建登记与设备身份核对

**What to build:** 浏览器登记构建后，选空闲设备只读安装身份，用户明确确认后固定基准；冲突或关键字段不可读时阻断。

**Blocked by:** 01、02

**Status:** resolved

- [x] AC-INPUT-01：同 key 同身份复用，不同身份冲突且原记录不变
- [x] AC-BUILD-01：业务 version 与实测 versionName 冲突拒绝确认
- [x] 同一已固定构建不从另一设备自动重新学习身份
- [x] 每次运行独占后复核身份，冲突或不可读阻断
- [x] 报告说明身份核对等级，不称 APK 摘要已验证

## Comments

- 实现提交 `b08f51e`（`feat(issue04): 构建登记与设备身份核对`）。
- 不新增表：核对记录、固定基准与核对等级写在 `app_builds.metadata.identity`；迁移 head 仍为 `0004`。
- 身份读取只发 `adb shell dumpsys package <pkg>`，与工单 02 的短检查租约（`device_checks.kind='identity'`）共用，设备 busy 时不访问设备。
- 验收：`tests/test_issue04_builds.py` 14 passed；worktree 全量 276 passed；`scripts/export_openapi.py --check` 通过。
- 已知接线缺口：“每次运行独占后复核”当前以 `POST /builds/{id}/identity-checks`（`purpose=pre_run`）提供，运行提交路径尚未调用它，需在工单 08（运行生命周期）接线。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
