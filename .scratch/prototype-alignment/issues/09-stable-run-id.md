# 09: 稳定运行编号

**What to build:** 运行获得持久且唯一的展示编号，跨任务、运行、报告、告警和导出保持一致，历史 UUID 链接仍可用。

**Blocked by:** 08

**Status:** resolved

- [x] AC-ID-01：同一运行跨页面编号一致
- [x] 过滤、分页、新增运行和授权历史变更不重编号
- [x] 历史回填只执行一次且幂等，不改已有编号
- [x] UUID 始终是精确身份，展示编号不替代主键

## Comments

- 实现提交 `3713fe5`（`feat(issue09): 稳定运行编号持久分配`）。
- 根因：`display_id` 原来是查询期 `row_number() OVER (ORDER BY created_at, id)` 现算的，插入更早的记录或删掉历史数据就会让同一个运行换号（spec INV-10）。
- 新增迁移 `0007_run_display_no`：`test_runs.display_no`（bigint）+ 序列 `test_run_display_no_seq` 作列默认值 + 唯一索引；历史行按 `(created_at, id)` 回填一次，与旧的动态算法同口径，已流出的 `RUN-xxxx` 引用迁移后仍指向同一运行。回填语句带 `WHERE display_no IS NULL`，重复执行是空操作。
- 展示编号只做格式化（`domain/runs.format_display_id`），列表、详情、WS 快照、任务列表、报告都读同一列；`GET /runs` 不再用 CTE 现算，`_display_id()` 那条 count 查询删除。
- 任务列表原先返回 `RUN-<uuid>`（与运行页的 `RUN-0001` 不是一个东西），改为最新运行的持久编号，并在 `run` 引用里也给出 `display_id`；没有运行的任务仍是 `TASK-<uuid>`。
- 报告：`runId`/`hostRunId` 改用持久展示编号（与 api-design.md §2.5 的示例一致），并新增 `id`（UUID）保证精确身份；`GET /runs/{display_id}` 仍是 404，路径参数只接受 UUID。
- 验收：`tests/test_issue09_stable_run_id.py` 6 例（持久/唯一/格式、新增运行与回填更早时间/删除旧运行后不重编号、列表/详情/WS/任务/报告编号一致、UUID 精确身份、回填幂等且按 created_at 排序、新运行接最大号）；worktree 全量 360 项（359 passed / 1 skipped）；`export_openapi.py` 已重新生成并通过 `--check`（`TaskRunRefOut` 新增 `display_id`）；迁移 head `0007`。
- 已知边界：编号是**全局**递增（与旧算法一致，保证历史编号不跳号），因此编号会暴露跨项目的运行总量；若后续要按项目编号，需要单独迁移并明确历史编号如何保留。告警/通知模块尚未实现，接上时直接复用同一 `display_id`。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
