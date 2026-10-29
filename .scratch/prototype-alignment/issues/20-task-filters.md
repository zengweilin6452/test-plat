# 20: 任务中心过滤与 URL 恢复

**What to build:** 任务中心支持搜索、模块和状态组合过滤，刷新与前后导航结果一致，切换 scope 时重置相关过滤。

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] AC-FILTER-01：组合过滤、刷新和前后导航结果一致
- [ ] URL 保留 scope、application、q、test_type、state
- [ ] 切 scope 清空相关参数和本地状态，不保留陈旧过滤
- [ ] 运行态过滤以关联运行查询实现，不把运行 state 当任务 lifecycle 或 readiness
