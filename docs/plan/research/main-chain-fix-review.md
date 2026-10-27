# 任务创建与运行调度修复自查

日期：2026-10-26。基线：08563abf300c8d55749ce18b50348f0f1157800e。第二轮见文末。

## 范围与结论

本轮仅修复任务向导请求契约、运行创建和设备调度，并补回归。作者已自查差异；没有独立审查，不代表完整项目验收通过。未提交、推送、部署或操作现有业务数据库。

- 向导选择已登记应用，应用标识随选择填入；设备限制为同项目的在线资源。请求使用 `application_id/test_type/config`，`perf` 映射为 `performance`，幂等键使用 `Idempotency-Key`。切换步骤重置内容滚动位置。
- 运行创建显式生成 UUID，以数据库唯一键原子处理重复请求，保留请求级事务。修订必须实际存在且属于所选应用、项目和指定任务；冻结修订配置、设备和测试类型。
- 调度锁定运行行，先绑定资源及档案，再创建租约；指定设备忙时保持排队，不切换其它设备。启动 runner 在事务提交之后；启动失败释放租约并置 errored。
- 事件分配序号先锁父运行，再查询最大序号，移除 PostgreSQL 不支持的聚合结果行锁。

## 验证证据

先运行新增回归：原实现前端 4 条失败、后端 9 条失败，覆盖请求契约及实际 PostgreSQL 外键路径。

最终验证：

- 独立 PostgreSQL 数据库中执行 Alembic 迁移和 `pytest tests -o addopts= -q --tb=short -p no:cacheprovider`：185 passed，1 个 `_p2_common` 已导入导致的 pytest assertion rewrite warning，无失败或跳过。外层脚本同时设置两个数据库环境变量，防止夹具回落到业务库；结束后删除本轮测试库。
- 本轮新增 18 个后端测试实例：运行 UUID、顺序与并发幂等、事件失败事务回滚、修订归属、配置冻结、设备状态与项目归属、资源绑定和租约外键、指定设备忙后重试、并发调度互斥、并发事件序号、启动失败释放，以及向导请求头和配置回读。
- `npm --prefix web test`：6 passed。覆盖请求构造、性能类型映射、必选应用、设备状态、Web 配置和幂等请求头。
- `npm --prefix web run typecheck`、Vite 生产构建、`git diff --check` 通过。构建输出在忽略的 `.runtime/fix-main-web-build`。
- agent-browser 在独立数据库、18001 临时服务和生产构建上完成向导实际交互：未选应用拦截；登记应用自动填标识；离线/未授权设备禁选；选择在线设备；确认和提交；列表可见；详情为 draft；再次同名提交复用原任务。数据库核对仍为 1 个任务、1 个修订，版本、场景、包名和设备配置已保存。

## 残余风险和边界

- 创建任务依然需要项目内已有 environment。演示种子脚本没有创建它；浏览器验证先观察到明确错误，再只向隔离库补齐环境后重试成功。未修改业务库或默认种子流程。
- 调度回归替换进程启动器，验证数据库状态与调用边界，未验证真实设备执行。真 UI runner、性能采集、viewer 等此前验收缺陷仍在原范围之外。
- 任务创建的现有幂等表为进程内缓存；本轮验证请求头接入和顺序重试，不承诺任务创建在多进程下的持久幂等。运行创建的幂等由 PostgreSQL 唯一键保证，已测并发。
- 取消和导入路由仍有既有的手动提交模式；本轮只修复普通运行创建请求事务，未验收取消、导入和完整生命周期。
- 未修改初始迁移、vendor、依赖版本或 CI；此前整体验收仍不通过。

## 第二轮（2026-10-27）：其余阻塞项修复（未真机验证）

用户授权范围：修复 UI runner / 性能采集 / 调试 viewer 相关的其余阻塞，性能采集以
`D:\workspace\claudecode-test\moblie-xn` 工作树最新代码为准（经 `scripts/vendor_sync.py sync mobile_perf`
受控同步进 vendor，源仓库只读）；三项只修复，不做真机验证。未提交、未推送。

### 修复内容

- 性能页列表恒空：后端枚举为 `performance`（DB CHECK），页面此前比对 `'perf'`。
  新增 `TestType` 类型与 `moduleName()` / `isPerformanceType()`（`web/src/constants.ts`），
  PerfPage 以 `isPerformanceType(run.test_type) || 'joint'` 过滤并新增「类型」列；
  OverviewPage / TasksPage / TaskDrawer / ReportsPage 统一改走 `moduleName()`。
- 报告查看：新增 `ReportDrawer` 与 `fetchRunReport` / `fetchRunArtifacts`，
  展示 verdict、reason、mode（live/imported）、junit 计数、metricsSummary
  （缺失指标显示 `notTestedReason`/`missingReason`，不用 0 顶替）与证据下载链接。
- 模板上传契约：前端改为 vendor 真实契约——`POST /templates` 体
  `{snapshot_id, region[4], logical}`，同名覆盖走 `PUT` + `expected_old_sha256`，
  清单读 `{templates:[...]}`；删除旧 base64 上传路径（UiPage 模板 tab 重写）。
- 调试抽屉契约：WS 帧改为解析 vendor 的 JSON 文本帧（`{kind:'frame', jpeg_base64}`）；
  层级树先 `POST /snapshots` 再 `GET /snapshots/{id}/tree`（children 为下标）；
  定位验证 `{target:{by,value}}`，结果含 matches 坐标宽高与 note。
- 性能采集 vendor 基线：`vendor_sync.py sync mobile_perf` 同步 moblie-xn 工作树
  （217 文件 / 27.8 MiB，含 pageflow 整页耗时、时钟偏移测量、trend 网络档位泛化），
  首次同步与源有滞后导致 `test_kit_pageflow` 失败，重新同步后消除。
- 平台侧核对（只读，未改代码）：`server/app/integrations/mobile_perf.py` 的
  `_expected_keys` 会把报告 `metricsSummary` 里真实产出的 key（含新增 `page_load_ms`）
  一并映射进 metric_summaries，`notTested`/`sampleCount==0` 均写 missing_reason 不写 0，
  与 vendor 新产出兼容，无需改动。

### 验证证据（本轮新鲜执行）

- vendor mobile_perf：在 `vendor/mobile_perf` 包根 `PYTHONPATH=src pytest tests/unit tests/contract -q`
  → **619 passed, 0 failed, 8 skipped**（junit 汇总 15.3s，exit 0）。
- 后端全量：`.runtime/verify_main_chain.py tests`（独立库 fix_main_ce07976111，跑完即删）
  → **201 passed, 3 warnings**（55.4s）。
- 前端：`npx tsc --noEmit` 通过；`npm test` → **12 passed**（原 6 + 新增 report-and-debug 6 条，
  覆盖 moduleName / isPerformanceType / conclusionText / metricCell / junitCounts /
  buildTreeIndex+nodeLabel）；`npm run build`（Vite）成功；`git diff --check` 干净。
- vendor 与源一致性：`diff -r` 仅剩 `__pycache__` 差异；源 `tests/device`（真机用例）不在
  vendor 同步范围内，源仓库 HEAD 8df850f + 工作树未提交修改均包含在本次同步。

### 残余风险和边界

- 无真机验证（按授权范围明确排除）：UI runner、性能采集、调试 viewer 的设备侧链路
  均未实跑；模板上传/快照/定位验证依赖 viewer 真实会话，同样未实测。
- 无浏览器端到端实测（本轮未启动前端服务走 agent-browser）；UI 行为由 12 条单测 + 类型检查 + 构建覆盖。
- 无独立审查（作者自查）；vendor 下存在历史遗留 `__pycache__` 未登记文件
  （`vendor_sync.py check` 会报），非本轮产生，未清理。
- 本机便携 PostgreSQL 55432 此前处于停止状态（遗留 postmaster.pid），本轮直接以
  `postgres.exe` 启动用于回归；停库方式与 `pg_portable_setup.ps1` 说明一致，未改数据目录。
- 未修改初始迁移、依赖版本或 CI；未提交、未推送。

## 第三轮（2026-10-27）：真机链路、浏览器 E2E 与独立审查

受托补齐前两轮列为「未覆盖」的三项。授权范围：真机操作克制可逆、不 commit/push、
每项附可查验证据。

### 1. 真机链路（打通）

- 在线设备实测为 **84cb2c4e**（myron / 25102RKBEC），前两轮文档写的 749622c9 已不在线；
  隔离库资源串相应更新。
- 隔离环境：`.runtime/verify_live_chain.py`（自建 live_chain_* 库，名字记录在
  `.runtime/live-chain-database.txt`，18002 单端口 serve API + web/dist，
  TESTDOCK_CONTROL_URL 指向自身）。
- 用例：`.runtime/live_chain_tests/test_live_device.py`（截图 + UI 树 + Home 键，克制可逆），
  驱动脚本 `.runtime/live_chain_drive.py`。
- 结果：**completed / passed**。junit `{"tests":1,"failures":0,"errors":0,"present":true}`；
  `GET /runs/{id}/report` verdict=passed、mode=live、deviceProfile=84cb2c4e；
  artifacts 含截图（1200×2608 PNG）与 UI 树。
- 过程中修复三个真 bug（各带回回归测试）：
  - `GET /runs/{id}` 500：run_components 查询引用不存在的 started_at/ended_at
    （`server/app/routers/runs.py`，改 created_at）。
  - runner pytest 插件撞名：D:/python312 的 editable mobile-auto 入口点已自动加载
    evidence 插件，显式 `-p` 再注册即崩（`server/runner_pkg/testdock_runner/ui_job.py`
    新增 `_evidence_plugin_preloaded()` 守卫）。
  - dispatcher spawn 未传控制面 token → runner control_disabled → 60s 后被 reconciler
    判 lease_expired（`server/app/runner/dispatch_runner.py` 回落
    `get_control_url_and_token()`）。
- 后端回归：隔离库 test_run_submission + test_runner_contracts **29 passed**。

### 2. 浏览器端到端（重点：调试抽屉，全部走通）

agent-browser 驱动真实 Chrome 访问 `http://127.0.0.1:18002/#/ui`（截图在
`.runtime/live-e2e-shots/`）：

- 任务抽屉（01-*）：就绪状态、修订摘要正确。
- 报告中心 + ReportDrawer（02-*）：conclusionText、junit 共1/失败0/跳过0、
  设备档案 84cb2c4e、mode=live。
- 调试抽屉全生命周期（09-*、10-*、11-*）：点设备自动建会话 → 轮询 active →
  **WS 实时预览已连接**（探针记录 NEW→OPEN 3ms，无重试；python 第二客户端同会话
  12/12 秒连，6 秒收到 57 帧 ≈9.5fps，帧内容为锁屏时钟/通知的真实画面）→
  采集快照（代理 POST /snapshots）→ 层级树渲染（systemui 真实节点+边界）→
  点树节点自动填定位值 → 验证定位「唯一匹配，验证通过」（matches 含 x/y/宽/高）→
  关闭会话按钮 → DB closed、WS close code=1000 干净收尾。
- 过程中定位并修复调试抽屉两个前端 bug（`web/src/components/DebugDrawer.tsx`）：
  - 抽屉打开后没有任何代码调用 createMutation（会话永远建不出来）→ 补 open 驱动的
    useEffect + createPendingRef。
  - **WS 建连 effect 依赖含 wsStatus，而 effect 自己 setWsStatus('connecting')**：
    重渲染触发 cleanup 立即 close 刚建的 socket，表现为握手后 1ms 内 1006 并以
    2s 周期循环耗尽 15 次重试；另 detailQuery.data 每次轮询都是新对象，refetch 也会
    关掉已连好的 socket。改为依赖 `ws_path` 字符串 + 显式 wsAttempt 重试计数；
    cleanup 先摘 handlers 再 close。另发现 detailQuery 无轮询——会话 opening 阶段
    响应里没有 ws_path，旧 fallback 拼 session.id 掩盖了这一点，补 refetchInterval
    轮询到 active。
  - 修复后：tsc 通过、`npm test` 12 passed、Vite 构建成功、浏览器实测首连即 OPEN。
- 平台 WS 中继独立验证：python websockets 连 `/api/v1/ws/debug/{id}` 收到 scrcpy
  实帧（jpeg≈103KB、496×1080、source=scrcpy）。
- 边界：平台代理只转发 snapshots/image/tree/locators/validate/templates 与 WS 预览；
  vendor viewer 的 `/input/touch` 等触控端点未代理，浏览器内不能触控真机（只读调试）。

### 3. 独立审查（已做，独立上下文 subagent）

审查范围：main-chain-fix 全部 49 文件改动（三态门禁、缺失指标不写 0、租约互斥、
非 completed 运行 outcome 为 NULL 四条领域规则为重点）。结论：

- 四条领域规则全部守住（file:line 证据）；审查者自行实跑后端 7+55 测试与
  web 12 测试/tsc。
- 2 MEDIUM：导入运行可被 dispatcher 抢跑（`_QUEUED_SQL` 未排除 source='import'）；
  `_record_results` 解析 report.json 无异常保护。**未修复**（超出本轮授权，待定夺）。
- 3 LOW：internal.py validation_error 传字符串；runner debug 分支 close 异常未捕获；
  模板代理无项目隔离。ADVISORY：joint 静默降级 UI、expires_at 不续期等。

### 事故报告（业务库被短暂污染，如实记录）

隔离引导脚本首版用 `os.environ.copy()` 的副本设置环境变量，但脚本在当前进程
import app——应用实际连到了**业务库 testdock**。reconciler 将 161 条陈旧运行
（created ≤2026-10-26 20:53，全部早已废弃）置 errored(lease_expired)，其中 59 条
陈旧 queued 被派发后 pytest_error 快速失败；新增约 3182 条 run_events、59 条租约
创建/释放记录。已核实：无真机触碰（租约串号全为 P3xxx 假串）、无 completed/failed
结论被改写（reconciler 只动非终态）、无数据删除。脚本已修（写回 os.environ 并加
注释），隔离库已重建。此事故是隔离环境的教训：**同进程 import app 必须写回
os.environ，且引导脚本应启动后立刻自检所连库名。**

### 本轮残余风险和边界

- 性能采集（mobile_perf）真机链路未实测（授权三项不含；vendor 619 单测上轮已过）。
- 调试抽屉的图像模板上传交互未在浏览器内走（API 级已验证 POST /templates 成功）。
- 审查发现的 2 MEDIUM 未修复；`expires_at` 不续期意味着长会话可能到时失效。
- 环境收尾状态：隔离服务（18002）与 postgres 55432 保持运行供查验；隔离库
  live_chain_8a820943（名字见 `.runtime/live-chain-database.txt`）未删除——
  删除需另行授权。未 commit、未 push。

### 4. 追加：投屏验收（2026-10-27 02:07，按 william 降标后的通过标准）

新标准：web 页面能看到手机投屏（息屏/锁屏画面也算）即通过；不启动 app、不操作
界面、不解锁、不改任何设置。

- 流程：浏览器打开 `/#/ui` → 调试 tab → 点 84cb2c4e → 抽屉自动建会话 →
  实时预览徽标「已连接」，canvas 持续渲染息屏画面，连接保持无断开
  （截图 `12-mirroring-dozing.png`）。
- 接口证据：python 客户端连 `/api/v1/ws/debug/{id}`，5 秒收到 **49 帧**
  （≈9.8fps，恒定 9577 字节黑帧 = 息屏画面本身），单帧 496×1080
  （`12-mirroring-frame.png`）。全程未唤醒设备（mWakefulness=Dozing）。
- **结论：投屏链路通过**——平台 → runner debug job → vendor viewer(scrcpy) →
  平台 WS 中继 → 浏览器 canvas 全通，且不要求解锁。
- 附带观察（未修）：页面 reload 时抽屉曾自动创建会话后自身消失，留下孤儿 active
  会话占租约（需手动 DELETE 才释放）——抽屉 open 生命周期与会话关闭未完全对齐，
  建议后续修复。
- 另核实：演示假设备（ABC123456789 等）打开调试抽屉时 WS 会立即被服务端以 1000
  关闭并有限重试——对无真机的设备行为正确，不无限重连。

## 第四轮（2026-10-27）：修复发现的问题

对第三轮发现的缺陷做最小修复，全部带回归或复验。

- **孤儿调试会话（前端）**：两层防护——(a) createMutation 在途时抽屉被关，
  onSuccess 检测 openRef 后立即释放新会话；(b) 新增 open 转 false 的兜底 effect，
  任何不经 handleClose 的关闭路径（父组件清 target 等）都会就地关闭活动会话，
  不再占住设备租约。卸载兜底保留。注：02:03 的孤儿会话未复现出确切触发路径，
  但新防护覆盖该类问题的全部应用内路径；页面整页刷新/卸载导致的在途 DELETE 丢失
  仍由服务端租约 expires_at 兜底回收。
- **MEDIUM：导入运行可被 dispatcher 抢跑**：_QUEUED_SQL 排除
  `config_snapshot->>'source' = 'import'`（NULL 安全）；显式指派路径加同样守卫
  （reason=import_not_dispatchable）。回归：导入源运行不可被轮询/指派、
  不阻塞普通运行派发（test_run_submission.py 2 条）。
- **MEDIUM：_record_results 无异常保护**：report.json 损坏（半截 JSON/IO 错误）
  按"无性能报告"处理，finalize 照常完成，指标缺失由 missing_reason 表达。
  回归：损坏 report.json 下 finalize 完成、outcome=not_tested、0 指标行。
- **LOW：internal.py validation_error 传字符串**：改为列表；字符串曾被 join
  拆成单字消息。回归：POST /internal/runs/{id}/events 传非数组返回 400 且
  message 完整。
- **LOW：runner debug 分支 close 回报未捕获异常**：包 try/except ControlError，
  失败 emit_text(close_report_failed)，不再拖垮退出码。
- **LOW：模板代理无项目隔离（未修，如实说明）**：整个 API 请求路径不存在项目
  上下文（无鉴权、/resources 等同样返回全部项目），单独给 /templates 加隔离
  只能是装饰性的。真正修复需要「请求携带项目身份」的设计决策（全 API 层），
  待定夺后统一实施。（后继：第五轮按会话隔离落地，见下。）

验证：隔离库后端定向回归 test_run_submission + test_import_and_finalize +
test_p5_debug_api + test_runner_contracts **49 passed**（含 3 条新增）；
web tsc 通过、npm test 12 passed、Vite 构建成功；浏览器冒烟（新 bundle，
新隔离环境）：建会话 → active → WS OPEN → 关闭会话按钮 → 会话 closed、
活动租约归零、WS code=1000。环境备注：18002 隔离服务曾中断，已重启，
当前隔离库为 live_chain_68829ada（.runtime/live-chain-database.txt）；
旧库 live_chain_8a820943 未删除（等授权）。未 commit、未 push。

## 第五轮补充（2026-10-27）：复验发现测试引擎绑定缺陷

编排方（多 Agent 会话）按用户要求复验第四轮三项修复时发现：

- **test_run_submission.py 直连 dispatcher 的用例从未把引擎绑到测试库**：
  模块导入期 `from app.main import app` 先实例化 settings（此时
  TESTDOCK_DATABASE_URL 尚未被 _p3_common 设置，落到默认 DSN=业务库
  testdock），而这些用例不经过 client 夹具，没人调用 reset_db_engine。
  诊断插件实测引擎指向业务库。第四轮"49 passed"依赖同会话前序用例
  （client 夹具）残留的绑定，属运行顺序运气；单跑该用例必连业务库
  （本轮单跑复现 no_queued_run，所幸业务库当时无 queued 运行未造成
  写入——业务库 pytest 数据最新仍为 00:46 事故窗口，已核实无新污染）。
- 另一偶发源：client 夹具未设 TESTDOCK_SCHEDULER=0，lifespan 起的后台
  派发循环会抢走用例手动 dispatch_one 之前的 queued 运行。
- 修复（最小差异，沿用本仓先例）：spawns 夹具加 reset_db_engine(TEST_DB)
  （同 test_import_and_finalize._finalize 做法）；client 夹具加
  TESTDOCK_SCHEDULER=0（同 _p3_common.api_client 做法）。
- 系统性缺口（未修，待定夺）：_p3_common._p3_environment（autouse，
  绑测试库+关调度）没有任何测试模块导入，实为死代码；若在 tests/conftest.py
  挂载可一并消除此类隐患，但影响面是全部 P3 模块，另行决策。

复验证据：全新测试库（testdock_ut_fix3b，alembic head）跑
test_run_submission + test_import_and_finalize **30 passed**；
此前必挂的 test_import_source_run_does_not_block_normal_dispatch
隔离单跑通过；web tsc 通过、npm test 12 passed。测试沙箱库
（testdock_ut_fix3/fix3b）与残留隔离库 live_chain_68829ada 已删除，
临时诊断脚本已清理。未 commit、未 push。

## 第五轮（2026-10-27）：模板代理按调试会话隔离（用户指示后落地）

上一轮判为「需设计决策」的模板隔离，经进一步取证找到了正确边界：vendor 的
TemplateStore 绑定 `session.config.assets_dir`（viewer/app.py 784/1336/1405），
模板数据本身就是按调试会话隔离的——所以不需要全 API 的项目上下文，会话 id
就是隔离键。按 william 指示实施「模板代理强制显式调试会话」：

- **后端（routers/debug.py）**：删除「无 session_id 时挑最新活动会话」的全局
  兜底（A 项目的请求会落到 B 项目的 viewer 上，即上一轮报告的泄漏点）；
  `_template_session` 现要求显式 session_id，缺失走项目统一的
  validation_error（400），非活动会话 409，上游不可达 503 不变；
  templates_unavailable/501 契约随之删除。
- **前端**：endpoints.ts 三个模板函数（fetch/create/update）全部加 sessionId
  参数；DebugDrawer 新增 onSessionChange 上抛会话建立/释放；UiPage 持有
  debugSessionId——模板查询仅在「模板页签 + 有会话」时发起（queryKey 含
  会话 id），无会话渲染诚实空态（不调接口），登记表单无会话时拒绝提交，
  错误分支同步更新（no_active_debug_session/debug_session_required 已随
  后端契约消失，新增 debug_session_not_active 提示）。
- **回归**：test_templates_501_without_session 改为 test_templates_400_without_session
  （GET/POST/PUT 三方法均 400 validation_error 且 message 完整），新增
  test_templates_with_unknown_session_404；活动会话用例的 GET /templates
  补上 `?session_id=`。

验证（本轮新鲜执行）：隔离库 fix_main_b6918fed61 后端定向回归 **50 passed**
（建库→alembic→pytest→DROP WITH FORCE）；web tsc 通过、npm test 12 passed、
Vite 构建成功。真机浏览器冒烟（84cb2c4e，隔离服务 18002）：无会话时切到
模板页签 **不发任何 /templates 请求**（resource timing 为空）且显示
「尚未建立调试会话」空态；建会话 → active 后经页签触发请求 URL 为
`/api/v1/templates?session_id=d1bd57ba-…`，返回该会话 viewer 的真实清单
（2 条既有模板）；关闭抽屉后会话 API 确认 closed、页面回到无会话空态。
证据截图：.runtime/live-e2e-shots/13-templates-session-isolated.png。
未 commit、未 push。
