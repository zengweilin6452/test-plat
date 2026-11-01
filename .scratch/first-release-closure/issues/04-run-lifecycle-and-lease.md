# 04: 运行生命周期、资源独占与取消

**What to build:** 核对任务修订的创建与验证（草稿 → 已验证、同名冲突、幂等），以及从已验证修订发起运行后的排队/占用/派发/取消/终态/释放；事件可恢复；设备忙时排队或明确拒绝；取消后设备及时释放且最终状态可见。

**Blocked by:** 01, 03

**Status:** ready-for-agent

## 现状指针

- 提交运行：`server/app/routers/runs.py`（`_insert_run` / `_resolve_revision`）。
- 派发与租约：`server/app/scheduler/dispatcher.py`、`server/app/domain/leases.py`。
- 生命周期：`server/app/domain/runs.py`、`server/app/runtime.py`。
- 事件：`server/app/domain/events.py`、`server/app/routers/ws.py`。
- 既有测试：`test_issue08_run_lifecycle.py`、`test_issue09_stable_run_id.py`、`test_issue15_resource_readiness.py`、`test_p3_transitions.py`、`test_run_submission.py`、`test_p5_control_token.py`。

## 实现要点

0. 核实任务修订：编辑产生不可变修订；同名但不同配置返回冲突；同一幂等键不同内容拒绝、同内容复用；`readiness=validated` 必须由显式验证产生。
1. 核实必须绑定 `revision_id`（或先解析并固定）；草稿修订不能发起运行。
2. 核实 queued → dispatching → running → completed/failed/errored/cancelled 的合法边；非 completed 的 outcome 必须 NULL。
3. 核实设备忙：指定设备被占 → 保留 queued 或按 `resource_busy` 呈现；不可重试原因 `requested_device_not_found` / `requested_device_platform_mismatch` / `device_unavailable` 分别收敛。
4. 核实取消：`POST /runs/{id}/cancel` 后 runner 进程树被终止、run 终态可见、租约释放、设备可再次派发。
5. 核实事件恢复：WS 断线后按 sequence 补齐；同一事件幂等。
6. 本工单允许修 dispatcher/runner 中与 01 接线相关的缺陷，但不要重写 01 的副本消费逻辑。

## 验收标准

- [ ] 任务修订不可变；同名不同配置冲突；幂等键语义正确；验证后 readiness=validated。
- [ ] 未验证修订发起运行被拒；已验证修订正常入队。
- [ ] 设备被占时不会并发执行；抢占失败按原因区分且不误判为掉线。
- [ ] 取消后最终状态、事件与设备释放均可观察；无残留活动租约。
- [ ] 事件 sequence 可恢复，重复投递不产生重复行。
- [ ] 运行结束后设备可立即被下一次运行领取。
- [ ] 测试使用专用库；不使用真机跑完整 UI（真机验收留给 10 记录）。

## 验证命令（建议）

```powershell
cd server
$env:TESTDOCK_TEST_DATABASE_URL="postgresql+psycopg://testdock@127.0.0.1:55432/<ticket04_db>"
D:\python312\python.exe -m pytest tests/test_issue08_run_lifecycle.py tests/test_issue09_stable_run_id.py tests/test_issue15_resource_readiness.py tests/test_p3_transitions.py tests/test_run_submission.py -q
```

## 约束

- 禁止把测试库指向共享库 `testdock`（8000 调度器会认领并占用真机）。
- 不修改 `vendor/`、不安装依赖、不 push。

## Comments
