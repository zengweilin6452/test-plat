# 设备注册与资源池同步方案设计

> 状态：**已实施（2026-10-28，T1–T8 代码完成；真机验收待做）**。G4 schema 变更已于 2026-10-27 签字批准（见 §5.1）。
> 前置事实全部来自 2026-10-27 的实测（adb 输出、库查询、live HTTP），来源见 §1.2。
> 关联文档：`api-design.md` §2.2、`development-plan.md` §8.2、`frontend-spec.md` §61、`data-model.md` §5。

## 1. 问题

### 1.1 一句话

平台的设备池是一张**只读的空表**：没有任何生产代码去问 adb"现在插着什么设备"，
所以真机插上也永远不显示。`POST /resources/sync` 在 `api-design.md:71` 与
`development-plan.md:401` 都已定义，**但从未实现**（实测 404）。

### 1.2 实测证据

| 检查 | 结果 |
| --- | --- |
| 真机 `84cb2c4e`（Redmi 25102RKBEC）在 `adb devices` 中 | ✅ `84cb2c4e  device` |
| 该 serial 在 `execution_resources` 中 | ❌ 0 行 |
| `POST /api/v1/debug-sessions {"serial":"84cb2c4e"}` | ❌ `not_found: device 84cb2c4e 不存在` |
| `POST /api/v1/resources/sync` | ❌ HTTP 404 |
| `POST /api/v1/resources` | ❌ HTTP 405 |
| `server/app/` 内任何 `adb` 调用 | ❌ 一处都没有 |
| `execution_nodes` 的写入方 | ❌ 只有 `seed_demo.py` 与 pytest |
| `execution_nodes.heartbeat_at` 的写入方 | ❌ 无人维护 |

### 1.3 现状的连带后果

- **调试抽屉不可用**：`debug.py:311` 按 `resource_key` 查库，真机查不到即 404。
- **运行无法派发到真机**：`leases._PICK_SQL` 只从 `execution_resources` 取
  `status='ready'` 的行，表里没有真机就永远派不出去。
- **档案匹配无从谈起**：`resource_profiles` 目前只有 seed 的两条，且 `spec` 缺
  `model` 字段，`normalize_profile()` 直接抛 `ProfileNormalizationError`
  （实测：`设备档案缺少字段 ['model']`）。

### 1.4 测试污染（独立但同源的缺陷）

本次清理前库里 955 台设备里 **949 台**是 pytest 残留。根因有两层：

1. `server/tests/conftest.py:63` 的 `_EXTERNAL_DSN` 默认指向**共享开发库**
   `127.0.0.1:55432/testdock`。
2. `_p3_common.drop_project()` 只发 `DELETE FROM projects`，而全部外键都是
   `NO ACTION`，必然 `ForeignKeyViolation`，又被 `except: pass` 吞掉——实测确认。
   于是每个用例留下一整棵孤儿数据树。

不修这两处，设备同步做完了也会被测试残留重新淹没。

## 2. 目标与非目标

**目标**

1. 真机插上后，`POST /resources/sync` 能把它登记进池子，出现在设备页。
2. 设备特征自动匹配或创建 `resource_profiles`，档案可比性口径不破。
3. 设备消失置 `offline`，历史运行与调试记录不受影响。
4. 设备列表支持按项目过滤。
5. 测试默认连不到开发库，清理失败不再静默。

**非目标（本期不做）**

- `POST /resources/{id}/readiness`（vendor `Keeper.run()` 就绪检查）——相邻但独立，另开。
- 真正的多机 agent 上报协议——本期只把**接口形态与数据模型**做成多节点可扩展。
- 前端项目切换器的完整体验——本期只做最小可用的默认项目解析。
- `POST /resources/sync` 的定时化（后台轮询）——本期只做手动触发。P2 若做，
  业界路径不是轮询而是 `adb track-devices` 常驻监听（先例与调研见 §10.2 第 1 条）。

## 3. 设计决策

### D1. adb 路径：默认走仓库自带的 vendor adb

```
settings.adb_path（新增）
  默认 = REPO_ROOT / "vendor/mobile_auto/tools/adb/adb.exe"
  覆盖 = TESTDOCK_ADB 环境变量
```

实测该二进制存在且可用：

```
Android Debug Bridge version 1.0.41 / Version 37.0.1-15733141
```

**为什么不复用 `mobile_perf.resolve_adb()`**：它的随包默认是
`vendor/mobile_perf/SoloPi/platform-tools/adb.exe`（另一个文件，版本恰好相同），
且解析链依赖 `MOBILE_PERF_ADB` / `ADB` 两个当前未设置的环境变量。平台需要一条
**自己的、可预测的**默认路径，而不是跟着 vendor 的内部布局漂移。

**为什么不用 adbutils**：`adbutils 2.12.0` 本机可用，但它是 vendor 的可选依赖，
`server/pyproject.toml` 未声明。把 API 进程绑到它上面违反 §5.2 只读纪律的
精神（API 进程不应硬依赖 vendor 依赖树）。

**实现形态**：`server/app/integrations/devices.py`，用 `subprocess.run([adb, "devices", "-l"])`
直接调二进制，**不 import 任何 vendor 包**，
`test_app_never_imports_vendor_packages_at_module_level` 继续绿。
这是与 `integrations/discover.py` 完全一致的既有模式。

**路径不存在时的行为**：不静默降级、不猜 PATH。`POST /resources/sync` 返回
`503 adb_unavailable`，details 带期望路径与 `TESTDOCK_ADB` 提示。理由：
静默回落到 PATH 上的 adb 会让"同一台机器不同 shell 看到不同设备"这种问题
无法复现。

### D2. 聚合所有节点：接口按节点聚合，本期只有本机节点

数据模型本来就支持多节点：`uq_execution_resources_project_id_node_id_resource_key`
是 `(project_id, node_id, resource_key)`，同一 serial 在两个节点上是两行，不会互撞。

**本期实现**：

- 一个内置的"本机执行节点"概念，`execution_nodes.name = '本机执行节点'`，
  `capabilities = {"adb": true, "local": true}`，按 `(project_id, name)` 幂等 upsert。
- `POST /resources/sync` 遍历**所有** `status='online'` 的节点：
  - 能探测的节点（本期只有本机）→ 扫 `adb devices -l`，按 D3/D4 处理；
  - 探测不到的节点（未来 agent 离线）→ 结果里记 `{"node_id":…, "status":"unreachable"}`，
    **不**因此把该节点的设备全标 offline。理由：节点失联 ≠ 设备消失，混为一谈会让
    一次网络抖动把整个机房的设备打成 offline。
- 响应按节点分组返回，前端设备页按 `node_id` 分组显示。

**明确记录的限制**：`execution_nodes` 今天没有任何注册/心跳写入方。
本期 sync 会顺手更新本机节点的 `heartbeat_at`，但"远端节点如何注册"不在本期范围。
接口形态（按节点聚合、按节点报告 unreachable）先定下来，避免以后改契约。
该形态与 STF provider / Sonic agent / GADS node 的收敛结果一致（调研见 §10.2 第 2 条）。

### D3. 档案匹配：用设备特征算指纹，命中即复用，未命中即建档

#### D3.1 采集哪些特征

实测真机可读（`vendor/mobile_auto/tools/adb/adb.exe -s 84cb2c4e shell …`）：

| 来源 | 实测值 |
| --- | --- |
| `getprop ro.product.brand` | `Redmi` |
| `getprop ro.product.manufacturer` | `Xiaomi` |
| `getprop ro.product.model` | `25102RKBEC` |
| `getprop ro.build.version.release` | `17` |
| `getprop ro.build.version.sdk` | `37` |
| `wm size` | `Physical size: 1200x2608` |

#### D3.2 规范化与指纹

复用已有的 `server/app/domain/profiles.py::normalize_profile`（**不新写一份口径**）：

```python
spec = {
    "os_name": "Android", "os_version": "17",
    "screen_resolution": "1200x2608", "model": "25102RKBEC",
}
canonical = normalize_profile(spec)      # "android-17|1200x2608|25102rkbec"  ← 实测通过
fingerprint = sha256(json.dumps(canonical_spec, sort_keys=True)).hexdigest()
```

匹配键用 **`(project_id, platform, fingerprint)`** —— 库上已有唯一索引
`uq_resource_profiles_project_id_platform_fingerprint`，天然幂等，并发安全。

- **命中** → 复用该 `profile_id`。
- **未命中** → 新建档案，`name` 取 `"{brand} {model} / Android {version} / {resolution}"`，
  `spec` 存规范化后的四字段。

#### D3.3 探测失败（unauthorized / offline）

`execution_resources.profile_id` 是 **NOT NULL**，所以未授权设备也必须有档案。
处理方式：每个 `(project, platform)` 惰性建一个"未识别设备"档案，
`spec = {"unknown": true}`，指纹取其固定哈希。设备授权后下一次 sync 重新探测，
把 `profile_id` **升级**为真实档案。

**安全性**：`test_runs.profile_id` 是独立列，历史运行不会被改写；
`resource_profiles` 的唯一索引是 `(project_id, platform, fingerprint)`，
升级只是改资源行指向，不产生脏档案。

#### D3.4 与 seed 档案的关系（必须写清楚）

seed 的两条档案 `spec` 缺 `model`，**无法被 `normalize_profile` 规范化**（实测抛错），
因此永远匹配不上真机。这是既有事实，不是本次引入的缺陷。后果：

- 真机会创建自己的档案，与 seed 的"Android 旗舰 / Android 中端"并存；
- 建议 `seed_demo.py` 后续给档案补 `model` 字段，或干脆不再造设备——
  **本期不改 seed**，只记录。

### D4. 同步语义：消失置 offline，永不删行

```
adb 里在，DB 里无        → INSERT（status 按 adb 状态映射）
adb 里在，DB 里也在      → UPDATE status / profile_id / last_seen_at
adb 里无，DB 里有（本节点）→ UPDATE status = 'offline'，保留行
```

**为什么永不删行**：`test_runs.resource_id` 与 `debug_sessions.resource_id` 都
`REFERENCES execution_resources(project_id, id)`。删行会撞历史外键，或迫使我们把
历史记录的设备指针清空——那等于篡改历史。实测确认这两个外键存在。

**adb 状态映射**：

| adb 状态 | `execution_resources.status` |
| --- | --- |
| `device` | `ready` |
| `unauthorized` | `unauthorized` |
| `offline` | `offline` |
| 其他（`recovery`、`sideload` 等） | `draining`（不可调度但不谎报离线） |

**例外：有未释放租约的设备不动**。若设备正在被 run 或调试会话占用，
即使 adb 里看不到，也**不**改它的 status，只记入响应的 `busy_skipped` 列表。
理由：平台不该在作业执行中把设备从底下抽走；设备真拔了，runner 会失败，
reconciler 60s 后回收租约，下一次 sync 自然把它标 offline。让既有状态机收敛，
而不是让 sync 抢在状态机前面做决定。

**已知限制**：拔掉后永不插回的设备会永久留在 `offline`。本期不做归档/软删，
前端靠 `status` 过滤隐藏。需要"清理僵尸设备"时另开需求。

### D5. 项目过滤

现状：`GET /resources`、`/overview`、`/applications`、`/runs`、`/tasks`、`/suites`
**全部没有 `project_id` 参数**（实测：各 router 的 `Query(project_id=…)` 计数为 0）。
多项目并存时数据必然混在一起。

**本期范围（P0）**：`GET /resources?project_id=<uuid>`
- 参数可选；不传 = 全部项目（保持向后兼容，避免一次性改爆前端）。
- 传了但项目不存在 → 404，不返回空列表（空列表会被误读成"这个项目没设备"）。

**配套（P0，最小）**：新增 `GET /projects`，返回 `{id, code, name, archived_at}`。
前端 `store/scope.ts` 已有"URL 优先 + localStorage 兜底"的成熟模式，
照同一套加 `project` 维度：URL `?project=<id>` 优先，否则取上次选择，
否则取第一个未归档项目。

**配套（P1，本期不做但必须记录）**：`/overview`、`/applications`、`/runs`
的 `project_id` 过滤。只给 `/resources` 加过滤会造成"设备页按项目、
工作台算全库"的口径分裂，必须在下一期补齐，否则比不加更糟。

### D6. 测试默认库：删掉共享库默认值，失败不再静默

**改动一：`conftest.py` 去掉 `_EXTERNAL_DSN` 默认值。**

```python
# 现在（危险）：没有环境变量时默认连开发库
_EXTERNAL_DSN = "postgresql+psycopg://testdock@127.0.0.1:55432/testdock"
dsn = os.environ.get("TESTDOCK_TEST_DATABASE_URL") or _EXTERNAL_DSN
```

改为：只有显式设置 `TESTDOCK_TEST_DATABASE_URL` 才复用外部库，
否则一律用临时实例。

**改动二：让临时实例在 `pytest_configure` 阶段就绪，而不是等 fixture。**
这一条是难点，必须说明原因：`_p3_common` 在**模块导入期**读取
`os.environ["TESTDOCK_TEST_DATABASE_URL"]` 算 `HAVE_DB`，而 `pg_instance` 是
session 级 fixture、在收集之后才创建。若只做改动一，`TEST_DB` 会是空串，
`requires_db` 让 P3 全部 **skip** —— 209 个测试变成"全绿的空跑"，正是
Hard Stop 里的 hollow green。

因此：`pytest_configure(config)` 里同步起临时实例 + 跑 `alembic upgrade head`
+ 写入 `TESTDOCK_TEST_DATABASE_URL` / `TESTDOCK_DATABASE_URL`，
`pytest_unconfigure` 负责停实例、删目录。`pg_instance` 改成读取已就绪的实例。
代价是每次跑测试多 ~10–20s 的 initdb，换来"测试物理上碰不到开发库"。

**改动三：`drop_project` 按外键顺序删，且不吞异常。**

现在的 `DELETE FROM projects` 必然 `ForeignKeyViolation`（实测）。改为按
依赖叶子优先的顺序删子表再删项目；非预期异常直接抛出，让残留立刻暴露，
而不是攒成 949 台。

> 参考实现：本次手工清理用的 `.runtime/cleanup_test_projects.py` 里那份
> `ORDER` 列表（23 张表 + projects），已在真实库上验证过 11619 行删除成功。

## 4. 接口契约

### 4.1 `POST /api/v1/resources/sync`

请求（body 可空）：

```json
{ "project_id": "<uuid>", "node_id": "<uuid>" }
```

- `project_id` 缺省 = 所有项目（每项目各自登记自己的设备）。
- `node_id` 缺省 = 所有 online 节点。
- 写操作，沿用既有 `X-TestDock-Client: web` 守卫（与 `POST /runs` 一致）。

响应 200：

```json
{
  "started_at": "2026-10-27T14:30:00Z",
  "duration_ms": 1832,
  "adb_path": "D:/.../vendor/mobile_auto/tools/adb/adb.exe",
  "nodes": [
    {
      "node_id": "bce697d2-…",
      "node_name": "本机执行节点",
      "status": "ok",
      "seen": 1,
      "created": 1,
      "updated": 0,
      "offlined": 0,
      "busy_skipped": [],
      "devices": [
        {
          "resource_key": "84cb2c4e",
          "status": "ready",
          "action": "created",
          "profile": {
            "id": "…",
            "name": "Redmi 25102RKBEC / Android 17 / 1200x2608",
            "created": true
          }
        }
      ]
    }
  ]
}
```

错误：

| HTTP | code | 场景 |
| --- | --- | --- |
| 404 | `not_found` | `project_id` / `node_id` 不存在 |
| 503 | `adb_unavailable` | adb 二进制缺失或不可执行（details 带期望路径） |
| 502 | `adb_probe_failed` | adb 执行失败/超时（details 带 stderr 尾部） |

**部分成功不报错**：某个节点 unreachable 时整体仍 200，该节点 `status: "unreachable"`。
理由：一次同步里一个节点挂了不该让其他节点的结果全部丢弃。

### 4.2 `GET /api/v1/resources`（增强）

新增可选 `project_id`；响应每条新增 `node_id`、`last_seen_at`。

`last_seen_at` 已在 `api-design.md:82` 的契约里，但库里**没有这一列**
（实测 `execution_resources` 10 列，无 `last_seen_at` / `updated_at`）。

### 4.3 `GET /api/v1/projects`（新增）

```json
{ "items": [ { "id": "…", "code": "testdock-demo", "name": "星河 Demo",
               "archived_at": null } ], "total": 1 }
```

## 5. 数据变更

### 5.1 迁移 0002

| # | 变更 | 理由 |
| --- | --- | --- |
| G4 | `execution_resources.last_seen_at TIMESTAMPTZ NULL` | `api-design.md:82` 已承诺该字段；没有它无法区分"从未同步过"与"3 天前还在" |
| — | 索引 `(project_id, status)` 已存在（`resources_ready`） | 无需新增 |

> `data-model.md` §5 声明"唯一允许的平台新增"是 G1–G3。G4 需要评审确认后
> 补进那张表，否则违反既有约定。**这是本方案唯一需要签字的 schema 变更。**
>
> **签字记录**：✅ G4 加列已批准 —— 评审人 dev，2026-10-27。
> `data-model.md` §5 已同步补入 G4 行，表头由"三处"改为"四处"，
> 风险 R1 随之关闭。

不加列的话，退化方案是把 `last_seen_at` 塞进 `execution_nodes.capabilities` 或
不提供该字段——前者语义错位，后者破坏已公布的 API 契约，都不推荐。

### 5.2 不新增表

"本机执行节点"复用 `execution_nodes`；"未识别设备"档案复用 `resource_profiles`。
`(project_id, name)` 唯一索引保证节点 upsert 幂等。

## 6. 实施拆分

| 步骤 | 内容 | 依赖 | 验收 |
| --- | --- | --- | --- |
| T1 | `conftest.py` 去默认值 + `pytest_configure` 起临时实例；`drop_project` 修外键顺序 | — | 全量测试数不减少（≥209）；测试跑完开发库行数不变 |
| T2 | 迁移 0002 加 `last_seen_at` | G4 已签字（2026-10-27），依赖已满足 | `alembic upgrade head` / `downgrade` 往返幂等 |
| T3 | `integrations/devices.py`：adb 解析 + 特征探测（纯 subprocess） | D1 | 单测覆盖 `adb devices -l` 三种状态解析；`test_no_vendor_import` 保持绿 |
| T4 | `domain/profiles.py` 增 `spec_from_probe()` + `fingerprint_for()` | T3 | 真机 spec → `android-17|1200x2608|25102rkbec` |
| T5 | `POST /resources/sync` 路由与事务 | T2–T4 | 见 §7 |
| T6 | `GET /resources?project_id=` + `GET /projects` | T2 | 传不存在项目返回 404 |
| T7 | 前端：设备页 `project` 维度 + 同步按钮 + `last_seen_at` 列 | T5, T6 | 浏览器实跑 |
| T8 | 回归测试：跨项目隔离、offline 收敛、busy 跳过、adb 缺失 | T5 | 新增用例全绿 |

**顺序理由**：T1 必须最先做，否则 T5 的集成测试写进开发库，一边验证一边污染。

## 7. 验收标准

**功能**

1. 插上真机 → `POST /resources/sync` → `GET /resources` 出现该 serial，
   `status=ready`，`profile` 非空，`last_seen_at` 为本次时间。
2. 同一台设备再 sync 一次：`created=0, updated=1`，不产生重复档案
   （`uq_resource_profiles_project_id_platform_fingerprint` 兜底）。
3. 拔掉设备 → sync → `status=offline`，行仍在，历史 `test_runs` 不受影响。
4. 未授权设备 → `status=unauthorized`，`profile` 是"未识别设备"档案；
   授权后再 sync → 档案升级为真实档案。
5. 设备被 run 占用期间拔掉 → sync 后 `status` 不变，出现在 `busy_skipped`。
6. `GET /resources?project_id=<其他项目>` 不返回本项目设备；不存在的 id 返回 404。
7. 用真机 serial 建调试会话成功（不再是 404）。

**数据纪律（回归断言）**

8. sync 从不 `DELETE FROM execution_resources`（代码审查 + 测试断言行数不减）。
9. 档案指纹符合 `ck_resource_profiles_fingerprint_hex64`（64 位小写十六进制）。
10. `resource_profiles.spec` 始终是 JSON object（`ck_resource_profiles_spec_object`）。
11. sync 与 dispatcher 并发：设备被 `FOR UPDATE SKIP LOCKED` 领走时，
    sync 不得把它的 `status` 从 `ready` 改成别的（要么跳过，要么等锁）。

**测试基础设施**

12. 未设 `TESTDOCK_TEST_DATABASE_URL` 时，测试全部跑在临时实例上；
    跑前跑后 `127.0.0.1:55432/testdock` 的 `execution_resources` 行数不变。
13. 测试数量与当前持平（209 后端），无新增 skip。

**前端**

14. 设备页显示真机、档案名、最后在线时间；点"调试"能打开抽屉。
15. 空池时仍显示 `Empty` 空态，不编造占位数据。

## 8. 风险与未决项

| # | 风险 | 影响 | 处置 |
| --- | --- | --- | --- |
| R1 | **G4 加列违反 `data-model.md` §5 的"仅三处"约定** | ~~需评审签字~~ | ✅ 已解决：2026-10-27 签字批准（dev），G4 已补入 `data-model.md` §5 |
| R2 | `pytest_configure` 起实例让每次跑测试变慢 ~10–20s | 开发体验 | 可接受；如需加速可保留 `TESTDOCK_TEST_DATABASE_URL` 显式复用 |
| R3 | adb `devices -l` 在未授权设备上读不到 model，档案只能是"未识别" | 首次授权前档案名难看 | 授权后自动升级；文档说明 |
| R4 | 拔掉的设备永久留 `offline`，池子会越长越大 | 长期运维 | 本期不做清理；后续需求可参考 STF/atxserver2 的"管理端归档"形态（§10.2 第 6 条） |
| R5 | 只给 `/resources` 加项目过滤，`/overview` 仍算全库 | 口径分裂 | 明确列为 P1，不能长期停在 P0 |
| R6 | `seed_demo.py` 的档案缺 `model`，永远匹配不上真机 | 演示数据与真机档案并存 | 本期不改；建议后续清理 seed 的假设备 |
| R7 | adb 需要设备端授权，无人值守环境无法自动完成 | 首次接入需人工点手机 | 文档写明；`unauthorized` 状态本身就是给用户看的提示 |
| R8 | 未验证：多节点聚合只有本机一个真实节点，远端路径无数据可测 | 设计可能过度 | 接口形态先定，实现保持最简；等真有多节点再补 |

## 9. 明确不做的事

- 不修改 `vendor/**` 任何文件（§5.2 只读纪律）。
- 不在 `server/app/**` 顶层 import vendor 包。
- 不删除 `execution_resources` 任何行。
- 不改 `alembic/versions/0001_initial.py`。
- 不动 `seed_demo.py` 的数据（R6 只记录）。
- 不做 `readiness` 端点、不做定时同步、不做远端 agent。

## 10. 开源方案调研（2026-10-27）

> 调研范围：GitHub 上与"真机接入设备池 + 在线状态维护 + 多节点同步"同域的项目。
> 结论先行：**没有可直接搬用的方案**——它们都是自带前端/鉴权/转码栈的完整产品，
> 而本平台已有自己的 lease、调度与前端。但"设备上下线怎么感知、多节点怎么建模"
> 这两个核心问题在所有活跃项目里都已解决且路径一致，本方案的接口契约与它们
> 收敛的结果对得上，可以直接借鉴其演进方向。

### 10.1 同域项目一览

活跃度取自 2026-10-27 的 GitHub API（`gh api repos/<repo>`）。

| 项目 | 星标 / 活跃度 | 定位 | 对本方案的价值 |
| --- | --- | --- | --- |
| [DeviceFarmer/stf](https://github.com/DeviceFarmer/stf)（STF 的维护中 fork） | 4.6k★，2026-10 仍在提交 | 浏览器控制安卓设备的完整设备农场 | 设备即插即显、`unauthorized`/`offline` 状态口径、设备预约（group）模型 |
| [SonicCloudOrg/sonic-server](https://github.com/SonicCloudOrg/sonic-server) + [sonic-agent](https://github.com/SonicCloudOrg/sonic-agent) | 2.2k★ / 1.7k★，活跃 | 云真机平台：后端 + 每机常驻 agent | 「每台机器一个常驻 agent 上报设备」的多节点形态 |
| [openatx/atxserver2](https://github.com/openatx/atxserver2) | 1.4k★，README 已声明停止开发 | 设备管理服务 + android provider | provider 上报模型可参考；**已弃坑，不可作为依赖** |
| [AppiumTestDistribution/appium-device-farm](https://github.com/AppiumTestDistribution/appium-device-farm) | 656★，活跃 | Appium 2.0 插件，管理设备分配 | 设备排队/租约语义与本项目 lease 模型同型 |
| [shamanec/GADS](https://github.com/shamanec/GADS) | 402★，活跃 | 远程控制 + Appium 的设备网格 | node 注册与设备汇总 |
| [agoda-com/android-farm](https://github.com/agoda-com/android-farm) | 178★ | USB + 模拟器设备农场 | 小体量参考 |

### 10.2 借鉴点（按本方案的设计决策对号入座）

1. **D2/D4 的上下线感知：轮询是 P0 起步，`track-devices` 是终态。**
   STF 不轮询 `adb devices`：其底层 adb 库 [adbkit](https://github.com/DeviceFarmer/adbkit)
   走 adb 协议的 `host:track-devices`——一条持久连接，设备插拔/状态变化时 adb
   server **主动推送**事件（add/remove/change），拔线到 offline 是秒级。
   本期手动 `POST /resources/sync`（轮询 `adb devices -l`）作为 P0 正确——无常驻
   进程、实现最简；但 P2 做定时化时应直接上 `adb track-devices` 常驻监听
   （Python 侧 `adbutils.track_devices()` 已封装），不要轮询。这不违反 D1：
   D1 约束的是 API 进程不 import vendor 包，监听器可以是独立小进程。

2. **多节点模型：所有活跃项目收敛到同一形态。**
   STF（provider）、Sonic（agent）、GADS（node）都是"每台机器一个常驻进程，
   向 server 注册并上报本机设备；server 失去节点 → 该节点设备置 offline"。
   这印证 D2 的两个契约：①按节点聚合；②节点 unreachable ≠ 设备 offline
   （server 不替 agent 扫设备）。atxserver2 的演进也印证了这一点：它最终
   同样从 server 端直管转向 provider 上报。本期"本机执行节点"就是该模型的
   退化形态（agent 与 server 同进程），将来加远端 agent 不用改契约。

3. **状态口径无冲突。**
   STF 的设备状态（connected / offline-unavailable / unauthorized / unplugged）
   与 D4 的 adb→`execution_resources` 映射一一对应：`draining` 即 STF 的
   "unavailable（USB 接触不良等，不可调度但不谎报离线）"。

4. **占用中的设备不许动状态是业界一致做法。**
   appium-device-farm 的设备排队/占用释放、STF 的 group 预约（起止时间绑定
   设备组）与本项目 lease + fencing（G2）同型，确认 D4"有未释放租约的设备
   sync 不改 status、只记 `busy_skipped`"是对的。

5. **D6 的临时测试实例有成熟先例。**
   [testcontainers-python](https://github.com/testcontainers/testcontainers-python)
   （2.3k★）与 [dbfixtures/pytest-postgresql](https://github.com/dbfixtures/pytest-postgresql)
   （532★）都是"每次测试会话起临时 Postgres、结束即弃"，与本方案
   `pytest_configure` 起临时实例同型——不是孤例，无需担心做法怪异难维护。

6. **R4（僵尸 offline 设备）有现成形态可抄。**
   STF/atxserver2 都保留设备历史行，由管理端提供手动移除/归档入口，而非定时
   删行——与 D4"永不删行"一致。R4 的后续需求按"管理端归档"做即可，届时另议。

### 10.3 明确不采纳的

- **引入 STF / Sonic 作为平台组件**：它们是完整产品（自带前端、鉴权、屏幕
  转码栈），嵌进来等于再造一个平台；STF 还是 Node.js 技术栈，与本仓库
  Python 后端不兼容。只借鉴模型，不引依赖。
- **依赖 atxserver2**：README 已声明停止开发，仅作模型参考。
- **server 直连远端节点的 adb server**（`adb -H` / TCP adb）：活跃方案全部
  走 agent 上报而非 server 直连远端 adb；D2"探测不到的节点不扫、不 offline"
  的决策与此一致。
