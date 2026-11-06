# 15: 资源就绪检查与占用语义

**What to build:** 在线、空闲候选与占用分别展示；busy 设备不探测；检查只读不自愈；正式运行在独占后重新检查。

**Blocked by:** 02

**Status:** resolved

- [x] AC-RES-01：ready+idle、ready+busy、offline、unauthorized、draining 计数准确
- [x] AC-RES-02：占用预览不新建调试、不额外采屏、不抢租约
- [x] AC-RES-03：按测试类型检查，未知项不冒充通过
- [x] AC-READ-01：手动检查和运行准备均不执行 tcpip/connect、安装或设置修改
- [x] 检查失败不自动自愈，设备保持不可分配并说明原因

## Comments

- 实现提交 `eba47fd`（`feat(issue15): 资源池五状态计数与服务端汇总`）。
- AC-RES-01：`GET /resources` 响应新增 `counts`（ready_idle / ready_busy / offline / unauthorized / draining），busy 与每行字段同口径（存在未释放租约）；summary 改为"X 可用 / Y 占用中 / Z 不可用"。前端设备页四张统计卡改用服务端 counts（覆盖完整集合），加载中回退本地推导。
- AC-RES-02 / AC-READ-01 / 失败不自愈：行为在工单 02 已落地并有既有测试覆盖——busy 设备领不到检查租约直接 409 `device_busy` 且零 adb 访问（`test_busy_device_is_not_probed`）；检查只发白名单只读命令、不 tcpip/connect/安装/设置修改；检查失败写 fail 结论并释放租约，不改设备状态。本工单测试复验计数侧并依赖这些回归。
- AC-RES-03：`ReadinessCheckIn.test_type` 是 Literal（ui/performance/joint），未知值 422（有测试）；`_REQUIRED_CHECKS` 按类型取必需项，检查项缺失或 unknown 一律进 blocking，不冒充通过。
- 验收（定向）：`test_issue15_resource_readiness.py` 2 例 + p7_device_sync、issue02_readiness 回归全过；web `tsc --noEmit` 通过；OpenAPI `--check` 通过。全量未跑（按指示）。
- 已知边界："占用预览"没有独立端点——设备页对 busy 设备的可见信息来自列表行的 lease 字段与 409 details，不新建调试会话、不采屏、不抢租约（busy 预览语义由这两个既有行为构成）。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
