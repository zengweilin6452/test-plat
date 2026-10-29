# 14: 历史缺 original 的显式重分析

**What to build:** 已完成且有可用数据的历史运行，即使缺 original，也可显式追加 reanalysis；原始缺失标记持续保留。

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] AC-GATE-02：只新增 reanalysis，原 outcome 不变
- [ ] 报告持续显示 original 缺失，不补造
- [ ] 未完成或输入不可用时拒绝并说明缺项
- [ ] 重复请求幂等，不追加重复记录
- [ ] 未知历史档案不伪造可比来源
