# TestPlat-Auto 修复报告（P1-01..04 + P2-01，P2-02/03 出方案）

工作分支：`fix/p1-security-hardening`（worktree `D:\workspace\zcodetest\.zcode\worktrees\294b\testplat-auto`，基于 `221c77d`，改动未提交，共 32 个文件 +904/-145，另新增 4 个测试文件与 `app/dependencies.py`）。

任务书基线说明：任务书写 HEAD=4e6b176 且有未提交修改；实测主仓与 worktree 均已推进到 `221c77d`（任务书所述的未提交修改已作为 CI 修复提交落地），主仓工作区未被触碰。

---

## 1. 修复的问题

| 编号 | 问题 | 结论 |
|---|---|---|
| P1-01 | Fencing token 校验可被"缺 token"绕过 | 已修复（并发现、修复了更严重的 409 泄露新 token 缺陷） |
| P1-02 | 重复导入覆盖 Artifact 证据，DB 与磁盘不一致 | 已修复 |
| P1-03 | 服务可绑定非回环地址 | 已修复（三层防护） |
| P1-04 | 用户侧写端点 Client Header 防护缺失/失效 | 已修复（发现 9 处"假守卫"） |
| P2-01 | Import 文件系统边界过宽 | 已收紧 |
| P2-02 | Runtime→Router 反向依赖 | 仅出方案（改动量超本轮授权，见 §8） |
| P2-03 | 大组件拆分 | 仅出方案（见 §8） |

## 2. 根因

**P1-01（三处叠加 + 一处新发现）**
- `verify_fence()` 默认 `require_token=False`：token 缺失时 `ok=True, checked=False` 直接放行。
- `fail_run` 仅在 `token is not None` 时校验；`complete_run` / `heartbeat_run` / `GET fence` 均未强制。
- `extend_lease()` 的 SQL 带 `CAST(:token AS bigint) IS NULL OR ...`：不带 token 的心跳会按 run_id 续租**当前活动租约**——租约转手后续的是新 Runner 的租约。
- 审查中新发现：`errors.fence_mismatch()` 的 details 回显 `expected`（当前租约 token）。旧 Runner 拿旧 token 被拒时，能从 409 响应里**学到新 Runner 的 token 再冒用**——单修缺 token 绕过挡不住这条路，必须一并去掉。

**P1-02**：`_insert_run()` 对重复 request_key 返回既有 Run（created=False），但 `import_run` 不看这个标志，无条件 `_import_artifacts_dir()` 覆盖复制；随后 `finalize_run()` 见已终态直接返回 → **数据库 sha256 仍是 A、磁盘文件已是 B**；B 文件数更少时还留下混合证据目录。复制过程本身无暂存，中途失败留下"半批产物"。

**P1-03**：`TESTDOCK_HOST` / `TESTDOCK_WEB_HOST` 在 config、vite 配置、启动脚本三层都没有任何校验，`0.0.0.0` 会被原样绑定。

**P1-04**：守卫函数住在 `routers/tasks.py`；更严重的是 applications / projects / legacy_review 共 9 个写端点写的是 `Depends(client_header_required)` —— 那是**返回** ApiError 对象的工厂函数，作为依赖被调用时**从不抛出**，ApiError 实例被静默当成参数值吞掉，属于形同虚设的假守卫（measured：这些端点此前无 header 也返回 200/201）。另有 analyses / baselines / gate_policies / runs(create,cancel,import) / debug 模板与代理等 14 处完全没有声明守卫。

**P2-01**：`source_dir` 仅做 `is_dir()`，rglob 全量复制（含 `.env`、`.git` 等隐藏敏感文件，会被登记为可下载证据），无 symlink、数量、字节上限。

## 3. 修改的文件

**后端核心**
- `server/app/domain/leases.py`：`verify_fence()` 删除 `require_token` 参数、一律 fail-closed（缺 token → ok=False 且不回显 expected）；`extend_lease()` token 必填、SQL 删掉 IS NULL 分支。
- `server/app/errors.py`：`fence_mismatch(run_id, provided)` 不再携带 `expected`。
- `server/app/routers/internal.py`：ack / heartbeat / fence / events / complete / fail 全部强制 fence（终态幂等重试分支保留在 fence 之前，语义为"不能改状态但可重试"）；新增 `_coerce_token()`（bool/float/垃圾串一律拒绝，防 `int(7.9)==7` 误整形）。
- `server/runner_pkg/testdock_runner/protocol.py`：`events()` 携带 `fencing_token`（与新端点契约一致）。
- `server/app/routers/runs.py`：import 幂等重构（见 §4）；create_run / cancel_run / import_run 加守卫。
- `server/app/dependencies.py`（新增）：`require_client_header()` 上移至此。
- `server/app/routers/tasks.py`、`builds.py`、`debug.py`、`resources.py`：导入切到共享模块；tasks.py 删除本地定义。
- `applications.py`、`projects.py`、`legacy_review.py`：假守卫 `Depends(client_header_required)` → `Depends(require_client_header)`。
- `analyses.py`、`baselines.py`、`gate_policies.py`、`debug.py`（6 个端点）、`resources.py`（sync）、`workspace.py`（手写校验统一）：补齐守卫。
- `server/app/config.py`：`LOOPBACK_HOSTS` + `ensure_loopback_host()` + `host` 字段校验器。
- `server/app/main.py`：`main()` 绑定前二次校验（纵深防御）。
- `server/app/domain/artifacts.py`：`SKIP_DIRS`/`SKIP_SUFFIXES` 提为公开常量（导入复制与登记同口径）。

**脚本 / 前端 / 契约**
- `scripts/dev_up.ps1`：回环预检快速失败。
- `web/vite.config.ts`：`assertLoopback()` 校验 `TESTDOCK_WEB_HOST` 与 `TESTDOCK_HOST`。
- `docs/contracts/openapi.json`：按仓库惯例用 `scripts/export_openapi.py` 再生（diff 仅新增 `X-TestDock-Client` header 参数，无其他形状变化）。

## 4. 修改方案与设计理由

**P1-01**：选择"删除 `require_token` 参数、一律 fail-closed"而非"必填参数"，因为全仓已无任何合法的宽松调用点（grep 证实仅 internal.py 与测试调用），少一个参数就少一类"忘了传 True"的错误。fence_mismatch 不回显 expected 是把"拒绝"与"情报"分开：调用方自己提供的 `provided` 可以回显，当前租约 token 不能。心跳被拒改为 409：Runner 心跳线程对 `fence_mismatch` 异常置 `fence_lost` 立即退出（runner_pkg/env.py:101-110），停止信号等价且更强；无效心跳同时不再落心跳事件，避免 reconciler 把过期执行者当活人。ack/events 一并加 fence 的理由：事件流是运行证据，旧 dispatch 的残留进程不得在新 run 的事件流留痕；Runner 协议本来就带 token（ack）或可携带（events），真实链路零改动。

**P1-02**：指纹（相对路径+sha256+大小，登记同口径过滤）随 Run 行的 `config_snapshot.import_fingerprint` **原子落库**——不引入新表/迁移，DB 即权威。幂等契约：同键同指纹→duplicate（不复制不重登记，已终态连 finalize 都不再进，直接回读已登记证据）；同键异指纹→409 `idempotency_conflict`（first-write-wins）；Run 未终态（上次 finalize 前崩溃）→ 同内容重试补完收敛（恢复路径）。复制改"暂存目录 + 同卷 `os.replace` 原子改名"，失败清暂存——目标目录要么不存在、要么完整，磁盘与 DB 永不出现"半批已登记"状态。旧版本无指纹的 Run 回退到与受管目录现算指纹比对。

**P1-03**：三层防护（config 校验器在导入期即失败 / main() 二次校验 / vite 与 dev_up.ps1 各自快速失败），错误信息明说"需先设计认证/Origin/CSRF，不能仅开放 Host"。

**P1-04**：守卫上移共享模块；假守卫换真依赖；40 个用户侧写端点全量盘点（脚本化核对），`/internal/*` 保持 X-Control-Token 且显式测试断言两类鉴权不混用；健康检查与纯查询保持开放并记录为例外。

**P2-01**：canonical path + 逐文件确认未逃逸源根 + 目录/文件 symlink 一律拒绝 + 隐藏/缓存文件过滤（与 scan_artifacts 同口径，`.env`/`.git` 不再进可下载证据）+ 文件数 5000 / 总字节 2GiB 上限；不设导入目录白名单，保留"从本地任意目录导入 vendor 产物"的工作流。

## 5. 新增的测试用例

| 文件 | 用例 | 数 |
|---|---|---|
| `tests/test_p1_fencing.py` | 缺/错/垃圾 token 心跳拒绝且零副作用；complete/fail 必须当前 token；fence 查询缺 token 不泄露；events/ack 过 fence；A/B 租约转手后旧 Runner 全部写操作被拒且续不动新租约；domain 层 extend_lease 精确匹配；终态幂等重试 | 11 |
| `tests/test_p1_loopback.py` | 允许名单×5 / 拒绝名单×8 参数化；Settings 层接受与拒绝；vite 配置与 dev_up.ps1 守卫的静态防漂移断言 | 16 |
| `tests/test_p1_client_header.py` | 40 个写端点 ×（缺头 428 / 错头 428 / 正头放行）参数化 + internal 面不混用 + 只读例外 | 122 |
| `tests/test_import_and_finalize.py`（追加） | 场景 A 同内容重复导入（monkeypatch 拦截 copy2 证明零复制 + sha256 逐文件比对）；场景 B 异内容 409 且磁盘字节级不变；场景 C 复制中途失败→零证据行/无暂存残留/同内容重试恢复；symlink 拒绝 + 隐藏文件过滤 | 4 |

既有测试适配：`test_issue02/04/08/16/run_submission/perf_dispatch` 补租约与 token；`test_issue08` 取消后心跳断言更新为 409 契约；`test_perf_gate_api` 等 4 个文件 fixture 注入默认 client header；`test_issue02` 缺 token 断言更新为 fail-closed。

## 6. 测试执行结果（全部 measured）

```
python -m ruff check .                      → All checks passed!
python -m alembic upgrade head（全新库）      → 0001 → 0011 完成
python -m pytest -o addopts="" -q           → 819 passed, 2 skipped（14m29s，
                                              全新迁移库 p1fix_final，非跳过 DB）
  2 个 skip 均为"本机无 symlink 权限"的环境跳过，非 DB 跳过
python scripts/vendor_sync.py check         → 失败（预存在问题，见 §8，非本次引入）
python scripts/test_vendor_sync_check.py    → [check] OK: 2 文件逐字节一致
cd web: npm run typecheck / npm test / npm run build
                                            → tsc 通过；90 pass / 0 fail；✓ built in 1.19s
进程级实测：TESTDOCK_HOST=0.0.0.0 python -m app.main → ValidationError 拒绝启动
            TESTDOCK_WEB_HOST=0.0.0.0 npm run build → 回环约束错误拒绝
```

Phase 验收对照（任务书 P1-01 验收目标）：旧 Runner 永远不能通过缺少 token 的方式绕过 fencing——专项测试覆盖缺 token、错 token、过期 token、A/B 并发接管、续租保护、事件零污染、token 不泄露，全部通过（measured）。

## 7. 数据库迁移情况

未新增迁移（指纹复用 `config_snapshot` JSONB，无 schema 变更）。全新 scratch 库 `p1fix_final` 上 `alembic upgrade head` 从 0001 顺利推进到 0011，全量测试在该库上通过；未连接开发库 `testdock`。

## 8. 未解决的问题

1. **VENDOR.lock.json 失配（基点 221c77d 的预存在问题，上游已解决，本分支无需处理）**：实测锁文件记录 CRLF 时代哈希（GLOSSARY.md size=5182, sha256=515103fb…＝CRLF 变体实测值），而 221c77d 的 vendor blob 是 LF（5089），故本 worktree 的 `vendor_sync.py check` 失败 144 处（vendor/ 与锁文件在本轮**零改动**，git status 证实）。追查 CI 记录发现该问题**已在上游修复**：`c8a7438 fix(vendor): 快照按原始字节入库（配合 * -text）` 重做了 vendor 快照与锁，CI 在 `cdb88b7`/`9f0aeff` 两次全绿（run 43557510582 / 43558495766）。本分支基点早于该修复；**合并/rebase 到现 master 后 vendor check 自然通过**，不要在本分支重生锁（会与上游冲突）。
2. **P2-02 Runtime→Router 反向依赖**：`runtime._apply_original_gate` 函数内惰性导入 `routers.analyses.evaluate_run_original`。实测其传递依赖闭包约 400 行（`evaluate_run_original` 本体 ~150 行 + `_load_run/_load_components/_load_metrics/_profile_of/_is_complete/_latest_policy_id/_default_baseline_run_id/_not_tested_evaluation/_evaluation_response/_json` ~226 行），且函数直接抛 HTTPException（HTTP 语义内嵌）。属于任务书"较大架构调整→先提交独立方案"的情形，本轮不动代码。**方案**：新建 `services/analysis.py`，把上述闭包整体搬入并把 HTTPException 翻译成 domain 错误（errors.py 信封不变）；`analyses.py` 只留 HTTP 解析与响应映射，`runtime.py` 改依赖 services。建议独立一轮执行并回跑 test_issue12/13/14/perf_gate 套件。
3. **P2-03 大组件拆分**：~~本轮不做~~ → **已获批准并在后续轮次执行完毕**（见 §10 补记）。
4. **symlink 校验分支本机未实测**：环境拒绝创建符号链接，该分支被 skip；过滤与边界逻辑已被同文件的隐藏文件用例验证，symlink 分支靠代码审查（inferred）+ CI（若 runner 有权限）覆盖。

## 9. 剩余风险

- **Runner 协议变化**：失效身份的心跳/ack/events 现在返回 409。在仓 Runner（runner_pkg）已兼容（fence_lost → 退出）；若有**仓库外**旧版 Runner 只认 200+cancel 语义，会在租约失效后收到 409——其行为取决于它如何处理非 200（vendor 不直接访问 /internal，风险低，inferred）。
- **uvicorn CLI 旁路**：`uvicorn app.main:app --host 0.0.0.0` 不经过 `settings.host`，应用层拦截不到；项目部署形态是 `python -m app.main` / dev_up.ps1，两者均已防护。残余风险记录在案。
- **指纹回退路径**：旧版本导入的 Run 无存储指纹，回退为与受管目录现算比对；若历史受管目录被人工改动过，同内容重试会被误判冲突（安全侧偏置，可接受）。
- **`docs/contracts/openapi.json` 已再生**：写端点新增 `X-TestDock-Client` header 参数；契约测试 7/7 通过。前端如硬编码旧 OpenAPI 快照需同步（web 测试 90/90 未受影响）。

## 10. 是否建议进入下一阶段

**建议进入**。后续合并顺序建议：本分支 rebase/merge 到现 origin/master（含 `c8a7438` vendor 快照修复与全绿 CI）→ 复跑 `vendor_sync.py check` 与全量 pytest → 提交。P1 四项已全部修复并有回归测试钉死（全量 819 通过）；P2-02/P2-03 待批准后按 §8 方案独立执行。

---

## 补记（下一阶段执行记录，2026-11-14）

**集成与 P2-02**：分支已 rebase 到 origin/master（`9f0aeff`）并提交；集成后全量 819 passed ×2；`vendor_sync check` 355 文件逐字节一致（基点 221c77d 的锁失配随上游 `c8a7438` 消除）。P2-02 已落地（`services/analysis.py`，Runtime 不再反向 import routers，错误信封逐字段兼容，定向 50 用例 + 全量 819 通过）。

**P2-03 已执行**（用户批准，五步提交，每步定向验证）：

| 文件 | 之前 | 之后 | 拆分方式 |
|---|---:|---|---|
| `server/app/routers/runs.py` | 1650+ | 1549 | 导入通道 IO 机制（指纹/边界/原子复制/证据回读）→ `services/run_import.py`（177 行）；请求编排留在路由层 |
| `server/app/routers/debug.py` | 1492 | ~1190 | 会话业务（viewer 端口登记、runner 进程管理、关闭编排、框选凭证库、审计）→ `services/debug_session.py`（430 行）；端点/代理/WS/视图留在路由层；进程内 dict 由服务持有、路由层共享同一对象 |
| `server/app/routers/analyses.py` | 1065 | 520 | P2-02 已分离判定核心；本轮复检不再机械拆 |
| `web/src/components/TaskWizard.tsx` | 1050 | 398 | `wizard/wizardModel.ts`（237 行，纯校验/模型）+ `wizard/wizardSteps.tsx`（582 行，三步视图，状态全部由向导持有经 props 传入）；TaskWizard 再导出全部公开名，既有消费方导入零改动 |
| `web/src/components/DebugDrawer.tsx` | 2265 | 1865 | `debug/debugModel.ts`（363 行，纯模型/坐标/手势/框选算法）+ `debug/TreeBranch.tsx`（103 行）；**组件状态、WS 生命周期与面板 JSX 逐字保留**——顺序回归测试钉死的行为契约不动 |

验证（每步 measured）：
- 后端定向：import 套件 11+1、debug 套件 9 文件 66 用例、gate 套件 50 用例全过；ruff 全绿；
- web：typecheck 干净、90/90 用例、build 成功；4 处源码文本断言随迁移指向新文件（其行为保护语义不变）；
- 全量后端（P2-03 后、全新迁移库 p2_03_final）：819 passed / 2 skipped。

WS 生命周期、设备控制协议、状态同步在本轮拆分中零改动：DebugDrawer 组件体逐字保留（所有语句顺序断言照常通过）；debug.py 的 WS 透传与控制端点未动；服务层 `_forward` 与路由层同形。

**待办移交**：真机验收（含 07 现场 DPI/高对比度复验）按用户安排另行执行；分支推送已获准并完成（`fix/p1-security-hardening`）。
