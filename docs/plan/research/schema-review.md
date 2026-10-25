# schema.sql 静态审查报告

> 审查对象：`docs/platform-prototype/schema.sql`（TestDock 多端平台数据库草案 v1）。
> 审查方式：只读静态分析 + 文档比对；本机没有 PostgreSQL 客户端，未建库、未执行 SQL。
> 审查人：inv-perf（Team Lead 调研员）；task-5；2026-10-25。

## 0. 审查对象、方法与结论摘要

### 0.1 对象与度量

| 文件 | 行数 | 字节 | 说明 |
| --- | --- | --- | --- |
| `docs/platform-prototype/schema.sql` | 730 | 43,211 | PostgreSQL 17 DDL 草案；`BEGIN;` 在 L7、`COMMIT;` 在 L730；自述 REVIEW ONLY（L3）、无扩展（L2） |
| `docs/platform-prototype/database-design.md` | 237 | 23,259 | 设计说明：§3 表清单 L48-81、§4 任务/版本/执行语义 L83-104、§5 跨端配置与性能口径 L106-120、§6 并发与租约 L122-143、§7 归档与索引 L145-165、§8 权限 L167-178、§10 验收 L207-223 |
| `docs/platform-prototype/verify-design.cjs` | 59 | 3,502 | 设计一致性脚本；头部自述不是 PG 解析器（L1），尾部自述未执行 PG（L58） |
| `docs/platform-prototype/index.html` | 332 | 168,894 | 字段字典 `databaseTables` 在 L124，是 verify 脚本的唯一对照源 |

### 0.2 方法

- 只读：未修改 `docs/platform-prototype/` 下任何文件，未写入 `D:/workspace/claudecode-test/moblie-xn` 或其它既有项目。
- 用 Node（v24.14.0）一次性解析 `schema.sql` 统计 DDL 元素：24 张 `CREATE TABLE`、231 列、56 个外键、73 条 `CHECK`、56 条表级 `UNIQUE` + 1 条列级 `UNIQUE`、0 个命名约束、15 条显式索引、255 条 `COMMENT`。
- 实际执行 `node docs/platform-prototype/verify-design.cjs` 复核脚本口径（输出见附录 A）。
- 逐条比对 `database-design.md` 的约束口径（L124-131）、索引要求（L149-161）与验收项（L209-222）。

### 0.3 结论摘要

1. **建表顺序自洽**：56 个外键全部指向更早创建的父表，0 个前向引用；15 条显式索引集中在 L713-728、位于全部表之后。按 PostgreSQL 语义可以一次建库（未在真实 PG 执行，标注未确认）。
2. **复合外键目标唯一键 56/56 齐全**：`UNIQUE(project_id, id)` 只在需要作外键目标的父表声明，`verify-design.cjs` 的 L46-51 检查与本文程序化复核都通过。
3. **租约部分唯一索引与设计一致**：L721、L722、L728 三条 `WHERE released_at IS NULL` 恰好对应 `resource_id`、`run_id`、`debug_session_id`，配合 L415 的二选一 `CHECK`，语义完整（对照 `database-design.md:129`）。
4. **非法状态能被拦截**：`queued` 存 `passed`、`completed` 缺 `outcome` 都由同一条 `CHECK`（`schema.sql:341`）拦截，`database-design.md:216` 的三项验收在 DDL 层可满足。
5. **三态口径有两处 DDL 可补未补**：`test_runs` 有 `reason_code`（L322）却没有“`not_tested` ⇒ 原因非空”的 CHECK；`run_components`（L431-449）根本没有 `reason_code` 列（详见 7.1-P0-3）。
6. **约束全部未命名**：122 条表级约束 + 41 条列级约束中 `CONSTRAINT` 关键字出现 0 次；初始迁移能建，但后续任何 `DROP/ALTER` 与 Alembic autogenerate 不可靠（详见 7.1-P0-2）。
7. **COMMENT 覆盖完整**：24/24 表、231/231 列，合计 255 条；0 缺失、0 孤儿、0 重复；但 15 条显式索引没有注释。
8. **索引能满足 `database-design.md` §7 的 6 类主查询，但有 11 处缺口**，集中在调试会话资源冲突、指标跨运行趋势、重跑链、档案/修订/基线外键列、游标分页一致性（详见 §3.3）。
9. **复合外键索引只有项目前缀**：33 个复合外键中 0 个拥有“以完整引用列集为前导”的普通索引，父行删除/更新时 RI 检查退化为项目内扫描；因全部外键为默认 NO ACTION 且以归档代替删除（`database-design.md:131`），风险低。
10. **迁移落地阻塞项只有工程口径**：`BEGIN;/COMMIT;` 包装、约束命名、单一真源三条必须在冻结 schema 基线前处理；DDL 本身未发现语法级阻塞（详见 §6、§7.1）。

---

## 1. 24 表清单与依赖顺序

### 1.1 建表顺序与直接父表

| # | 表 | 定义行号 | 直接父表（外键所在行） |
| --- | --- | --- | --- |
| 1 | `projects` | L10-16 | 根表，被其余表引用（PK 在 L11） |
| 2 | `project_members` | L25-33 | `projects` L27 |
| 3 | `applications` | L43-54 | `projects` L45 |
| 4 | `app_builds` | L65-81 | `projects` L67；`applications` L79 |
| 5 | `environments` | L95-106 | `projects` L97 |
| 6 | `execution_nodes` | L117-129 | `projects` L119 |
| 7 | `resource_profiles` | L141-153 | `projects` L143 |
| 8 | `execution_resources` | L164-181 | `projects` L166；`execution_nodes` L178；`resource_profiles` L179 |
| 9 | `test_suites` | L195-207 | `projects` L197；`applications` L206 |
| 10 | `suite_versions` | L218-233 | `projects` L220；`test_suites` L231 |
| 11 | `test_tasks` | L246-259 | `projects` L248；`applications` L258 |
| 12 | `task_revisions` | L272-295 | `projects` L274；`test_tasks` L289；`environments` L290；`app_builds` L291；`suite_versions` L292 |
| 13 | `test_runs` | L312-348 | `projects` L314；`applications` L335；`task_revisions` L336；`test_runs` 自引用 L337；`execution_resources` L338；`resource_profiles` L339 |
| 14 | `debug_sessions` | L370-385 | `projects` L372；`execution_resources` L381 |
| 15 | `resource_leases` | L397-416 | `projects` L399；`test_runs` L411；`debug_sessions` L414 |
| 16 | `run_components` | L431-449 | `projects` L433；`test_runs` L446 |
| 17 | `case_results` | L464-479 | `projects` L466；`run_components` L477 |
| 18 | `artifacts` | L493-513 | `projects` L495；`test_runs` L511；`run_components` L512 |
| 19 | `metric_summaries` | L531-550 | `projects` L533；`run_components` L547 |
| 20 | `baselines` | L567-587 | `projects` L569；`applications` L581；`environments` L582；`suite_versions` L583；`resource_profiles` L584；`run_components` L585 |
| 21 | `gate_policies` | L602-614 | `projects` L604；`applications` L612 |
| 22 | `gate_evaluations` | L625-644 | `projects` L627；`run_components` L639；`gate_policies` L640；`baselines` L641 |
| 23 | `run_events` | L659-675 | `projects` L661；`test_runs` L673 |
| 24 | `audit_events` | L689-701 | `projects` L691 |

### 1.2 顺序满足性判定

- **0 个前向引用**：程序化比对 56 条 `REFERENCES` 的目标表起始行号，全部早于引用它的表。主链为 `projects` → `applications`/`environments`/`execution_nodes`/`resource_profiles` → `execution_resources` → `test_runs` → `run_components`/`debug_sessions`/`resource_leases` → 结果与门禁表。
- **唯一的自引用合法**：`test_runs.parent_run_id` 的外键 L337 指向 `test_runs(project_id, application_id, id)`（目标唯一键 L332），同表内引用在 PostgreSQL 中允许。
- **没有“后置补 FK”的余地**：所有外键都内联在 `CREATE TABLE` 内（列级 23 条、表级 33 条），全文没有 `ALTER TABLE ... ADD CONSTRAINT`，因此拆分迁移时无法靠“先建表、后加外键”解耦顺序。
- **索引顺序无风险**：15 条 `CREATE INDEX` 位于 L714-L728，注释 L713 明确它们是显式查询/并发索引；`CREATE INDEX` 不参与外键依赖，全部在表之后是对的。
- **风格问题（不阻塞）**：同一语义的 `leases_one_live_debug`（L728）被放在文件末尾，与 L721、L722 两条租约索引分开，建议归位便于阅读。

### 1.3 按域拆分迁移时必须遵守的切点

- `execution_resources` L164 必须早于 `test_runs` L312（`test_runs` L338 引用它）。
- `test_runs` L312 必须早于 `debug_sessions` L370（L381）、`resource_leases` L397（L411）、`run_components` L431（L446）、`artifacts` L493（L511）、`run_events` L659（L673）。
- `run_components` L431 必须早于 `case_results` L464（L477）、`artifacts` L493（L512）、`metric_summaries` L531（L547）、`baselines` L567（L585）、`gate_evaluations` L625（L639）。
- `gate_policies` L602 与 `baselines` L567 必须早于 `gate_evaluations` L625（L640、L641）。
- 最容易拆错的两处：`gate_evaluations`（同时依赖 `run_components`、`gate_policies`、`baselines`）与 `artifacts`（同时依赖 `test_runs` 与 `run_components` 的复合唯一键 L444）。若与父表放同一批就会产生前向引用，必须改写成后置 `ALTER TABLE ADD CONSTRAINT`——当前文件没有这种写法。

---

## 2. 约束审查

### 2.1 复合外键目标唯一键：56/56 已声明

- 方法：解析全部 56 条 `REFERENCES`（列级 23 + 表级 33），检查目标列集是否在父表有 PK/`UNIQUE` 精确匹配 → **0 缺失**。
- 落点：`projects` 仅 PK（L11，只被单列外键引用）；`applications` L51、L52；`app_builds` L76、L77；`environments` L103；`execution_nodes` L126；`resource_profiles` L149、L150；`execution_resources` L175、L176；`test_suites` L203、L204；`suite_versions` L228、L229；`test_tasks` L256、L257；`task_revisions` L286、L287；`test_runs` L331、L332、L333；`debug_sessions` L379、L380；`run_components` L443、L444；`gate_policies` L610；`baselines` L579。
- 例外说明：`project_members` 没有 `UNIQUE(project_id, id)`（L32 只有业务唯一键），但它不被任何表引用，不构成缺口；`projects` 没有 `project_id` 列，子表用单列外键引用其 PK，正确。
- **观察（非缺陷）**：22 张表同时声明 PK(`id`) 与 `UNIQUE(project_id, id)`，部分还多一层 `UNIQUE(project_id, application_id, id)`。`test_runs` 有 5 个唯一索引（L331-334 + PK）——每个都是某个复合外键的硬性目标（PG 要求被引用列集存在唯一约束），不能当冗余删除；代价是写放大，属可接受权衡。

### 2.2 部分唯一索引（未释放租约）

- 三条部分唯一索引：L721 `leases_one_live_resource (project_id, resource_id) WHERE released_at IS NULL`；L722 `leases_one_live_run (project_id, run_id) WHERE released_at IS NULL`；L728 `leases_one_live_debug (project_id, debug_session_id) WHERE released_at IS NULL`。
- 与 `database-design.md:129`（未释放租约对 resource_id、run_id、debug_session_id 分别使用部分唯一索引）逐字对应；释放判据是 `released_at IS NULL`，不是时间比较，与 `database-design.md:139`（到期只表示需要检查、不能立即释放）一致。
- 互斥完整性：L415 `CHECK ((run_id IS NOT NULL) <> (debug_session_id IS NOT NULL))` 保证同一行只属于运行或调试，三条索引不会互相溢出。
- **语义缺口**：L413 只要求 `released_at >= created_at`，没有禁止未来时间。写入未来 `released_at` 会让该行退出三条部分唯一索引，从而可在“实际未释放”时再建一条未释放租约。DDL 无法用 `now()` 可靠约束（stable 函数在 CHECK 中语义不可靠），需服务层只写当前时间，或改成 `released` 布尔标志 + `released_at`（见 7.2-S2）。
- 租约令牌：L403 `fencing_token > 0`、L410 `UNIQUE(project_id, resource_id, fencing_token)`；`database-design.md:137` 要求 token 等于递增后的实例 `fence_counter`（L173），DDL 不校验两表相等，必须在分配事务中实现。
- 补充：`resource_leases.resource_id`（L400）没有直接外键到 `execution_resources`，但 L415 保证必有 `run_id` 或 `debug_session_id`，两者分别通过 L411、L414 的复合外键带 `resource_id` 校验，因此资源归属仍被完整约束。

### 2.3 CHECK 约束全量口径

计数：**73 条 = 40 条列级 + 33 条表级**，全部未命名。

#### 2.3.1 platform（4 处）

- `applications.platform` L46、`resource_profiles.platform` L144、`execution_resources.platform` L169、`test_runs.platform` L316，取值均为 `android/ios/web`，与 `database-design.md:110-114` 三端一致。
- `test_runs.platform` 不是自由文本：L335 复合外键 `(project_id, application_id, platform)` 保证运行平台与应用平台一致；L338 保证与实例平台一致。

#### 2.3.2 role（1 处）

- `project_members.role` L30：`owner/maintainer/runner/viewer`，与 `database-design.md:169-174` 权限表一致。

#### 2.3.3 state / status（5 处）

- `execution_nodes.status` L123：`online/offline/draining`。
- `execution_resources.status` L172：`ready/offline/unauthorized/draining`。
- `test_runs.state` L320：`queued/dispatching/running/finalizing/completed/errored/cancelled`（与 `database-design.md:89` 一致）。
- `run_components.state` L439：`pending/running/completed/errored/cancelled`（无 `dispatching/finalizing`，符合子组件粒度）。
- `debug_sessions.state` L375：`opening/active/closing/closed/lost`。

#### 2.3.4 outcome（3 处，注意口径不一致）

- `test_runs.outcome` L321：`passed/failed/not_tested`，可空，仅 `completed` 时非空（由 L341 联动）。
- `run_components.outcome` L440：`passed/failed/not_tested`，规则同 L448。
- `case_results.outcome` L470：`passed/failed/skipped/errored`，NOT NULL——用例层枚举，含 `skipped`、无 `not_tested`。
- 影响：三列同名不同域，DAO/枚举不能复用同一类型；`database-design.md:104` 的汇总规则需要在“用例 skipped”与“组件 not_tested”之间做映射，二者不是同义词。

#### 2.3.5 availability（1 处）

- `artifacts.availability` L505：`available/missing/expired`，默认 `available`，与 `database-design.md:92` 一致。
- DDL 无法表达 `expired` 与 `expires_at` 的时间关系（`now()` 不适合进 CHECK），保留策略需服务层/批处理（`database-design.md:165` 已写）。

#### 2.3.6 sha256 / 摘要（3 处）

- `app_builds.sha256` L73（可空）、`artifacts.sha256` L503（NOT NULL）、`resource_profiles.fingerprint` L146（NOT NULL），正则同为 `^[0-9a-f]{64}$`（小写 64 位十六进制）。
- 注意：可空列 + CHECK 对 NULL 求值为 UNKNOWN 即通过，因此 `app_builds` 可以不填摘要入库；若要求强制，应改 NOT NULL 或按平台条件非空。
- `schema.sql:159` 注释说明 `fingerprint` 是规范化档案的 SHA-256；与包摘要语义不同、格式相同，可接受。

#### 2.3.7 jsonb_typeof（14 处，覆盖全部 14 个 jsonb 列）

- 要求 `object`（12 处）：`app_builds.metadata` L80、`environments.config` L105、`execution_nodes.capabilities` L128、`resource_profiles.spec` L152、`suite_versions.manifest` L232、`task_revisions.config` L293、`test_runs.config_snapshot` L340、`run_components.summary` L447、`baselines.metrics_snapshot` L586、`gate_policies.rules` L613、`run_events.payload` L674、`audit_events.changes` L700。
- 要求 `array`（2 处）：`case_results.steps` L478、`gate_evaluations.checks` L642。
- 全部 14 个 jsonb 列均有顶层类型检查，**无遗漏**（14 = 12 object + 2 array）。
- 局限：只校验顶层类型，不校验 `schemaVersion`、必填字段、大小上限（`database-design.md:13` 要求应用层 schemaVersion 与大小上限）。

#### 2.3.8 其余 42 条（23 列级 + 19 表级）

- 列级数值/枚举（23 条）：`execution_resources.kind` L171、`run_components.kind` L435、`artifacts.kind` L499；`test_suites.test_type` L200、`task_revisions.test_type` L281；`test_tasks.lifecycle` L251；`task_revisions.readiness` L282；`metric_summaries.statistic` L540；`gate_evaluations.mode` L631、`gate_evaluations.verdict` L633；`version/revision > 0` L223、L277、L576、L607；`lock_version > 0` L252、L326；`fencing_token > 0` L403；`fence_counter >= 0` L173；`attempt > 0` L469；`duration_ms >= 0` L471；`byte_size >= 0` L502；`sample_count >= 0` L541；`sequence > 0` L663。
- 表级组合/时间（19 条）：`execution_resources` L180（web ⇔ browser_slot，非 web ⇔ device/simulator，与 `database-design.md:114` 一致）；`task_revisions` L294（`readiness=validated` 时 build 与 suite_version 必须非空）；`test_runs` L341（state/outcome）、L342（终态 ⇔ `ended_at`）、L343（running 及之后必须有实例与开始时间）、L344（`resource_id` 与 `profile_id` 同空同非空）、L345/L346/L347（时间单调）；`debug_sessions` L382（`expires_at > created_at`）、L383（closed/lost ⇔ `closed_at`）、L384；`resource_leases` L412、L413、L415（run/debug 二选一）；`run_components` L448（state/outcome 同 test_runs 口径）；`metric_summaries` L548（value 与 missing_reason 反向互斥）、L549（有值时 sample_count>0 且非 ±Inf/NaN）；`gate_evaluations` L643（not_tested ⇒ reason_code 非空）。
- 计数核对：2.3.1-2.3.7 共 31 条（4+1+5+3+1+3+14），加本节 42 条 = 73 条，与解析结果一致。

## 3. 索引审查

### 3.1 全量索引口径

- **显式 `CREATE INDEX` 15 条**（L714-L728），其中 **7 条部分索引**（L714、L721、L722、L723、L724、L727、L728）、**8 条全量索引**（L715、L716、L717、L718、L719、L720、L725、L726）。
- **约束隐含索引 81 条**：24 个主键 + 57 个唯一约束（56 条表级 `UNIQUE` + `projects.code` L12 的列级 `UNIQUE`）。
- 索引总数约 **96 条**；表 24 张，平均每表 4 条，属多租户外键设计的正常水位。

| # | 索引 | 行号 | 列 / WHERE | 服务场景 | 对应设计 |
| --- | --- | --- | --- | --- | --- |
| 1 | `runs_queue` | L714 | `(created_at, id) WHERE state = 'queued'` | 调度器 `FOR UPDATE SKIP LOCKED` 领取排队运行 | `database-design.md:154` |
| 2 | `runs_project_recent` | L715 | `(project_id, created_at DESC, id DESC)` | 项目最近运行列表（游标分页） | `database-design.md:153` |
| 3 | `runs_app_recent` | L716 | `(project_id, application_id, created_at DESC, id DESC)` | 应用最近运行 | `database-design.md:153` |
| 4 | `runs_platform_recent` | L717 | `(project_id, platform, created_at DESC, id DESC)` | 端维度最近运行 | `database-design.md:153` |
| 5 | `runs_revision` | L718 | `(project_id, revision_id)` | 修订 → 运行 | 服务协议（`database-design.md:135`） |
| 6 | `runs_resource` | L719 | `(project_id, resource_id)` | 实例 → 运行 | `database-design.md:155` |
| 7 | `resources_ready` | L720 | `(project_id, platform, status)` | 可分配实例筛选 | `database-design.md:155` |
| 8 | `leases_one_live_resource` | L721 | `UNIQUE (project_id, resource_id) WHERE released_at IS NULL` | 一实例一活租约 | `database-design.md:129`、L155 |
| 9 | `leases_one_live_run` | L722 | `UNIQUE (project_id, run_id) WHERE released_at IS NULL` | 一运行一活租约 | `database-design.md:129` |
| 10 | `leases_expiry` | L723 | `(expires_at) WHERE released_at IS NULL` | 过期租约扫描 | `database-design.md:155` |
| 11 | `gate_one_original` | L724 | `UNIQUE (project_id, component_id) WHERE mode = 'original'` | 每组件单一原始判定 | `database-design.md:158` |
| 12 | `evaluations_component` | L725 | `(project_id, component_id, created_at DESC)` | 组件判定历史 | `database-design.md:158` |
| 13 | `audits_project_time` | L726 | `(project_id, created_at DESC, id DESC)` | 审计分页 | `database-design.md:159` |
| 14 | `artifacts_expiry` | L727 | `(expires_at) WHERE availability = 'available'` | 保留策略扫描 | `database-design.md:165`（保留期） |
| 15 | `leases_one_live_debug` | L728 | `UNIQUE (project_id, debug_session_id) WHERE released_at IS NULL` | 一调试会话一活租约 | `database-design.md:129` |

### 3.2 与 database-design.md 索引要求逐条对照

说明：任务描述写“第 5 节”，但当前文档的索引要求在 **§7 文件归档、索引与容量（L145-165）**，§5（L106-120）是跨端配置与性能口径。下表按文件实际内容对照。

| 设计要求（行号） | schema.sql 落点 | 判定 |
| --- | --- | --- |
| 项目、应用、目标端最近运行（L153） | L715、L716、L717 | 满足 |
| 待运行队列 `state = 'queued'` 部分索引（L154） | L714 | 满足 |
| 资源状态索引（L155） | L720 | 满足 |
| 未释放租约唯一索引（L155） | L721、L722、L728 | 满足 |
| 到期索引（L155） | L723 | 满足 |
| 运行事件续读 `project_id + run_id + sequence` 唯一索引（L156） | 表级 `UNIQUE (project_id, run_id, sequence)` L671（PG 自动建索引） | 满足，但不是显式 `CREATE INDEX`，verify 脚本不检查 |
| 用例结果、指标、证据以父关联为唯一键前缀（L157） | `case_results` L476、`metric_summaries` L546、`artifacts` L509 | 满足 |
| 每组件单一 original + 组件时间查询（L158） | L724、L725 | 满足 |
| 审计 `project_id + 时间 + id`（L159） | L726 | 满足 |
| 列表采用 `created_at + id` 游标分页（L161） | 仅 L715-L717、L726 带 `id DESC` 尾列 | **部分满足**（见 G10） |
| 不先对全部 JSONB 建 GIN（L161） | 无 GIN 索引 | 满足 |

### 3.3 索引缺口清单

G1 **调试会话的资源冲突与过期扫描无索引**。`debug_sessions` 现有索引只有 PK L371、`UNIQUE(project_id, id)` L379、`UNIQUE(project_id, id, resource_id)` L380，没有以 `resource_id` 为前导的索引；而 `database-design.md:136` 要求“人工调试先锁调试会话再锁资源”，服务层必须按 `(project_id, resource_id, state)` 找活动会话，目前只能扫项目内全部调试会话。同时 `expires_at` 无索引（租约侧有 L723 可对比），过期清理只能全表扫。建议：`(project_id, resource_id)` 与 `(expires_at) WHERE state IN ('opening','active','closing')`。

G2 **指标跨运行趋势/基线对比无索引**。`metric_summaries` 唯一键 L546 以 `component_id` 为第二列，按 `(project_id, metric_key, metric_version, scope, window_key)` 过滤没有可用索引；`database-design.md:118` 的曲线/趋势读取必须 join `run_components` → `test_runs`，指标维度无法走索引。建议补 `(project_id, metric_key, metric_version, scope, window_key, statistic)` 或把 run 维度纳入覆盖索引。

G3 **重跑链无索引**。`test_runs.parent_run_id`（L318，外键 L337）无索引，查“某运行的全部重跑”会按项目扫描（`database-design.md:99` 的重跑语义需要该查询）。

G4 **档案关联无索引**。`test_runs.profile_id`（L324，外键 L339）与 `execution_resources.profile_id`（L168，外键 L179）都没有索引；“某档案下的实例/运行”无法索引，父行更新/删除的 RI 检查也只能项目级过滤。

G5 **任务修订的外键列无索引**。`task_revisions.environment_id`（L278）、`build_id`（L279）、`suite_version_id`（L280）没有 `(project_id, 列)` 索引（外键 L290-L292），删改父表时退化为项目内扫描。

G6 **基线的外键列无索引**。`baselines.environment_id`（L571）、`suite_version_id`（L572）、`profile_id`（L573）、`source_component_id`（L574）无索引（外键 L582-L585）。

G7 **门禁查询维度缺失**。`gate_evaluations.policy_id`（L629）、`baseline_id`（L630）无索引（外键 L640-L641）；现有 L725 只服务 component + 时间，查“某规则版本产生过哪些判定”“某基线被哪些判定引用”都会扫描。

G8 **证据子组件维度缺失**。`artifacts.component_id`（L497，复合外键 L512）没有索引；L509 `(project_id, run_id, logical_key)` 只能按 run 定位，取某组件的全部证据需 run 内扫描。建议 `(project_id, run_id, component_id) WHERE component_id IS NOT NULL`。

G9 **审计实体追溯缺失**。`audit_events` 只有 L726 `(project_id, created_at, id)`，按 `(entity_type, entity_id)` 查单实体历史无索引（`database-design.md:176` 的授权与追溯场景常用）。

G10 **游标分页口径不一致**。`database-design.md:161` 要求 `created_at + id`：实际只有 `runs_*` 三条（L715-L717）与审计（L726）带 `id DESC` 尾列；`evaluations_component` L725 有 `created_at` 无 `id`；`test_tasks`（L257）、`suite_versions`（L230）、`case_results`（L476）、`artifacts`（L509）都依赖唯一键前缀，不具备稳定游标。若列表 API 统一用 `created_at + id` 分页，这几处会退化为复合排序。

G11 **队列公平性**。`runs_queue` L714 是全局 `(created_at, id) WHERE state = 'queued'`，跨项目 FIFO；若要项目配额/优先级调度，需要新列或新索引。设计未要求，记录待决。

### 3.4 外键索引覆盖率（量化）

- **23 个单列 `project_id` 外键**：22 张表的 `UNIQUE(project_id, id)` 前导列精确覆盖；唯一例外 `project_members` 由 L32 `(project_id, identity_issuer, identity_subject)` 前缀覆盖。→ 23/23 有可用前导索引。
- **33 个复合外键**：全部只有 `project_id` 前导覆盖，**0 个**以“完整引用列集”为前导的普通索引（程序化比对全部索引列集后确认）。
- 后果：父行 `DELETE/UPDATE` 时 PG 的 RI 检查只能按项目前缀过滤，复杂度退化为 O(项目内行数)。因全部外键为默认 NO ACTION、设计明确以归档代替删除（`database-design.md:131`），风险低；但 `database-design.md:10` 提到跨实体事务会包含父行更新，建议至少补 G4、G5、G6 的高频父表索引。

---

## 4. COMMENT 覆盖

- **数量**：24/24 表 COMMENT（L17、L34、L55、L82、L107、L130、L154、L182、L208、L234、L260、L296、L349、L386、L417、L450、L480、L514、L551、L588、L615、L645、L676、L702）；231/231 列 COMMENT；合计 **255 条**。
- **校验**：程序化比对 255 条 COMMENT 的目标 → 0 条指向不存在的表/列、0 条重复、0 张表缺注释、0 列缺注释。任务要求的“数量与抽样”结论是：**没有缺口**。
- **抽样**：`projects` L17-L22（5 列）；`test_runs` L349-L367（18 列全覆盖，含 `state` L357、`outcome` L358、`reason_code` L359）；`resource_leases` L417-L428（11 列）；`metric_summaries` L551-L564（13 列）；`audit_events` L702-L711（9 列）。
- **质量**：注释把“服务层必须完成的不变量”写进表注释（`resource_profiles` L154、`test_runs` L349、`resource_leases` L417、`case_results` L480、`baselines` L588、`gate_evaluations` L645）。对开发有用，但它们是意图声明，不是 DDL 保证——评审与实现时不要误读为“已由数据库强制”。
- **缺口**：15 条显式索引没有 COMMENT（PG 支持 `COMMENT ON INDEX`）。部分索引语义（L721-L728）最需要注释，建议补，例如“未释放租约唯一性，到期不等于释放”。

---

## 5. verify-design.cjs 的校验口径与局限

### 5.1 它做什么（按代码顺序）

1. L6-L7 读入 `index.html` 与 `schema.sql`；L8-L9 用 `vm` 编译 `index.html` 中唯一的 `<script>`（即 JS 语法检查）。
2. L10 从该脚本抽出 `const databaseTables=[...]` 作为“字段字典”。**注意：对照源是 `index.html:124` 的字典，不是 `database-design.md`**。
3. L11-L12 用正则 `/CREATE TABLE (\w+) \(\n([\s\S]*?)\n\);/g` 抓表名与表体，再按 `,\n` 切分成“定义行”数组。
4. L13 表数量相等；L14 表名唯一；L19-L22 逐表 `deepEqual`（空白归一化后）SQL 定义行 == 字典的 `fields[].definition` + `constraints[]`；L23-L24 字段名唯一。
5. L26-L28 对 `UNIQUE`/`FOREIGN KEY` 约束里的本地列做存在性检查。
6. L30-L33 全局扫描 `REFERENCES`，**每出现一次计一个外键**（列级与表级都计）→ 56。
7. L34-L35 目标表存在；L36-L39 本地/目标列数一致（arity）；L40-L45 目标列存在 + 类型 token（按空白切分第 2 段）相等；L46-L51 目标列集必须是字典里声明的 PK/`UNIQUE`。
8. L54 断言 `BEGIN` 与 `COMMIT` 包裹；L55 断言无 `DROP/DELETE/TRUNCATE`；L56 断言 `index.html` 无外链脚本。
9. L57-L58 打印统计并自述“未执行任何 PostgreSQL 语句”。

### 5.2 实测结果（本轮）

- 命令：`node docs/platform-prototype/verify-design.cjs`（Node v24.14.0）。
- 输出：`Static design checks PASS: 24 tables, 231 columns, 56 foreign keys; JS syntax and SQL/UI definitions consistent.` 以及 `No PostgreSQL statements executed. ...`（退出码 0）。
- 与 `database-design.md:229` 的记录（24 表、231 字段、56 外键）一致。

### 5.3 局限（重要）

1. **不是 SQL 解析器**（L1 自述）：正则要求严格格式——`CREATE TABLE x (` 换行、`);` 结束、定义行以 `,\n` 分隔；任何多行字段定义、内联注释、尾逗号换行都会解析失败或错位（当前文件刚好满足）。
2. **只证明文本一致**：证明的是“`schema.sql` 与 `index.html` 字典一致”，不是“SQL 可执行”或“语义正确”。两者都是人工维护，同步出错会一起通过（循环校验）。
3. **不验证 CHECK 语义**：括号/类型/运算符可行性、NULL 三值逻辑、`~` 正则与 `jsonb_typeof` 可用性都不执行（L58 自述）。
4. **完全不验证索引**：15 条 `CREATE INDEX`（含 7 条部分索引）不在校验范围内；索引列是否存在、`WHERE` 是否合法、是否重复都无检查。
5. **不验证约束命名/可演进性**：0 个 `CONSTRAINT` 名不会报错，而这正是 Alembic 增量迁移的隐患（7.1-P0-2）。
6. **不验证外键 MATCH 语义**：可空复合外键（`artifacts` L512 `(project_id, run_id, component_id)`）在 `component_id IS NULL` 时按 MATCH SIMPLE 整体跳过，脚本无法发现。
7. **唯一键检查是文本扫描**：只认字段定义中的 `PRIMARY KEY`/`UNIQUE` 与表级 `UNIQUE (...)` 文本，无法识别等价的唯一索引（当前文件恰好没用唯一索引替代约束）。
8. **与迁移口径相反**：L54 只是断言 `BEGIN/COMMIT` 存在，而 Alembic 场景恰恰要去掉它（7.1-P0-1）；脚本里也没有 `alembic_version`、重复执行、downgrade 的概念。
9. **不验证 COMMENT / 性能 / 权限 / RLS / 并发 / 恢复**（L58 与 `database-design.md:237` 已自述）。

结论：该脚本适合当“文档-字典-代码”一致性门禁（本轮 PASS 可作为现状证据），**不能替代真实 PostgreSQL 建库与迁移测试**。

---

## 6. Alembic 落地建议

### 6.1 结论：初始迁移用单文件

- 推荐：**单一 revision**（如 `0001_initial_schema`，`down_revision=None`），一次建 24 张表 + 15 条索引 + 255 条 COMMENT。
- 理由：
  1. 全部外键内联在 `CREATE TABLE` 中（列级 23 + 表级 33），PostgreSQL 的 DDL 是事务性的，单迁移 = 原子成功/失败，不留半套 schema；链式多 revision 只保证“单个 revision”原子。
  2. 没有历史数据要搬，拆分不产生分阶段收益。
  3. 顺序正确性是本 schema 的主要风险（见 1.3），排序集中在一个文件里更容易 review。
  4. `alembic_version` 天然实现 `database-design.md:211` 要求的“重复执行由版本管理拦截”，无需 `IF NOT EXISTS`（当前文件也没有用，正确）。
- 代价：单文件约 700-900 行，review 负担大。用本文 §1.1 的表顺序 + §3.1 的索引清单当 checklist 可缓解。
- 何时再拆：团队强制“单迁移行数上限”、或需要按域回滚时，按 6.4 的 6 域链拆；首版不建议。

### 6.2 schema.sql 构造 → Alembic/SQLAlchemy 写法对照

| schema.sql 构造 | 迁移写法 | 注意 |
| --- | --- | --- |
| `id uuid PRIMARY KEY` | `sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True)` | 不要用 `sa.String(36)` |
| `text` | `sa.Text()` | 无长度上限语义 |
| `timestamptz NOT NULL DEFAULT now()` | `sa.DateTime(timezone=True), server_default=sa.text('now()')` | 用 `server_default`，不要 Python 侧 `default` |
| `integer` / `bigint` | `sa.Integer()` / `sa.BigInteger()` | — |
| `double precision` | `sa.Float(precision=53)` 或 `postgresql.DOUBLE_PRECISION` | `metric_summaries.value` L542 |
| `jsonb NOT NULL DEFAULT '{}'::jsonb` | `postgresql.JSONB, server_default=sa.text("'{}'::jsonb")` | 需 `from sqlalchemy.dialects import postgresql` |
| 列级 `CHECK (...)` | `sa.Column(..., sa.CheckConstraint(..., name='ck_...'))` | 现有 40 条列级 CHECK 全部无名 |
| 表级 `UNIQUE (...)` | `sa.UniqueConstraint(..., name='uq_...')` | 现有 56 条 |
| 表级 `FOREIGN KEY ... REFERENCES ...` | `sa.ForeignKeyConstraint([...], ['t.c1', ...], name='fk_...')` | 现有 33 条 |
| 表级 `CHECK (...)` | `sa.CheckConstraint(sa.text('...'), name='ck_...')` | 现有 33 条；`jsonb_typeof`/正则/`float8` 比较必须用 `sa.text` |
| `CREATE [UNIQUE] INDEX ... [WHERE ...]` | `op.create_index(..., unique=..., postgresql_where=sa.text('...'))` | 7 条部分索引；唯一索引不能写成 `sa.UniqueConstraint` |
| `COMMENT ON TABLE/COLUMN` | `op.execute(原文)` 或 `comment=` 参数 | 255 条；建议 `op.execute` 保真 |
| `BEGIN;` / `COMMIT;` | **删除** | Alembic 自身已在事务中，见 7.1-P0-1 |

### 6.3 需要手工 `op.execute()` 或方言参数的 DDL

1. **255 条 COMMENT**（24 表 + 231 列）：建议 `op.execute` 原样执行，中文 UTF-8、与 `schema.sql` 逐字一致、便于 diff；若用 `comment=` 参数，`create_table` 会变得极长且难以逐字校验。
2. **7 条部分索引**（`schema.sql:714`、`:721`、`:722`、`:723`、`:724`、`:727`、`:728`）：可用 `postgresql_where=sa.text('...')`；若要保证与评审稿逐字一致，直接用 `op.execute(CREATE INDEX ...)`。注意 L721/L722/L728 是**唯一索引**、L724 也是唯一索引，必须 `unique=True` + `postgresql_where`，不能用 `UniqueConstraint`（PG 的 `UNIQUE` 约束不能带 `WHERE`）。
3. **14 条 `jsonb_typeof` CHECK**（L80、L105、L128、L152、L232、L293、L340、L447、L478、L586、L613、L642、L674、L700）：用 `sa.CheckConstraint(sa.text("jsonb_typeof(col) = 'object'"))`；注意 `op.execute` 里不要出现裸 `%`（避免被当成参数占位符），本文件的正则 `^[0-9a-f]{64}$` 没有 `%`，安全。
4. **3 条正则 CHECK**（`app_builds.sha256` L73、`resource_profiles.fingerprint` L146、`artifacts.sha256` L503）：`~ '^[0-9a-f]{64}$'` 用 `sa.text` 原样。
5. **2 条 float8 边界 CHECK**（`metric_summaries` L548、L549）：`'-Infinity'::float8` / `'Infinity'::float8` 用 `sa.text` 原样；`op.execute` 也可，但注意 `::` 在 SQLAlchemy 中的转义。
6. **枚举型 CHECK**（platform/role/state/outcome/availability/kind/statistic/mode/verdict 共 24 条列级）：建议统一 `sa.text` 并在迁移里补名，便于以后加端/加状态时精确 `DROP CONSTRAINT`。
- 不需要 `op.execute` 的部分：普通建表、普通索引、`uuid/timestamptz/jsonb/integer/bigint` 类型、`server_default`。

### 6.4 如果拆分：6 域链与风险

| revision | 内容（schema.sql 行号） | 依赖 |
| --- | --- | --- |
| `0001_identity_projects` | `projects` L10-16、`project_members` L25-33 | — |
| `0002_catalog_resources` | `applications` L43-54、`app_builds` L65-81、`environments` L95-106、`execution_nodes` L117-129、`resource_profiles` L141-153、`execution_resources` L164-181 | 0001 |
| `0003_suites_tasks` | `test_suites` L195-207、`suite_versions` L218-233、`test_tasks` L246-259、`task_revisions` L272-295 | 0001、0002 |
| `0004_execution` | `test_runs` L312-348、`debug_sessions` L370-385、`resource_leases` L397-416、`run_components` L431-449 | 0002、0003 |
| `0005_results_perf_governance` | `case_results` L464-479、`artifacts` L493-513、`metric_summaries` L531-550、`baselines` L567-587、`gate_policies` L602-614、`gate_evaluations` L625-644 | 0002、0003、0004 |
| `0006_telemetry_indexes` | `run_events` L659-675、`audit_events` L689-701、全部 15 条索引 L714-728 | 0003、0004、0005 |

- 风险 1：链式顺序即部署顺序，一旦误插/重排，空库 `upgrade head` 会失败（外键目标不存在）。
- 风险 2：拆分后每个 revision 是独立事务，失败时已提交前序 revision，“半套 schema”概率上升；除非 `env.py` 显式设置 `transaction_per_migration=False`（Alembic 默认即整链一个事务，需确认版本行为）。
- 风险 3：0006 的索引依赖 0004/0005 的表，若未来把索引下放到各域，必须重新验证索引对表的依赖。
- 收益：评审粒度细、按域回滚方便。结论：首版单文件；等 schema 稳定、团队确需按域演进时再拆。

### 6.5 迁移验收建议（在隔离空库）

- `alembic upgrade head` 成功；再次执行不产生变更（`alembic_version` 拦截，对应 `database-design.md:211`）。
- 用 `pg_catalog`/`information_schema` 断言：24 表、231 列、56 外键、73 CHECK、57 UNIQUE、15 条显式索引（其中 7 条 `pg_index.indpred IS NOT NULL`）、255 条 COMMENT。
- `alembic downgrade base` 能按反依赖顺序 DROP（downgrade 需手写，Alembic 不保证自动生成可靠的反向脚本）。
- `pg_dump --schema-only` 与 `schema.sql` 做规范化 diff（剥离 `BEGIN/COMMIT`、统一排序），作为“单一真源”的自动校验（见 7.1-P0-4）。
- `database-design.md:209-222` 的行为验收仍需真实 PG 与并发测试。本机无 PostgreSQL，以上均未执行。

---

## 7. 必须改 / 建议改清单

### 7.1 必须改（生成初始迁移、冻结 schema 基线之前）

**P0-1 去掉 `BEGIN;`/`COMMIT;` 事务包装，并调整校验口径。**
- 证据：`docs/platform-prototype/schema.sql:7` 是 `BEGIN;`、`docs/platform-prototype/schema.sql:730` 是 `COMMIT;`；`docs/platform-prototype/verify-design.cjs:54` 强制断言二者存在。
- 影响：Alembic 的 `upgrade` 在事务中执行，迁移内再 `COMMIT` 会提前提交，后续语句失败时无法回滚，破坏原子性。这是**唯一确定的迁移阻塞项**（DDL 语法本身未发现阻塞）。
- 处理：`schema.sql` 保留为评审稿（它自述 REVIEW ONLY，L3）；迁移文件不带包装；`verify-design.cjs` 的 L54 断言改为只对评审稿生效，或改成对迁移后的数据库做 introspection 校验。

**P0-2 给全部 CHECK / UNIQUE / 外键补显式名称。**
- 证据：程序化统计，122 条表级约束 + 41 条列级约束中 `CONSTRAINT` 关键字出现 **0 次**（例如 `schema.sql:79` 的 `FOREIGN KEY (project_id, application_id) REFERENCES ...`、`schema.sql:341` 的 `CHECK (...)` 都没有名字）。
- 影响：初始迁移能建，但之后任何 `ALTER TABLE ... DROP CONSTRAINT`、Alembic autogenerate、依赖约束名的测试都要靠 PG 自动命名（`test_runs_state_check`、`test_runs_check1` 之类），顺序一变名字就变，无法写稳定的增量迁移。
- 处理：迁移里统一命名前缀（`pk_`/`uq_`/`fk_`/`ck_`），不改语义；`schema.sql` 同步补名，保持“评审稿 = 迁移”可比。

**P0-3 三态口径补齐：`not_tested` 必须有原因。**
- 证据：`test_runs` 有 `reason_code`（`schema.sql:322`），但只有 L341 的 state/outcome 联动，没有“`not_tested` ⇒ reason 非空”的 CHECK；`run_components` 有 `outcome`（L440）却没有 `reason_code` 列；对照 `gate_evaluations` L643 已有 `CHECK (verdict <> 'not_tested' OR reason_code IS NOT NULL)` 可作范式。口径来源：`database-design.md:98`（缺指标/样本不足/基线不可比属于 completed + not_tested 并保留原因）、`database-design.md:216`。
- 影响：DDL 允许 `completed + not_tested + reason 为空` 写入，后续报告无法解释“未判定”原因；给 `run_components` 补原因字段属于 schema 变更，必须在基线冻结前决定，否则要出第二次迁移。
- 处理（二选一）：a) `test_runs` 加 CHECK（`outcome <> 'not_tested' OR reason_code IS NOT NULL`），`run_components` 加 `reason_code text` 并同样加 CHECK；b) 明确原因只存 `run_components.summary`（L441）并写进设计文档，同时给 `test_runs` 加 CHECK。推荐 a。

**P0-4 确定单一真源，避免“24 表/231 列”三处手工同步。**
- 证据：`docs/platform-prototype/schema.sql`（DDL）、`docs/platform-prototype/index.html:124`（`databaseTables` 字典）、`docs/platform-prototype/database-design.md:48-81`（表清单）三处各自维护；`verify-design.cjs:20-22` 只证明前两者一致，不证明与 `database-design.md` 一致。
- 影响：迁移后若继续以 `index.html` 为字典，`schema.sql` 与迁移会与文档漂移；若以迁移为真源，`schema.sql` 应由迁移或 `pg_dump` 生成。
- 处理：约定“迁移 = 可执行真源，`schema.sql` = 从迁移导出的评审快照（含约束名）”，`verify` 改为 migrate → dump → diff。这条决定会改变 P0-1 的处理方式，因此与 P0-1 一起定。

### 7.2 建议改（不阻塞初始迁移，按优先级）

**S1 补索引（对应 G1-G9）。** 优先级：G1（调试会话冲突，`database-design.md:136` 的锁顺序依赖它）> G2（趋势/基线，核心功能）> G3（重跑）> G4-G9。具体：`debug_sessions (project_id, resource_id)` 与 `(expires_at) WHERE state IN ('opening','active','closing')`；`metric_summaries (project_id, metric_key, metric_version, scope, window_key)`；`test_runs (project_id, parent_run_id)`；`test_runs (project_id, profile_id)`、`execution_resources (project_id, profile_id)`；`task_revisions` 三个外键列；`baselines` 四个外键列；`gate_evaluations (project_id, policy_id)`、`(project_id, baseline_id)`；`artifacts (project_id, run_id, component_id) WHERE component_id IS NOT NULL`；`audit_events (project_id, entity_type, entity_id, created_at DESC)`。注意 `database-design.md:161` 的口径是“按实测 EXPLAIN 增加”，建议先建库+样本数据，再按需补，避免一次性写放大。

**S2 修复 `released_at` 可写未来时间绕过部分唯一索引。**
- 证据：`schema.sql:413` 只要求 `released_at >= created_at`；L721、L722、L728 的 `WHERE` 是 `released_at IS NULL`。
- 影响：任何能写 `resource_leases` 的路径写入未来 `released_at`，即可在“实际未释放”时让部分唯一索引放行第二条未释放租约，破坏“一实例一活租约”。
- 处理：服务层禁止写入未来时间（只允许 NULL 或 `now()` 之前）；或改为 `released boolean` + `released_at` 双列，部分索引 `WHERE released = false`。DDL 侧用 `now()` 不可靠。

**S3 归档唯一键的可复用性需要确认。** `applications UNIQUE(project_id, platform, identifier)` L53、`environments UNIQUE(project_id, name)` L104、`execution_nodes UNIQUE(project_id, name)` L127、`test_suites UNIQUE(project_id, application_id, name)` L205、`projects.code UNIQUE` L12 都不看 `archived_at`（L49、L101、L201、L14）。归档后同名/同 identifier 无法复用，只能改名。这是取舍（`database-design.md:131` 说归档不使历史关联失效），但需产品确认；若允许复用，改成部分唯一索引 `WHERE archived_at IS NULL`。

**S4 `run_components` 缺时间字段。** 只有 `created_at` L442，没有 `started_at`/`ended_at`（`test_runs` 有 L327-L328 与联动 CHECK L342）；子组件“何时开始/结束”不可查，排障只能靠 `run_events`（L659-675）。建议补两列 + 类似 L342 的 CHECK。

**S5 文本列允许空串。** `projects.code` L12、`projects.name` L13、`applications.identifier` L48、`app_builds.build_key` L70、`artifacts.logical_key` L498、`test_runs.request_key` L319、`metric_summaries` 的 `metric_key/unit/scope/window_key` L535-L539、`resource_leases.holder_id` L404 等只有 NOT NULL，没有 `length(trim(...)) > 0`；空串会被唯一键当作有效值。建议关键标识加 CHECK，或由服务层 Pydantic 校验（更符合 `database-design.md:13` 的应用层校验主张）。

**S6 `audit_events.entity_id` 固定 uuid（L695）。** 未来若审计非 UUID 实体（配置键、外部 ID）会受限；`schema.sql:708` 自述它是“历史追溯引用而非跨表通用外键”。若已确定所有实体都是 UUID 则保持，否则改为 text 并保留 `entity_type`。

**S7 `debug_sessions` 缺最长时长与“每资源至多一个活动会话”的 DDL。** L382 只有 `expires_at > created_at`；活动会话唯一性依赖租约部分唯一索引 L728，DDL 不要求调试会话必有租约。建议加 `expires_at <= created_at + interval '...'` 上限（需产品定值）。

**S8 游标分页索引按 API 设计统一（G10）。** 若列表统一用 `created_at + id`，给 `test_tasks`、`suite_versions`、`case_results`、`artifacts`、`gate_evaluations` 补 `(父列..., created_at DESC, id DESC)`。

**S9 补索引 COMMENT（§4 末）。** PG 支持 `COMMENT ON INDEX`；至少给 7 条部分索引起名并注明语义。

**S10 `projects.code` 全局唯一（L12）。** 当前单组织可用；若未来多组织/多租户，需要 `org_id` 维度。`database-design.md:223` 的待决项可加一条。

**S11 `artifacts` 的 `UNIQUE(project_id, storage_key)`（L510）会阻止内容寻址去重。** 若 `storage_key` 计划用内容摘要（sha256）实现跨运行共享同一文件，L510 会让第二次引用失败；若 `storage_key` 一定包含 run 维度（如 `runs/<id>/...`）则无影响。`database-design.md:147` 只写“写入不可变对象键”，建议明确键是否含运行维度。

**S12 索引放置顺序（cosmetic）。** `leases_one_live_debug`（L728）与 L721/L722 同属租约唯一性，建议归位。

### 7.3 不建议改（澄清，避免误当缺陷）

- `test_runs` 的 5 个唯一索引（L331-L334 + PK）：每个都是不同复合外键的**必需**目标（PG 要求被引用列集存在唯一约束），删除会导致 L411 等外键无法创建。
- `projects` 没有 `UNIQUE(project_id, id)`：根表没有 `project_id` 列，子表用单列外键引用 PK，正确。
- `project_members` 没有 `UNIQUE(project_id, id)`：叶子表、无被引用，且有业务唯一键 L32。
- 没有独立 `reports` 表：`database-design.md:79` 明确报告是查询视图 + `artifacts` 文件。
- 没有 GIN 索引：`database-design.md:161` 明确不先对全部 JSONB 建 GIN。
- jsonb 只做顶层类型检查：`database-design.md:13` 把深字段与大小上限交给应用层。
- 部分唯一索引用 `released_at IS NULL` 而不是时间比较：`database-design.md:139` 明确“到期只表示需要检查”。

---

## 附录 A：本轮证据

- 实跑 `node docs/platform-prototype/verify-design.cjs`（Node v24.14.0）→ 退出码 0，输出 `Static design checks PASS: 24 tables, 231 columns, 56 foreign keys; JS syntax and SQL/UI definitions consistent.`
- 解析统计（Node 一次性脚本，未落盘）：24 `CREATE TABLE`、231 列、56 `REFERENCES`（23 列级 + 33 表级）、73 `CHECK`（40 列级 + 33 表级）、56 表级 `UNIQUE` + 1 列级 `UNIQUE`、0 命名约束、15 `CREATE INDEX`（8 全量 + 7 部分）、255 `COMMENT`（24 表 + 231 列）、0 孤儿/重复 COMMENT、0 前向引用、0 外键目标缺唯一键。
- 未修改任何被审文件；未安装 PostgreSQL。

## 附录 B：未确认事项

1. **未在真实 PostgreSQL 17 执行该 DDL**（本机无 `psql` 客户端；`database-design.md:237` 同样声明）。语法判定基于 PG17 官方文档与静态阅读：`uuid/text/timestamptz/jsonb`、部分索引、正则 CHECK、`'-Infinity'::float8` 比较均为合法语法，但“可建库”未经运行验证。
2. 未验证 CHECK 的实际求值行为（NULL 三值、NaN 比较、`jsonb_typeof` 名称解析），仅按 PG 文档推断；其中 `metric_summaries` L549 对 ±Inf/NaN 的拦截是推断结论。
3. 索引缺口的影响程度未做 `EXPLAIN` 实测（无库、无数据）；优先级基于查询模式推断。
4. 行号以本轮读取的文件为准（`schema.sql` 730 行、`database-design.md` 237 行、`verify-design.cjs` 59 行）；若文件被并行修改，行号需重新校准。
5. P0-1/P0-4 属工程口径，是否阻塞取决于团队是否采用 Alembic 与“迁移为真源”的决策；若换用其它迁移工具，P0-1 的具体形式会变，但“评审稿不能直接当迁移”的结论不变。


