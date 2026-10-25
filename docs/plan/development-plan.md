# TestDock Auto · 平台开发方案 v1（详细方案，待评审）

> 依据：`docs/platform-prototype/`（原型 4 份文档）+ 只读盘点（`docs/plan-input/mobile-auto-capability.md` 536 行、`docs/plan-input/mobile-perf-capability.md` 345 行、`docs/plan-input/prototype-ui-spec.md` 492 行、`docs/plan/research/*`）。
> 边界：**不改动** `D:\workspace\claudecode-test\moblie-auto` 与 `D:\workspace\claudecode-test\moblie-xn`；只把核心能力**复制**进本仓库并做适配。
> 本轮交付：方案文档（不含实现代码）。评审通过后按 §11 分期实施。

## 0. 文档地图

| 文档 | 内容 |
| --- | --- |
| `docs/plan/development-plan.md`（本文） | 目标、架构、选型、核心语义、分期与验收、风险、工时 |
| `docs/plan/data-model.md` | 24 表落地策略、Alembic 迁移、CHECK/唯一索引与后端校验映射 |
| `docs/plan/api-design.md` | REST/WS 端点、请求响应、错误码、幂等与并发语义 |
| `docs/plan/vendor-integration.md` | 复制清单+sha256 校验、适配层、lease 注入、viewer 代理、许可 |
| `docs/plan/frontend-spec.md` | 9 页面 → 组件 → API 矩阵、与原型的行为差异、验收用例 |

## 1. 目标与范围

### 1.1 一句话目标

把两个单机能力包（`mobile_auto` UI 自动化、`mobile_perf` 性能采集）升格为有数据库、有任务模型、有共享设备池、有服务端强制语义的 Web 平台：浏览器里配置任务 → 平台分配设备并独占 → 真机执行真实 pytest / 真实性能采集 → 结果、证据、三态门禁结论入库可追溯。UI 与交互沿用原型，数据换成真实数据。

### 1.2 首期做什么（In Scope）

1. 单一工作空间的多端项目管理（Android 真执行；iOS/Web 仅配置草稿）。
2. 任务 + 不可变修订（`test_tasks` + `task_revisions`，草稿→验证）。
3. 运行生命周期 7 状态 + `outcome` 三态严格分离。
4. 共享设备池：DB 权威租约 + `fencing_token`，同设备同时刻只一个持有者。
5. 真实执行：UI = 宿主 `pytest` + vendor 插件（失败证据自动归档）；性能 = vendor `PerfKit.collect()`；联动 = 一 run 两组件。
6. 证据与报告：vendor 原生产物原样落盘 + sha256 入库；平台汇总报告为查询视图+导出接口（不建 `reports` 表，与原型一致）。
7. 三态门禁：基线按设备档案隔离，`original` 唯一，`reanalysis` 试算不覆盖历史。
8. 设备调试：真实预览(WS)、冻结快照、层级树、定位验证、模板版本，复用 vendor `viewer`（反向代理接入，不改其代码）。
9. 9 个前端页面（工作台/项目与应用/UI 自动化/性能测试/执行资源/任务中心/报告中心/接入说明/数据设计）。

### 1.3 明确不做（Not in Scope，首期）

| 不做 | 原因 | 何时 |
| --- | --- | --- |
| 多租户 / 组织 / OIDC | 原型只有演示账号；DB 仅留 `identity_issuer/subject` | 二期 |
| 细粒度 RBAC | 首期单工作空间，`project_members.role` 只落库不鉴权 | 二期 |
| Web / iOS 真实执行 | 无适配器 | 三期 |
| 跨机器设备调度 / Agent 网关 | 两个 vendor 的租约、scrcpy、adb 全部不可跨机器 | 三期（需先重写租约层） |
| 实时性能推送（边采边看） | vendor 无此接口；`mark()` 也无回调 hook | 二期评估 |
| 对象存储 / S3 | 首期文件系统 + sha256 足够 | 二期 |
| 修改 vendor 源码 | 明确禁止；适配全在 `server/app/integrations/` 与 `runner_pkg/` | 永不（如需走 fork 分支并记录） |
| SoloPi 源码改造 / 重打包 | 直接用 `dist/solopi` 的 debug apk | — |
| 移动端 H5 适配 | 原型是桌面端 | — |

### 1.4 成功判据（验收口径）

1. 真机接入后，从 UI 建任务 → 运行 → 看到通过/失败与失败证据，全程无需命令行（命令行仅部署/排障）。
2. 同设备并发提交两个运行：第二个必须排队或拒绝，绝不并发访问设备（并发测试可证）。
3. 性能缺样本时结论必须是 `not_tested` 且带 `reason_code`；不得 passed，不得把缺失写成 0。
4. 任一运行可回答：哪个修订、哪台设备、什么版本、原始报告在哪、证据 sha256 多少。
5. vendor 回归测试（unit/contract/integration）在宿主 100% 通过，`vendor/**` 与源仓库逐字节一致。

## 2. 关键前提与已核实事实

| # | 事实 | 证据 | 对方案的影响 |
| --- | --- | --- | --- |
| F1 | 两个 vendor 都是单机单设备、进程内能力包，Python ≥3.12 | `mobile_auto/__init__.py:9-31`、`mobile_perf/pyproject.toml`（`dependencies=[]`） | 平台首期必须与设备同机；执行器是「同机子进程」而非远程 Agent |
| F2 | `mobile_auto` 租约=Windows 文件区域锁（`msvcrt.locking`），非 Windows 直接抛 `DeviceUnavailable` | `core/lease.py:79`、`:72` | 平台租约必须自建（DB 权威）；vendor 锁只作本机兜底 |
| F3 | `DeviceSession` / `acquire_from_pool` 支持注入 `lease_factory` | `session.py:174`、`pool.py:31` | 未来上 Linux 容器可在适配层注入 fcntl 实现，无需改 vendor |
| F4 | `viewer` 硬编码只允许 `127.0.0.1/localhost/::1` 的 Host/Origin，bind 回环，无鉴权 | `viewer/app.py:1485,1490`、`server.py:69` | 平台用同机反向代理接入（代理侧伪造 Host/Origin + 平台鉴权） |
| F5 | `viewer` 快照库纯内存（重启即失） | `viewer/store.py`（MAX_LIVE_SNAPSHOTS=3 等） | 冻结快照只作调试态；需留存转 `artifacts` 落盘 |
| F6 | 取消结局 7 种，`unknown`=结果不可信 | `session.py:487,499` | 平台映射 `unknown → errored`（outcome NULL），不得猜 passed/failed |
| F7 | 性能采集本体在手机侧：SoloPi APK（`com.alipay.hulu`）经 Harness 子进程执行；Python 只做编排/拉取/聚合/判定 | `solo.py`（ADR-0002 边界）、`kit.py:1011,1078` | 性能任务必须真机 + adb + SoloPi + 无障碍真实 Bound；执行器直接调 `PerfKit.collect()` |
| F8 | 判定是纯函数 `judge.judge(report, spec)`，判 median，三态，默认样本下限 10 | `judge.py:93`、`:20` | 直接复用，平台不重写阈值逻辑 |
| F9 | vendor 指标缺失无 NULL 语义：样本不进序列 + `notTested/notTestedReason` | `metrics.py:39-162`、`judge.py` | 平台适配层转成 `value NULL + missing_reason`（DB CHECK `schema.sql:548`） |
| F10 | `not_tested` 原因是自由中文文本；基线可比性只比 `deviceProfile` 字符串 | `judge.py`、`kit._resolve_profile`（跨档案 `ProfileMismatchError`） | 平台必须归纳成 `reason_code` 枚举，并规范化 deviceProfile 字符串，否则判定恒 not_tested |
| F11 | `mobile_perf.gate` 在非 Windows 完全 passthrough（不加锁）；且 `collect` 数分钟窗口内不持锁（每条设备命令各借一次） | `gate.py:140`、`kit.py` `_borrowed` | 长租约只能平台自建；不能依赖 vendor gate 保证互斥 |
| F12 | `PerfStore`=SQLite WAL 6 表，无 CREATE INDEX、无 user_version/迁移 | `store.py` `_SCHEMA` | 平台不用 PerfStore 作权威（用 PG）；必要时仅作本地缓存 |
| F13 | 性能产物 `runs/<runId>/{artifacts/*.csv(gb18030), meta.json, report.json, report.html}`；`report.html` 内嵌 echarts ≈1MB 零外链；`report.json` 顶层 19 键（schemaVersion=1…integrity） | `report.py:141`、实测 98,850B / 1,087,797B | 原样归档即可离线打开；`artifacts` 字段是采集机绝对路径 → 归档时改写为相对 URI |
| F14 | 原型没有后端，状态存 `localStorage`，「运行」由按钮推进 | `index.html:103,250` | 原型只作 UI 规格；`mutateTask` 的「推进」不实现 |
| F15 | 原型 DB 草案 = 24 表 / 231 字段 / 56 外键（PG17 语法），未建库 | `schema.sql:1-7,730` | 作为 Alembic `0001` 输入，需核对可执行性（见 data-model.md） |
| F16 | 本机：无 PostgreSQL、无 docker；EDB portable PG17.6（330MB）HTTP 200 可下 | 实测 | 开发库用 EDB 便携版，脚本一键起停（§4.4） |
| F17 | DSH 沙箱内 pytest 无法运行（`%TEMP%` `WinError 5`，`--basetemp` 亦失败） | 实测，见 §12.1 | vendor 回归与平台 DB 测试必须在宿主 shell/CI 跑；CI 注入 `TMP/TEMP/HOME/--basetemp` |
| F18 | 本机已装 fastapi/uvicorn/sqlalchemy/pydantic/httpx/pytest/websockets/PIL/cv2/numpy/adbutils/uiautomator2；缺 alembic、psycopg | 实测 | 补 2 个依赖，镜像可取 |

### 2.1 三条必须记住的物理限制

- 限制 A：平台进程与 Android 设备必须同一台机器（ADB + scrcpy + 文件锁 + SoloPi harness）。跨机器唯一路径是重写租约与通道，属三期。
- 限制 B：同一台手机同一时刻只能有一个执行者。且 vendor 的两套 gate 都不足以保证（F2 仅 Windows、F11 采集窗口不持锁）→ 必须由平台 DB 租约强制。
- 限制 C：SoloPi 采集前提是真机已 `adb install` 该 debug apk 且无障碍服务真实 Bound；这是部署前置，平台要在设备页做成「就绪检查」（复用 `keeper.Keeper.run()`）。

## 3. 总体架构

### 3.1 部署形态（首期：单机三进程）

```
┌──────────────────── 浏览器 ────────────────────┐
│ web/ (Vite+React+TS)  →  http://127.0.0.1:8000 │
└────────┬───────────────────────────────────────┘
         │ REST /api/v1/*   +   WS /ws/*
┌────────▼───────────────────────────────────────────────────┐
│ api 进程：FastAPI + SQLAlchemy(async) + Alembic            │
│  · 领域服务: tasks/revisions/runs/leases/gates/artifacts   │
│  · 调度器: 短事务领取 queued，分配设备，发执行指令          │
│  · 反代: /api/v1/debug/* → 本机 vendor viewer              │
│  · 静态托管: web/dist                                      │
└──────┬──────────────────────────┬──────────────────────────┘
       │ SQL (psycopg3)           │ 子进程 spawn（同机）
┌──────▼─────────┐   ┌───────────▼────────────────────────────┐
│ PostgreSQL 17  │   │ runner 子进程（每运行一个）             │
│ 24 张表        │   │  · ui:   pytest + mobile_auto 插件      │
│ artifacts 元数据│   │  · perf: mobile_perf.PerfKit.collect()  │
└────────────────┘   │  · debug: vendor viewer(127.0.0.1:随机) │
                     │  统一: 平台租约(DB) + vendor 本机锁     │
                     └───────────┬────────────────────────────┘
                                 │ adb / scrcpy
                           ┌─────▼─────┐
                           │ Android 真机│
                           └───────────┘
文件系统：data/artifacts/<project>/<run_id>/…（vendor 原生产物原样落盘）
```

为什么「api 进程 + 每运行一个 runner 子进程」而不是 api 直接 import vendor：

1. vendor `DeviceSession` 单 worker 串行模型 + pytest 会动 `sys.modules`/信号，与 FastAPI 事件循环同进程互相拖死。
2. 子进程崩溃（真机断连、scrcpy 段错误、SoloPi harness 崩）不传染 api；超时可 `kill` 兜底。
3. 仍满足限制 A/B（同机），且进程天然是 fencing 边界（进程即执行身份）。
4. 未来换远程 Agent 只替换「怎么启动进程」，协议不变。

### 3.2 三条核心数据流

流 1：UI 自动化运行

```
POST /runs (request_key) → runs.state=queued
 → 调度器短事务: SELECT … FOR UPDATE SKIP LOCKED → 绑定 resource_id
 → bump fence_counter → INSERT resource_leases(fencing_token) → state=dispatching
 → spawn runner: python -m testdock_runner ui --run-id … --serial … --suite …
     runner: vendor DeviceLease.acquire（本机兜底）→ DeviceSession.start()
           → pytest 跑用例（-p mobile_auto.evidence.pytest_plugin --mobile-devices S --mobile-evidence）
           → 产出 junit.xml + artifacts/evidence/<id>/ + run-manifest.jsonl
 → 退出码+结果 JSON → state=finalizing → 归档 artifacts(sha256)
 → 判定 outcome（passed/failed）→ state=completed/errored → 释放租约
```

流 2：性能采集运行

```
POST /runs → queued → dispatching（同上租约）
 → spawn runner: python -m testdock_runner perf --run-id … --serial … --package … --items CPU,Memory --duration 300
     runner: Keeper.run() 就绪检查 → PerfKit(gate=PlatformGate).collect(target, items, duration_s)
           → 产出 run-YYYYMMDD-HHMMSS-xxxx/{report.json, report.html, *.csv, meta.json}
 → 归档: report.json 作为 artifact(kind=perf_report_native，不可变)
 → metric_summaries 批量写入（缺失=NULL+missing_reason）
 → judge(report, JudgeSpec) → gate_evaluations(mode=original, verdict, reason_code)
 → state=completed, outcome=verdict（not_tested 也属 completed，不是 errored）
```

流 3：设备调试会话

```
POST /debug-sessions {serial, purpose} → 获取租约（run_id NULL、debug_session_id 非空）
 → spawn runner: python -m testdock_runner debug --serial … --port 0
     runner 启动 vendor start_debug_viewer()（127.0.0.1:随机）→ 回传 base_url
 → debug_sessions.state=active, base_url 入库
浏览器 → 平台 /api/v1/debug/{serial}/preview (WS) → 代理到 base_url（伪造 Host/Origin）
DELETE /debug-sessions/{id} → 停 runner → 释放租约
```

### 3.3 后端模块划分

| 模块 | 职责 | 关键文件 |
| --- | --- | --- |
| `app/api` | 路由、依赖注入、错误信封（`code/message/request_id`，与 vendor viewer 一致） | `routers/*.py` |
| `app/domain` | 领域服务与唯一状态转换入口（禁止路由层直写 `state`） | `runs.py`、`leases.py`、`gates.py`、`artifacts.py` |
| `app/db` | ORM 模型、会话、迁移 | `models.py`、`alembic/versions/0001_initial.py` |
| `app/runner` | 子进程协议、超时/取消/回收、日志落盘 | `spawn.py`、`protocol.py`、`manager.py` |
| `app/integrations` | 与 vendor 的唯一接触面 | `mobile_auto.py`、`mobile_perf.py`、`viewer_proxy.py`、`leases.py` |
| `app/scheduler` | 领取、心跳、陈旧租约回收、告警计算 | `dispatcher.py`、`reconciler.py` |
| `app/ws` | 运行状态推送、调试预览转发 | `live.py` |
| `testdock_runner`（独立包） | 子进程入口；只有它 import vendor | `__main__.py`、`ui_job.py`、`perf_job.py`、`debug_job.py` |

> 规则：`app/api`、`app/domain` 禁止 `import mobile_auto` / `import mobile_perf`；用测试守住（§12.3）。

## 4. 技术选型与仓库结构

### 4.1 选型表（含被否方案）

| 层 | 选择 | 理由 | 否掉的方案 |
| --- | --- | --- | --- |
| 数据库 | PostgreSQL 17 | `schema.sql` 已用 PG 语法：跨列 CHECK、部分唯一索引、`FOR UPDATE SKIP LOCKED`、JSONB | SQLite（无部分唯一索引/无 SKIP LOCKED，把强制语义变成约定） |
| 后端 | FastAPI + SQLAlchemy 2.0 async + Alembic + psycopg3 | 已装前两者；vendor 是 async；Alembic 把 `schema.sql` 变成有版本号的迁移 | Django（重、异步弱）、Flask（缺 OpenAPI/注入） |
| 前端 | Vite + React 18 + TS + TanStack Query + zustand | 原型是 innerHTML 全量重写式 vanilla，接 API 会失控；React 可拆 9 页并复用原型 CSS | ①继续 vanilla 单文件（无状态管理/无类型/难测试）②Vue |
| 图表 | 复用原型手绘 SVG `polyline` 手法 | 性能页只需归档曲线 + 基线虚线；避免引 echarts 与 vendor `report.html` 重复 | echarts（vendor 侧已有，平台侧不必） |
| 样式 | 从 `index.html` 抽 `tokens.css` + CSS Modules | 视觉必须与原型一致 | tailwind（要重写全部视觉，与「按原型开发」冲突） |
| 执行 | 同机 `asyncio.create_subprocess_exec`，每运行一 runner | 见 §3.1 | 线程池（崩溃传染）、Celery（单机无必要） |
| 部署 | `uvicorn` 单进程 + `scripts/dev_up.sh`（生产可用 nssm/systemd） | 首期单机单用户 | docker-compose（本机无 docker） |

### 4.2 仓库结构（目标态）

```
testplat-auto/
├─ docs/
│  ├─ platform-prototype/        # 原型（只读）
│  └─ plan/                      # 本方案（5 份）
├─ vendor/                       # 只读能力包（见 vendor-integration.md）
│  ├─ VENDOR.lock.json           # 源路径/git 提交/每文件 sha256/复制范围
│  ├─ mobile_auto/               # 源: moblie-auto/src/mobile_auto + tools/adb + docs
│  └─ mobile_perf/               # 源: moblie-xn/src/mobile_perf + dist/solopi
├─ server/
│  ├─ pyproject.toml             # testdock-server
│  ├─ app/                       # FastAPI（§3.3）
│  ├─ runner_pkg/testdock_runner/# 子进程入口
│  ├─ alembic/                   # env.py + versions/0001_initial.py
│  └─ tests/
├─ web/
│  ├─ src/pages/                 # 9 个页面
│  ├─ src/components/            # Badge/Table/Dialog/Drawer/Timeline/…
│  ├─ src/styles/tokens.css      # 从原型抽取
│  └─ src/api/                   # 与 api-design.md 一一对应
├─ scripts/
│  ├─ vendor_sync.py             # 复制 + 生成/校验 VENDOR.lock.json
│  ├─ pg_portable_up.sh|.ps1     # EDB 便携版初始化/起停
│  ├─ dev_up.sh                  # 起 PG、迁移、起 api、起 web dev
│  ├─ run_vendor_tests.sh        # 宿主跑 vendor 回归（沙箱内禁止）
│  └─ seed_demo.py               # 演示种子（对齐原型）
├─ data/                         # 运行时（git 忽略）
│  ├─ artifacts/<project>/<run_id>/
│  ├─ runner-logs/<run_id>.log
│  ├─ tmp/                       # TMP/TEMP/HOME 注入目标（F17）
│  └─ pgdata/
└─ .github/workflows/ci.yml      # PG service + pytest + web build（宿主等价环境）
```

### 4.3 依赖清单（新增）

| 依赖 | 版本 | 用途 | 现状 |
| --- | --- | --- | --- |
| `fastapi`/`uvicorn`/`sqlalchemy`/`pydantic`/`httpx`/`websockets` | 已装 | 后端骨架 | 已有 |
| `alembic` | 1.20.1 | 迁移 | 未装（镜像可解析） |
| `psycopg[binary]` | 3.x | PG 驱动（async） | 未装（镜像可解析） |
| `python-multipart` | 最新 | 表单/上传 | 待装 |
| `pytest-asyncio`/`anyio` | 已装/兼容 | 平台测试 | 部分已有 |
| `node`/`npm` | v24.14/11.9 | 前端构建 | 已装 |
| `react`/`react-dom`/`react-router-dom`/`@tanstack/react-query`/`zustand`/`vite`/`typescript` | 最新 LTS | 前端 | 未装（`npm i`，走 npmmirror） |

### 4.4 开发/运行环境落地（含本机无 PG 的解法）

1. `scripts/pg_portable_setup.sh`：下载 EDB portable 17.6 zip（已核实 200）→ 解压 `.runtime/pg17` → `initdb -D data/pgdata -U testdock --auth=trust` → `pg_ctl start -o "-p 55432"` → `createdb testdock`。
2. 连接串：`TESTDOCK_DATABASE_URL=postgresql+psycopg://testdock@127.0.0.1:55432/testdock`（默认值写死在 `app/config.py`）。
3. 拿不到 PG 的环境首期不支持 SQLite 替代（D2 前提，见 §13 R1）。
4. vendor 安装：`pip install -e vendor/mobile_auto -e vendor/mobile_perf`（不改源码，仅可编辑安装），并注入 `TMP/TEMP/HOME → data/tmp`（F17）。
5. SoloPi 前置：`adb install -r vendor/mobile_perf/dist/solopi/SoloPi-selfbuild-debug.apk` + 手动开启无障碍；平台设备页用 `Keeper.run()` 做就绪检查并给出人话指引。

## 5. vendor 复制与适配边界

> 细节在 `docs/plan/vendor-integration.md`。此处为决策摘要。

### 5.1 复制什么（已定，约 26MB）

| 来源 | 复制 | 不复制 |
| --- | --- | --- |
| `moblie-auto/src/mobile_auto/**`（32 py/8097 行 + assets） | 是 | — |
| `moblie-auto/tools/adb/**`（9.2MB，`find_adb_binary` 优先用它） | 是 | — |
| `moblie-auto/tests/{unit,contract,integration,fixtures}` | 是（1.5M+32K+16K+1.6M） | `tests/device/**`（7.1M，需真机） |
| `moblie-auto/docs/{integration.md,validation.md}` | 是 | 其余 |
| `moblie-xn/src/mobile_perf/**`（21 py + assets 1008K） | 是 | — |
| `moblie-xn/dist/solopi/**`（7.7M，含 debug apk + platform-tools） | 是 | — |
| `moblie-xn/tests/{unit,contract,integration,fixtures}` | 是（304K/20K/16K/168K） | `tests/device/**` |
| — | — | SoloPi 源码 56M、`runs/` 5M、`docs/snapshots` 3.6M、`solopi-master.tar.gz` 17.8M、`__pycache__` |

### 5.2 只读纪律（硬规则）

1. `scripts/vendor_sync.py --check` 证明 `vendor/**` 与源仓库对应文件逐字节一致（sha256 清单）。
2. 平台永不写 `vendor/**`；改造只在 `server/app/integrations/` 与 `server/runner_pkg/`。
3. 需要的小修（如 Linux 租约）用注入：`DeviceSession(lease_factory=PortableLease)`（F3 已确认可行），不 patch vendor 文件。
4. 升级 vendor = `vendor_sync.py` + `run_vendor_tests.sh` + 平台集成测试，三步全绿才算完成。

### 5.3 适配层（4 个文件，全在 `server/app/integrations/`）

| 文件 | 职责 | 关键点 |
| --- | --- | --- |
| `mobile_auto.py` | 构造 `DeviceSession`/`MobileAdapter`/`MobileConfig`（`screenshot_source="u2"` 保证全分辨率取证）、`artifacts_dir` 指向 `data/artifacts/...` | 只被 runner 使用 |
| `mobile_perf.py` | 构造 `PerfKit(serial, adb_path, runs_dir, gate=PlatformGate)`；调 `collect()`；把 `report.json` 映射成 `metric_summaries` | `gate` 用平台租约适配；`notTested/notTestedReason` → `NULL+missing_reason`（F9） |
| `viewer_proxy.py` | 启停 vendor viewer 子进程；HTTP+WS 反代；伪造 `Host/Origin=127.0.0.1:<port>`；平台鉴权前置 | 不改 vendor 白名单（F4） |
| `leases.py` | `PlatformGate(DeviceGate)`：`borrow()` = 校验 DB token 仍属本 run → 再开 vendor `FileLockGate`（本机兜底）→ 两者都成功才进上下文 | 顺序与异常路径见 §7.1 |

## 6. 数据模型与迁移

> 字段级映射见 `docs/plan/data-model.md`。此处只给策略与首批使用范围。

### 6.1 迁移策略

1. `alembic/versions/0001_initial.py` = `schema.sql` 的 24 张表原样搬成迁移（表名/列名/CHECK/唯一索引/外键全保留）；生成后 `pg_dump --schema-only` 与 `schema.sql` 结构 diff，差异必须为零或记录在案。
   1a. 必须先处理独立评审的 4 个阻塞项（`docs/plan/research/schema-review.md`）：删掉 `schema.sql` L7/L730 的 `BEGIN/COMMIT`（否则破坏迁移原子性）、163 条匿名约束全部显式命名、补 `run_components.reason_code` 与 `not_tested` 原因约束、`GET /schema` 改为从 `schema.sql` 生成（单一真源）。详见 `data-model.md` §8。
2. 迁移不写业务数据；种子由 `scripts/seed_demo.py`（3 端应用、6 设备四态、4 套件、3 场景、2 基线）。
3. 之后每迭代一个新 revision，禁止改 `0001`。

### 6.2 首期真正用到的表（其余建表但空跑）

| 组 | 表 | 首期用途 |
| --- | --- | --- |
| 基础资产 | `projects`、`applications`、`environments`、`resource_profiles` | 单项目 + 三端应用 + staging + Android 档案 |
| 执行资源 | `execution_resources`、`resource_leases`、`debug_sessions` | 设备池、租约、调试会话 |
| 测试定义 | `test_tasks`、`task_revisions`、`suites`、`suite_versions`、`cases` | 任务 + 不可变修订 + pytest 收集的套件版本 |
| 任务运行 | `test_runs`、`run_components`、`case_results` | 运行、组件结果、用例结果 |
| 结果证据 | `artifacts`、`evidence` | 产物登记（sha256）、失败证据索引 |
| 性能质量 | `metric_summaries`、`baselines`、`gate_policies`、`gate_evaluations` | 指标、基线、策略、三态判定 |
| 治理追溯 | `audit_events`、`run_events`（以 schema 实际命名为准） | 状态迁移与关键动作审计 |

### 6.3 四条「DB 强制 + 后端也查」的约束

| 约束 | DB 表达 | 后端额外校验 |
| --- | --- | --- |
| 结论与状态互锁 | `(state='completed') = (outcome IS NOT NULL)`；终态才允许 `ended_at` | `transition()` 唯一入口，非法迁移 422 |
| 租约互斥 | 三个部分唯一索引 + `(run_id IS NOT NULL) <> (debug_session_id IS NOT NULL)` | 领取设备在同一事务内 `fence_counter+1 RETURNING` |
| 指标缺失 | `(value IS NULL) <> (missing_reason IS NULL)` | 适配层写 NULL 必带 `missing_reason`，禁 0.0（F9） |
| 门禁可解释 | `verdict <> 'not_tested' OR reason_code IS NOT NULL`；每组件最多一条 `original` | 试算走 `reanalysis`，绝不 UPDATE 原行 |

## 7. 核心语义实现（最关键一节）

### 7.1 设备租约 + fencing

获取（一个 DB 事务 + 一个本机动作）：

```sql
BEGIN;
SELECT id FROM execution_resources
 WHERE status='ready' AND last_seen_at > now() - interval '60 seconds'
   AND id NOT IN (SELECT resource_id FROM resource_leases WHERE released_at IS NULL)
 ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1;
UPDATE execution_resources SET fence_counter = fence_counter + 1
 WHERE id = :rid RETURNING fence_counter;
INSERT INTO resource_leases(resource_id, run_id, fencing_token, acquired_at, heartbeat_at)
VALUES (:rid, :run_id, :fence, now(), now());
COMMIT;   -- 之后 state=dispatching
```

本机兜底：runner 拿到任务后 `FileLockGate.borrow(serial)`。拿不到（别的机器/账号持有）→ 释放 DB 租约并标 `errored`，不许带病执行。

fencing 校验点（不做每次点击校验，成本不可接受）：runner 在 4 个边界 `GET /internal/runs/{id}/fence` 校验 token：①进 running 前 ②每个 `mark` 前 ③进 finalizing 前 ④写结果前。任一失配 → 停设备操作、丢结果、`state=errored`+`outcome=NULL`（对齐 F6 的 unknown）。

心跳与回收：runner 每 10s 写 `heartbeat_at`；`reconciler.py` 每 15s 扫 `heartbeat_at < now()-60s` → 置 `released_at`、`state=errored`、`run_events(reason='lease_expired')`。回收只释放 DB 行；本机锁随进程退出自然释放。

释放顺序（必须）：`runner 停止设备 → 释放 vendor 锁 → 标记 DB 租约`。反序会出现「DB 空闲但本机仍锁」（设备页 idle 但调试打不开）。

### 7.2 运行状态机（唯一入口 + 不可回退）

```
queued ─dispatch─► dispatching ─ack─► running ─finalize─► finalizing ─archive─► completed
   └── cancel ──┴──── cancel ─────┴──── cancel ─────────┘→ cancelled
   任何执行态遇 设备断连 / runner 崩溃 / fence 失配 / 超时 ──► errored
```

- `transition(run_id, expect_state, to_state, *, outcome=None, reason=None, actor)`：内部 `UPDATE … WHERE id AND state=:expect RETURNING *`，0 行即 409。
- 终态后不允许 UPDATE 覆盖；重跑 = 新 run + `parent_run_id`。
- `outcome` 只在 `completed` 非空；`errored/cancelled` 必须 NULL（DB CHECK 兜底）。
- 与 vendor 取消结局映射：`cancelled-queued/cancelled-before-send → cancelled`；`unknown → errored`；`failed → completed(outcome=failed)`；`completed/finished → completed(outcome 由断言/门禁定)`。

### 7.3 三态门禁（禁止压成二态）

- 判定只复用 vendor `judge.judge(report, JudgeSpec)`；`JudgeSpec` 由 `gate_policies` 行构造（memory<240 fail、cpu<35（warn/fail 可配）、fps≥50 fail、min_samples=10）。
- `gate_evaluations` 每次判定一行：`mode='original'`（每组件唯一）+ 多条 `reanalysis`。
- 不可比 = not_tested：`baseline.resource_profile_id != run.resource_profile_id`（或 deviceProfile 规范化后不等）→ not_tested + `reason_code='profile_mismatch'`（对齐原型 `perfVerdict` 第 1 步）。
- 样本不足 → not_tested + `reason_code='sample_count_below_minimum'`，保留实际 `sample_count`。
- reason_code 枚举平台自建（vendor 只给自由中文，F10）：`profile_mismatch / sample_count_below_minimum / metric_missing / device_degraded / gate_policy_missing / run_incomplete`，同时保留 vendor 原文到 `reason_text`。
- 前端必须展示三态与 reason；报告页同屏展示 `original` 与「试算结果」，并标注「试算不改写历史报告」。

### 7.4 证据不可变与两套报告并存

- 落盘：`data/artifacts/<project_id>/<run_id>/` 原样保存（`report.json`、`report.html`、`evidence/<16hex>/`、`*.csv`、`junit.xml`）。
- 入库：每文件一行 `artifacts`（`logical_key`、`kind`、`sha256`、`size_bytes`、`availability='available'`、`captured_at`）；finalize 阶段算 sha256 并读回校验。
- 两套报告：vendor 原生 `report.json`（19 键）作 artifact 原样保留；平台汇总报告由 API 现算返回（字段对齐原型 `exportReport`：`runId/hostRunId/status/verdict/thresholdsAtRun/reason/metricsSummary`），不建表、不可覆盖。
- `artifacts` 中的绝对路径（F13）在归档时改写为相对 `storage_uri`，避免换机后链接失效。
- `availability` 的 `missing/expired` 必须在 UI 可见，不能静默 404。

### 7.5 幂等与并发

- 创建运行：`request_key`（前端 UUID v4）→ `UNIQUE(project_id, request_key)`；重复提交返回既有 run。
- 领取设备：`FOR UPDATE SKIP LOCKED`（DB 级），不用「先查后改」。
- 配置保存：`test_tasks.lock_version` CAS，冲突 409 + 最新版本，前端提示「他人已更新」。
- 运行中禁改配置：runner 只用启动时的 `task_revision_id` 快照。

## 8. API 设计概要

> 完整契约在 `docs/plan/api-design.md`（含每个端点的请求体、响应体、错误码、鉴权、幂等语义）。本节给形状与决策。

### 8.1 通用约定

| 项 | 约定 |
| --- | --- |
| 基址 | `/api/v1`；前端与 api 同源（生产由 api 托管 `web/dist`），开发用 Vite proxy |
| 认证 | 首期无登录，服务只 bind `127.0.0.1`；写操作要求 `X-TestDock-Client: web` 头（防跨站表单）。二期接 OIDC 时只替换依赖项 |
| runner 通道 | 独立 `/internal/*`，要求 `X-Control-Token`（启动时生成写入 `data/control.token`，随 argv 传给 runner），api 重启轮换 token，旧 runner 立即失联即视为崩溃回收 |
| 错误信封 | `{"code":"lease_conflict","message":"…","request_id":"…","details":{}}`，与 vendor viewer 信封一致（`viewer/app.py:535-538`） |
| 分页 | `?limit=50&cursor=<opaque>`，响应 `{items:[], next_cursor}`；列表默认按 `created_at desc` |
| 幂等 | `POST /runs`、`POST /baselines` 接受 `request_key`（UUID），重复返回 200 + 原对象 |
| 时间 | 一律 UTC ISO8601；前端按浏览器时区显示（原型顶栏日期为固定串，需替换为真实时钟） |
| 枚举 | 全部走 §7 定义；前端不得把 `null outcome` 显示成失败 |

### 8.2 端点清单

| 分组 | 端点 | 说明 |
| --- | --- | --- |
| 概览 | `GET /overview?platform=` | 工作台 4 卡数字 + 最近运行 6 条 + 资源前 3 台 + 告警（由真实数据算，替换原型硬编码 2 条） |
| 项目应用 | `GET /projects`、`GET /applications?platform=`、`GET /applications/{id}`、`GET /resource-profiles` | 项目与应用页 |
| 资源 | `GET /resources?status=`、`GET /resources/{id}`、`POST /resources/sync`、`POST /resources/{id}/readiness` | `sync` 调 `adb devices` 更新 `status`；`readiness` 跑 `Keeper.run()` 返回无障碍/电池/时钟检查项 |
| 任务 | `GET /tasks?module=&status=&q=`、`POST /tasks`、`GET /tasks/{id}`、`PATCH /tasks/{id}`、`POST /tasks/{id}/validate`、`POST /tasks/{id}/archive`、`GET /tasks/{id}/revisions` | `POST` 一次创建 `test_tasks`+`task_revisions(draft)`；`validate` 把 readiness 置 `validated`（要求 build/suite_version 已绑定，`schema.sql:294`） |
| 套件 | `GET /suites`、`GET /suites/{id}/versions`、`POST /suites/{id}/discover` | `discover` 在宿主跑 `pytest --collect-only -q` 生成不可变 `suite_versions` + `cases` |
| 运行 | `POST /runs`、`GET /runs?state=&module=&task_id=`、`GET /runs/{id}`、`POST /runs/{id}/cancel`、`GET /runs/{id}/events` | 创建即 `queued`；`cancel` 只对非终态有效 |
| 结果 | `GET /runs/{id}/components`、`GET /runs/{id}/cases`、`GET /runs/{id}/artifacts`、`GET /runs/{id}/artifacts/{aid}/download`、`GET /runs/{id}/report`、`GET /runs/{id}/report/export` | `report` 现算平台汇总（对齐原型 `exportReport` 字段）；`export` 返回同结构 JSON（不落库） |
| 性能 | `GET /runs/{id}/metrics`、`GET /analyses?run_id=`、`GET /analyses?task_id=` | `analyses` 返回 verdict+checks+指标+趋势序列+上下文+试算，直接喂性能页 |
| 基线 | `GET /baselines?application_id=&resource_profile_id=`、`POST /baselines` | 从某 run 建基线（同一 run 同档案唯一） |
| 门禁 | `GET /gate-policies`、`PUT /gate-policies/{id}`、`POST /runs/{id}/gate-evaluations` | 后者建 `reanalysis` 试算，**永不改 original** |
| 调试 | `POST /debug-sessions`、`GET /debug-sessions`、`DELETE /debug-sessions/{id}`、`WS /ws/debug/{sid}`、`POST /debug-sessions/{id}/snapshots`、`GET /debug-sessions/{id}/snapshots/{nid}/image` | 反代 vendor viewer（F4） |
| 定位/模板 | `POST /locators/validate`、`GET /templates`、`POST /templates`、`PUT /templates/{logical:path}`、`GET /templates/{logical:path}/image` | 复用 vendor `TemplateStore`；路径穿越校验（`store.py:56-69`） |
| 运行推送 | `WS /ws/runs/{id}`、`WS /ws/runs`（列表页订阅状态变化） | 事件 `{type:'state', state, progress, stage}`，服务端 2s 轮询 DB 或 LISTEN/NOTIFY（首期轮询） |
| 元信息 | `GET /audit-events?run_id=&limit=`、`GET /schema` | `schema` 返回静态 JSON（24 表/231 字段的字典数据，供「数据设计」页搜索与分组） |

### 8.3 runner ↔ api 的内部协议

| 端点 | 作用 |
| --- | --- |
| `POST /internal/runs/{id}/ack` | runner 已接管，`dispatching → running`（幂等） |
| `POST /internal/runs/{id}/heartbeat` | 每 10s 续租 `heartbeat_at`；响应带 `{"cancel":true}` 时 runner 主动收尾 |
| `GET /internal/runs/{id}/fence` | 校验 `fencing_token`，失配返回 409（runner 立即停设备操作） |
| `POST /internal/runs/{id}/events` | 追加 `run_events`（阶段、设备状态、采集指标名等），可控频率 |
| `POST /internal/runs/{id}/complete` | 提交终态 + outcome + 摘要（含 artifacts 清单） |
| `POST /internal/runs/{id}/fail` | 提交 `errored` + `error_code` + 现场路径 |

## 9. 前端规格（与原型的关系）

> 细节在 `docs/plan/frontend-spec.md`（页面 → 组件 → API 矩阵 + 每页验收用例）。

### 9.1 必须与原型一致的部分（视觉与交互规格）

1. 9 项导航、图标、分组、顺序、`#hash` 路由、`document.title` 规则、`active/aria-current`、tasks 角标。
2. 全部组件原语外观：`heading/tabs/empty/badge/btn/toast/modal/drawer/table`；状态徽章颜色语义。
3. 全局 `targetScope`（all/android/ios/web）的作用范围与文案（含「执行资源待接入」「规划中」模板页）。
4. 任务列表过滤三件套（搜索/模块/状态）、编号规则（draft=`TASK-<id>`，其余 `RUN-<id>`）、行内进度条。
5. 新建向导 3 步字段、校验规则（包名正则、名称/版本 maxlength、时长 10-3600 整数）、错误区 `role=alert`。
6. 运行详情 4 阶段 timeline 文案与 stage 推导；报告中心「一句话结论」映射文案；三态展示不得压成二态。
7. 性能页 `perfVerdict` 的判定顺序与文案（含「告警不改结论」「跨档案，不作对比」「当前设备不支持」）。
8. JSON 导出字段与文件名 `TestDock-RUN-<id>-DEMO.json`（去掉 `prototype:true`，改 `demo:false`）。

### 9.2 必须偏离原型的部分（因为接真实数据）

| 原型行为 | 平台行为 | 理由 |
| --- | --- | --- |
| 「运行套件」直接改本地状态推进进度 | 创建真实 run，WS 订阅真实 state/progress | 无后端模拟必须移除 |
| 状态单字段 `status`（含 passed/failed/not_tested/queued） | 拆 `state`(7) + `outcome`(3)，UI 展示态由两者组合推导 | DB 约束（`schema.sql:341`） |
| 设备 `busy` 由「有 running 任务」推导 | `busy` 由 `resource_leases` 是否存在 + `status` 联合推导 | 调试会话也占用设备 |
| 硬编码 2 条告警 | 由 `metric_summaries` vs `gate_policies` 实算（阈值不符/样本不足） | 真实数据 |
| 「验证定位」返回演示字符串 | 调 vendor `locators/validate` 真校验，返回匹配坐标与置信度 | F5 缺口 |
| 快照在 localStorage | 快照在后端内存（vendor），冻结后落 `artifacts` 才持久 | F5 |
| 「直接控制（演示）」复选框 | 真实开关，受租约与调试会话约束 | 安全 |
| 应用/设备/套件数据写死 | 来自 DB（种子脚本提供与原型同名的演示数据，保证视觉一致） | — |
| 无登录 | 首期也无登录（仅回环），但显示「本地演示环境」条 | 与 §8.1 一致 |

### 9.3 前端工程约束

- 目录：`web/src/{pages,components,api,styles,stores}`；每页一个 `Page.tsx` + 一个 `*.test.tsx`。
- 数据层：TanStack Query（`staleTime: 0` 用于运行中对象，`refetchInterval` 由 WS 触发的 invalidate 替代）。
- 状态：`targetScope` 与筛选条件放 zustand 并**持久化到 URL query**（修正原型刷新丢失问题，验收用例覆盖）。
- 不引入 UI 框架；样式用 CSS Modules + 从原型抽取的 `tokens.css`（颜色/间距/圆角/字阶）。
- 图表：自写 `<TrendChart>`（SVG polyline + 基线虚线 + 缺失段断开），不引 echarts。

## 10. 执行器（runner）设计

### 10.1 进程协议

```bash
python -m testdock_runner ui    --run-id 42 --serial <serial> --revision 7 \
      --artifacts-dir data/artifacts/xinghe/42 --control-url http://127.0.0.1:8000 \
      --control-token <token> --timeout 1800
python -m testdock_runner perf  --run-id 43 --serial <serial> --app com.example.xinghe \
      --items CPU,Memory,FPS --duration 300 --runs-dir data/artifacts/xinghe/43/perf …
python -m testdock_runner debug --session-id 9 --serial <serial> --port 0
```

| 项 | 约定 |
| --- | --- |
| 输出 | stdout 每行一个 JSON 事件（`{"t":"stage","name":…}`、`{"t":"metric",…}`、`{"t":"result",…}`），api 转发到 WS 并落 `run_events` |
| 退出码 | `0` 成功（含测试失败但结果已提交）、`2` 用例失败、`3` 基础设施错误、`4` 被取消、`5` fence 失配 |
| 环境注入 | `TMP/TEMP/HOME/USERPROFILE → data/tmp`（F17 必需）、`PYTHONPATH` 指向 `vendor/*`、`PYTHONIOENCODING=utf-8` |
| 超时 | ui：30 分钟默认（可配）；perf：`duration + 300s`；debug：无超时（随会话） |
| 取消 | api 置 `cancel_requested` → 心跳响应带 `cancel` → runner 优雅停（释放设备、写 `cancelled`）；10s 未退 → `kill` |
| Windows 强杀 | `taskkill /T /F /PID`，确保 scrcpy/adb 子进程一并回收 |
| 日志 | `data/runner-logs/<run_id>.log`（stdout+stderr 全量），api 只保留末尾 200 行到 `run_events` |
| 幂等 | 同一 `run_id` 重复启动 runner 必须被 fence 拒绝（api 侧检查 runner pid 已在跑） |

### 10.2 ui job 具体动作

1. 算 sha256 校验 vendor 锁（可跳过：`--skip-vendor-check`）。
2. `DeviceLease.acquire`（本机兜底，F2）→ 失败即 `fail(3, 'local_lease_busy')`。
3. `DeviceSession(config)` → `start()` → `MobileAdapter(session)`。
4. 生成临时 pytest 入口 `conftest.py`（提供 `--mobile-config`，因 vendor 插件不注册该选项，见能力盘点）→ 跑 `pytest vendor/mobile_auto/tests/...` 或用户仓库（路径记在 revision 里）。
5. 用 vendor 插件参数：`--mobile-devices <serial> --mobile-evidence`；`artifacts_dir` 指向 run 目录。
6. 收 `junit.xml` + `artifacts/evidence/<16hex>/` + `run-manifest.jsonl` → 提交 complete（`outcome = junit 是否全绿`）。

### 10.3 perf job 具体动作

1. `PerfKit(serial=…, adb_path=vendor/mobile_auto/tools/adb/adb.exe, runs_dir=…, gate=PlatformGate(token))`。
2. `ensure_ready()`（`keeper.Keeper.run()`）→ 不就绪即 `fail(3, readiness 原因)`. 
3. `collect(target=package, items=[CPU,Memory,FPS], duration_s=…)`；每 10s 心跳 + 上报进度（阶段串，非指标值——vendor 无实时推送，F 缺口 ①）。
4. 产物目录 `runs/<runId>/` 原样搬到 artifacts；`report.json` 登记为 `kind=perf_report_native`。
5. `judge.judge(report, spec)` → 提交 verdict + checks；样本不足自然得 `not_tested`。

### 10.4 debug job 具体动作

1. 起 vendor `start_debug_viewer(config)`（`server.py:69`，回环 + 端口探测 20 次）。
2. 回传 `{base_url}` 给 api（stdout 事件），api 写 `debug_sessions.base_url`。
3. 保持前台等待 api 的 SIGTERM/取消；收到即 `handle.stop()` 并退出。

## 11. 分期实施计划

> 原则：每期合并后系统仍可用（`think` 的阶段独立性）。P1 之后任何一期停摆都不影响已有页面可浏览真实数据。

### P0 仓库骨架与 vendor 落地（3 人日）

| 项 | 内容 |
| --- | --- |
| 交付 | `vendor/**` + `VENDOR.lock.json`、`scripts/vendor_sync.py`、`scripts/run_vendor_tests.sh`、`server/pyproject.toml` 空壳、`web/` vite 空壳、`.github/workflows/ci.yml` |
| 验收 | `vendor_sync.py --check` 全绿；宿主 `run_vendor_tests.sh` 两个包 unit+contract 100% 通过；`ci.yml` 在宿主等价环境绿 |
| 风险 | vendor 测试在沙箱跑不了（F17）→ 必须在宿主执行，CI 是关键补偿 |

### P1 数据层 + 只读 API + 前端外壳（5 人日）

| 项 | 内容 |
| --- | --- |
| 交付 | EDB 便携 PG 脚本、`alembic 0001`（24 表）、`seed_demo.py`、只读端点（overview/applications/resources/tasks/schema）、前端 9 页骨架 + 导航 + tokens.css + 真实数据渲染 |
| 验收 | 结构 diff（`pg_dump --schema-only` vs `schema.sql`）零差异或差异登记；9 页均可打开且显示种子数据；`targetScope` 过滤与原型一致 |
| 可独立合并 | 是：平台变成「真实数据的只读看板」 |

### P2 任务配置与套件（5 人日）

| 项 | 内容 |
| --- | --- |
| 交付 | 任务 CRUD + 修订 + readiness 校验、套件 discover（pytest collect）、新建向导 3 步、任务详情抽屉 |
| 验收 | 向导校验规则与原型一致（含错误文案位置）；创建后 `task_revisions(readiness='draft')`；`validate` 在缺 build 时拒绝并说明；重复提交同名不产生重复任务 |
| 可独立合并 | 是：可完整配置任务，只是不能跑 |

### P3 运行生命周期 + 租约 + UI 自动化真跑（8 人日）

| 项 | 内容 |
| --- | --- |
| 交付 | `resource_leases`+fencing、调度器、reconciler、runner(ui)、junit/证据归档、运行详情 drawer 真实 timeline、报告中心 UI 分支、WS 状态推送、`POST /runs/import`（降级通道） |
| 验收 | ①两个并发提交只有一个进入 running ②kill runner 后 60s 内回收为 `errored` ③真机跑通 1 个套件并看到失败截图+UI 树+`run-manifest.jsonl` ④任何页面刷新后进度不丢 |
| 可独立合并 | 是：UI 自动化闭环成立（性能仍只读） |

### P4 性能采集与三态门禁（6 人日）

| 项 | 内容 |
| --- | --- |
| 交付 | runner(perf)、`metric_summaries` 写入（NULL+missing_reason）、`judge` 复用、`gate_evaluations`(original/reanalysis)、性能分析页、基线与门禁策略页、导出 JSON |
| 验收 | ①样本 <10 必得 `not_tested` 且 reason 正确 ②跨档案必得 `profile_mismatch` ③改阈值只产生 reanalysis，original 行字节不变（比对 `updated_at` 与内容 hash）④GPU 不支持显示 `—` 不显示 0 |
| 可独立合并 | 是 |

### P5 设备调试与模板（5 人日）

| 项 | 内容 |
| --- | --- |
| 交付 | debug_sessions + viewer 反代（HTTP+WS）、快照/层级树/定位验证、模板库管理、设备就绪检查（Keeper）、设备页四态 |
| 验收 | ①同一设备运行中无法开调试（且提示占用者）②预览 10fps 流畅、断开后租约释放 ③定位验证返回真实坐标 ④模板新版本不改旧版本 |
| 可独立合并 | 是 |

### P6 加固与交付（3 人日）

| 项 | 内容 |
| --- | --- |
| 交付 | 审计事件页、数据设计页（24 表字典 + 4 泳道 + 4 写入流程，来自 `GET /schema` 静态数据）、接入说明页、E2E 脚本、README + 部署手册 |
| 验收 | 12 条端到端清单（§12.4）全绿；新人按 README 从零起环境 ≤ 30 分钟 |

合计 **35 人日**（1 人 ≈ 7 周；2 人并行 ≈ 4 周，前后端可完全并行，P2/P3 后端串联）。

## 12. 测试策略与验收

### 12.1 环境前提（重要，已在实测中踩到）

1. **vendor 回归测试不能在 DSH 沙箱内跑**（`%TEMP%` `WinError 5`，`--basetemp` 亦失败）→ 只在宿主 shell/CI 跑，脚本 `scripts/run_vendor_tests.sh` 统一注入 `TMP/TEMP/HOME/USERPROFILE=TMPDIR=data/tmp`。
2. 平台测试同样遵守：pytest 命令统一走 `scripts/pytest_platform.sh`（内部设 env + `--basetemp=data/tmp/pytest`）。
3. 平台集成测试用 EDB 便携实例 + 每测试独立 schema（`CREATE SCHEMA test_<uuid>` + `search_path`），测完 drop。

### 12.2 测试分层

| 层 | 内容 | 工具 | 门禁 |
| --- | --- | --- | --- |
| vendor 回归 | 两包 `tests/unit` + `tests/contract`（+ integration） | pytest | 100% 通过，且 `vendor_sync --check` 绿 |
| 平台单测 | 状态机非法迁移、租约并发（2 线程抢 1 设备）、门禁三态全路径、幂等 request_key、artifact sha256、deviceProfile 规范化 | pytest + anyio | 覆盖 domain 分支 ≥ 90% |
| 平台集成 | 真 PG：migration 往返、CHECK 约束生效、SKIP LOCKED 并发领设备、runner 子进程协议（用 fake runner） | pytest + httpx | 全绿 |
| 前端单测 | 9 页渲染 + 三件套过滤 + 三态展示 + 导出 JSON 字段快照 | vitest + RTL | 全绿 |
| 端到端 | 见 12.4，需真机 | 手工 + 脚本 | 发布前全跑 |

### 12.3 架构约束测试

- `tests/test_no_vendor_import.py`：遍历 `server/app/{api,domain,db}` 的 AST，禁止 `import mobile_auto` / `import mobile_perf`。
- `tests/test_vendor_readonly.py`：跑 `vendor_sync.py --check`。
- `tests/test_enum_sync.py`：DB 枚举值集合 == 后端 Enum 集合 == 前端常量集合（三处对齐）。

### 12.4 端到端验收清单（12 条）

1. 起环境：`scripts/dev_up.sh` → 打开 `http://127.0.0.1:8000`，9 页无报错。
2. 工作台数字与 DB 一致（运行数/通过率/需关注/可用资源）。
3. 切 `targetScope=ios`：工作台显示规划态、任务列表为空且有说明文案；刷新后 URL 仍带 `scope=ios`。
4. 新建 UI 任务：包名非法被拦、名称超 60 字被拦、设备选 offline 被禁、确认后跳任务中心。
5. UI 任务运行：进度从 queued→dispatching→running→finalizing→completed 真实推进，timeline 阶段与之一致。
6. 故意失败用例：报告页有失败截图、UI 树、异常栈、evidence id。
7. 并发：同一设备再提交一个运行 → 显示排队；设备页显示占用者与排队数。
8. 取消运行中任务：state=cancelled，outcome 为空，设备 10s 内回到 idle。
9. 性能任务：采集完成 → 4 指标卡有值，样本 ≥10 判定 passed；把采集时长改到 <10 样本 → not_tested 且 reason 可见。
10. 换基线（不同档案）→ 指标卡显示「跨档案，不作对比」，verdict=not_tested。
11. 改门禁阈值 → 生成 reanalysis，报告里 original 结论不变（时间戳与内容 hash 不变）。
12. 调试会话：设备页「打开调试」→ 预览有画面、层级树可点、定位验证返回坐标；关闭后设备回 idle；此时再提交运行能正常排队/执行。

## 13. 风险、假设与降级方案

### 13.1 Premise collapse（最关键假设）

**本方案假设**：目标机器上真机可被平台独占，并在单个 run 时长内稳定完成「adb + scrcpy + SoloPi 无障碍」链路。

**若不成立**（设备频繁断连 / SoloPi 无法 Bound / 无人值守真机不可用），则：平台退化为「配置 + 产物归档 + 查看分析」形态——真机执行仍由开发者在命令行跑 `mobile-perf` / `pytest`，再通过 `POST /runs/import`（P3 内置，成本 0.5 人日）把 vendor 产物目录导入平台，同样得到证据、指标、三态门禁与可追溯报告。这个降级通道是**主动设计**的，不是临时补丁。

### 13.2 风险表

| # | 风险 | 影响 | 对策 |
| --- | --- | --- | --- |
| R1 | 本机无法安装 PostgreSQL | P1 阻塞 | 用 EDB 便携 zip（已实测 200）；不降级 SQLite（会丢部分唯一索引与 SKIP LOCKED，等于丢掉核心语义） |
| R2 | vendor 测试只能在宿主跑 | 回归靠人工 | CI（宿主等价 runner）+ 本地脚本；沙箱内只跑平台单测 |
| R3 | viewer WS 反向代理不稳（二进制帧 + 自定义 close code 4403/4404/4429） | 调试页画不出画面 | 备选：`iframe` 直连 `127.0.0.1:<random>` + 一次性 token 校验（回环 + 一次性 = 可接受）；P5 首个 spike 决定 |
| R4 | `deviceProfile` 字符串不一致导致判定恒 `not_tested`（F10） | 性能结论永远不可用 | 平台定义 `normalize_profile()`（系统版本/分辨率/机型规范化），入库前统一；单测覆盖 6 种脏写法 |
| R5 | 性能采集无法中途取消（vendor `collect` 取消能力未核实） | 设备被长时间占用 | 先核实（P4 第一天）；无则 kill 进程 + `errored`+outcome NULL + 明确文案「采集中断，指标不完整」 |
| R6 | uvicorn 多 worker 会重复调度 | 重复执行 | 部署固定 `--workers 1`；调度仍用 SKIP LOCKED 做二次兜底 |
| R7 | Windows 中文路径 / gb18030 CSV | 解析乱码 | 全链路 `encoding` 显式声明；artifacts 用相对 URI |
| R8 | 前端重写导致视觉偏离原型 | 验收不通过 | tokens.css 从原型抽取 + 每页截图对照清单（P1 就做） |
| R9 | 时钟漂移 / 心跳抖动 | 误回收运行 | 时间一律用 DB `now()`；回收阈值 60s，心跳 10s（6x 余量） |
| R10 | SoloPi/wetest scrcpy 许可不清 | 法务风险 | 仅内部使用不分发；许可结论记入 `vendor-integration.md`，不阻塞开发 |

### 13.3 明确延迟的未知（有 owner、有触发点）

| 未知 | 何时必须解决 | owner | 不解决怎么办 |
| --- | --- | --- | --- |
| 本机是否允许装 PG 便携版 | P1 开工前 | 用户 | 无法进 P1，回到选型 |
| 真机数量与可用时段 | P3 验收前 | 用户 | P3 用 fake runner 验证链路，真机延后 |
| vendor `collect` 可否取消 | P4 第一天 | 后端 | 用 kill 兜底 |
| viewer WS 代理可行性 | P5 第一天 | 前端 | 用 iframe 备选 |
| 身份方案（二期） | 二期规划 | 用户 | 首期回环无登录 |

## 14. 实施建议

1. **顺序**：P0 → P1 → P2 → P3（此时已可用）→ P4 → P5 → P6；P4/P5 可并行。
2. **每个 P 的完成定义**：代码 + 测试 + 文档段落 + 该期验收项全绿 + `vendor_sync --check` 绿。
3. **不可妥协的三个语义**（任何时候都不许为赶进度压掉）：三态门禁不压二态、缺失指标不写 0、租约互斥不靠约定。
4. **建议先做 P3 的 spike**（0.5 人日）：拿真机跑一次 `python -m testdock_runner ui` 手工版，确认真机链路时间与稳定性，再决定后续排期。

## 15. 需要你拍板的 6 个决策

| # | 决策 | 推荐 | 备选 |
| --- | --- | --- | --- |
| D1 | PostgreSQL 部署方式 | 便携版 EDB 装到 `.runtime/pg17`（脚本一键起停） | 你已有的 PG 实例（给连接串）/ SQLite 降级（不推荐，丢核心约束） |
| D2 | 前端技术栈 | React 18 + Vite + TS（照原型视觉重写） | 继续 vanilla 单文件（省 2 人日，但接 API 后必失控） |
| D3 | 首期执行范围 | 仅 Android 真机（UI + 性能 + 调试） | 追加 iOS/Web（本机无 Apple 工具链，且无适配器） |
| D4 | 是否保留「导入已有 vendor 产物」降级通道 | 保留（0.5 人日，抗 premise collapse） | 不做，赌真机链路始终可用 |
| D5 | 认证 | 首期无登录 + 仅回环访问 | 简单口令（+0.5 人日）/ 完整账号体系（二期） |
| D6 | 视觉 | 严格复刻原型 | 允许在保持信息结构前提下微调间距与配色 |

---

附：本方案配套子文档 `data-model.md`、`api-design.md`、`vendor-integration.md`、`frontend-spec.md` 与本文件同目录，评审通过后一起作为实施依据。
