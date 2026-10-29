# 01: 契约与类型基线

**What to build:** 浏览器、API 与迁移共享一套请求/响应类型、错误码和 OpenAPI 基线；新增迁移骨架，不改 0001；契约测试可在 CI 运行。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] 现有端点 OpenAPI 与前端类型一致，严格响应模型不丢字段
- [ ] 新增迁移只追加，0001 保持原件
- [ ] 统一错误码与 request_id 可追溯，敏感值不回显
- [ ] 契约测试在 CI 中可运行，失败会阻断
