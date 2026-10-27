# 数据模型落地说明（data-model.md）

> 配套：`docs/plan/development-plan.md` §6、`docs/platform-prototype/schema.sql`（730 行，PG17）、`docs/platform-prototype/database-design.md`（237 行）。
> 原则：**原型 schema 是权威**。平台不自由发挥字段，只补「原型没有但运行必需」的三处（见 §5）。

## 1. 迁移策略

| 步骤 | 动作 | 产物 |
| --- | --- | --- |
| 1 | `alembic init server/alembic`（async 模板，`sqlalchemy.url` 从 `app/config.py` 读） | `alembic/env.py` |
| 2 | 手写 `versions/0001_initial.py`：逐表搬 `schema.sql` 的 `CREATE TABLE`（含 `CHECK`/`UNIQUE`/`FK`/`DEFAULT`），索引单独 `op.create_index` | 24 表 + 全部索引 |
| 3 | 结构一致性验证：`pg_dump --schema-only`（去注释/排序标准化）与 `schema.sql` 做 diff 脚本 `scripts/schema_diff.py` | diffs 报告 |
| 4 | 差异处理：**只允许「平台新增」类差异**（见 §5），并写入 `diffs.md` 说明理由；不允许缺列/改类型 | `docs/plan/schema-diffs.md` |
| 5 | 之后每迭代一个新 revision，`0001` 永久冻结 | — |

为什么手写而不是 `alembic revision --autogenerate`：autogenerate 只能从 ORM 模型反推，而 `schema.sql` 里有 ORM 不擅表达的跨列 CHECK（`(state='completed') = (outcome IS NOT NULL)`）、部分唯一索引（`WHERE released_at IS NULL`）、`DO $$` 之类，autogenerate 会静默丢掉 → 语义就没了。手写 730 行的搬迁工作约 2 人日，一次性成本。

## 2. 24 张表（按原型 7 组）

| 组 | 表 | 首期 | 说明 |
| --- | --- | --- | --- |
| 基础资产 | `projects` | ✅ 用 | 单项目 `xinghe` |
| | `applications` | ✅ 用 | 3 端：`xinghe-android` / `-ios` / `-web` |
| | `environments` | ✅ 用 | `staging` |
| | `resource_profiles` | ✅ 用 | 设备档案（系统/分辨率/机型），**性能基线可比性的唯一依据** |
| 执行资源 | `execution_resources` | ✅ 用 | 设备实体 + `status` + `fence_counter` |
| | `resource_leases` | ✅ 用 | 平台权威租约（run 或 debug 二选一） |
| | `debug_sessions` | ✅ 用 | 调试会话 |
| 测试定义 | `test_tasks` | ✅ 用 | 任务 + `lifecycle` + `lock_version` |
| | `task_revisions` | ✅ 用 | 不可变修订 + `readiness` |
| | `suites` | ✅ 用 | 套件（一个 pytest 目录/文件集合） |
| | `suite_versions` | ✅ 用 | `discover` 生成的不可变快照 |
| | `cases` | ✅ 用 | 用例条目（nodeid + 名称） |
| 任务运行 | `test_runs` | ✅ 用 | 运行主表（7 状态 + outcome） |
| | `run_components` | ✅ 用 | 一次 run 内 ui/perf/debug 组件各一行 |
| | `case_results` | ✅ 用 | 用例级结果（passed/failed/skipped/errored） |
| 结果证据 | `artifacts` | ✅ 用 | 产物登记（sha256，`availability`） |
| | `evidence` | ✅ 用 | 失败证据索引（指向 artifacts + 失败类型/消息） |
| 性能质量 | `metric_summaries` | ✅ 用 | 指标汇总（`value` 可 NULL + `missing_reason`） |
| | `baselines` | ✅ 用 | 基线（绑 run + 档案） |
| | `gate_policies` | ✅ 用 | 门禁阈值策略 |
| | `gate_evaluations` | ✅ 用 | 判定（original 唯一 / reanalysis 多条） |
| 治理追溯 | `audit_events` | ✅ 写 | 关键动作审计 |
| | `run_events` | ✅ 写 | 运行事件流（阶段、诊断） |
| | `builds` | ⬜ 空 | 应用构建版本（首期用 `applications.version_label` 直接填） |

> 表名以 `schema.sql` 实际为准（`database-design.md` 的中文表名是描述）。P1 第一步：把 `schema.sql` 的 24 个 `CREATE TABLE` 名字与列名导出成清单，与本表核对后校准。

## 3. 强制约束清单（迁移里必须逐条落地）

### 3.1 跨列 CHECK

```sql
-- test_runs: 结论与状态互锁
CHECK ((state = 'completed' AND outcome IS NOT NULL)
    OR (state <> 'completed' AND outcome IS NULL))            -- schema.sql:341
-- test_runs: 终态才允许结束时间
CHECK ((state IN ('completed','errored','cancelled')) = (ended_at IS NOT NULL))  -- :342
-- test_runs: 执行态必须有设备
CHECK (state NOT IN ('running','finalizing','completed')
    OR (resource_id IS NOT NULL AND started_at IS NOT NULL))  -- :343
-- task_revisions: 字段完整 != 可运行
CHECK (readiness = 'draft' OR (build_id IS NOT NULL AND suite_version_id IS NOT NULL))  -- :294
-- resource_leases: run 与 debug 互斥
CHECK ((run_id IS NOT NULL) <> (debug_session_id IS NOT NULL))  -- :415
-- metric_summaries: 缺失必须带原因
CHECK ((value IS NULL AND missing_reason IS NOT NULL)
    OR (value IS NOT NULL AND missing_reason IS NULL))        -- :548
-- gate_evaluations: 未测必须可解释
CHECK (verdict <> 'not_tested' OR reason_code IS NOT NULL)    -- :643
```

### 3.2 部分唯一索引（互斥的最终保险）

```sql
CREATE UNIQUE INDEX leases_one_live_resource ON resource_leases(resource_id)
  WHERE released_at IS NULL;                       -- :721
CREATE UNIQUE INDEX leases_one_live_run      ON resource_leases(run_id)
  WHERE released_at IS NULL AND run_id IS NOT NULL;  -- :722
CREATE UNIQUE INDEX leases_one_live_debug    ON resource_leases(debug_session_id)
  WHERE released_at IS NULL AND debug_session_id IS NOT NULL;  -- :728
CREATE UNIQUE INDEX gate_one_original ON gate_evaluations(run_component_id)
  WHERE mode = 'original';                         -- :724
```

### 3.3 幂等唯一键

| 表 | 唯一键 | 用途 |
| --- | --- | --- |
| `test_runs` | `(project_id, request_key)` `:334` | 重复点「运行」只产生一条 |
| `gate_evaluations` | `(project_id, request_key)` `:638` | 重复试算只产生一条 |
| `run_events` | `(project_id, run_id, source_key, source_event_id)` `:672` | runner 重发事件不重复 |

## 4. 关键表的平台侧使用约定

### 4.1 `test_runs` 状态迁移只能走 domain 层

```python
# server/app/domain/runs.py
async def transition(run_id, *, expect: RunState, to: RunState,
                     outcome: Outcome | None = None,
                     reason: str | None = None, actor: str) -> TestRun:
    # UPDATE test_runs SET state=:to, outcome=:outcome, ended_at=... 
    #   WHERE id=:run_id AND state=:expect RETURNING *
    # 0 行 -> 409 state_conflict（带当前真实 state）
    # 非法迁移表见 development-plan.md §7.2，422 illegal_transition
```

### 4.2 `metric_summaries` 写入映射（vendor → 平台）

| vendor 形态 | 平台写入 |
| --- | --- |
| `metricsSummary[key].median` 有值 | `value = median`, `missing_reason = NULL`, `statistic='median'`, `sample_count>0`, `unit` 来自指标字典 |
| `notTested[key] = true` + `notTestedReason` 中文 | `value = NULL`, `missing_reason = 映射码`（见 §4.4），原文存 `missing_reason_text`（§5 新增列） |
| 键不存在（设备不支持，如 gpu） | `value = NULL`, `missing_reason='device_unsupported'` |
| 样本数 < 策略下限 | 仍写 `value`（数据是真实的），`sample_count` 如实写；判定阶段产生 `not_tested` |

**禁止**：把缺失写成 `0`、把 `notTested` 丢掉、把 `sample_count=6` 写成 `180`（原型演示数据里的 180/6 是假数据，平台必须用真实值）。

### 4.3 `artifacts` 登记规则

| 字段 | 规则 |
| --- | --- |
| `logical_key` | 相对 run 目录的路径，如 `perf/report.json`、`evidence/ab12cd34ef567890/failure-frame.png` |
| `kind` | `perf_report_native` / `perf_report_html` / `perf_csv` / `ui_junit` / `ui_evidence_frame` / `ui_ui_tree` / `ui_manifest` / `snapshot_png` / `runner_log` |
| `sha256` / `size_bytes` | finalize 阶段计算并读回复验；不一致 → run `errored` |
| `availability` | 文件在生产上存在为 `available`；被运维清理为 `missing`；超保留期为 `expired`（不删行） |
| `storage_uri` | 绝对路径（`F13` 问题）→ 平台改写为 `s3://`-like 的根相对形式 `runs/<run_id>/<logical_key>` |

### 4.4 `reason_code` 枚举（平台自建，补齐 vendor 的自由文本）

| 码 | 触发 |
| --- | --- |
| `profile_mismatch` | 基线档案 ≠ 运行档案（原型 `perfVerdict` 第 1 步） |
| `sample_count_below_minimum` | 有效样本 < `min_samples`（第 2 步） |
| `metric_missing` | 任一被门禁覆盖的指标缺失 |
| `device_degraded` | 采集期间出现崩溃/ANR/降级标记（`logwatch`/`jank`） |
| `gate_policy_missing` | 该应用无生效策略 |
| `run_incomplete` | run 未到 completed（errored/cancelled）却有判定请求 |

映射函数 `to_reason_code(vendor_not_tested_reason: str) -> str`：按关键词匹配（`档案`→profile_mismatch、`样本`→sample_count_below_minimum、`不支持`→metric_missing…），**未匹配一律 `metric_missing` 并记录原文**，不允许返回空。

## 5. 原型 schema 需要补的四处（唯一允许的「平台新增」）

| # | 新增 | 理由 | 影响 |
| --- | --- | --- | --- |
| G1 | `metric_summaries.missing_reason_text TEXT NULL` | vendor 只给中文原因，枚举不够解释给人看 | 加列，CHECK 不变 |
| G2 | `execution_resources.fence_counter BIGINT NOT NULL DEFAULT 0` | 租约 fencing token 来源（原型没有） | 加列 + 默认 0 |
| G3 | `test_runs.parent_run_id UUID NULL REFERENCES test_runs(id)` | 「重新运行」追溯链（原型抽屉里有「重新运行自 RUN-x」文案但 DB 无字段） | 加列 + 引用 |
| G4 | `execution_resources.last_seen_at TIMESTAMPTZ NULL` | `api-design.md:82` 已承诺该字段；没有它无法区分「从未同步过」与「3 天前还在」（`device-registration.md` §5.1） | 加列，NULL 允许 |

> G4 由 `device-registration.md` §5.1 提出，2026-10-27 评审签字批准（dev）。

> 若评审认为不得改原型 schema，替代方案：G1 存进 `metric_summaries.extra JSONB`（若存在）、G2 用 `resource_leases.id` 自增序列代替（弱化 fencing，可接受但退一步）、G3 用 `run_events` 记录。此替代方案成本 +0.5 人日且语义变弱，**不推荐**。

## 6. 种子数据（`scripts/seed_demo.py`）

对齐原型视觉，避免「页面空空一片」：

| 实体 | 数量 | 对齐原型 |
| --- | --- | --- |
| 项目 | 1 | 星河 / `xinghe` |
| 应用 | 3 | android `com.example.xinghe`、ios `com.example.xinghe.ios`、web `https://staging.example.test` |
| 设备 | 6 | 4 ready + 1 unauthorized + 1 offline（与原型一致） |
| 套件 | 4 | 核心链路回归 12 / 登录与账号 6 / 下单链路 8 / 个人中心 5（合计 31） |
| 场景 | 3 | 首页滑动 / 商品详情 / 搜索 |
| 历史 run | 8~12 | 含 1 个 passed + 1 个 failed + 1 个 not_tested + 1 个 errored，覆盖报告页所有分支 |
| 基线 | 1 | 从某个 passed 性能 run 建 |
| 门禁策略 | 1 | memory<240 fail / cpu<35 warn / fps≥50 fail / min_samples 10 |

种子脚本必须 `--reset`（清表）与 `--dry-run`；执行后打印各表行数。

## 7. 平台测试要覆盖的 DB 断言

1. 直接 INSERT `state='completed'` 但 `outcome IS NULL` → 必须被 CHECK 拒绝。
2. 同一 `resource_id` 插两条 `released_at IS NULL` 租约 → 必须被部分唯一索引拒绝。
3. 同一 `run_component_id` 插两条 `mode='original'` → 拒绝；两条 `reanalysis` → 允许。
4. `metric_summaries` 插 `value=NULL` 且 `missing_reason=NULL` → 拒绝。
5. `gate_evaluations` 插 `verdict='not_tested'` 且 `reason_code=NULL` → 拒绝。
6. 并发 10 个事务抢 1 台设备 → 恰好 1 个成功，其余 409/空结果。
7. 迁移往返：`alembic upgrade head` → `downgrade base` → `upgrade head` 三次幂等。

## 8. 原型 schema 独立评审结论（`docs/plan/research/schema-review.md`，428 行，已实跑 verify-design.cjs）

评审规模：24 表 / 231 列 / 56 外键 / 73 CHECK / 57 UNIQUE / 15 显式索引 / 255 条 COMMENT；CREATE TABLE 顺序 0 前向引用，56 外键全部指向更早父表，索引统一在 L714-728，自引用仅 `test_runs` L337。`verify-design.cjs` 实跑 PASS。

**关键认知**：`verify-design.cjs` 只做 `schema.sql` 与 `index.html:124` 字典的文本 deepEqual + 外键算术 + BEGIN/COMMIT 断言，**不执行 PG、不验 CHECK 语义/索引/约束命名**。所以「校验通过」不等于「可建库」。

### 8.1 四个必须改（阻塞迁移，P1 开工即做）

| # | 问题 | 处理 |
| --- | --- | --- |
| P0-1 | `schema.sql` L7/L730 的 `BEGIN;`/`COMMIT;` 会提前提交事务，破坏 Alembic 迁移原子性 | 生成迁移时删除这两个语句；`alembic_version` 天然防重复执行 |
| P0-2 | 163 条约束全部未命名（匿名），后续 ALTER / autogenerate 不可靠 | 迁移中对每条约束显式命名：`ck_<table>_<col>_<slug>`、`fk_<table>_<col>_<ref>`、`uq_<table>_<cols>` |
| P0-3 | `run_components` 缺 `reason_code`；`test_runs` 缺「not_tested 必须有原因」CHECK，与 `database-design.md:98/216` 冲突 | 迁移补 `run_components.reason_code TEXT NULL` 与 `test_runs.not_tested_reason TEXT NULL` + `CHECK (outcome <> 'not_tested' OR not_tested_reason IS NOT NULL)`，与 §5 的 G1-G3 一起作为「平台新增」登记 |
| P0-4 | `schema.sql` / `index.html:124` 字典 / `database-design.md:48-81` 三处手工同步，易漂移 | **单一真源 = `schema.sql`**；`GET /schema` 的 JSON 由构建脚本从 `schema.sql` 解析生成；前端不再手写字典；`verify-design.cjs` 改为校验生成物与 schema.sql 一致 |

### 8.2 迁移中必须手工 op.execute 的部分

| 对象 | 数量 | 实现方式 |
| --- | --- | --- |
| COMMENT（表/列） | 255 | 逐条 `op.execute("COMMENT ON TABLE/COLUMN ... IS ...")` |
| 部分唯一索引 | 7（含 3 条租约 + `gate_one_original` 等） | `op.create_index(..., unique=True, postgresql_where=sa.text(...))`；`UniqueConstraint` 不支持 WHERE |
| `jsonb_typeof` CHECK | 14 | `op.execute` 直写 |
| 正则 CHECK | 3 | `op.execute` 直写（注意 PG 正则与 Python 字符串转义叠加） |
| float8 边界 CHECK | 2 | `op.execute` 直写，建库后实测取值边界 |

### 8.3 优先补的 4 个索引（评审列出 11 处缺口 G1-G11）

| 索引 | 用途 |
| --- | --- |
| `debug_sessions (resource_id) WHERE state IN ('opening','active')` | `database-design.md:136` 的锁顺序依赖「按资源找活动会话」 |
| `metric_summaries (run_id, metric_key)` 与 `(application_id, metric_key, captured_at)` | 跨运行趋势 |
| `test_runs (parent_run_id) WHERE parent_run_id IS NOT NULL` | 重跑链路 |
| `task_revisions (task_id)`、`baselines (application_id, resource_profile_id)` | 复合外键列未索引，删除/更新会全表扫 |

### 8.4 两处语义漏洞（服务层兜）

1. `schema.sql` L413 允许 `resource_leases.released_at` 写未来时间，可绕过部分唯一索引（凭空造一个「未释放」空档）。CHECK 不能引用 `now()`，改为服务层校验 + 单测 + `audit_events` 记录释放来源。
2. 归档唯一键不能复用：`lifecycle=archived` 后同名任务仍可新建，需要业务唯一键 `(project_id, name) WHERE lifecycle <> 'archived'`（原 schema 无）。首期服务层校验，二期补部分唯一索引。

### 8.5 评审建议但不采纳的部分

| 建议 | 不采纳理由 |
| --- | --- |
| 初始迁移按 6 域拆多个 revision | PG DDL 事务性已保证原子回滚；单文件更易与 `schema.sql` 逐字对照，拆分收益低、出错面大（评审 §6.4 亦以单文件为首选） |
| 立即重构 24 表（S1-S12 全做） | 首期目标跑通闭环；S 系列多为容量/体验优化，放二期，避免首期反复改 schema |

### 8.6 评审的未确认项（转入 R 系列风险）

| 未确认 | 影响 | 何时消除 |
| --- | --- | --- |
| 本机无 PG，DDL 未真实建库 | CHECK 求值、索引收益未实测 | P1 第一天：EDB 便携实例建库 + `alembic upgrade head` |
| 255 条 COMMENT 与 7 条部分索引的 Alembic 写法 | 迁移可能报错 | 同上，一次跑通即固化 |
