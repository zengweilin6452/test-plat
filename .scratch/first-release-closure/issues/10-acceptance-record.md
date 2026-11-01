# 10: 首期交付验收记录

**What to build:** 在 `integration/first-release-closure` 的最终 HEAD 上，产出一份可追溯的验收记录：逐项标明已通过、已实现待验、未完成或受阻，附当前版本、测试条件与证据；区分历史结果与本次结果。

**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08, 09

**Status:** resolved

## 交付物

新建 `.scratch/first-release-closure/acceptance.md`，结构建议：

1. **版本与范围**：集成分支名、HEAD commit、数据库迁移 head、原型参考版本（文件哈希）、测试环境（Windows 版本、Python/Node 版本、设备 serial、来源配置状态）。
2. **逐项验收表**：对应 spec 的 31 条 User Stories 与 Integration/Testing Decisions，每项：状态（已通过 / 已实现待验 / 未完成 / 受阻）、证据（测试名+结果、API 调用、截图、事件/报告 id）、条件（设备、数据库、来源）、备注。
3. **本次实际执行的验证**：命令、时间、结果；未执行项写清原因与需要谁提供什么。
4. **发现并修复的范围内缺陷**：工单号、提交、复验证据。
5. **已知边界与后续**：真机未覆盖项、来源未配置、跨机器/多用户等 out-of-scope。
6. **结论**：是否满足「首期核心流程与交付验收」；不把未执行记为通过。

## 实现要点

1. 在当前 HEAD 重跑受影响范围的验证，不直接摘抄历史结论；历史证据只作参考并标注日期。
2. 至少包含：后端相关测试、前端 typecheck/build/test、契约检查、`alembic heads`、专用库上的集成测试。
3. 真机部分：若执行，记录 serial、应用/构建、套件版本、运行 id/display_id、报告证据；若未执行，明确写「未执行」及原因。
4. 可信套件来源当前为空（`GET /api/v1/suite-sources` 返回空）：记录为环境阻塞，不伪造真实来源验收。
5. 记录测试库隔离方式，确认未向共享库 `testdock` 写入测试 run。
6. 验收记录提交到集成分支（本地提交，不 push）。

## 验收标准

- [ ] 31 条 User Stories 每条都有状态与依据，不存在「无证据的通过」。
- [ ] 记录当前版本（commit）、迁移 head、原型参考版本、设备/来源条件。
- [ ] 本次执行与历史证据分开标注。
- [ ] 未执行项写清原因与解除条件。
- [ ] 记录本次修复的缺陷与复验证据（链接到工单/提交）。
- [ ] 不在记录里声称未做的真机/来源验证已完成。

## 约束

- 不修改 `vendor/`、不安装依赖、不 push。
- 验收记录是交付物本身，不得用历史工单勾选代替当前 HEAD 的验收。

## Comments

- 2026-11-01 交付：`.scratch/first-release-closure/acceptance.md`（提交 `74dfed6`，合入 `9fc8354`），在 HEAD `cf9f799` 上重跑验证，不摘抄历史结论。
- 本次结果：后端全量 544 项（543 passed / 1 skipped / 0 failed，退出码 0；`addopts=-q` 与命令行 `-q` 合成 `-qq` 不打印收尾行，判定方式已写入记录）、定向 19 文件 200 passed、前端 `tsc --noEmit` 0 / `npm test` 47 passed / `npm run build` 成功、`alembic heads=0008`、契约基线一致；专用库 `testdock_frc10`，共享库 `testdock.test_runs` 为 0。
- 31 条 User Stories：已通过 22、已实现待验 8、未完成 0、受阻 1（US1 可信来源为空）。真机 UI / 性能 / 联动 / 调试、真实来源、1440×900 像素核对均未执行并写明解除条件，未记成通过。
- 结论：自动化与契约层满足；首期交付验收为「有条件通过」，不满足点已在记录 §6 单列。
- 2026-11-01 评审修复复验：`code-review` 两轴在集成分支上提出 14 条，采纳 8 组并在 `cba314a`/`f810806`/`57f9cd5`（合并 `4b4fea2`）修复——取消登记已落盘产物、`runner_terminated` 如实回报、派发窗口复查取消、快照 id 白名单、会话关闭清理验证凭证、报告页展示采集窗口、契约文档补齐、死代码清理；驳回 1 条已被 `finalize` 终态短路证伪的"取消覆盖完成态"。
- 复跑结果：后端全量 559 项（558 passed / 1 skipped / 0 failed，退出码 0）、定向 119 passed、`tsc` 0、`npm test` 48 passed、`npm run build` 成功、`alembic heads=0008`。验收记录新增 §7，§2 状态判定不变。
