# 22: 数据库字典与生成器

**What to build:** 数据库页正确消费顶层分组，字典覆盖当前迁移 head，支持中文搜索、外键互跳和准确导出。

**Blocked by:** 01

**Status:** ready-for-human

- [x] AC-DB-01：七组与当前全部表完整显示，无重复无遗漏
- [x] AC-DB-02：生成器包含当前 head 字段（如 last_seen_at），nullable/default/PK/FK 与权威结构一致
- [x] AC-DB-03：中文搜索、无匹配、外键双向跳转、流程表定位和导出逐项正确
- [ ] 生成过程不修改业务库；空结果不残留无关表详情

## Comments

- 实现提交 `a1b05ba`（`feat(issue22): 数据库字典覆盖迁移链与分组一致性`）。
- AC-DB-02：生成器从只解析 0001 扩展为遍历 0002+ 迁移（op.create_table / op.add_column），字典现在包含 task_request_keys 表与 last_seen_at / cancel_requested_at / cancel_requested_by / display_no 列（26 表 / 259 列）；生成只读迁移源码 ast，不连业务库。
- AC-DB-01/03：分组"任务运行"补入 task_request_keys（含中文表名），路由层徽章计数按表清单重算；新增一致性测试（表无重复、分组无遗漏、徽章计数一致）。中文搜索 / 外键互跳 / 导出由 DatabasePage 既有实现承载（P6 交付），本轮未做浏览器走查。
- 已知边界：0007 用 op.execute 设置的 DEFAULT nextval / NOT NULL 不在 AST 里，display_no 行的 nullable/default 显示与 0001 口径的列略有差异——结构存在性与分组以迁移为准；后续如需逐列精确默认值，应改为 information_schema 快照（生成时连只读库）。
- 验收（定向）：`test_issue22_schema_dictionary.py` 2 例全过。
