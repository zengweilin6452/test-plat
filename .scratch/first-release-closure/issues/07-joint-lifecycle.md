# 07: 联动运行——同一次 UI 执行内的性能采集

**What to build:** 核对联动运行在同一资源独占期内，用同一次 UI 执行驱动性能采集窗口；UI 结束立即停采；UI 与性能分别保存真实结果，失败矩阵按实际状态呈现。

**Blocked by:** 01, 04, 06

**Status:** resolved

## 现状指针

- `server/runner_pkg/testdock_runner/joint_job.py`（`run_joint_job` 复用 `run_ui_job`）。
- 派发超时：`server/app/runner/spawn.py:177-187`（`--ui-timeout` 与总 deadline 缓冲）。
- 平台收敛：`server/app/runtime.py`、`server/app/domain/joint_policy.py`。
- 既有测试：`server/tests/test_issue16_joint_lifecycle.py`。

## 实现要点

1. 核实采集窗口使用真实时间戳包围 `run_ui_job` 调用；UI 一返回立即 finalize，不补采。
2. 核实 UI 与性能组件分别落 `run_components` 与报告；矩阵：
   - 采集启动失败：UI 未执行（cancelled），性能 errored；
   - UI 超时：UI errored(ui_timeout)，性能 cancelled；
   - 用例断言失败：completed/failed，不是 runner 故障；
   - 取消/基础设施失败按实际状态。
3. 核实 01 的副本接线在联动路径同样生效（同一 `UiJobOptions`）。
4. fake 模式只用于矩阵测试，不得冒充真机验收；真机可用的部分做一次真实运行并留证据。
5. 修复缺陷并补测试。

## 验收标准

- [ ] 一次联动运行只有一条资源租约，UI 与性能共享同一独占期。
- [ ] 报告记录采集起止与 UI 执行窗的时间关系，窗口覆盖 UI。
- [ ] UI 与性能结果分别可查；任一失败不伪造另一组件结论。
- [ ] 失败矩阵各行的终态/outcome 符合契约（非 completed outcome=NULL）。
- [ ] 联动执行使用固定副本（与 01 一致），有回归测试。
- [ ] 真机验证若完成，记录设备、版本、证据；未完成则明确记录未执行。

## 验证命令（建议）

```powershell
cd server
$env:TESTDOCK_TEST_DATABASE_URL="postgresql+psycopg://testdock@127.0.0.1:55432/<ticket07_db>"
D:\python312\python.exe -m pytest tests/test_issue16_joint_lifecycle.py -q
```

## 已核实缺陷（探索笔记）

- `ui_timeout_s` 只进窗口描述（`joint_job.py:147-153`），真实 pytest deadline 仍用总 `options.timeout`（`ui_job.py:321`）——UI 窗口上限是装饰。
- UI 超时分支返回前不调用 `scope.finalize()`（`joint_job.py:155-168`），没有 report.json，采集未收口。
- 派发不合并 `suite_versions.manifest.ui_timeout_s`（`dispatcher.py:84-105`），生产恒为默认 600；既有测试直接把值塞进修订 config，掩盖了缺口。
- runner 写出的 `collectWindow`（`joint_job.py:197`）被平台 `runtime.py:688-707` 只挑 4 个键丢弃，`/report` 看不到采集窗口。
- 详细笔记：`C:\Users\williamzeng\AppData\Local\Temp\testdock-frc-notes\07-joint.md`

## 约束

- 不修改 `vendor/`、不安装依赖、不 push。
- 真机 749622c9 同一时刻只允许一个占用；跑完必须释放。

## Comments

- 2026-11-01 修复四项已核实缺陷：
  1. `ui_timeout_s` 成为真实 pytest deadline：新增 `UiJobOptions.ui_timeout_s` 与 `ui_job.resolve_execution_deadline`，joint 在执行前固定该值，UI 与窗口描述读同一个数。
  2. UI 超时也先停采并写 `report.json`：`_stop_collection` + `_write_joint_report` 统一正常/超时两条路径，超时返回 `ui errored(ui_timeout)` / `performance cancelled`，outcome 均为 NULL。
  3. 派发合并 `suite_versions.manifest.ui_timeout_s`（`dispatcher._suite_ui_timeout`），版本快照优先，非 joint/旧清单仍走 spawn 夹紧兜底。
  4. `collectWindow` 不再被 `runtime._report_json_payload` 丢弃，`/report` 直接透出采集起止与 UI 窗口。
- 失败路径也登记产物：runner `fail_report` 携带 `artifacts_dir`，`/internal/runs/{id}/fail` 交给 `finalize_run` 登记，超时前的 report.json 与窗口证据可通过 `/report` 查到。
- fake 链路补齐 `outcome`，断言失败在组件行显示为 completed/failed 而非 not_tested。
- 提交：`c9bfc8e`，合入 `631d41d`。
- 测试（`testdock_frc07`）：`test_issue16_joint_lifecycle.py` 等定向 71 passed；实现代理跑后端全量 543 passed + 1 skipped。
- 未执行：真机联动运行（不占用 749622c9），证据留 10 记录。
- 遗留：`ui_timeout_s` 以套件清单为准，修订里的冲突值被覆盖（版本不可变优先）；前端只补了 `collectWindow` 类型，展示留 09/10。
