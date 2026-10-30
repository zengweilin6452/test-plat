# 07: 任务修订、同名冲突与幂等

**What to build:** 创建和编辑产生不可变修订；同名但不同配置返回冲突；同一幂等键不同内容拒绝，同内容跨重启复用。

**Blocked by:** 06

**Status:** ready-for-human

- [x] AC-CONTRACT-01：同名换构建或套件不得悄悄复用旧任务
- [x] AC-CONTRACT-02：PATCH 与 validate 均形成新修订，并发修改返回 stale_version
- [x] validate 成功后页面采用响应中的最新 revision_id
- [x] config 整份替换，不深合并；省略绑定字段表示不变
- [x] 旧修订与旧运行引用不被回写

## Comments

- 实现提交 `8910f90`（`feat(issue07): 任务修订、同名冲突与幂等`）。
- 判重从路由层移入 `services/tasks.py::create_task`，与建任务同一事务：先比较内容，再落库，避免"判定通过→并发插入→重复建任务"。
- 幂等键持久化：新增迁移 `0005_task_request_keys`（`(project_id, request_key)` 唯一，存规范化内容 sha256 与首次绑定的任务）。同键同内容复用（200），同键不同内容 409 `idempotency_conflict`；键随任务同一事务写入，跨进程、跨重启有效，不再依赖进程内字典。
- 并发同键用 `pg_advisory_xact_lock(hashtextextended(...))` 串行化，读到的键行一定是已提交的；唯一约束作为兜底。
- 同名任务：内容（平台、类型、构建、套件、环境、config 规范化比较）一致才复用（200）；不同则 409 `task_configuration_conflict`，details 只给 `existing_task_id`、`existing_name` 与差异字段名，不回显配置值。
- PATCH：`config` 整份替换（不做深合并，删键可表达）；省略绑定字段沿用上一修订；CAS 失败 409 `stale_version` 且不追加修订。validate 成功追加 `validated` 修订，响应即最新 `revision.id` / `lock_version`，原修订保持 `draft`。
- 验收：`tests/test_issue07_task_revisions.py` 14 例（同名同内容复用、换构建/套件/config 冲突、幂等键落库与跨引擎重启复用、同键异内容冲突、整份替换、省略不变、stale 不追加修订、validate 采用新 revision、CAS 并发、旧修订与旧运行不被回写）；worktree 全量 337 项（1 skipped）；`export_openapi.py --check` 通过；迁移 head 0005。
- 已知接线缺口：浏览器侧"采用响应 revision_id 并据此发起运行"归工单 18/19；运行与试算的幂等键内容比较归工单 08/16（本工单只覆盖任务创建）。
