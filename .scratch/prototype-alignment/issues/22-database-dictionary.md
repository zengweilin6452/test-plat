# 22: 数据库字典与生成器

**What to build:** 数据库页正确消费顶层分组，字典覆盖当前迁移 head，支持中文搜索、外键互跳和准确导出。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] AC-DB-01：七组与当前全部表完整显示，无重复无遗漏
- [ ] AC-DB-02：生成器包含当前 head 字段（如 last_seen_at），nullable/default/PK/FK 与权威结构一致
- [ ] AC-DB-03：中文搜索、无匹配、外键双向跳转、流程表定位和导出逐项正确
- [ ] 生成过程不修改业务库；空结果不残留无关表详情
