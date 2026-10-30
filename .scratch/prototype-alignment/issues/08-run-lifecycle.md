# 08: 运行创建、事件恢复与取消

**What to build:** 浏览器显式绑定修订发起运行；WS 与 REST 事件按序号可恢复；取消事实不丢，且不覆盖固定输入。

**Blocked by:** 07

**Status:** ready-for-human

- [x] AC-LIVE-01：断线重连不丢终态、不重复事件
- [x] AC-CONTRACT-03：超过 500 条事件后仍可补拉，取消事实不丢失
- [x] 显式提交应用、平台、任务、修订与幂等键；跨归属引用拒绝
- [x] overrides、source_dir、test_paths 不能改写固定输入
- [x] 取消先受理后收敛；与完成竞争不伪造 cancelled

## Comments

- 实现提交 `c0ebe8a`（`feat(issue08): 运行生命周期、取消受理与事件恢复`）。
- 提交身份显式化：`application_id` 必填（不再"取该平台最早创建的应用"）、`task_id` 必填；跨应用/跨项目的任务、修订、父运行一律按 `not_found` 拒绝。省略 `revision_id` 时只解析已验证修订，并在 201/200 响应里回传实际 `revision_id`/`task_id`，派发时不再重解析。
- 固定输入：`overrides`/`source_dir`/`test_paths`/`fake_outcome`/`source` 出现在浏览器请求里直接 400 `validation_error`，且不落任何运行行；导入通道 `POST /runs/import` 走 `internal=True`，仍只允许 `source=import`。
- 取消改为持久化事实：新增迁移 `0006_run_cancel_requested`（`test_runs.cancel_requested_at/by`，并把历史事件里的首次取消时间回填）。`POST /runs/{id}/cancel` 用一条条件 UPDATE 受理（`COALESCE` 保留首次时间，终态不在 `WHERE` 范围内 → 409 `state_conflict`）；`queued` 直接迁移 `cancelled`，执行中只受理不改状态，由心跳 `cancel` 或 reconciler 收敛，与完成竞争时保留真实终态。心跳与 reconciler 的判定都读列，不再翻事件。
- 事件恢复：`GET /runs/{id}/events` 保留 `items/total/after`，新增 `next_after`/`has_more`（多取一条判断是否还有下一页）；WS snapshot 带 `last_sequence`，runner/内部端点推的事件帧带 `sequence`，客户端按 `(run_id, sequence)` 去重后从 `last_sequence` 补拉。
- 进度投影统一：列表、详情、WS 共用 `_EVENT_PROGRESS_SQL`（由 `run_events` 聚合 progress 与 last_sequence），权重与 `domain/events.STAGE_WEIGHTS` 由一条静态断言守住；完全没有事件时 progress 仍为 `null`。
- 顺手修复：`POST /internal/runs/{id}/heartbeat` 原先给 `extend_lease` 多传了 `lease_seconds`，只要 fence 通过就 TypeError → 心跳恒 500（续租与取消下发实际不可用）。改为传 `token` 只续自己的租约，并补了续租断言。
- 夹具调整：`_p3_common.make_project` 现在为每个测试项目造 build + suite + suite version + `validated` 修订（validated 行受 DB CHECK 约束，缺一不可）；`test_issue04_builds` 的构建列表断言改为按 id 取本次登记的构建。
- 验收：`tests/test_issue08_run_lifecycle.py` 17 例（缺应用/任务/幂等键、省略修订固定并回传、草稿修订拒绝、五种固定输入改写拒绝、跨应用父运行 404、queued 取消收敛与重复取消 409、执行中取消只受理且与完成竞争保留 completed、终态取消 409、心跳读列并续租、621 条事件分页与取消事实保留、列表/详情/WS 投影一致、WS 实时终态与重连重放、阶段权重静态一致）；worktree 全量 354 项（353 passed / 1 skipped）；`scripts/export_openapi.py --check` 通过（路由返回裸 dict，契约文件无变化）；迁移 head `0006`。
- 接口说明同步：`docs/plan/api-design.md` §2.4/§3.1/§4 更新为显式身份、固定输入、取消语义、事件分页与 WS 重连口径。
- 已知接线缺口：运行前构建身份复核与固定代码副本接线未进派发路径（工单 04、05 原留待本工单），已单列为工单 24，原因见该工单 Comments。浏览器侧取消按钮与断线补拉的消费方归工单 18/19。
