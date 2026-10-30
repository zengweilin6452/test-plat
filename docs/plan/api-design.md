# API 设计（api-design.md）

> 配套：`docs/plan/development-plan.md` §8、`docs/plan/frontend-spec.md`（前端消费方）、`viewer/app.py:522-538`（错误信封来源）。

## 1. 通用约定

### 1.1 基址与认证

| 项 | 值 |
| --- | --- |
| Base | `http://127.0.0.1:8000/api/v1` |
| 浏览器认证 | 无（首期回环 + `X-TestDock-Client: web` 要求写操作带上） |
| runner 认证 | `/internal/*` 要求 `X-Control-Token`（`data/control.token`，600 权限，api 启动生成） |
| CORS | 开发期允许 `http://127.0.0.1:5173`；生产同源不开放 |

### 1.2 错误信封

```json
{ "code": "lease_conflict", "message": "设备 7f3a… 已被 RUN-12 占用",
  "request_id": "01JB…", "details": { "holder_run_id": 12 } }
```

| HTTP | code | 场景 |
| --- | --- | --- |
| 400 | `validation_error` | 字段校验（pydantic） |
| 404 | `not_found` | 资源不存在 |
| 409 | `state_conflict` | 状态迁移前置不满足（运行已被取消等） |
| 409 | `illegal_transition` | 非法状态迁移 |
| 409 | `lease_conflict` | 设备已被占 |
| 409 | `stale_version` | `lock_version` CAS 失败（任务被他人改） |
| 409 | `fence_mismatch` | runner token 失配 |
| 422 | `readiness_incomplete` | 修订未就绪就运行 |
| 424 | `device_not_ready` | 设备 offline/unauthorized |
| 500 | `internal_error` | 未捕获 |
| 503 | `runner_spawn_failed` | 子进程起不来（vendor 缺失等） |

### 1.3 幂等与并发

- 写操作带 `request_key`（UUIDv4）：`POST /runs`、`POST /baselines`、`POST /gate-evaluations`。重复 key 返回 **200** + 既有对象（首次 201）。
- 乐观锁：`PATCH /tasks/{id}` 必须带 `lock_version`，冲突返回 409 + 最新对象。
- 运行中禁改：revision 已绑定 run 后 `PATCH` 返回 409 `revision_locked`。

## 2. 资源端点

### 2.1 概览

```http
GET /api/v1/overview?platform=android
```

```json
{
  "stats": { "runs": 12, "pass_rate": 67, "attention": 3,
             "resources": { "idle": 4, "total": 6, "note": null } },
  "recent_runs": [ { "id": 47, "display_id": "RUN-47", "name": "首页滑动性能巡检",
                      "module": "perf", "state": "completed", "outcome": "failed",
                      "started_at": "2026-10-25T12:00:00Z" } ],
  "top_resources": [ { "id": "7f3a", "name": "Pixel 7 Pro", "status": "ready",
                        "busy": false, "profile": "Android 14 / 1440x3120 / Pixel 7 Pro" } ],
  "alerts": [ { "kind": "metric_breach", "run_id": 47, "text": "首页滑动内存 PSS 268MB，阈值 <240MB" },
              { "kind": "low_samples", "run_id": 44, "text": "搜索场景有效样本 6，低于下限 10" } ]
}
```

规则：`platform != android` 时 `resources.idle=0`、`note=执行资源待接入`、`runs` 只统计该端（首期恒 0）。`alerts` 由 DB 实算，最多 5 条。

### 2.2 设备（执行资源）

```http
GET  /api/v1/resources?status=ready
POST /api/v1/resources/sync           # 扫描 adb devices，增删/更新 execution_resources
POST /api/v1/resources/{id}/readiness # vendor keeper.Keeper.run() 就绪检查
```

```json
// GET /resources 单项
{ "id": "7f3a", "serial": "emulator-5554", "name": "Pixel 7 Pro",
  "status": "ready", "busy": false, "holder": null, "queued_runs": 1,
  "profile_id": "prof-1",
  "profile": { "os": "Android 14", "resolution": "1440x3120", "model": "Pixel 7 Pro",
               "profile_key": "android14|1440x3120|pixel7pro" },
  "last_seen_at": "2026-10-25T12:00:00Z" }

// POST /resources/{id}/readiness
{ "ready": false,
  "checks": [ { "name": "adb", "ok": true },
               { "name": "solopi_installed", "ok": true, "detail": "com.alipay.hulu 1.5.4" },
               { "name": "accessibility_bound", "ok": false,
                 "hint": "请在手机上开启 SoloPi 无障碍服务" },
               { "name": "battery", "ok": true, "detail": "82%" } ] }
```

`busy` 由 `resource_leases WHERE released_at IS NULL` 判定；`holder` = `{kind: run|debug, id, display_id}`；`queued_runs` 为等待该设备的 queued 数。

### 2.3 任务与修订

```http
GET    /api/v1/tasks?module=ui|perf|joint&state=…&q=…&limit=&cursor=
POST   /api/v1/tasks                    # 建任务 + 首个修订
GET    /api/v1/tasks/{id}
PATCH  /api/v1/tasks/{id}               # 仅未绑定 run；带 lock_version
POST   /api/v1/tasks/{id}/validate      # readiness draft -> validated
POST   /api/v1/tasks/{id}/archive
GET    /api/v1/tasks/{id}/revisions
POST   /api/v1/tasks/{id}/suites/discover  # pytest --collect-only
```

```json
// POST /tasks 请求（新建向导 3 步的最终提交）
{
  "request_key": "6f1c…",
  "project_id": "xinghe", "application_id": "xinghe-android",
  "name": "首页滑动性能巡检", "module": "perf",
  "platform": "android", "package_name": "com.example.xinghe",
  "app_version": "3.8.0-rc.2",
  "suite_id": null, "scenario": "首页滑动",
  "device": { "resource_id": "7f3a", "allow_busy_queue": true },
  "perf": { "duration_s": 300, "items": ["CPU","Memory","FPS"], "extra_items": ["Network","Battery"] },
  "ui": null
}
// 响应 201
{ "id": 12, "display_id": "TASK-12", "lifecycle": "draft",
  "revision": { "id": 7, "readiness": "draft", "lock_version": 0 } }
```

校验（与原型一致）：`name` 1-60；`package_name` 匹配 `^[a-zA-Z]\w*(\.[a-zA-Z]\w*)+$` 且 ≤120；`app_version` ≤40；`duration_s` 整数 10-3600（`module != ui` 必填）；`items` 非空且属白名单；非 android 端允许建任务但 readiness 永远 draft。

### 2.4 运行

```http
GET /api/v1/runs?state=completed&test_type=ui&q=RUN-47&cursor=…&limit=50
// -> { items, total, next_cursor, has_more }
```

过滤与分页（spec §9.3）：`scope`（android/ios/web）、`state`（七态）、`application_id`、`test_type`（ui/performance/joint）；`q` 在**完整过滤集合**里按文字包含匹配 display_id / 任务名 / 应用名（`position()` 实现，`%`/`_` 按字面处理，不解释为 SQL 通配）。游标 `cursor` 封了过滤条件快照与创建水位（`display_no`），换过滤条件带旧游标或非法游标返回 400 `validation_error`；翻页沿 `next_cursor` 直到 `has_more=false`。报告中心传 `state=completed`，只取完成报告。

```http
POST /api/v1/runs
{ "request_key": "…", "application_id": "…", "platform": "android",
  "task_id": 12, "revision_id": 7,          // revision_id 可省略
  "device": { "resource_id": "7f3a" } }
// 201 -> { id: 47, display_id: RUN-47, state: queued, revision_id: 7, task_id: 12 }
// 200 -> 同 request_key 重放既有运行：{ …, "duplicate": true }（不新建、不重解析修订）
```

前置校验顺序（失败即返回，错误码见 §1.2）：`application_id` 必填且与 `platform` 一致 → `task_id` 必填 → 修订属于该任务/应用/项目且 `readiness=validated` → 设备存在且 `status=ready` → 目标端为 android。跨应用/跨项目的任务、修订、父运行一律按 `not_found` 拒绝；省略 `revision_id` 时只解析已验证修订，并把实际 `revision_id` 回传，派发时不再重解析。

固定输入：执行输入（`overrides`、`source_dir`、`test_paths`、结果字段）只来自修订；请求里出现 `overrides`/`source_dir`/`test_paths`/`fake_outcome`/`source` 直接 400 `validation_error`。内部导入通道 `POST /runs/import` 与浏览器真执行隔离，不能成为绕过固定输入的通道。

```http
GET  /api/v1/runs/47
```
```json
{ "id": 47, "display_id": "RUN-47", "task_id": 12, "revision_id": 7,
  "module": "joint", "state": "running", "outcome": null,
  "resource_id": "7f3a", "resource_name": "Pixel 7 Pro",
  "started_at": "2026-10-25T12:00:00Z", "ended_at": null, "duration_s": null,
  "progress": 45, "stage": 2, "cancel_requested": false,
  "parent_run_id": null, "request_key": "…",
  "components": [ { "kind": "ui", "state": "running", "outcome": null },
                  { "kind": "perf", "state": "pending", "outcome": null } ] }
```

`stage`（1-4）规则与原型一致：`progress<40`→1、`<85`→2、`==100`→3、终态→4。`progress` 由 run_events 的阶段权重算（ui：就绪 20 / pytest 80 / 归档 100；perf：就绪 15 / 采集 75 / 判定 100）。

`display_id`（`RUN-0001`）由 `test_runs.display_no` **持久分配**：新增运行、过滤、分页、历史数据回填或删除都不重编号，同一个运行在任务列表、运行列表/详情、WS 快照、报告与导出里永远是同一个字符串。`id`（UUID）才是精确身份——路径参数只接受 UUID，`GET /runs/RUN-0001` 返回 404。

```http
POST /api/v1/runs/47/cancel
// 202 -> { "id": 47, "state": "running", "cancel_requested": true,
//          "cancel_requested_at": "2026-10-25T12:01:00Z" }
```

取消语义：先受理、后收敛。受理事实写进 `test_runs.cancel_requested_at`（重复受理保留首次时间），不依赖事件流是否完整。`queued` 直接迁移 `cancelled`；执行中只受理不改状态，runner 从心跳的 `cancel` 标志感知，再由 `complete`/`fail` 或 reconciler 收敛 —— 若恰好完成，终态就是真实完成态，不伪造 `cancelled`。终态运行取消返回 409 `state_conflict`。

```http
GET /api/v1/runs/47/events?after=0&limit=200
// -> { "items": [...], "total": 200, "after": 0, "next_after": 200, "has_more": true }
```

`items` 按 `sequence` 升序；`total` 是本页条数；`next_after` 是下一页起点（空页沿用 `after`）；`has_more` 表示后面还有。客户端循环补拉直到 `has_more=false`，按 `(run_id, sequence)` 去重。取消事实以 `test_runs` 列为准，不因事件分页或清理丢失。

### 2.5 结果与报告

| 端点 | 返回 |
| --- | --- |
| `GET /runs/{id}/components` | 组件列表（含 vendor 结果摘要） |
| `GET /runs/{id}/cases` | `nodeid, name, outcome, duration_ms, failure_message` |
| `GET /runs/{id}/artifacts` | `id, kind, logical_key, sha256, size_bytes, availability, download_url` |
| `GET /runs/{id}/artifacts/{aid}/download` | 文件流（缺失 404 + availability=missing 说明） |
| `GET /runs/{id}/report` | 平台汇总报告（见下） |
| `GET /runs/{id}/report/export` | 同结构 + `Content-Disposition` |

平台汇总报告（对齐原型 `exportReport`，去掉 `prototype:true`）：

```json
{ "runId": "RUN-47", "hostRunId": "RUN-47", "name": "首页滑动性能巡检",
  "projectId": "xinghe", "applicationId": "xinghe-android", "platform": "android",
  "environmentId": "staging", "resourceId": "7f3a",
  "module": "perf", "status": "not_tested", "verdict": "not_tested",
  "target": "com.example.xinghe", "deviceProfile": "android14|1440x3120|pixel7pro",
  "durationS": 300,
  "metricsSummary": { "memory": { "median": 268, "unit": "MB", "sampleCount": 180 },
                      "cpu":    { "median": 24.6, "unit": "%", "sampleCount": 180 },
                      "fps":    { "median": 58.2, "unit": "fps", "sampleCount": 180 },
                      "gpu":    { "median": null, "unit": "%", "sampleCount": 0,
                                   "missingReason": "device_unsupported" } },
  "thresholdsAtRun": { "mem_pss_mb": ["lt", 240, "fail"],
                        "cpu_process_pct": ["lt", 35, "warn"],
                        "fps_frame": ["ge", 50, "fail"] },
  "reason": "sample_count_below_minimum",
  "reasonText": "有效样本数为 6，低于默认下限 10",
  "evaluatedAt": "2026-10-25T12:05:00Z", "mode": "original",
  "vendorReports": [ { "kind": "perf_report_native", "artifact_id": 91 } ] }
```

### 2.6 性能分析与门禁

```http
GET  /api/v1/analyses?run_id=47            # 运行分析页数据
GET  /api/v1/analyses?task_id=12&limit=20  # 趋势（同档案）
POST /api/v1/runs/47/gate-evaluations      # 试算 (reanalysis)
{ "request_key": "…", "policy_id": 1, "baseline_run_id": 39 }
GET  /api/v1/baselines?application_id=xinghe-android&resource_profile_id=prof-1
POST /api/v1/baselines  { "request_key":"…", "run_id": 39 }
GET  /api/v1/gate-policies                 # 首期单条全局策略
PUT  /api/v1/gate-policies/{id}            # 改阈值，不回写历史
```

```json
// GET /analyses?run_id=47
{ "run": { }, "verdict": "not_tested", "mode": "original",
  "reason": "sample_count_below_minimum",
  "reasonText": "有效样本数为 6，低于默认下限 10",
  "checks": [],
  "metrics": [ { "key": "memory", "median": 268, "unit": "MB", "baseline": 221,
                 "min": 160, "max": 340, "sampleCount": 6, "supported": true } ],
  "thresholds": { },
  "context": { "appVersion": "3.8.0-rc.2", "scenario": "首页滑动",
               "deviceProfile": "android14|1440x3120|pixel7pro",
               "window": "300s", "statistic": "median", "source": "SoloPi + 补采" },
  "series": [ { "t": 0.0, "memory": 265 }, { "t": 2.0, "memory": 267 } ],
  "baselineOptions": [ { "id": 3, "runId": "RUN-39",
                         "profile": "android14|1440x3120|pixel7pro", "sameProfile": true } ],
  "trial": null }

// POST /runs/47/gate-evaluations 试算结果
{ "evaluation_id": 12, "mode": "reanalysis", "verdict": "passed",
  "checks": [ { "metric": "memory", "op": "lt", "threshold": 240, "actual": 268,
                 "level": "fail", "ok": false } ],
  "note": "试算不改写历史报告" }
```

**硬规则**：`POST /runs/{id}/gate-evaluations` 只 INSERT `mode=reanalysis`；任何路径都不 UPDATE 既有 `gate_evaluations` 行。

### 2.7 调试会话与模板

```http
POST   /api/v1/debug-sessions { "serial": "7f3a", "purpose": "定位排查" }
// 201 -> { "id": 9, "state": "opening" }   state: opening → active → closing → closed
GET    /api/v1/debug-sessions/{id}     # 含 base_url 与 ws_path
DELETE /api/v1/debug-sessions/{id}
WS     /api/v1/ws/debug/{id}           # 代理 vendor /api/v1/preview
POST   /api/v1/debug-sessions/{id}/snapshots
GET    /api/v1/debug-sessions/{id}/snapshots/{nid}/image
POST   /api/v1/locators/validate       # { snapshot_id, locator } -> matches[]
GET    /api/v1/templates               # 复用 vendor TemplateStore 清单
POST   /api/v1/templates               # { logical_path, png_base64, confidence }
PUT    /api/v1/templates/{logical:path}
GET    /api/v1/templates/{logical:path}/image
POST   /api/v1/templates/validate      # IMAGE 目标验证 -> { matches[], scores[], note }
```

模板路径校验直接复用 vendor `validate_logical_path`（`store.py:56-69`）：拒绝 `..`、绝对路径、非法字符；同名冲突 409。

图像目标必须走 `/templates/validate`，不能走 `/locators/validate`：vendor 的 `_query_payload` 对 image 目标返回 4 元组（带 scores），而 `capture_and_query_sync` 在 `with_scores=False` 时按 3 元组解包，`by='image'` 必 500（真机实测 2026-10-28）。`vendor/` 是只读源仓库，平台侧改转发 vendor 自己的 `/api/v1/templates/validate`。

### 2.8 元信息

| 端点 | 用途 |
| --- | --- |
| `GET /api/v1/audit-events?run_id=&limit=` | 审计（谁改过阈值/取消了运行） |
| `GET /api/v1/schema` | 「数据设计」页数据源：静态 JSON（表/字段/分组/泳道/写入流程），构建时从 `schema.sql` 生成 |
| `GET /api/v1/health` | `{status, db, vendor:{mobile_auto,mobile_perf,versions}, runners:{active}}` |

## 3. WebSocket 协议

### 3.1 运行状态推送 `/api/v1/ws/runs/{id}`

服务端 → 客户端（text frame，JSON）：

```json
{"type":"snapshot","run":{...}}          // run 与 GET /runs/{id} 同一投影，含 progress/stage/last_sequence/cancel_requested
{"type":"state","state":"running","progress":45,"stage":2,"at":"..."}
{"type":"event","kind":"stage","name":"采集开始","sequence":42,"at":"..."}
{"type":"finished","state":"completed","outcome":"failed"}
```

客户端 → 服务端：只允许 `{"type":"ping"}`。关闭码：`4404` run 不存在、`4409` 已终态（推完即关）。

断线重连：先收到 snapshot（含 `last_sequence`），再用 `GET /runs/{id}/events?after=last_sequence` 补拉缺口，按 `(run_id, sequence)` 去重；终态运行重连时 snapshot 之后直接推 `finished`，不重放历史事件。

实现：api 每 2s 查一次 `test_runs + run_events`（首期简单，数据量小）；runner 事件经 hub 即时插入推送。二期可换 `LISTEN/NOTIFY`。

### 3.2 调试预览 `/api/v1/ws/debug/{id}`

双向透传 vendor 帧（json 与 binary 都不改），加三层保护：①仅 `debug_sessions.state=active` 接受 ②平台侧限 4 客户端/设备（对齐 vendor `_MAX_WS_CLIENTS_PER_DEVICE=4`）③会话关闭即 close(1000)。

## 4. runner 内部 API

| 端点 | 请求 | 响应 |
| --- | --- | --- |
| `POST /internal/runs/{id}/ack` | `{pid, started_at}` | `{ok:true, revision:{...}, task:{...}}` |
| `POST /internal/runs/{id}/heartbeat` | `{pid, progress, stage, fencing_token}` | `{ok:true, cancel: bool, fence_ok: bool}`（`cancel` 读 `test_runs.cancel_requested_at`，并顺带续租） |
| `GET /internal/runs/{id}/fence` | — | `{token}` 或 409 `fence_mismatch` |
| `POST /internal/runs/{id}/events` | `{events:[{source_key, source_event_id, kind, payload}]}` | `{accepted: n}` |
| `POST /internal/runs/{id}/complete` | `{outcome, components, cases, metrics, artifacts, verdicts}` | `{ok:true}` |
| `POST /internal/runs/{id}/fail` | `{error_code, message, stage}` | `{ok:true}` |

所有 `/internal/*` 幂等：`complete`/`fail` 对已终态 run 返回 200 + `{already:true}`（runner 可安全重试）。

## 5. 前端调用约定

| 项 | 约定 |
| --- | --- |
| 客户端 | `web/src/api/client.ts` 单一 `request()`；失败抛 `ApiError{code,message,request_id}` |
| 轮询 | 只在 WS 不可用时降级为 2s 轮询（列表页）；详情页必须用 WS |
| 缓存 | TanStack Query：列表 `staleTime: 5000`；运行中对象 `staleTime: 0` + WS invalidate |
| 导出 | `GET /report/export` → 前端 `Blob` 下载，文件名 `TestDock-RUN-<id>.json` |

## 6. 与原型 JSON 导出的差异清单

| 原型字段 | 平台处理 |
| --- | --- |
| `prototype: true` | 移除（平台数据不是演示数据） |
| `notice` | 移除；改为真实 `reason` + `reasonText` |
| `metricsSummary.*.source: synthetic_demo` | 改为 `vendor_report` / `device` |
| `metricsSummary.*.sampleCount`（固定 6/180） | 真实样本数（缺失指标给 0 + `missingReason`） |
| `verdict` 复制 `status` | 独立取值（`status` 来自 state/outcome，`verdict` 来自 gate_evaluations） |
| `thresholdsAtRun` 硬编码 | 来自 `gate_evaluations.thresholds_snapshot`（运行时刻快照，之后改策略不回溯） |
| `reason` 恒 `sample_count_below_minimum` | 真实 `reason_code` |
