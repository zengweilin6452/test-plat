# 05: 报告可追溯套件版本与固定副本

**What to build:** 报告要能从运行追溯到构建、任务修订、**套件版本与其固定代码副本摘要**、资源档案与证据；失败时可查看截图、日志与断言；证据可用/过期/缺失、检索分页、导出与重跑保持可用。

**Blocked by:** 04

**Status:** resolved

## 现状指针

- 报告构建：`server/app/routers/runs.py:880-1024`（`_report_view`）。
  - 已有 build / revision / resourceProfile / evidence / vendorReports / junit。
  - **缺**套件版本（`task_revisions.suite_version_id` → `suite_versions.version`）与 `manifest.code_copy.tree_sha256`。
- 证据与产物：`server/app/domain/artifacts.py`、`server/app/routers/runs.py` 的 `/report`、`/report/export`、`/artifacts/.../download`。
- 检索分页：`server/app/routers/runs.py` 的 completed 过滤与游标分页（工单 10）。
- 既有测试：`test_issue10_report_search.py`、`test_issue11_report_evidence.py`、`test_import_and_finalize.py`。

## 实现要点

1. 在报告视图增加套件块，例如：
   `suite: {id, version, source_ref, source_commit, code_copy: {tree_sha256, file_count, root_rel}}`。
   缺失时明确 null，不用别的版本冒充。
2. `revision` 块补 `suite_version_id`；导出与页面消费同一份视图。
3. 确保报告只读：后续重新发现/改来源不能改变历史报告引用的版本与摘要。
4. 证据三态与下载链接维持现有契约；缺失/过期不给假链接。
5. 失败运行能定位到失败截图、日志与断言信息；报告抽屉与实际产物一致，缺失时说明原因。
6. 检索、分页、重跑（新记录不覆盖历史）回归。
7. 需要时同步 `web/src/api/types.ts` 与报告抽屉展示；页面空态/缺失态如实。

## 验收标准

- [ ] 报告包含构建、修订、套件版本、代码副本树摘要、资源档案与证据。
- [ ] 固定副本缺失/损坏导致未执行的运行，报告不伪造套件结论。
- [ ] 证据 available/missing/expired 分别呈现；仅 available 有下载入口。
- [ ] 失败运行可查看失败截图/日志/断言，缺失或过期时说明原因。
- [ ] 超过一页的报告仍能通过搜索与游标分页找到；重跑生成新记录。
- [ ] 导出内容与页面报告同源。
- [ ] 新增字段有回归测试；OpenAPI 检查通过（若契约变更）。

## 验证命令（建议）

```powershell
cd server
$env:TESTDOCK_TEST_DATABASE_URL="postgresql+psycopg://testdock@127.0.0.1:55432/<ticket05_db>"
D:\python312\python.exe -m pytest tests/test_issue10_report_search.py tests/test_issue11_report_evidence.py tests/test_import_and_finalize.py -q
cd ../web
npx tsc -p tsconfig.json --noEmit
```

## 已核实缺陷（探索笔记）

- `_report_view`（`server/app/routers/runs.py:880-1024`）没有 suite 块，`revision` 也没有 `suite_version_id`；导出同源同样缺。
- `domain/artifacts.py:252` 只写 `availability="available"`，没有过期清扫，导致 missing/expired 在生产不可达、下载门控形同虚设。需要能产生三态的真实路径或明确的过期判定。
- `web/src/components/ReportDrawer.tsx:161-207` 未展示 build/revision；`web/src/api/types.ts:122-174` 无 suite 字段。
- 详细笔记：`C:\Users\williamzeng\AppData\Local\Temp\testdock-frc-notes\05-report.md`

## 约束

- 不修改 `vendor/`、不安装依赖、不 push。
- 报告字段只追加，不破坏既有前端消费。

## Comments

- 2026-11-01 实现完成（`974bc2b`，合并 `5d42a3d`）。①报告新增 `suite {id, version, source_ref, source_commit, code_copy{tree_sha256,file_count,root_rel}}` 与 `revision.suite_version_id`，只读 `suite_versions` 不可变行，缺失为 null；导出与页面同源。②证据三态改为读取时复核：`expires_at` 过期→expired，磁盘缺文件/storage_key 不可解析→missing，否则 available；仅 available 给 `download_url`，并附 `unavailable_reason`。③新增 `TESTDOCK_ARTIFACT_RETENTION_DAYS`（默认 0 = 未启用保留期；启用后登记写 `expires_at`，expired 真实可达）。④失败运行报告可定位截图/日志/断言（junit.xml 可下载），产物被清理时说明原因。⑤前端 ReportDrawer 展示构建/修订/套件/副本摘要与证据三态；缺失态如实。
- 证据：新增 `test_issue05_report_traceability.py` 11 例 + 既有报告检索/证据/导入收敛，后端定向 84 passed；前端 30 passed；tsc 无错；契约测试通过（`/report` 未建模，无需刷新 openapi）。
- 遗留：默认未配置保留期时 expired 不会自然出现（需宿主配置天数或产物被清理）；保留期默认值是否开启待工单 10 按部署口径记录。
