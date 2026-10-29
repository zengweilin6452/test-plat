# 10: 完成报告检索与分页

**What to build:** 完成报告在服务端按 completed 过滤，并对完整结果集合提供搜索、筛选和游标分页，超过 200 条仍可找到。

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] AC-REP-01：目标报告位于截断范围外时仍可分页或检索到
- [ ] AC-FILTER-01：搜索、模块、状态组合过滤在刷新和前后导航后一致
- [ ] 只有 completed 进入完成报告列表
- [ ] 游标绑定过滤条件与创建水位，非法游标返回 422
- [ ] errored/cancelled 的部分证据不混入完成报告列表
