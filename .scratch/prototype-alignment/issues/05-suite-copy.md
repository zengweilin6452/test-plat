# 05: 受控来源与固定代码副本

**What to build:** 从预配置来源登记套件，服务端保存 V1 代码副本与摘要；发现和执行都读副本，来源更新产生新版本。

**Blocked by:** 01、03

**Status:** ready-for-human

- [x] AC-INPUT-02：旧版本在来源目录变化后仍使用 V1
- [x] 浏览器不能传任意宿主路径；越界与符号链接逃逸拒绝
- [x] 原件损坏或缺失阻断，不回退到可变来源目录
- [x] 磁盘不足返回明确错误，不自动淘汰旧副本
- [x] 旧 suite 无副本时标记“未保留固定代码”，新运行前须显式创建新版本

## Comments

- 实现提交 `20ee1eb`（`feat(issue05): 受控来源与固定代码副本`）。
- 来源改为 `TESTDOCK_SUITE_SOURCES`（JSON 数组：id/name/path/test_types）；`GET /suite-sources` 只回 id、显示名与适用类型。
- `POST /suites` 登记即发布 V1：解析来源 → `copy_source` 固定副本 → 在副本上 `collect_suite` → 套件 + 首版本同一事务。
- `POST /suites/{id}/discover` 只收 `source_id`；传 `suite_root` 由 schema 拒绝（422 validation_error），不再接受任意宿主路径。
- 版本视图新增 `has_code_copy`；UI/joint 版本缺 `manifest.code_copy` 时 readiness 校验阻断，performance 声明式场景豁免。
- 错误只回 `source_id` 与 `details.reason`（source_not_configured/source_type_mismatch/source_symlink/source_missing/disk_full…），不回显宿主目录；磁盘不足不淘汰旧副本、不发布版本。
- 验收：`tests/test_issue05_suite_sources.py` 9 例（链接用例走 junction 回退）；worktree 全量 312 passed / 1 skipped；`scripts/export_openapi.py --check` 通过；迁移 head 仍为 `0004`（未新增迁移）。
- 已知接线缺口：运行派发（`runner/spawn.py`、`scheduler/dispatcher.py`）尚未调用 `prepare_execution_copy`，执行侧真正读副本留待工单 08（运行生命周期）接线。
- 来源管理目前只有环境变量，没有浏览器侧配置入口；界面部分归工单 18/21。
