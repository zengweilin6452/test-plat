# 13: 原始判定冻结与原子收敛

**What to build:** 执行前固定默认策略与同档案基线；finalizing 内完成原始判定、组件聚合与终态，不出现 completed 缺 original。

**Blocked by:** 12、03

**Status:** ready-for-agent

- [ ] AC-GATE-01：排队期间策略变化不改执行快照
- [ ] AC-CONTRACT-05：原始判定、组件结论与终态同事务收敛
- [ ] 显式指定版本失效时不偷偷替换
- [ ] 无默认同档案基线时记录缺失，不回退跨档案
- [ ] 重试幂等，每个性能组件只有一条 original
