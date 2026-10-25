# moblie-xn 的 `src/mobile_perf` 能力盘点（平台复用取证）

> 取证对象：`D:\workspace\claudecode-test\moblie-xn`（只读，未做任何写入/git 操作/测试执行）。产出仅供 Lead 编写平台开发方案。
> 引用约定：`文件:行号` 中的 `文件` 均相对 `moblie-xn/src/mobile_perf/`，除非写了别的完整路径。行号取自 2026-10-25 的工作区快照。
> 可信度约定：**未核实** = 未能从代码或真实产物直接证实；其余结论均有代码行或真实 run 产物对应。
> 真实产物样本：`runs/trainapp-main-v3-run1-195853/`（target `com.sinosoft.trainapp`、49.4s、5 采集项、40 个 CSV）与 `runs/byd-academy-run*/180358`。

## 0. 结论速览（给方案决策用）

1. 形态是**零依赖 Python 库 + CLI + pytest 插件**三入口（`pyproject.toml`：`dependencies=[]`、`[project.scripts] mobile-perf='mobile_perf.cli:main'`、`[project.entry-points.pytest11]`）。平台若同机同 Python，**进程内 import `PerfKit` 是最短路径**。
2. 采集本体不在 Python 里：Python 只做**编排 + 拉取 + 聚合 + 入库 + 判定**，真实采样是 SoloPi APK（`com.alipay.hulu`）在手机上执行，经 Harness 子进程（`solo.py`）启动/停止。**必须真机 + adb + 预装 SoloPi + 无障碍授权**，无模拟器/无端侧替代路径。
3. 一次采集的产物是 `runs/<runId>/` 三件套：`artifacts/*.csv`（原始，gb18030）、`meta.json`、`report.json`（~99 KB/49s）、`report.html`（单文件、内嵌 ECharts 1.03 MB，零外部请求）。
4. 判定与趋势是**纯函数 / 只读库**：`judge.judge(report, spec)` 不读库不连设备（judge.py:93）；`kit.trend`/`kit.leak_trend` 只查 SQLite（kit.py:799/854）。平台可在不改库的情况下**离线复判**既有 report.json。
5. 设备互斥是**短事务文件锁**（Windows msvcrt，非 Windows 直接 passthrough 告警）：`gate.py`，锁目录 `~/.mobile-auto/leases/`。它只保证**同机多进程**不抢同一台设备，跨机器无任何互斥能力。
6. **三类关键平台缺口**（详见 §11）：没有实时指标推送（`serve` 仅预留，cli.py:366）、没有打标回调（`mark()` 只写内存→report，无 hook）、marks 在 HTML 里只进元信息表不出现在曲线图上（report.py:642）。
7. 报告 JSON 的 `artifacts` 字段是**采集机的绝对 Windows 路径**（真实样本为 `D:\workspace\...\artifacts\--21114_Network_....csv`，JSON 字符串内反斜杠转义），跨机器搬运后该字段失效——平台入库时应重新映射或只保留相对名。
8. 阈值/基线**存在 SQLite 的 baselines 表**，但 `JudgeSpec` 也可以完全由调用方内存构造；平台若要把「阈值即代码/配置中心」做进去，judge 层无需改动。

## 1. 包边界与工程事实

- `pyproject.toml`（41 行）：name `mobile-perf` 0.1.0，`requires-python=">=3.10"`，运行时依赖空；dev 依赖仅 `pytest>=8.0`、`ruff>=0.4`；`packages=["src/mobile_perf"]`；`[tool.pytest.ini_options]` `testpaths=["tests"]`、`addopts="-q"`、marker `device`。
- 依赖方向（代码注释与 `docs/嵌入指南.md` §1 引用了「ADR-0001 短事务设备准入」「ADR-0002 Harness 子进程边界」；`docs/adr/` 未逐份精读，**编号与标题的对应关系未核实**）：`metrics/judge/gate/session/report/supplement/jank/leak/startup/dialog` 基本为纯逻辑或只依赖标准库；`solo.py` 是**唯一**知道 Harness 存在方式的模块（ADR-0002：子进程边界，绝不 import Harness）；`cli.py`/`pytest_plugin.py` 是适配层；`kit.py` 是门面。
- 模块规模（行）：kit 1153、report 662、keeper 524、logwatch 422、cli 388、store 381、collector 323、pytest_plugin 289、metrics 256、supplement 254、solo 252、leak 238、startup 224、gate 191、judge 187、session 144、jank 110、adb 106、dialog 66、__init__ 16、__main__ 7。
- 唯一第三方资产：`assets/echarts.min.js`（1,030,900 字节），仅 HTML 报告使用，不参与采集。

## 2. 公共出口与门面 API

### 2.1 包出口（`__init__.py:3-15`）

```python
__all__ = ["CollectError", "JudgeSpec", "PerfKit", "ProfileMismatchError",
           "SessionSpec", "TrendError", "Verdict"]
```

- `CollectError / PerfKit / ProfileMismatchError / TrendError` ← `.kit`；`JudgeSpec / Verdict` ← `.judge`；`SessionSpec` ← `.session`。
- 注意：**没有导出** `CollectSession`/`CollectScope`/`ReadinessReport`/`MetricSpec`；平台若要类型标注需深引子模块（例如 `from mobile_perf.session import CollectSession`），这属于「可接受但非契约」的用法。
- `__main__.py:1-6` → `from .cli import main`，即 `python -m mobile_perf` 等价于 `mobile-perf`。

### 2.2 门面 `PerfKit`（kit.py:516，构造函数 kit.py:523）

全关键字构造：`PerfKit(*, adb_path=None, serial=None, repo_root=None, runs_dir=None, backend=None, store=None, db_path=None, adb_runner=None, keep_runs=200, keep_days=30.0, gate=None, clock=time.monotonic, sleep=time.sleep, device_call=None, doctor_fn=None, dialog_probe=None, device_profile=None, logwatch_factory=None, foreground_restore=True, dialog_dismiss=None)`。

- 默认值来源：`adb_path` 经 `adb.resolve_adb` 三级解析（adb.py:33）；`runs_dir` 默认 `<repo>/runs`；`store` 默认 `PerfStore(<repo>/data/mobile_perf.db)`；`gate` 默认 `FileLockGate()`（kit.py:606）。
- `serial` 允许为 `None`：此时**只读门面可用**（judge/trend/leak_trend 不碰设备），任何触设备入口会抛 `ValueError('必须提供设备 serial（显式参数或 CLI/env 解析）')`（kit.py:703 起）。
- 属性：`store`（kit.py:591）、`backend`（:598）、`gate`（:606）。`backend` 可注入实现 `CollectBackend` Protocol（kit.py:87：`start(target,items)->str`、`stop(session_id,output_dir)->dict`），默认 `HarnessBackend`（kit.py:95）走 `solo.perf_start/perf_stop` 子进程——**这是平台替换采集实现（例如自研端侧采集）的唯一官方缝**。

### 2.3 公共方法清单（签名 / 位置 / 语义）

| 方法 | 签名 | 位置 | 语义要点 |
|---|---|---|---|
| `ensure_ready` | `ensure_ready() -> ReadinessReport` | kit.py:703 | 需 serial；构造 `keeper.Keeper` 并把 `call_device/run_doctor/dialog_probe` 逐个包成 `_borrowed()` 短事务；`keeper.run()` 后做前后台守卫、可选弹窗代点、写 `store.upsert_device(serial,status=online\|needs_attention\|offline,health=report.as_dict())` 并缓存 `last_readiness`。**每次 `run_collect` 都会先跑它**。 |
| `collect` | `collect(spec: SessionSpec\|None=None, *, target=None, items=None, host_run_id=None, runs_dir=None, supplement=None, supplement_interval_s=..., start_mode=_UNSET, jank_thresholds_ms=None) -> CollectScope` | kit.py:1011 | 显式关键字优先于 `spec`；无 serial→`ValueError`；target/items 都缺→`TypeError('collect 需要 SessionSpec 或显式 target=/items= 参数')`。返回**上下文管理器**，真正的采集窗口从 `__enter__` 开始。 |
| `run_collect` | `run_collect(*, target, items, duration_s, host_run_id=None, runs_dir=None, supplement=True, supplement_interval_s=..., start_mode=None, jank_thresholds_ms=None) -> dict` | kit.py:1078 | `duration_s<=0`→`ValueError('duration_s 必须为正数')`；语义=`ensure_ready()` → `with collect(...)` → `sleep(duration_s)` → 返回 `scope.report`。**无人值守批量采集用这个**。 |
| `save_baseline` | `save_baseline(report, name, metric_keys=None) -> int` | kit.py:963 | 把 report.`metricsSummary` 每指标的 `median` 写 `baselines` 表，绑定 `target_pkg` + `device_profile`；返回写入行数。 |
| `judge` | `judge(report, spec: JudgeSpec) -> Verdict` | kit.py:992 | `store.fetch_baseline(spec.baseline)` 解析出 profile+data 后调 `judge.judge` 纯函数（`spec.resolved(...)`）。 |
| `trend` | `trend(pkg, metric, profile=None) -> dict` | kit.py:799 | 未知 metric→`TrendError`；无 run→`TrendError`；跨档案在 `_resolve_profile` 处抛 `ProfileMismatchError`（kit.py:61）。 |
| `leak_trend` | `leak_trend(pkg, profile=None, *, min_runs=leak.DEFAULT_MIN_RUNS, slope_threshold=None, level='fail')` | kit.py:854 | 取 `mem_pss_mb` 的跨 run 序列 → `leak.analyze_leak_trend` → 可选 `leak.leak_verdict`。 |

私有但**平台可能要用**的：`_borrowed(purpose, action)`（kit.py:612，短事务借设备）、`_shell(args, timeout_s=15.0)`（:617）、`_read_foreground_state`/`_restore_foreground`/`_guard_foreground`（:621/:638/:659）、`_measure_clock_offset_s`（:913）。使用私有 API 需接受无兼容承诺。

### 2.4 `SessionSpec`（session.py:21）/ `CollectSession`（session.py:73）/ `mark` 时序

```python
@dataclass(frozen=True)
class SessionSpec:            # session.py:21
    target: str
    items: list[str]
    host_run_id: str | None = None
    runs_dir: str | Path | None = None
    supplement: bool = True
    supplement_interval_s: float = supplement.DEFAULT_INTERVAL_S   # 2.0
    start_mode: str | None = None   # __post_init__ 校验 ∈ startup.STARTUP_MODES，否则 ValueError (session.py:39)
```

- `Mark`（session.py:48，frozen）：`label: str`、`elapsed_s: float`。
- `SessionRecord`（session.py:56）：`session_id/target/items/serial/started_at/stopped_at/duration_s/marks/stop_payload`；`marks_as_list() -> [{"label","elapsedS": round(...,3)}]`（session.py:69，camelCase 只有在序列化时出现）。
- `CollectSession`（session.py:73）构造全关键字：`(*, target, items, serial, start: Callable[[], str|None], stop: Callable[[str|None, str], dict], clock=time.monotonic, now=lambda: isoformat`）。`start()`（:109）重复调用抛 `RuntimeError('session already started')`；`elapsed_s() -> float|None`（:123）；`stop(output_dir) -> SessionRecord`（:129）先调注入的 `stop_call` 拿 payload，再算 `duration_s`。
- **`mark` 的签名与时序**：`mark(label: str) -> Mark`（session.py:117）。未 `start()` 时抛 `RuntimeError('cannot mark before start')`（:104 `_require_started`）；`elapsed_s = clock() - started_mono`（单调时钟，**与报告里的 startedAt 墙钟是两套时间基准**，所以 report 用 `elapsed_s` 浮点秒对齐曲线，不是时间戳）。打标**不落事件表、不发通知、不写文件**——只进 `SessionRecord.marks`，最终经 meta.json/report.json 暴露。

### 2.5 `CollectScope` 生命周期（kit.py:132）

- `__init__`（:143）关键字：`kit, *, target, items, host_run_id, runs_dir, supplement, supplement_interval_s, start_mode=None, jank_thresholds_ms=None`；`run_id` 属性（:183）；`mark(label)`（:186）未进作用域时抛 `RuntimeError('cannot mark before collect scope is entered')`——**平台若想在 UI 上打标，必须在 `with` 块内调用**。
- `__enter__`（:191）顺序：读前台状态 → 建 `CollectSession`（`start`=backend.start，`stop`=backend.stop）→ `session.start()` → 启动 `SupplementPoller` → 启动 crash watch（`_start_crash_watch` kit.py:1121）→ `_guard_foreground(phase='after_start')` → 若有 `start_mode` 则 `_run_startup`（:222，每条 adb shell 各自短事务借用）。
- `__exit__`（:246）**无条件**调 `finalize()`（:250）并 `return False`（异常继续上抛）。`finalize` 幂等，顺序：停补采轮询 → `session.stop(artifacts_dir)` → 停 logwatch → `after_stop` 前台守卫 → `validate_artifacts` → 若 `stop_payload['outputPath']` 存在则 `cleanup_after_pull`（**行数校验通过才删设备端**，得到 `integrity={deviceRowCheck:passed|failed|skipped, deviceDirRemoved:bool, mismatches?, probeError?}`）→ `aggregate_artifacts`（本地 CSV 聚合，**原始 CSV 永不入库**）→ 合并 supplement/jank/startup 聚合 → `report.summarize_aggregates` → `metrics.mark_not_tested(readiness.degraded_items)` → 写 `meta.json`（字段见 §3.4 实例）→ `report.build_report` → `store.record_session/record_metrics/record_run_artifacts` → 逐类 `record_event`（`supplement_degraded`、logwatch 的 crash/anr、`logwatch_warning`、keeper events、`foreground`、`startup`、`integrity_warning`）→ `collector.enforce_retention` → `report_data['events']=store.fetch_events(runId)` → `write_report` + `write_html` → `self.report`。
- 推论（对平台重要）：**report 的构造在 `with` 块退出时才完成**；块内的 `scope.report` 尚不存在（`__enter__` 未设）。若平台要边采边推，只能读 `scope.session`/补采实例或尾随设备 CSV。

## 3. 报告产物

### 3.1 `report.json` 顶层字段（`report.build_report` report.py:141；真实样本实测 19 键，另有条件键）

| 字段 | 类型 | 来源/说明 |
|---|---|---|
| `schemaVersion` | int | `SCHEMA_VERSION=1`（report.py:19），**目前无版本迁移逻辑**，平台需自己判版本。 |
| `runId` | str | 目录名即 runId；真实样本 `trainapp-main-v3-run1-195853`（自定义命名，非 `new_run_id` 的 `run-YYYYmmdd-HHMMSS-xxxx` 形态）。 |
| `target` | str | 被测包名，如 `com.sinosoft.trainapp`。 |
| `items` | list[str] | 采集项，如 `["CPU","FPS","Memory","Network","Battery"]`。 |
| `serial` | str | 设备序列号（真机 `749622c9`）。 |
| `deviceProfile` | str | 档案标识，由调用方/kit 生成，真实值 `2206123SC-Android14`（机型+系统）。**判定的可比性只比这个字符串**（§5）。 |
| `hostRunId` | str | 宿主运行 ID，用于把多次采集挂到同一业务用例上；真实样本与 runId 相同。 |
| `startedAt`/`stoppedAt` | ISO8601 带偏移 | 墙钟时间。 |
| `durationS` | float | 秒，真实样本 49.391。 |
| `soloSessionId` | str | SoloPi 会话 UUID，真实样本 `b6a85062-...`。 |
| `marks` | list | `[{"label":str,"elapsedS":float}]`，按打标顺序；真实样本 3 条（run1_start 3.812 / run1_half 26.641 / run1_end 49.391）。 |
| `artifacts` | list[str] | 拉回本地的 CSV 路径（**绝对 Windows 路径**，见 §0.7）。 |
| `metricsSummary` | dict[str,obj] | 每 canonical key 一条，结构见 §3.2。 |
| `series` | dict[str,obj] | 曲线数据，见 §3.2。 |
| `events` | list[obj] | 来自 `store.fetch_events`（SQLite 行直出，**含 `run_id` 字段**），见 §3.2。 |
| `startup` | obj\|null | 冷/温启动编排结果，真实样本非空。 |
| `integrity` | obj | `{deviceRowCheck, deviceDirRemoved}`。 |
| `jank` | obj\|null | 有分级指标时出现：`{sourceMetric, granularity:'per_sampling_window', thresholdsMs}`；真实样本非空。 |

条件键：`startup`、`jank` 可为 `null`；`series` 可能缺某些指标（无样本）。

### 3.2 子结构

- `metricsSummary[key]` = `{unit, source, min, median, mean, max, p90, sampleCount, labelZh, labelEn}`（`_with_metric_labels` report.py:190；`summarize_aggregates` :206）。**降级时额外两个字段**：`notTested: true`、`notTestedReason: "<中文原因>"`（metrics.mark_not_tested:209；真实样本 battery 指标带 `'设备充电中，巡检 degraded_items 含 Battery，该采集项降级 not_tested'`）。
- `series[key]` = `{unit, source, labelZh, labelEn, points: [[x, y], ...]}`；`x` = 相对首样本的**秒**（`_row_time_ms` report.py:110 支持 `RecordTime`(ms)/`SimpleTime`(s)/`elapsed_s`(s)/行号回退），y 为值；`MAX_SERIES_POINTS=3600` 等距抽样 `_downsample`（:134）。真实样本 17 条 series。
- `events[i]` = `{run_id, ts, kind, detail}`（store 行直出）。真实 `detail` 例：`{key:'gpu_util_pct', reason:'output_unparseable_or_unsupported', rounds:23, errors:0}`，`kind='supplement_degraded'`。已知 kind 集合（代码内出现）：`supplement_degraded`、`crash`、`anr`、`logwatch_warning`、keeper 的 `tcpip_heal`/`accessibility_needs_attention`/`clock_offset`/`dialog_*`、`foreground`、`startup`、`integrity_warning`（**未逐一穷举，未核实**是否存在其他 kind）。
- `startup`（真实样本全字段）：`{mode:'cold', metricKey:'app_cold_start_ms', ms:370.0, msSource:'total_time', launchState:'COLD', waitTimeMs:373.0, thisTimeMs:null, displayedMs:370.0, deviationMs:0.0, fullyDrawnMs:null, component:'com.sinosoft.trainapp/.MainActivity', status:'ok', error:null, elapsedS:2.859, ts:'...'}`。
- `solo.stop_payload` 不进最终 report（只用于拿 `outputPath`），`meta.json` 里也不含原始 payload 全量。

### 3.3 HTML 单文件如何内嵌 ECharts（`report.write_html` report.py:393-447）

1. 读 `assets/echarts.min.js` **全文**内嵌进 `<script>`，先做 `replace("</script", "<\\/script")`、`replace("<!--", "<\\!--")`（report.py:395-398）。
2. report 数据以 `json.dumps(ensure_ascii=False).replace("</", "<\\/")` 注入 `<script id="report-data">window.__REPORT__ = {...}</script>`。
3. 每个指标一个 `<div class="chart" id="chart-<key>">`；温度-帧率合并图 id `chart-combined-thermal-fps`（`_COMBINED_CHART_ID` report.py:450，`_combined_thermal_markup` :491，双 Y 轴，条件：series 有 `fps_frame` 且有 `temp_battery_c`/`gpu_util_pct`）。
4. 模板 `_HTML_TEMPLATE.format(...)` 之后**再**替换占位符 `__STARTUP_MARKLINE__`（`_startup_markline_script` :501）与 `__JANK_THRESHOLD_LINE__`（`_jank_threshold_line_script` :604），避免 CSS 花括号与 `format` 冲突。
5. 运行期**零外部请求**（无 CDN），因此可离线分发/挂附件。真实 `report.html` = 1,087,797 字节。
6. 图表上只有两类标注：启动点 markLine、卡顿三档阈值虚线；**marks（业务打标）不画竖线**，只出现在元信息表 `_meta_rows`（report.py:621-647，共 14 行、标签是「中文 / English」双语，Marks 行直接 `json.dumps` 整串，report.py:642）。

### 3.4 文件命名与落盘目录

- 目录：`<runs_dir>/<runId>/`；默认 `runs_dir=<repo>/runs`（kit.py 默认）。`collector.create_run_dir`（collector.py:51）已存在则 `RunDirError`。
- 库自动命名：`new_run_id(now=None) -> 'run-YYYYmmdd-HHMMSS-<4hex>'`（collector.py:45），目录名合法模式 `RUN_DIR_PATTERN=^run-\d{8}-\d{6}-[0-9a-f]{4}$`（collector.py:34；`ADB_TIMEOUT_S=30.0` :31）——**该 pattern 只用于 `enforce_retention` 的安全删除**，所以自定义 runId（如真实样本的 `trainapp-main-v3-run1-195853`）不会被保留策略清理。真实 `runs/` 下 4 个目录全部是自定义名。
- 单 run 目录实测内容：`artifacts/`（40 个 CSV，英文文件名如 `pss-main-19728_Memory_....csv`、`fps_FPS_....csv`、`frame_delay_max_FPS_....csv`）、`meta.json`、`report.json`、`report.html`。
- CSV 编码 `gb18030`（collector.py:26、report.py:22）；**列名仍是中文**（`全局占用(%)`、`帧率(帧)`…），英文开关只改文件名（见 §10）。
- 保留策略 `enforce_retention(runs_dir, store, *, keep_runs=200, keep_days=30.0, now=None) -> list[str]`（collector.py:278）：只清**名字匹配 pattern 且**库里有记录的 run，并 `store.delete_run`。
- 真实 `data/`：`mobile_perf.db` + `mobile_perf.db.bak-20261025`（人工备份，非代码行为）。
- 历史产物目录 `perf-output/`（老版脚本产物，非当前代码路径）：`extract_metrics.py`、`perf_analysis.json`、`performance-a5b87b47-.../`，其 CSV 为**中文文件名**——即英文开关未生效时期（或官方版 SoloPi）的对照样本。

## 4. 指标字典与缺失值语义（metrics.py）

`MetricSpec`（metrics.py:23，frozen）：`key/unit/source/label_zh/label_en/solo_columns: tuple[str,...]=()/solo_shapes: tuple[str,...]=()`。`METRICS: dict[str, MetricSpec]`（:39）共 **26 条**（21 条多行 + 5 条单行：`battery_pct`/`temp_battery_c`/`gpu_util_pct`/`app_cold_start_ms`/`app_warm_start_ms`）。`source` ∈ `solo_pi | pc_supplement | pc_orchestration | analysis`。

| key | unit | source | 中文标签 | 原始列/形状 | 行 |
|---|---|---|---|---|---|
| cpu_process_pct | % | solo_pi | 应用进程CPU占用 | 形状 `应用进程-main-*(%)` | 43 |
| cpu_global_pct | % | solo_pi | 全局CPU占用 | `全局占用(%)` | 48 |
| mem_pss_mb | MB | solo_pi | 应用PSS内存 | `PSS-main-*(MB)` | 53 |
| mem_privdirty_mb | MB | solo_pi | 应用PrivateDirty内存 | `PrivateDirty-main-*(MB)` | 58 |
| mem_global_mb | MB | solo_pi | 全局内存占用 | `全局占用(MB)` | 63 |
| fps_frame | fps | solo_pi | 帧率 | `帧率(帧)`（列标「帧」实为每秒帧数） | 68 |
| frame_delay_ratio_pct | % | solo_pi | 帧延迟占比 | `延迟占比(%)` | 74 |
| frame_delay_count | 次 | solo_pi | 帧延迟次数 | `延迟次数(次)` | 79 |
| frame_delay_max_ms | ms | solo_pi | 最长帧延迟 | `最长延迟时间(ms)` | 84 |
| net_rx_kbps / net_tx_kbps | kbps | solo_pi | 全局下/上行速率 | `全局下行速率(KB)`/`全局上行速率(KB)`（列标 KB 实为 KB/s） | 89/95 |
| net_rx_total_kb / net_tx_total_kb | KB | solo_pi | 累计全局下/上行流量 | `累计全局下行流量(KB)`/`…上行…` | 100/105 |
| battery_current_ma / battery_current_avg_ma | mA | solo_pi | 实时/平均电流 | `实时电流(mA)`/`平均电流(mA)` | 110/115 |
| battery_power_mw / battery_power_avg_mw | mW | solo_pi | 实时/平均功率 | `实时功率(mW)`/`平均功率(mW)` | 120/125 |
| battery_pct | % | solo_pi | 电量 | **无原始列**（真机样本无此列），映射待上游确认 | 130 |
| temp_battery_c | °C | pc_supplement | 电池温度 | 无 SoloPi 列，PC 侧 `dumpsys battery`（÷10） | 131 |
| gpu_util_pct | % | pc_supplement | GPU占用 | 无 SoloPi 列，`dumpsys gpu` 解析（机型相关） | 132 |
| app_cold_start_ms / app_warm_start_ms | ms | pc_orchestration | 冷/温启动耗时 | 无 SoloPi 列，`am start -W` 单样本 | 135/136 |
| app_jank_light/heavy/severe_count | 次 | solo_pi | 轻/重/严重卡顿窗口数(>100/>300/>700ms) | 由 `frame_delay_max_ms` 派生 | 141/145/149 |
| mem_pss_slope_mb_per_day | MB/day | analysis | 应用PSS内存增长斜率 | 由 `leak.analyze_leak_trend` 计算，非采集 | 154-160 |

- 中文列名→canonical key 的**唯一翻译点**：`column_to_metric(column) -> MetricSpec|None`（metrics.py:181），先精确列名 `_COLUMN_INDEX`（:164），再按形状 `_SHAPE_INDEX`（:165）前缀/后缀匹配（`*` 通配 pid 段）；字典外列一律 `None`（**丢弃**，不报错）。索引唯一性在 **import 期**强校验：重复映射 `raise RuntimeError`（:166-178）。
- 聚合口径 `aggregate_row(metric_key, values) -> {metric_key, unit, source, min, median, mean, max, p90, sample_count}`（:237）；`percentile(sorted_values, ratio)`（:226）线性插值；`median` = `percentile(0.5)`。
- **缺失值语义（关键）**：CSV 里的空值/无法解析值**不进入样本序列**（不是 NULL、也不是 0），该指标最终体现为「样本缺失」而非「值为空」：
  - 若整类都无样本 → 该 key 不进 `metricsSummary`/`series`（report 侧不写键）；
  - 若被巡检判定降级（充电时 Battery/Temperature）→ `mark_not_tested` 写 `notTested:true` + 中文 `notTestedReason`；
  - 判定侧见到 `notTested` 会跳过该指标（不判 passed/failed），见 §5；
  - **没有** `null`/NaN 进入 JSON（`json.dumps` 默认会写 `NaN` 非法 JSON，代码未使用 float('nan')，未核实是否存在 p90 为空字符串的历史脏数据）。
- 采集中断的补采缺失走事件而非字段：`supplement_degraded`（`reason` ∈ `adb_command_failed` / `output_unparseable_or_unsupported`，supplement.py 的 `_collect_degraded`）。

## 5. 判定（judge.py）

- `DEFAULT_MIN_SAMPLES = 10`（judge.py:20）；`_OPS = {lt, le, gt, ge}`（:23）；`_LEVELS=("fail","warn")`（:31）；三态常量 `VERDICT_PASSED='passed'`、`VERDICT_FAILED='failed'`、`VERDICT_NOT_TESTED='not_tested'`（:33-35）。
- `JudgeSpec`（:39，frozen）：`baseline: str`、`thresholds: dict[str, tuple[str, float, str]]`（metric_key → (op, threshold, level)）、`min_samples: int|None=None`、`baseline_profile: str|None=None`、`baseline_data: dict = field(default_factory=dict)`；`__post_init__`（:53-62）**只**校验每个阈值的 op ∈ `_OPS`、level ∈ `_LEVELS`（不校验 baseline 是否存在/非空，故空 baseline 在 judge 第 3 步才变成 `not_tested`）；`effective_min_samples` 属性（:65，`min_samples or DEFAULT_MIN_SAMPLES`）；`resolved(*, profile, data) -> JudgeSpec`（:68，`dataclasses.replace`）。
- `judge(report, spec) -> Verdict`（:93）是**纯函数**：不 import 业务模块、不读库、不连设备、不改入参。`Verdict`（:74）：`verdict, baseline, checks[], warnings[], reason|None` + `to_dict()`（:83，camelCase 输出）。
- 阈值形态：`"cpu_process_pct": ("le", 60.0, "fail")`，即「指标 median 必须 ≤ 60，否则 fail」。**判的是 median，不是 mean/p90**（check 里同时带 `median` 与 `threshold`）。
- 判定顺序（短路早退，全是 `not_tested` 而非报错）：
  1. `report['metricsSummary']` 空 → `not_tested('run 报告没有 metricsSummary 聚合数据，无法判定')`；
  2. `spec.baseline_profile` 有值且 `report['deviceProfile']` 不等 → `not_tested('设备档案不匹配：baseline … 绑定 …，run 为 …（口径不可比）')`；
  3. `spec.baseline_data` 空 → `not_tested('baseline … 不存在或没有任何指标数据，无法判定')`；
  4. 按 `sorted(spec.thresholds.items())` 逐项：entry 缺失 → `not_tested('run 缺少阈值引用的指标 … 的聚合数据')`；`entry.notTested` → 记 skipped + warning（`{metricKey, notTested:true, level:'warn', ok:None, reason}`）并 continue；`sampleCount < effective_min_samples` → `not_tested('指标 … 样本数 N 低于下限 M，统计口径不可判定')`；median 或 baseline 值缺 → `not_tested('缺少 median 或 baseline 参照值')`；
  5. 满足条件时生成 check：`{metricKey, median, op, threshold, level, ok, baselineValue, baselineSourceRunId, sampleCount, sourceRunId, window:{startedAt, stoppedAt}}`；
  6. skipped 且 `checks` 为空 → `not_tested('阈值指标全部标注 not_tested，无法判定: …')`；
  7. 任一 `ok=False` 且 `level=='fail'` → `failed`，否则 `passed`；`level=='warn'` 只进 `warnings`，**不拉低结论**。
- 基线可比性规则只有一条硬规则：**`deviceProfile` 字符串相等**（不解析机型/OS/分辨率/是否 root）。平台若需要更细的可比性（同 ROM、同刷新率），必须自己加一层 profile 规范化（否则不同机型字符串必然不匹配→永远 not_tested）。
- `not_tested` 原因形态是**自由中文文本**（`_not_tested` judge.py:185），**没有枚举常量**——平台若要做「原因分类」需正则/关键词匹配（已知 6 类文案见上）。**未核实**是否还有其他调用方绕过 `judge` 直接造 Verdict。

## 6. 设备准入 `DeviceGate`（gate.py，ADR-0001「短事务」）

- 常量：`DEFAULT_LEASE_DIR = Path.home()/'.mobile-auto'/'leases'`（:27）；锁文件 `<digest>.lock`，`digest = sha256(serial)[:24]`（`_digest` :53）；伴生 `<digest>.holder.json` 字段 `{pid, hostname, worker, purpose, acquired_at}`（gate.py:153-172）——`worker` 当前**恒为空串**（`"worker": ""`，没有调用方传入），**仅持锁者写、释放时不擦除**（便于事后归因；写失败静默忽略 `OSError`）。
- 协议：`DeviceGate` Protocol（:37）：`borrow(serial, *, purpose: str, timeout_s: float = 10.0) -> AbstractContextManager[None]`（:40）。平台只需实现这一个方法即可注入 `PerfKit(gate=...)`。
- 实现 `FileLockGate`（:77）：构造 `(lease_dir=None, *, serial=None, on_warning=None, platform=None, pid=None)`；`path`/`holder_path` 属性（:98/:102）；`held` 属性（:111）；`borrow`（:114）。
- **精确语义（进入/退出/持锁窗口）**：
  - 非 Windows（`platform` 判定）：发 `{"reason":"file lock unavailable on non-windows"}` warning（:124）并返回 `contextlib.nullcontext()` —— **完全不加锁**（多机/跨 OS 场景下等于无互斥，只能靠调度层）。
  - Windows：`_borrow_windows`（:130）打开锁文件 → `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)` **非阻塞**锁 1 字节（:140）。
  - 成功：`_write_holder(purpose)`（:153）后返回 `_HeldToken`（:64）；窗口 = **进入 `with` 到退出**，期间持有 OS 文件锁（进程崩溃时 OS 自动释放——这是选文件锁而非租约服务的原因）。
  - 失败：若 `<digest>.holder.json` 的 `pid` **等于当前进程 pid** → 返回 nullcontext（**嵌入模式重入放行**，:143-148）；否则 `raise GateBusyError("设备 {serial} 正被其他进程占用（purpose={purpose}），fast-fail 不重试")`。`GateBusyError(RuntimeError)`（:33）。
  - `_HeldToken._release()`（:174）：`msvcrt.locking(..., LK_UNLCK, 1)`（:182）→ 关句柄；**幂等**（`__exit__` 多次调用安全）。
  - `timeout_s` 参数**保留但本实现不等待**（fast-fail）。重试是宿主策略。
- **持锁窗口有多短**：`kit._borrowed(purpose, action)`（kit.py:612）每个设备动作一次 `borrow`。即 `ensure_ready` 的每条 adb 命令、startup 的每条 `am start`、`_read_foreground_state` 等都**各自**借一次。而 `collect` 窗口内（可能数分钟）**不持锁**——所以「短事务」= 只防命令级交错，不防整段采集被别人插入。平台若需「一次测试独占设备 30 分钟」，**必须由平台自己的长租约层保证**，`FileLockGate` 不提供。
- **与宿主长租约的关系（官方缝）**：`docs/嵌入指南.md` §2 明确：宿主持整生命周期租约时，注入一个把租约桥接成 `DeviceGate` 的适配器；mobile-auto 的参考实现是 `src/mobile_auto/_perf_gate.py` 的 `PerfDeviceGate(leases={serial: session._lease})`。此时所有 `borrow` 立即返回 nullcontext（因为宿主已持锁，或 holder.json pid 相同）。
- **CLI 独立模式如何对等互操作**：CLI 每个进程新建 `FileLockGate()`（kit.py:606），无显式 serial 时 `gate.borrow` 里做 `_require_serial`（:105，缺 serial 抛错）。两个 `mobile-perf` 进程抢同一台设备时，后到者在**首个设备命令**处收到 `GateBusyError` 并以非 0 退出（cli 未捕获 → traceback 到 stderr）。与宿主长租约进程互操作的前提是**双方都用同一 `DEFAULT_LEASE_DIR` 且 holder.json 的 pid 语义一致**；若宿主用自己的锁机制（非 msvcrt 文件锁），CLI 与宿主**不互斥**——这是当前最实际的落地风险。`_write_holder` 已核实：写 `pid`/`socket.gethostname()`/`worker=""`/`purpose`/UTC 毫秒 `acquired_at`（gate.py:153-172），失败静默。

## 7. 本地存储（store.py，SQLite WAL）

- `PerfStore(db_path)`（:98）：`_enable_wal`（:111）`PRAGMA journal_mode=WAL`、`_BUSY_TIMEOUT_MS=5000`、`_WAL_SWITCH_TIMEOUT_S=5.0`、`PRAGMA foreign_keys=ON`。连接**单连接、非线程安全**（未加锁，未核实多线程调用行为）。
- 表：
  - `sessions`（:128 起写入）：`run_id PK, solo_session_id, serial, device_profile, target_pkg, target_version, items_json, started_at, stopped_at, duration_s, sample_count, host_run_id, clock_offset_ms, status, run_dir`。
  - `metrics`：`(run_id, metric_key)` 复合 PK，`unit, source, min, median, mean, max, p90, sample_count`，FK cascade。
  - `events`：`id INTEGER PK AUTOINCREMENT, run_id, ts, kind, detail_json`。
  - `baselines`：`(name, metric_key)` 复合 PK，`target_pkg, device_profile, value, source_run_id, created_at`。
  - `runs_artifacts`：`run_id PK, dir_uri`。
  - `devices`：`serial PK, model, os_version, device_profile, status, health_json, updated_at`（`upsert_device` :309）。
- 查询能力：
  - `fetch_sessions(target=None, limit=50)`（:159，`ORDER BY started_at DESC`）；
  - `fetch_metrics(run_id)`（:207）；
  - `fetch_metric_series(target, metric_key, profile=None, limit=1000)`（:213，JOIN sessions+metrics，`ORDER BY started_at ASC`，**只返回含该指标的 run**，profile 过滤在 SQL 层）；
  - `fetch_events(run_id)`（:259）、`fetch_baseline(name)`（:303）、`fetch_devices()`（:348）、`run_ids()`（:371）、`fetch_run_artifacts`（:364）。
  - **无分页、无聚合 API、无时间范围过滤**：平台做大盘/趋势时需自己拉全量再算，或用 `fetch_metric_series` 的 limit 截断。
- 写路径：`record_session`（:128）、`record_metrics(run_id, aggregates)`（:177，**先 DELETE 该 run 再批量写**，幂等）、`record_event`（:243）、`record_baseline`（:276）、`delete_run`（:374，级联删 metrics/events/artifacts）。
- 索引与版本：**已核实无** `CREATE INDEX`（`_SCHEMA` store.py:26-93 只有 PK 与 FK 隐式索引）、**无** `user_version`（无 schema 版本号/迁移机制，`store.py` 全文无 `ALTER TABLE`）。`fetch_metric_series` 的 `ORDER BY s.started_at ASC LIMIT ?`（store.py:235）在 run 数上万后需补索引或物化，平台要自己管 schema 升级。
- **跨档案趋势拒绝规则**：不在 store，而在 `kit._resolve_profile(pkg, sessions, profile)`（kit.py:61）。规则：显式传 `profile` → 只保留该档案的 run；未传且历史 run 跨多个 `device_profile` → `raise ProfileMismatchError`（`ProfileMismatchError(TrendError)` kit.py:53），提示口径不可比；未传且只有单一档案 → 用它。`trend` 返回体带 `profileMismatch` 字段（kit.py:799 段）。
- 并发：WAL + busy_timeout 5s 支撑多进程读写（`嵌入指南.md` §5 明确 xdist 场景）；但**没有 schema 版本表**（`user_version` 未被读写，未核实），平台做升级需自己管。

## 8. 采集链路组件清单（一句话能力 + 对外入口）

| 文件 | 能力 | 对外可调用入口 |
|---|---|---|
| `adb.py` | ADB 路径三级解析 + 设备列举 | `resolve_adb(explicit, env=None, repo_root=None) -> Path`（:33）；`default_repo_root()`（:23）；`bundled_adb_path`（:28）；`adb_runner(cmd, timeout_s)`（:59）；`default_call_device(adb_path, *, runner=None, default_timeout_s=15.0)`（:76）→ `call(args, timeout_s=None)`（:81）；`list_devices`（:89）；`first_online_device`（:100，**多台在线返回 None**）。 |
| `solo.py` | 唯一知道 SoloPi Harness 的模块，子进程边界 | `run_harness(args, *, adb_path=None, serial=None, entry=None, repo_root=None, timeout_s=120.0, runner=None) -> HarnessResult`（:101）；`perf_start(...)`（:148，`['perf-start','--target-package',pkg,'--items',','.join(items)]`）；`perf_stop(...)`（:176，`['perf-stop','--session-id',sid,'--output',dir]`）；`doctor`（:204）；`perf_start_session_id(payload)`（:223）；`perf_stop_artifacts(payload)`（:245）。`subprocess_env()`（:78）强制 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` 并剔除 `PYTHONPATH`。 |
| `collector.py` | run 目录、CSV 聚合、拉取完整性、设备端清理、保留策略 | `new_run_id`（:45）、`create_run_dir`（:51）、`validate_artifacts`（:59）、`aggregate_artifacts`（:101）、`write_meta`（:121）、`verify_pull_integrity`（:174）、`remove_device_session_dir`（:238，仅允许安全前缀正则 :238）、`cleanup_after_pull`（:256）、`enforce_retention`（:278）。 |
| `keeper.py` | 设备就绪巡检 + 自愈（tcpip/无障碍/充电/前台/时钟/弹窗探针） | `Keeper(...).run() -> ReadinessReport`（:304/:353）；纯函数 `parse_devices_stdout`（:101）、`parse_battery_charging`（:111）、`parse_accessibility_bound`（:152）、`parse_foreground_package/component`（:183/:189）、`parse_wlan_ip`（:198）、`evaluate_clock_offset`（:204）、`is_tcp_serial`（:212）、`default_dialog_probe`（:251）、`parse_config_get_response`（:227）。`ReadinessReport`（:71）字段：`serial, ok, needs_attention, healed, checks, events, degraded_items, foreground_package, clock_offset_s` + `as_dict()`（camelCase）。 |
| `logwatch.py` | 旁路 `adb logcat` 抓 crash/ANR（不持设备锁） | `LogWatch(*, adb_path, serial, packages=None, clock_offset_s=None, spawn=None, stack_max=60)`（:326）`.start()/.stop(timeout_s=5.0) -> list[{kind,ts,detail}]`；纯函数 `parse_logcat_line`（:58）、`filter_by_packages`（:135）、`merge_duplicates`（:148）、`convert_ts`（:188）、`LogcatParser`（:204）。 |
| `supplement.py` | PC 侧温度/GPU 补采（不改采集项） | `SupplementPoller(*, adb_path, serial, interval_s=2.0, clock_offset_s, collect_temperature=True, collect_gpu=True, call_device=None, sleep, now)`（:86）`.start()/.stop(join_timeout_s=30) -> SupplementResult`（:77）；`write_supplement_csv`（:226）；`aggregate_samples`（:245）；`parse_battery_temperature`（:31）、`parse_gpu_utilization`（:37）、`to_unified_elapsed_s`（:61）。 |
| `startup.py` | 采集窗口内冷/温启动编排 + 双路计时 | `run_startup(*, shell, target, mode, sleep, now, elapsed) -> StartupResult`（:151）；`parse_am_start_w`（:57）、`parse_displayed_ms`（:90）、`parse_fully_drawn_ms`（:96）、`parse_duration_ms`（:46）、`resolve_launcher_component`（:115）。 |
| `leak.py` | 跨 run 内存泄漏 OLS | `analyze_leak_trend(runs, *, min_runs=3, min_span_hours=24.0) -> LeakTrend`（:78，`as_dict()` camelCase）；`leak_verdict(analysis, *, threshold, level='fail', baseline='leak_trend') -> Verdict`（:172）。 |
| `jank.py` | 卡顿三档派生（窗口口径，非逐帧） | `validate_thresholds`（:41）、`grade_samples(samples, thresholds_ms) -> {grade:count}`（:58，`>` 阈值才计，分桶互斥只计最高档）、`read_source_samples`（:73）、`aggregate_from_artifacts`（:92）。 |
| `dialog.py` | 权限弹窗代点（默认关，需人工标定坐标） | `make_dialog_dismiss_probe(call_device, serial, coords)`（:43）、`decide_dismiss`（:30）、`build_tap_args`（:37）、`is_permission_dialog_in_foreground`（:25）。 |
| `gate.py` | 同机进程级设备短事务互斥 | 见 §6。 |
| `session.py` | 采集会话时间轴与打标 | 见 §2.4。 |

## 9. 对外入口：CLI（cli.py）与 pytest 插件

### 9.1 CLI（`prog=mobile-perf`，进度写 stderr，最终 JSON 写 stdout；`build_parser` cli.py:27，`main(argv=None, *, kit_factory=None) -> int` cli.py:372）

| 子命令 | 参数 | 行为 |
|---|---|---|
| `doctor` | `--serial`、`--adb` | `_run_doctor`（:158）：`kit.ensure_ready()` 输出 readiness JSON。 |
| `collect` | 位置参数 `pkg`；`--items`（默认 `CPU,Memory`）、`--duration`（默认 180.0）、`--serial`、`--adb`、`--runs-dir`、`--run-id`、`--start-mode {cold,warm}`、`--jank-threshold 'light:100,heavy:300,severe:700'`、`--device-profile` | `_run_collect`（:174）：`kit.run_collect(...)`，stdout 输出 `{runId, runDir, reportJson, reportHtml, ...}`。默认不含 FPS（FPS 会弹告知框，无人值守不可用）。 |
| `report` | 位置参数 `run_id`；`--runs-dir`、`--db`、`--adb`、`--baseline`、`--threshold`（可重复，`METRIC:OP:VALUE:LEVEL`） | `_run_report`（:267）：`report.assemble_run_report` 重建 report（meta.json 优先、库行补 `deviceProfile`、无 metrics 行则重聚合），有 `--baseline` 时构造 `JudgeSpec` 并 `kit.judge`，把 `report_data['verdict']` 写入后**重写 JSON+HTML**，stdout 输出 `{runId, runDir, reportJson, reportHtml, verdict?}`。 |
| `trend` | 位置参数 `pkg`；`--metric`（必填）、`--profile`、`--serial`、`--adb`、`--db` | `_run_trend`（:322）：只读库，不探测设备。 |
| `leak` | 位置参数 `pkg`；`--profile`、`--min-runs`、`--slope-threshold`、`--level {fail,warn}`、`--serial`、`--adb`、`--db` | `_run_leak`（:341）：同上只读库。 |
| `serve` | 无 | `_run_serve`（:366）**预留未实现**，返回 2 并提示「设计方案 §6.6」。 |

- serial 解析 `_resolve_serial`（:142）：显式 `--serial` > 环境变量 `MOBILE_PERF_SERIAL` > `adb.first_online_device`。
- 阈值解析 `_parse_thresholds`（:252）、卡顿阈值 `_parse_jank_thresholds`（:228）。
- 退出码约定：成功 0；`GateBusyError` 与其余异常**未统一捕获**（走 traceback，退出码 1），平台若用 CLI 必须自己判 stderr。**未核实** `main` 是否捕获 `PerfKit` 的 `ValueError`。

### 9.2 pytest 插件（`pytest_plugin.py`，entry point 自动加载）

- 选项（`pytest_addoption` :26）：`--mobile-perf`（bool，**opt-in：不开时 `perf` fixture 直接 `pytest.fail`，零行为**）、`--mobile-perf-serial`、`--mobile-perf-items`、`--mobile-perf-runs-dir`、`--mobile-perf-db`、`--mobile-perf-baseline`、`--mobile-perf-threshold`（可重复 `METRIC:OP:LIMIT:LEVEL`）。
- ini：`mobile_perf_serial`、`mobile_perf_items`、`mobile_perf_thresholds`（`pytest_configure` :66）。
- marker：`mobile_perf_baseline(name)`；基线优先级 **session 级 `baseline=` 参数 > marker > `--mobile-perf-baseline`**。
- fixture：
  - `mobile_perf_kit`（:233，session 作用域；无 `--mobile-perf` 时 `yield None`；无 serial → `pytest.UsageError`；会话结束 `store.close()`）——**平台注入点**（同名覆盖即可换 adb/gate/device_profile/共享 store）。
  - `perf`（:267）→ `PerfFixture`（:188），`perf.session(target, items=None, *, baseline=None, thresholds=None, min_samples=None, host_run_id=None)`（:196）返回上下文管理器；用完读 `perf.results[-1]`（`PerfResult(run_id, target, report, verdict, error, judge_error, marks)` :98）。
- `_PerfSession`（:132）：`__enter__` 先 `kit.ensure_ready()` 再 `kit.collect(...)`（:150）；`__exit__`（:162）**无条件**调 `scope.__exit__`、再有 spec 时 judge、**异常只记 `result.error` 不抛新异常**（不掩盖原异常）。
- `pytest_runtest_makereport`（:278，hookwrapper）把 `section_text()` 追加到 `report.sections` 标题 `'mobile-perf'` → 进 JUnit XML / pytest-html。**阈值判 failed 不改变用例结论**，由宿主断言。
- 语义边界：插件只覆盖「pytest 驱动的用例」。平台若是自研 runner/HTTP 调度，应直接 import `PerfKit`，不要把场景写进 pytest。

## 10. SoloPi 端侧依赖与目录布局实例

### 10.1 端侧依赖（必须真机）

- APK：仓库内 `SoloPi/apk/SoloPi_v1.0.3.apk`（官方基线，`SHA256SUMS.txt` 记录 `d1486161258b1eea8514c0b8e04bb4c3c838bdeb1c494ce10aa2e8b20c0e4acf`）；自编译产物 `dist/solopi/SoloPi-selfbuild-debug.apk`（`build.cmd` 需 JDK 11；`cutover.cmd` 一键卸载官方→装自编译→写开关）。
- 包名：`DEFAULT_PACKAGE='com.alipay.hulu'`（`SoloPi/solopi-skill/scripts/harness/src/solopi_harness/solopi_ai.py:46`）；伴生 `com.alipay.hulu.agentmodel`（:47）；控制 URI `content://com.alipay.hulu.agentmodel.control`（:48）；ADB scheme activity `com.alipay.hulu.common.scheme.AdbSchemeActivity`（:53）。
- ADB 三级解析顺序（adb.py:33）：**显式参数** > 环境变量 `MOBILE_PERF_ADB` > 环境变量 `ADB` > 随包 `SoloPi/platform-tools/adb.exe`（platform-tools 37.0.1）；显式值存在但不是文件 → `AdbResolutionError`；随包缺失 → 报错。
- 端侧采集假设（不满足则采集失败或降级）：
  1. SoloPi App 已安装且为可被 Harness 驱动的版本（自编译版含两项开关；官方 1.0.3 无）。
  2. **无障碍服务已授权且真实 Bound**：`keeper.parse_accessibility_bound`（keeper.py:152）会识别「假开启」（dump 里有服务片段但 Bound 段为空）；假开启只 `needs_attention`，**不会代开**（keeper.py:432 `_accessibility_check`）。注意 `am force-stop` 会清无障碍授权（README 已知边界）。
  3. 告知型权限弹窗已抑制：开关 `KEY_SUPPRESS_INFO_DIALOG`（App 源 `SoloPi/solopi-app/common/src/main/java/com/alipay/hulu/common/service/SPService.java:68`），config scheme 可读可写布尔、默认 false（`ConfigSchemeResolver.java:118`），探针 `keeper.default_dialog_probe`（keeper.py:251，`adb forward tcp:23342` + `GET /scheme/config?action=get&key=...`）。
  4. 设备端 CSV 用英文文件名：开关 `KEY_CSV_ENGLISH_NAME`（`ConfigSchemeResolver.java:119`『性能 CSV 落盘文件名使用英文（列名保持中文）』，映射实现 `solopi-app/.../util/RecordUtil.java:206-248`）。
  5. 采集数据落设备 `/sdcard/solopi/records`，单会话目录 `performance-<id>`（harness 测试断言 `SoloPi/solopi-skill/.../tests/test_solopi_ai.py:4543-4544`；PC 侧安全前缀正则 collector.py:238 同口径）；Harness 限额：`PERFORMANCE_CSV_MAX_FILES=512`、单文件 64MB、总 256MB、512 列（`solopi_ai.py:165-168`）。
  6. Harness 调用形态：`[sys.executable, harness_entry, --adb, --serial, <子命令>...]`（solo.py:101），子命令 `perf-start`/`perf-stop`/`perf-analyze`（harness 引发行 10479/10493/10443），stdout 为 JSON 契约；超时 `PERF_START_TIMEOUT_S=180`、`PERF_STOP_TIMEOUT_S=300`（solo.py:31/32）。
  7. `FPS` 采集会弹告知框 → 官方版无人值守不可用；`--items` 默认故意不含 FPS（cli.py `DEFAULT_ITEMS='CPU,Memory'`（cli.py:24））。
  8. SoloPi 内部 adb 走手机 `tcpip 5555`，与 PC adb 通道独立（README 已知边界）；`keeper._heal`（keeper.py:413）会在设备离线且为 tcp 串时 `adb connect`，否则 `adb tcpip 5555` + `ip route` 取 wlan0 IP 再 connect，并记 `tcpip_heal` 事件。
  9. GPU 补采依赖机型（`kgsl` 需 root）；不支持时整类 `gpu_util_pct` 降级（真实样本 `supplement.degraded=[{key:'gpu_util_pct', reason:'output_unparseable_or_unsupported'}]`）。
  10. 充电中 `Battery`/`Temperature` 降级 not_tested（真实样本 battery 指标 `notTested:true`）。

### 10.2 目录布局实例

```
moblie-xn/
├─ data/           mobile_perf.db, mobile_perf.db.bak-20261025
├─ runs/
│  ├─ byd-academy-run1-180358/       artifacts/ + meta.json + report.json + report.html
│  ├─ byd-academy-run2-180358/
│  ├─ trainapp-main-v3-run1-195853/  （本次取证样本：49.391s，40 CSV，report.json 98,850 B）
│  └─ trainapp-main-v3-run2-195853/
├─ perf-output/    （历史/老版产物）extract_metrics.py, perf_analysis.json,
│                  performance-a5b87b47-…/（CSV 为中文文件名）
├─ dist/solopi/SoloPi-selfbuild-debug.apk
├─ SoloPi/apk/SoloPi_v1.0.3.apk, SoloPi/platform-tools/, SoloPi/solopi-app/, SoloPi/solopi-skill/
└─ scripts/perf_full_flow.py   docs/{嵌入指南.md, 设计方案-App性能测试组件.md, adr/, agents/}
```

- `meta.json` 实例字段（真实样本全量）：`runId/target/items/serial/deviceProfile/hostRunId/startedAt/stoppedAt/durationS/soloSessionId/marks/status='stopped'/integrity/supplement{enabled,intervalS,rounds,errors,degraded,clockOffsetS,clockOffsetSource}/startup{...}/jank=null`。
- 真实 `supplement.clockOffsetS=-3.743`（source `keeper`）——设备与宿主时钟差 3.7s，说明**曲线横轴对齐靠 offset 校正**（`to_unified_elapsed_s`），平台若自己算时间必须用同一 offset。

## 11. 平台接入面（能力 → 复用方式 → 平台需补什么）

| 能力 | 复用方式 | 平台需补什么 |
|---|---|---|
| 设备就绪巡检/自愈 | **进程内 import** `PerfKit(serial=...).ensure_ready()`（kit.py:703）或 CLI `doctor`；产物是 `ReadinessReport` + `devices` 表 | 需要 HTTP/异步任务时自己包一层；`needs_attention` 的处置策略（是否阻断执行）由平台定 |
| 一次完整采集（定时长） | **进程内** `kit.run_collect(target, items, duration_s, host_run_id=...)`；或 CLI `collect`（**跨机器必须走远端执行器**，因为 adb/SoloPi 在采集机） | 任务队列/设备调度/并发编排；`host_run_id` 与平台用例 ID 的映射规范 |
| 交互式采集（边驱 UI 边采） | **进程内** `with kit.collect(...) as scope: scope.mark('xxx')`（kit.py:1011/186） | **打标回调缺失**：`mark()` 无 hook、无事件、无推送（只进内存→report）。平台要「UI 步骤联动打标」需在调用点自己发消息（平台侧回调即可，不必改库），但要接受「报告里才有 marks」的时序 |
| 判定（阈值/基线） | **进程内纯函数** `judge.judge(report, JudgeSpec(...))`（judge.py:93），无需设备/无需库；或 CLI `report --baseline --threshold` | 阈值模型（配置中心/用例级）与 `deviceProfile` 规范化（否则恒 not_tested）；`not_tested` 原因分类（自由文本，需关键词映射） |
| 基线管理 | `kit.save_baseline(report, name, metric_keys)` + `store.fetch_baseline`（baselines 表） | 基线版本/审批/淘汰；`baseline` 名与用例的绑定关系 |
| 历史趋势 | `kit.trend(pkg, metric, profile)` / `kit.leak_trend(pkg, ...)`；或只在 SQLite 上自己查 `fetch_metric_series` | **跨档案拒绝**必须由平台在 UI 上解释（profileMismatch 提示）；大数据量需补索引/物化视图 |
| 报告（JSON/HTML） | 直接读 `runs/<runId>/report.json`；HTML 单文件可直接内嵌 iframe（零外链） | `artifacts` 绝对路径需重映射；把 HTML 存对象存储/加鉴权；`schemaVersion=1` 无迁移机制，平台需自己判版本 |
| 事件（crash/ANR/降级/integrity） | report.`events` 或 `store.fetch_events(runId)` | 事件是**采集结束后**才齐（logwatch 在 finalize 才 stop）；平台若要实时告警需自己 tail（见下） |
| **实时指标推送** | **缺失**：无 HTTP/SSE/WebSocket 服务；`serve` 仅预留（cli.py:366-370，返回 2） | 平台必须自建：轮询 PC 侧 `runs/<runId>/artifacts/*.csv`（**注意此时文件可能还在写**）、或复用 `SupplementPoller` 的 2s 采样节奏做旁路推流、或改 `CollectScope.__enter__` 增加回调（属改库） |
| 设备互斥 | 注入 `DeviceGate` 实现（gate.py:37）；CLI 默认 `FileLockGate`（同机 Windows 有效） | **跨机器不可用**（非 Windows passthrough、无中心锁服务）；平台需自建设备池 + 长租约（`collect` 窗口内本库不持锁，见 §6） |
| pytest 用例集成 | 插件自动加载：`pytest --mobile-perf --mobile-perf-serial=...`；结论进 JUnit section | 仅适用 pytest 体系；失败不改用例结论的语义需在平台报告里显式呈现 |
| 采集实现替换（自研端侧） | 注入 `backend=CollectBackend` 实现（kit.py:87） | 需自己实现 `start/stop` 契约与 CSV 列名→`metric_key` 映射（否则 `column_to_metric` 全丢） |

**必须真机/不可跨机器**：SoloPi 采集、adb 全链路、gate 文件锁、`runs/artifacts` 原始 CSV、开机的 `report.html`（可搬运，但 `artifacts` 字段失效）。
**可跨机器**：`report.json`（判定的全部输入）、SQLite 库（复制即用）、纯函数 `judge`/`leak`/`jank`/趋势计算。

## 12. 未核实与风险清单

1. **未核实**：ADR 实际编号清单（`docs/adr/` 未逐份读，本文只引用了「ADR-0001 短事务 / ADR-0002 子进程边界」两个说法，编号与标题的对应关系以该目录为准）。
2. **已核实**：SQLite 无 `CREATE INDEX`、无 `user_version`、无迁移脚本（store.py:26-93）；平台若长期存数需自建索引与 schema 版本管理。
3. **未核实**：`events.kind` 的完整枚举（代码内只见 9 类左右，无集中常量表）。
4. **未核实**：CLI `main` 的异常到退出码映射（未见统一 try/except）。
5. **风险**：`FileLockGate` 在非 Windows 完全不加锁；跨机器无互斥。
6. **风险**：`collect` 窗口内不持设备锁，「短事务」只防命令交错，长租约需平台补。
7. **风险**：`report.artifacts` 绝对路径、`schemaVersion` 无迁移、`not_tested` 原因自由文本 —— 三处都会影响平台的数据治理。
8. **风险**：实时数据只能靠平台自建（轮询 CSV / 旁路推流），且采集中的 CSV 可能半写（`aggregate_artifacts` 只在 finalize 后调用）。
