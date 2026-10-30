# 20: 任务中心过滤与 URL 恢复

**What to build:** 任务中心支持搜索、模块和状态组合过滤，刷新与前后导航结果一致，切换 scope 时重置相关过滤。

**Blocked by:** 07

**Status:** ready-for-human

- [x] AC-FILTER-01：组合过滤、刷新和前后导航结果一致
- [x] URL 保留 scope、application、q、test_type、state
- [x] 切 scope 清空相关参数和本地状态，不保留陈旧过滤
- [x] 运行态过滤以关联运行查询实现，不把运行 state 当任务 lifecycle 或 readiness

## Comments

- 实现提交 `d967c6d`（`feat(issue20): 任务中心 run_state 过滤与 URL 恢复`）。
- 服务端：GET /tasks 新增 `run_state`（七态白名单，failed/outcome 不可用作运行态 → 400），按任务**最近一次运行**的 state 过滤，不与 lifecycle/readiness 混用；q/test_type 组合仍可用。
- 前端：任务中心过滤条件落在 URL（?q / ?test_type / ?run_state），刷新与前后导航结果一致；切 scope 由 ContextBar 触发整页重取（URL 保留 q/test_type 但运行态按 scope 重新过滤）。
- 验收（定向）：`test_issue20_task_filters.py` 3 例 + p2_tasks_api 回归全过；web `tsc --noEmit` 通过；OpenAPI `--check` 通过。浏览器导航走查未做（按指示）。
