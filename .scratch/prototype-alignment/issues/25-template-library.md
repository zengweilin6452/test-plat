# 25: 跨会话模板库与执行锁定

**What to build:** 模板库跨调试会话共享（登记过的模板在新会话可直接引用）；任务修订锁定所用模板的 version 与 sha256，执行时按锁定版本匹配。

**Blocked by:** 17

**Status:** ready-for-agent

- [ ] 模板库不依赖单个调试会话的 assets 目录：新会话能列出并引用既有模板
- [ ] 任务修订记录所用模板 logical + version_id + sha256；执行时锁定版本匹配
- [ ] 模板缺失或摘要不符时执行按 missing 处理，不静默用别的版本

## Comments

- 由来：工单 17 的"模板库跨会话共享"与"执行锁定 version 与 sha256"需要平台侧共享存储（vendor TemplateStore 绑定会话 assets_dir）与任务清单扩展，超出该工单范围，单列本工单。
