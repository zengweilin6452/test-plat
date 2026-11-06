# 24: 执行接线——运行前身份复核与固定代码副本

**What to build:** 派发真实运行前，平台在已独占的设备上复核构建身份、把套件执行目录指向固定代码副本；复核失败或副本缺失时阻断该次运行，而不是让 runner 去读可变来源或未核对的安装包。

**Blocked by:** 08

**Status:** resolved

- [x] 派发时执行目录来自固定代码副本，不读可变来源目录；报告与事件记录实际使用的副本摘要
- [x] 旧套件无固定副本时阻断派发，并明确提示需先创建新套件版本，不回退到来源目录
- [x] 运行独占设备后、拉起 runner 前复核构建身份；冲突或关键字段不可读时阻断，设备随即释放
- [x] 身份复核与运行租约不互相死锁：同一设备同一时刻只有一条活动租约，复核在运行租约内完成（或改为领租约前短检查）
- [x] 三条阻断路径（副本缺失、摘要不符、身份冲突）各有回归测试，且被阻断的运行落在 errored/not_tested 而不是 completed

## Comments

- 由来：工单 04（“每次运行独占后复核身份”）与工单 05（“执行读固定副本”）都把执行侧接线留给了工单 08；工单 08 只做运行创建/事件恢复/取消，没有把这两段接进派发路径，因此单列本工单。
- 不在工单 08 内做的原因：身份复核会申请**短检查租约**（`device_checks`），而调度器在派发时已经持有同一设备的**运行租约**；`leases_one_live_resource` 唯一索引不允许两条活动租约并存，接线必须先决定复核在运行租约内完成还是调整领取顺序，属于独立设计决策。固定副本接线还需要改 runner 的工作目录与参数，并影响事件/报告里的路径记录。

## Comments

- 实现提交 `21f3ede`（`feat(issue24): 派发接固定代码副本与运行租约内身份复核`）。
- 固定副本接线（工单 05 缺口）：dispatch_one 在领取租约后、迁移 dispatching 前调用 `prepare_execution_copy`（复验摘要/树哈希），成功则把副本根目录写进 spawn 配置 `suite_root`；缺失/损坏 → 释放租约 + errored(execution_copy_missing)，绝不回退来源目录。
- 身份复核接线（工单 04 缺口）：spawn 前在**运行租约内**用只读 dumpsys 复核安装身份——不申请第二把租约（`leases_one_live_resource` 排斥），无死锁；构建身份 state=confirmed 且有 baseline 才复核；versionName 冲突 → errored(identity_mismatch) 且租约释放；不可读 → errored；pending → skipped（不冒充通过也不阻断，由报告的 verification_note 说明等级）。复核只发白名单只读命令（测试断言不含 install/tcpip/connect 等）。
- 夹具：`make_project` 的套件版本现在带真实可校验的 code_copy（副本根取自 TESTDOCK_CODE_COPIES_DIR / data 目录）。
- 验收（定向）：`test_issue24_execution_wiring.py` 4 例（副本缺失阻断、happy path 带 suite_root 且只读、身份冲突阻断并释放租约、pending 不阻断）+ run_submission / p3_transitions / p5_debug / import_and_finalize / p7_device_sync 回归全过；OpenAPI `--check` 通过。
- 已知边界：真机模式的 dumpsys 解析与 vendor 锁配合需要实机走查；runner 的 cwd/argv 仍未切换到副本目录（spawn 只把 suite_root 传给 runner，runner 侧消费归 runner 生命周期迭代）。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
