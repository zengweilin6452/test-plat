# 07: 联动运行——同一次 UI 执行内的性能采集

**What to build:** 核对联动运行在同一资源独占期内，用同一次 UI 执行驱动性能采集窗口；UI 结束立即停采；UI 与性能分别保存真实结果，失败矩阵按实际状态呈现。

**Blocked by:** 01, 04, 06

**Status:** ready-for-agent

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
