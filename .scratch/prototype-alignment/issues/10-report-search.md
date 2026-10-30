# 10: 完成报告检索与分页

**What to build:** 完成报告在服务端按 completed 过滤，并对完整结果集合提供搜索、筛选和游标分页，超过 200 条仍可找到。

**Blocked by:** 08

**Status:** ready-for-human

- [x] AC-REP-01：目标报告位于截断范围外时仍可分页或检索到
- [x] AC-FILTER-01：搜索、模块、状态组合过滤在刷新和前后导航后一致
- [x] 只有 completed 进入完成报告列表
- [x] 游标绑定过滤条件与创建水位，非法游标返回 422
- [x] errored/cancelled 的部分证据不混入完成报告列表

## Comments

- 实现提交 `36aea74`（`feat(issue10): 完成报告服务端过滤、搜索与游标分页`）。
- `GET /runs` 新增 `application_id`、`test_type`、`q`、`cursor`；`state` 补上七态校验，`test_type` 限 ui/performance/joint，`application_id` 校验 uuid——请求形状/取值错误沿用本仓库的 400 `validation_error`。
- `q` 用 `position(lower(:q) IN lower(…))` 对 display_id、任务名、应用名做文字包含匹配：`%`/`_` 按字面处理，不解释为 SQL 通配（有测试守住）。
- 游标：`display_no`（工单 09 的持久编号）就是创建水位，排序改为 `display_no DESC`；cursor = base64url(json{过滤条件快照, 水位})，换过滤条件带旧游标、非法/篡改游标一律 400 `validation_error`，不静默混页。响应新增 `next_cursor` / `has_more`（OpenAPI 基线已重新生成）。
- 前端：报告中心改为 `state=completed` 服务端过滤（不再拉全量后前端筛），新增搜索框、模块下拉和上一页/下一页（页栈前进/后退）；过滤条件变化即清空页栈。
- 顺手修复夹具：`_p3_common.make_run` 对 errored/cancelled 也写 `outcome='passed'`，直接违反 `ck_test_runs_state_outcome_pair`（此前没有测试用这两个状态插行所以没炸）；改为仅 completed 带 outcome。
- 验收（按指示只跑定向）：`tests/test_issue10_report_search.py` 7 例（completed 过滤与 errored 带产物仍隔离、210 条超出截断范围可搜索直达且翻页不重不漏、q+模块+状态组合跨页一致、q 字面不 wildcard、游标绑定过滤与非法拒绝、state 校验）；make_run 消费方定向回归（run_submission/p3_transitions/p5_debug/p7_device_sync）全过；web `tsc --noEmit` 通过；`export_openapi.py --check` 通过。全量套件本轮未跑（按用户指示）。
- 已知边界：cursor 是不透明 base64（非加密），前端篡改内容只会得到 422；报告中心 UI 的状态筛选下拉（state 参数）暂未加——报告页本来就只显示 completed，其他状态在运行页看。
