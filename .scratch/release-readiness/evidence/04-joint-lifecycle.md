# 04: 联动运行与资源释放 — 验收证据

- 执行时间：2026-11-08 21:05–21:18（本机时间）
- 版本：master @ `d3c2124`；环境同 02/03（隔离库 testdock_rr02、真机 749622c9）
- 联动套件：`计算器联动套件`（test_type=joint，绑定 com.miui.calculator），
  v1·4 用例·300s 与 v2·4 用例·30s·CPU/Memory/FPS（ui_timeout_s=600）

## 本轮发现并修复的范围内缺陷

| 缺陷 | 修复 | 复验 |
| --- | --- | --- |
| **联动版本无法从页面发布**：POST /suites/{id}/versions 一直被 `joint 清单缺少 ui_timeout_s（正整数秒）` 拒绝——前端 InputRegistration 发布载荷从未携带该契约必填字段（首期联动版本走 API 直发，页面路径从类型化清单校验引入起就是断的） | 前端补 `UI 执行超时（秒，10–3600，默认 600）` 输入并随 joint 发布体发送（抽出纯函数 `jointVersionPayload` 锁形状）；`valid` 门禁加 10–3600 校验 | `tsc --noEmit` 通过；web 全量 90/90（新增回归用例）；页面上真实发布 v1（300s）与 v2（30s）成功，版本选择/创建任务/运行全链路走通 |

## 验收项逐条（measured）

| AC | 结果 | 证据 |
| --- | --- | --- |
| 采集窗口覆盖 UI 执行，双组件结果及证据保留 | ✅ | RUN-0004（joint，v2·30s）：collectWindow 21:12:21.836→46.171（24.3s）**完整包围** UI 21:12:24.452→44.104（19.7s）；components：`ui completed/failed`（故意失败用例）+ `performance completed/not_tested` 分别保留；junit 4 用例 1 failure + 15 项真实指标 |
| 正常完成/组件失败/取消/执行错误收敛规则 | ✅ | 本轮真机覆盖完成（RUN-0004）与取消（RUN-0005）；组件失败矩阵（UI failed + perf errored 等组合）由 `test_issue16_joint_lifecycle.py` 21 项 + §16.2 修复矩阵自动化钉住（665 项全量含）；整体 failed 未伪装成通过 |
| 同设备运行与调试互斥 | ✅ | 租约 DB 层强制（`test_issue02_leases`、`test_issue04_run_lifecycle::test_busy_requested_device_never_runs_two_runs_concurrently`）；本轮运行串行执行、活动租约全程 0/1；调试互斥在 05 工单真机复核 |
| 运行结束/取消后资源可再次使用 | ✅ | RUN-0005 于 21:15:15 取消（HTTP 202、`runner_terminated=true`、终态 cancelled/outcome NULL/reason=cancel_requested，与运行结论分离）→ 活动租约 0 → RUN-0006 同设备 21:16:36 启动、26s completed；全程无非终态残留、无泄漏租约 |
| 历史 runner 消失为观察项 | ✅ | 本轮 6 次真机运行无 runner 消失复现；维持观察项口径（复现才按规格决策 11 限口径调查） |

## 运行身份

| 运行 | 类型 | 终态/结论 | 说明 |
| --- | --- | --- | --- |
| RUN-0004 | joint v2·30s | completed / failed | 采集窗包围 UI；ui=failed（故意用例失败）、performance=not_tested（无策略） |
| RUN-0005 | joint（同输入重跑） | cancelled / outcome NULL | 运行中取消，runner 进程树终止，租约即时释放 |
| RUN-0006 | joint（同输入重跑） | completed / failed | 取消后立即再运行成功，duration 26s |
