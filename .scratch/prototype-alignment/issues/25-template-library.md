# 25: 跨会话模板库与执行锁定

**What to build:** 模板库跨调试会话共享（登记过的模板在新会话可直接引用）；任务修订锁定所用模板的 version 与 sha256，执行时按锁定版本匹配。

**Blocked by:** 17

**Status:** ready-for-human

- [x] 模板库不依赖单个调试会话的 assets 目录：新会话能列出并引用既有模板
- [x] 任务修订记录所用模板 logical + version_id + sha256；执行时锁定版本匹配
- [x] 模板缺失或摘要不符时执行按 missing 处理，不静默用别的版本

## Comments

- 由来：工单 17 的"模板库跨会话共享"与"执行锁定 version 与 sha256"需要平台侧共享存储（vendor TemplateStore 绑定会话 assets_dir）与任务清单扩展，超出该工单范围，单列本工单。

## Comments

- 实现提交 `7f1b20d`（`feat(issue25): 共享模板库跨会话引用与执行锁定`）。
- 跨会话共享是**结构性事实**：runner 的 cwd 是 server/，debug_job 构造 MobileConfig 时不覆盖 assets_dir → vendor TemplateStore 根就是 server/assets（仓库里已存在 manifest.json/versions/）。所有调试会话共用同一存储。测试用 vendor TemplateStore 在同一根上做"A 会话 create → B 会话 list"的读写证据，并核对 version_id/image_sha256 一致。
- 执行锁定：修订 config.image_templates 声明 [{logical, version_id, sha256}]；`domain/templates.verify_template_pins` 派发前对共享库 manifest 逐条核对——缺失（missing）/ 版本或摘要不符（mismatch）→ 释放租约 + errored(template_pin_mismatch)；全部命中正常 spawn；未声明 skipped。资产根可用 TESTDOCK_TEMPLATE_ASSETS_DIR 覆盖（测试用）。
- 验收（定向）：`test_issue25_template_library.py` 5 例 + run_submission / p3_transitions / issue24 / p5_debug 回归全过；OpenAPI `--check` 通过。
- 已知边界：平台预检与 runner 实际加载之间存在极小的 TOCTOU 窗（派发后模板被并发更新）——vendor load 自带 sha256/尺寸校验，不符会直接失败而不是用错版本；UI 侧"把当前模板引用写入修订"的交互归任务向导迭代。
