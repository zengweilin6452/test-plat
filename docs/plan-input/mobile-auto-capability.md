# moblie-auto 能力盘点（平台开发证据材料）

- 取证对象：`D:\workspace\claudecode-test\moblie-auto`（下称"目标仓库"，下文路径均为仓库内相对路径）
- 取证方式：只读 `read` / `grep` / `ls`；未修改目标仓库、未执行其测试、未运行 git 命令。取证时间 2026-10-25。
- 用途：给平台开发方案提供"可复用面 / 接入方式 / 缺口"的证据。所有结论带 `文件:行号`；行号未逐行核对的地方标「未核实」。

---

## 0. 一句话结论

目标仓库是一个**单机、单设备、进程内**的 Android UI 自动化能力包（Python ≥3.12）：进程内 `DeviceSession`（serial 队列 + 跨进程文件租约）驱动 uiautomator2 与 scrcpy 双通道，向上暴露"15 方法契约"适配器和 3 个坐标手势；另有独立的 `viewer`（FastAPI，bind 127.0.0.1）提供证据浏览 / 快照 / 模板制作 / 拾取 / 预览 / 受控注入，`evidence` 提供失败取证 + pytest 插件，`imaging` 提供模板匹配与不可变模板库。

对平台而言：**驱动/取证/模板/预览能力可直接进程内复用**，而**设备资源调度、租约中心、鉴权、多机作业化、持久化**都需要平台侧新写——目标仓库刻意不做这些（见 §13）。

---

## 1. 包结构、公共出口、打包元数据

规模：`src/mobile_auto` 共 32 个 .py / 8097 行。

```
__init__.py(31)  _perf_gate.py(72)  cli.py(252)  config.py(355)
contracts.py(175)  errors.py(89)  pool.py(130)
core/  adapter(575) backend(295) device_ops(201) lease(174) selectors(391) session(535) ui_tree(72)
evidence/  collector(215) pytest_plugin(266)
imaging/  engine(582) store(324)
stream/  channel(453) selfheal(180) supervisor(230) upstream(491) upstream_proto(177) __init__(32)
viewer/  app(1500) candidates(93) server(83) store(116)
```

公共出口 `src/mobile_auto/__init__.py:9-31`（精确名字）：

- `MobileConfig`、`load_config`（来自 `config`）
- `ElementHandle`、`Locator`、`Target`（来自 `contracts`）
- `MobileAdapter`（来自 `core.adapter`）
- `DeviceSession`（来自 `core.session`）
- `__version__`
- `errors` 的全部 `__all__`（`from .errors import *` 后并入 `__all__`）

```python
# src/mobile_auto/__init__.py:21-31（形状）
__all__ = ["DeviceSession", "ElementHandle", "Locator", "MobileAdapter",
           "MobileConfig", "Target", "__version__", "load_config", *_errors_all]
```

打包（`pyproject.toml`）：

- name `mobile-auto` 0.1.0，`requires-python >=3.12`，build-backend hatchling，wheel 仅含 `src/mobile_auto`。
- 运行时依赖：`uiautomator2>=3.0`、`Pillow>=10.0`、`adbutils>=2.0`。
- extras：`image`(opencv-python-headless>=4.9, numpy>=1.26)、`stream`(wetest-scrcpy>=0.4.0,<0.5 + av>=10)、`viewer`(fastapi>=0.111, uvicorn>=0.30, websockets>=12.0)、`dev`(pytest>=8.0, pytest-asyncio>=0.23, httpx>=0.27, build>=1.2, ruff>=0.4)。
- console script：`mobile-auto = mobile_auto.cli:main`。
- pytest11 entry point：`mobile-auto-evidence = mobile_auto.evidence.pytest_plugin`（装包即自动生效的证据插件）。
- pytest ini：`testpaths=["tests"]`、`addopts="-q"`、`asyncio_mode="auto"`、marker `device`。
- ruff：line-length 100，target py312，select E,F,W,I,UP,B。
- `requirements-lock.txt` 为实锁：adbutils 2.12.0 / uiautomator2 3.7.1 / pillow 13.0.0 / numpy 2.5.4 / opencv-python-headless 5.0.0.93 / fastapi 0.161.1 / starlette 1.9.0 / pydantic 2.14.1 / uvicorn 0.54.0 / websockets 17.3 / pytest 9.1.1 / pytest-asyncio 1.4.0 / wetest-scrcpy 0.4.0 / av 18.1.0 / construct 2.10.70 / tidevice 0.12.11 / lxml 6.1.3；文件含 `-e` 指向本仓库路径。

---

## 2. core/session.py：会话模型（平台最需要理解的一层）

`DeviceSession` 是**唯一合法的设备访问入口**（README 明确），持有 1 个线程池（`ThreadPoolExecutor(max_workers=1, thread_name_prefix="mobile-auto-device")`，`core/session.py:119-121`）与设备租约。

### 2.1 生命周期状态机

设计文档 `core/session.py:1-14`；枚举 `core/session.py:41-48`。

| 状态 | 含义 | 进入条件 / 迁移 |
|---|---|---|
| `new` | 已构造未启动 | 构造时 |
| `ready` | 已连接、未持租约 | `start()` 后；`release_lease()` 从 leased 回到此 |
| `leased` | 已连接且独占设备 | `start()` 自动取租约；`acquire_lease()` |
| `draining` | 有界排空关闭中 | `close()` 进入（`core/session.py:409`） |
| `closed` | 已关闭 | 排空成功（`core/session.py:441`） |
| `faulted` | 在途结果不可知 | close 排空超时（`core/session.py:423-428`），保留租约 |

要点：`start()`（`core/session.py:174`）顺序为 枚举设备 → `resolve_serial`（`core/session.py:64-99`：未授权/多设备歧义都抛 `DeviceUnavailable`）→ `DeviceLease.acquire()` → `backend.connect(serial)` → LEASED；连接失败会释放租约。`faulted` 状态下 `submit()` 直接拒绝（`core/session.py:450-453`）。

### 2.2 操作队列语义（串行 + 三阶段）

- `submit(operation: Callable[[DeviceBackend], T]) -> Future[T]`（`core/session.py:445`）：所有设备操作进单 worker 队列，天然串行；`_pending` 计数用于排空。
- 入口取消检查：排队期间被取消的任务不执行（`core/session.py:462-464`，抛内部 `_OperationCancelled`）。
- `send_checkpoint()`（`core/session.py:477-485`）：**在真实设备发送调用之前**调用，标记 `entered_send=True`；已取消则抛 `_OperationCancelled` 且不进入发送阶段。这是"取消后设备侧结果是否未知"的判定开关。
- 排队期间取消 = `future.cancel()` 生效；已在执行 = `cancel()` 无效，只置标记。

### 2.3 取消语义（对平台任务取消/超时最关键）

三个方法配合：`mark_cancelled(future) -> str`（`core/session.py:487`）、`operation_outcome(future) -> str`（`core/session.py:499`）、`_operation_done`（`core/session.py:518`，完成时固化结局）。

| 结局字符串 | 含义 | 产生位置 |
|---|---|---|
| `cancelled-queued` | 未开始即取消，请求未发出 | `operation_outcome` 读 `future.cancelled()`（:508） |
| `cancelled-before-send` | 已取消且未进入发送阶段 | :497 / :525 |
| `unknown` | 已进入发送阶段后被取消，设备侧结果不可知 | :495-496 / :522-523 |
| `completed` / `failed` | 正常完成（结局固化，等待方是否感知不改变记录） | :526-529 |
| `running` | 仍在执行 | :516 |

Adapter 侧对应：`_call` 捕获 `asyncio.CancelledError` 后调用 `session.mark_cancelled`（`core/adapter.py:129`，确切分支见 :135-142）。**平台必须把 `unknown` 当作"结果不可信"对外呈现**（目标仓库在 `close` 超时、发送后取消两种路径都会产出它）。

### 2.4 截图双通道策略

`screenshot_bytes(backend) -> bytes`（`core/session.py:266-289`），在设备队列线程内调用，**返回永远是 PNG，调用方不感知来源**：

| `MobileConfig.screenshot_source` | 行为 |
|---|---|
| `u2` | 直连 `backend.screenshot_png()`（全分辨率） |
| `scrcpy` | 强制走 scrcpy `capture_png()`；失败**如实抛出，不静默回退**（:285-286） |
| `auto`（默认） | scrcpy 优先；失败计数达 `_SCRCPY_FAIL_LIMIT=3` 后降级 u2 `_SCRCPY_DEGRADE_SECONDS=60.0` 秒，窗口到期再试探测恢复（:36-38、:382-391） |

注：upstream 通道的 `capture_png` 分辨率 = 流分辨率（默认 max_size 1080），**全分辨率取证必须 `screenshot_source="u2"`**（README）。注入侧与截图共用同一失败计数/降级窗口（`core/session.py:300-341`）。

### 2.5 注入双通道

`inject_gesture(backend, source, scrcpy_gesture, u2_gesture) -> str`（`core/session.py:300`，返回 `"scrcpy"`/`"u2"`）：

- `source="auto"` → 取 `config.injection_source`；`"scrcpy"` 强制且故障如实抛；`"u2"` 直走。
- 手势安全由闭包保证：**DOWN 未发出**失败 → `_CleanFallback` → 整体回退 u2；**DOWN 已发出**失败 → 闭包内已抬指收尾，向上如实传播、**不重放**（避免双注入）（:308-310、:329-339）。
- `inject_tap`（:343）、`inject_swipe`（:354）、`inject_press_key`（:367，仅 `back`/`home` 走双通道，其余直接 u2）。

### 2.6 对外方法签名速查

| 方法 | 位置 | 签名/语义 |
|---|---|---|
| `__init__` | :105 | `(config: MobileConfig, *, backend_factory=None, device_enumerator=None, lease_factory=None, channel_factory=None)`——四个注入点（测试/平台替换用） |
| `start` | :174 | `() -> None` |
| `acquire_lease` | :202 | `() -> None`，READY↔LEASED |
| `release_lease` | :221 | `() -> None`，READY↔LEASED |
| `get_or_start_channel` | :240 | `() -> Channel`，须在队列线程 |
| `screenshot_bytes` | :266 | `(backend) -> bytes` |
| `healthy_channel` | :291 | `() -> Channel \| None`，`peek_healthy`，不启动 |
| `inject_gesture/tap/swipe/press_key` | :300/:343/:354/:367 | 见 §2.5 |
| `close` | :393 | `(timeout: float = 10.0) -> None`，幂等；超时 → FAULTED 并保留租约 |
| `submit` | :445 | `(operation: Callable[[DeviceBackend], T]) -> Future[T]` |
| `send_checkpoint` | :477 | `() -> None` |
| `mark_cancelled` | :487 | `(future: Future) -> str` |
| `operation_outcome` | :499 | `(future: Future) -> str` |
| 属性 | :142/:146/:150/:154 | `config` / `state` / `serial` / `dialog_guard_stats`；另有 `note_dialog_guard_attempt`（:165） |

---

## 3. core/adapter.py：15 方法契约面

契约清单来源 `tests/contract/test_contract.py:16-33`（docstring 指向 `docs/integration.md` §3），15 个异步方法 + `platform` 属性（`core/adapter.py:109`，值 `"android"`）。`__init__(session: DeviceSession)`（:111）。

### 3.1 逐个签名与语义

| # | 方法 | 行 | 签名 | 语义（轮询/事务） |
|---|---|---|---|---|
| 1 | `goto` | :279 | `(target: str = "", package: str \| None = None, activity: str \| None = None) -> None` | 空串→冷启动 `app_start(stop=True)`；非空→Deep Link，先按 `allowed_deeplink_schemes` 白名单校验 |
| 2 | `wait_for_load` | :318 | `() -> None` | 只等 `config.launch_ready_target`；缺失配置抛 `ConfigurationError`，超时 `WaitTimeout` |
| 3 | `back` | :353 | `() -> None` | 单次按键 |
| 4 | `click` | :513 | `(target: Target) -> None` | 原生：轮询 → 检查点 → 点击；IMAGE：单事务（见 §3.2） |
| 5 | `input_text` | :395 | `(target: Target, text: str) -> None` | `clear_text`+`set_text`，不读回、不记日志 |
| 6 | `get_text` | :553 | `(target: Target) -> str` | 缺失归一空串 |
| 7 | `get_attribute` | :415 | `(target: Target, name: str) -> str \| tuple[int,int,int,int]` | 属性取值/边界 |
| 8 | `wait_for` | :475 | `(target: Target, timeout: float \| None = None) -> bool` | 默认 `config.wait_timeout`、轮询间隔 0.5；负数/非有限值 `ValueError`；设备错误原样传播 |
| 9 | `is_visible` | :464 | `(target: Target) -> bool` | 单次查询，不轮询 |
| 10 | `find_elements` | :429 | `(target: Target) -> list[ElementHandle]` | 必须无序号，枚举全部并各自写 `index` |
| 11 | `extract_list` | — | **未实现** | 契约占位；`IMPLEMENTED_METHODS` 排除它，并有断言 `not hasattr(MobileAdapter, "extract_list")`（`tests/contract/test_contract.py:35-37`） |
| 12 | `screenshot` | :566 | `() -> bytes` | 走 §2.4 双通道 |
| 13 | `press_key` | :357 | `(name: str) -> None` | `_PRESS_KEYS = {back, home, enter, search, delete, recent}` |
| 14 | `scroll` | :371 | `(direction: str, amount: int) -> None` | `_SCROLL_DIRECTIONS={up,down,left,right}`，amount 为正整数像素，手势 0.3s |
| 15 | `close` | :573 | `() -> None` | `asyncio.to_thread(session.close)` |

内部机制：

- `_call(operation)`（:129）：`session.submit` + `asyncio.wrap_future`；`CancelledError` → `mark_cancelled`。
- `_poll_until(attempt, target)`（:198）：预算 `config.wait_timeout`、间隔 `config.poll_interval`；多匹配立即 `AmbiguousTarget`；超时 `ElementNotFound`；弹窗守卫命中可重置一次预算。
- `_dismiss_dialogs_once`（:231）：白名单 `config.dialog_guard`（仅 `u2_selector` 且必须带非空 packageName，`config.py:206-236`），命中不唯一则跳过；统计进 `session.dialog_guard_stats`。
- `_image_click_transaction`（:179）：采集 → 匹配 → 选唯一 → 检查点 → `inject_tap`；`_IMAGE_FRESH_SECONDS=1.0` 内复采一次。
- 模板缓存 `_TemplateCache`（:69）：键 `(store.root, logical)`，按清单 `version_id` 失效。

### 3.2 adapter.device 坐标手势面（契约外扩展，2026-10-24 决定）

`MobileAdapter.device`（`core/adapter.py:117`）返回 `core/device_ops.DeviceOps`（`core/device_ops.py:129`）。契约测试不涉及此面（docstring 明示）。

| 方法 | 行 | 签名 | 说明 |
|---|---|---|---|
| `tap` | :138 | `async tap(x: int, y: int, *, source: str = "auto") -> str` | 返回实际通道 `"u2"`/`"scrcpy"` |
| `swipe` | :153 | `async swipe(x0, y0, x1, y1, duration_s: float = 0.3, *, source: str = "auto") -> str` | 5px 主机侧插值 |
| `long_press` | :181 | `async long_press(x, y, hold_s: float = 0.8, *, source: str = "auto") -> str` | u2 侧用原生 `long_click(duration=hold_s)` |

约束：`_SOURCES=("auto","scrcpy","u2")`（:29）、`_MAX_SECONDS=10.0`（:30，阻塞会话队列线程的保护栏）；手势闭包 `tap_gesture`(:70) / `swipe_gesture`(:84) / `long_press_gesture`(:107) / `press_gesture`(:121)；DOWN 后失败补 `touch_up` 收尾（`_recover_up` :62）。

---

## 4. core/backend.py：设备接口形状与 ADB 发现

- `DeviceBackend` Protocol（`core/backend.py:127-157`）——执行核心对设备的**全部请求面**：`connect(serial)`、`close()`、`screen_size() -> tuple[int,int]`、`find_elements(by: Locator, value) -> list[BackendElement]`、`screenshot_png() -> bytes`、`tap(x,y)`、`app_start(package, activity, stop=False)`、`open_deeplink(uri)`、`press_key(name)`、`swipe(sx,sy,ex,ey,duration)`、`long_click(x,y,duration=0.8)`、`touch_up(x,y)`、`dump_ui() -> str`。伪实现见 `tests/unit/fakes.py`。
- `BackendElement` Protocol（:108-124）：`bounds` / `text` / `info` / `click()` / `clear_text()` / `set_text(text)`。
- `U2Backend`（:159）：uiautomator2 实现；u2 与 adbutils 一律**延迟导入**（包导入无设备副作用，:6）。`connect` 失败统一归 `DeviceUnavailable`（:170-171）。XPath 走独立子系统（:182-184）；`_PRESS_KEY_ALIASES` 映射 delete→del（:203-210）；`touch_up` 用 `device.touch.up`（:224-226）。
- ADB 发现 `find_adb_binary()`（:46-60）：**随包 `tools/adb/adb.exe` 优先** → adbutils 内置 → PATH。
- 设备枚举唯一实现 `enumerate_device_states() -> dict[str,str]`（:96-105），内部只跑 `adb devices`（:76-93，`_ADB_TIMEOUT_SECONDS=10`），保留 unauthorized/offline 原始状态。
- 设备选择 `resolve_serial(states, configured)`（`core/session.py:64-99`）。

---

## 5. 跨进程设备租约：core/lease.py + pool.py

### 5.1 实现事实

- 租约 = **Windows 文件区域锁**，不是数据库/Redis。
- 目录：`DEFAULT_LEASE_DIR = Path.home()/".mobile-auto"/"leases"`（`core/lease.py:27`）。
- 文件名：`digest = sha256(serial)[:24]` → `<digest>.lock` + 伴生 `<digest>.holder.json`（:45-47）。
- 类 `DeviceLease(serial, lease_dir: Path|None=None, *, worker="", purpose="")`（`core/lease.py:30,33`），支持 `with`（:153-159）。
- `acquire()`（:63）：`msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)` 锁文件第 0 字节（:79），**非阻塞**；失败抛 `DeviceBusy`。非 Windows 直接 `DeviceUnavailable("设备租约当前仅支持 Windows(plan 7.2)")`（:72）。
- `release()`（:109）：`LK_UNLCK`，释放**不删文件**（伴生 holder 内容会残留）。
- 占用探测：`probe_held() -> bool`（:125）——尝试锁字节 0 判定是否被占用；`held` 属性（:60）。
- 持有者信息：`_write_holder`（:88）写 `<digest>.holder.json`，字段 **pid / hostname / worker / purpose / acquired_at（UTC ISO 毫秒）**（:88-107）。
- `read_holder(serial, lease_dir=None) -> dict|None`（:161）：**只有 `probe_held()==True` 时**其内容才代表当前持有者（否则是上次残留）。

### 5.2 池化与运行态（pool.py）

- `acquire_from_pool(pool: tuple|list, *, worker="", wait_seconds=60.0, poll_interval=1.0, enumerator=None, lease_factory=None) -> tuple[str, DeviceLease]`（`pool.py:31`）：按候选列表非阻塞试锁，全忙重试至超时抛 `DeviceBusy`。
- 常量：`POOL_WAIT_SECONDS=60.0`、`POOL_POLL_INTERVAL=1.0`、`RUN_STATE_STALE_SECONDS=30.0`（:26-28）。
- `worker_artifacts_dir(base, worker) -> base/"xdist-<worker>"`（:75）。
- `write_run_state(runs_dir, *, worker, phase, serial=None, current_test=None)`（:81）：payload `worker/phase/serial/current_test/pid/heartbeat`，tmp+replace 原子写；`read_run_states(runs_dir)`（:110）心跳过期标 stale。

### 5.3 与平台租约对接（结论）

- 这套租约只在**同机、同 Windows 用户、同 lease_dir 默认值**下互斥；不同用户（`Path.home()` 不同）、不同 `lease_dir`、跨机器（含 SMB/NFS 共享目录）都不保证互斥——**不能当平台级租约用**。
- 平台若已有"设备占用表"，两者会形成双账本：平台必须把平台租约当"权威"，把本地 `DeviceLease` 当"本机兜底锁"，并在设备释放流程里同时归还（否则 `holder.json` 残留 + 锁文件残留会造成排障噪音，虽不阻塞获取）。
- 平台若要 Linux/容器化执行机，**必须重写 lease**（`fcntl.flock`）：`lease.py:72` 是硬编码分支，当前无 Unix 实现。
- 与 viewer 的交集：viewer 的写操作注入经 `_LeaseGuard` 做**短事务**取/放租约（`viewer/app.py:1007`，类在 :1208）；pytest 会话是**整生命周期**持有。二者同机同用户时会冲突（409/DeviceBusy），这是设计意图（`GET /api/v1/status` 暴露 `lease_held`/`busy`，`viewer/app.py:587-588`）。viewer 只读截屏路径是否取租约未逐行核实（标「未核实」）。

---

## 6. viewer/app.py：HTTP/WS 面与安全边界

创建入口 `create_app(session: DeviceSession|None=None, store: SnapshotStore|None=None, *, preview_interval=1.0, stream_interval=0.1, channel_manager=None, registry=None)`（`viewer/app.py:487`）；末尾 `app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True))`（:1120-1121）挂在根路径，API 全在 `/api/v1/*`。

### 6.1 全部路由（方法 + 路径 + 行号 + 用途）

| 方法 | 路径 | 行 | 用途 |
|---|---|---|---|
| GET | `/api/v1/devices` | :542 | adb 可见设备 ∪ 已建会话；不创建会话 |
| GET | `/api/v1/devices/{serial}/info` | :550 | 设备档案（品牌/型号/系统/分辨率），进程内缓存，未授权设备不碰 adb |
| GET | `/api/v1/status` | :575 | `service_version`、`device{serial,state,lease_held,busy}`、`devices`、`capture{can_capture,snapshots}` |
| GET | `/api/v1/evidence` | :599 | 证据清单（遍历 artifacts 任意层级，含 xdist 子目录） |
| GET | `/api/v1/evidence/{evidence_id}` | :605 | 证据 meta |
| GET | `/api/v1/evidence/{evidence_id}/files/{name}` | :614 | 证据文件（`cache-control: no-store`） |
| GET | `/api/v1/leases` | :630 | 设备占用可视（`probe_held` + holder.json） |
| GET | `/api/v1/runs` | :641 | 各 worker 运行态（`pool.read_run_states`） |
| POST | `/api/v1/snapshots` | :653 | 采集快照（body `with_tree`），返回尺寸/朝向/时间/树一致性 |
| GET | `/api/v1/snapshots/{id}/image` | :672 | 快照 PNG |
| GET | `/api/v1/snapshots/{id}/tree` | :683 | 快照 UI 树 JSON（无树→400 capability-unavailable） |
| POST | `/api/v1/snapshots/{id}/freeze` | :701 | 冻结/解冻（避免被 TTL/容量驱逐） |
| POST | `/api/v1/templates` | :716 | **服务端**从快照裁剪生成模板（不收浏览器图片）；同名冲突 409 |
| PUT | `/api/v1/templates/{logical:path}` | :743 | 更新模板：必须带 `expected_old_sha256`，不符 409 |
| GET | `/api/v1/templates` | :761 | 模板清单（logical / version_id / image_sha256） |
| GET | `/api/v1/templates/{logical:path}/image` | :778 | 模板当前版本 PNG |
| POST | `/api/v1/templates/validate` | :793 | IMAGE 目标重采匹配验证：返回 count/matches/scores/passed |
| POST | `/api/v1/pick` | :836 | 原生拾取：按快照坐标给候选节点 + 生成 locators（多候选标 `overlap`，不静默选） |
| POST | `/api/v1/locators/validate` | :880 | 任意定位方式验证（passed 仅唯一匹配） |
| WS | `/api/v1/preview` | :921 | 预览/投屏实时帧 |
| POST | `/api/v1/control` | :970 | 显式开启/关闭直接控制（默认关闭） |
| POST | `/api/v1/input/touch` | :1019 | 归一化坐标点击（nx,ny） |
| POST | `/api/v1/input/swipe` | :1049 | 归一化滑动（nx0,ny0,nx1,ny1,duration_ms 50–5000） |
| POST | `/api/v1/input/key` | :1088 | 按键注入（经通道 `press_key`） |
| POST | `/api/v1/input/wake` | :1105 | 唤醒屏幕 |

错误信封统一 `code/message/request_id`（异常处理器 `:535-538`，`_ERROR_STATUS` 映射 HTTP 码）；成功响应带 `x-request-id`（:532）。

### 6.2 WebSocket `/api/v1/preview`

- 连接即校验 Origin（:923-926，非法 `close(4403)`）；设备不可用先 accept 再发一条 `kind:"status"` 后 `close(4404)`（:927-938）。
- 每设备客户端上限 `_MAX_WS_CLIENTS_PER_DEVICE=4`，超限 `close(4429)`（:941-943）。
- 帧节奏：`source=="scrcpy"` 用 `stream_interval=0.1`（约 10fps），回退/状态帧用 `preview_interval=1.0`（:954-958）。
- 每客户端仅保留最新帧，上一帧未发完则丢弃新帧（`_PreviewSender` :1125-1129 注释），发送带超时（防 TCP 背压冻结）。

### 6.3 安全边界（平台接入必须知道）

- 中间件 `request_id_and_origin`（:522-533）：**Host 与 Origin 双校验**，失败 403 `forbidden-origin`。
- `_host_allowed(host)`（:1485）：`127.0.0.1` / `localhost` / `[::1]` / `testserver`。
- `_origin_allowed(origin)`（:1490）：`urlsplit` 后**精确比对 hostname** ∈ {127.0.0.1, localhost, ::1}，scheme http/https，端口任意（注释说明防 `localhost.attacker.example` 前缀绕过）。
- bind 地址：`viewer/server.py:69` `uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")`；`cli.py:215` `_cmd_serve` 同样 `host="127.0.0.1"`。**没有鉴权、没有 token、没有 TLS**。
- 直接控制默认关闭（`app.state.control_enabled`）；启用后仍受 50ms 节流（`_INJECT_MIN_INTERVAL_SECONDS=0.05`，:968）与"通道可用"约束（`StreamUnavailable`，:1009-1010）。
- 结论：viewer 是**本机开发者工具**，不是平台对外服务。平台若复用，必须前置网关（鉴权/限流/TLS），且跨机器访问需要改 bind 与 Origin/Host 白名单（硬编码）。

### 6.4 持久化位置（重要缺口）

`viewer/store.py` 的 `SnapshotStore` 是**纯内存**：`MAX_LIVE_SNAPSHOTS=3`、`MAX_TOTAL_BYTES=64MiB`、`LIVE_TTL_SECONDS=120`、`FROZEN_TTL_SECONDS=600`、`MAX_PIXELS=12_000_000`、`MAX_INPUT_BYTES=20MiB`（:16-21）；`Snapshot` 字段 `png/width/height/orientation/captured_at/tree_json/tree_captured_at/tree_error/tree_root/frozen/frozen_at/id(16hex)`（:29-53）；驱逐只针对未冻结（:100-106）。**进程重启即全部丢失**。

真正落盘的是：证据（`artifacts_dir/evidence/...` + `run-manifest.jsonl`）、模板（`assets_dir`）、运行态（`artifacts_dir/runs/`）。

### 6.5 viewer/server.py（--debug-viewer 后台服务）

`PORT_PROBE_LIMIT=20`、`_STARTUP_TIMEOUT_SECONDS=15.0`、`_find_free_port`（:23，bind 127.0.0.1，刻意不设 SO_REUSEADDR）→ `DebugViewerHandle`（:36，`.url` + `stop(timeout=10.0)`）→ `start_debug_viewer(config)`（:51）；缺 viewer extra 抛 `ConfigurationError`。

---

## 7. evidence：失败取证与 pytest 接入

### 7.1 产物结构与 manifest 字段

`collect_failure_evidence(session, failure: BaseException|str, *, operation_frames: Sequence[tuple[str, bytes]] = (), timeout: float = 5.0) -> dict`（`evidence/collector.py:35`）。

目录布局（`artifacts_dir` 下）：

```
artifacts/
  run-manifest.jsonl                     # 追加式 JSONL 运行清单
  evidence/<16hex>/
      meta.json                          # 记录主体
      failure-frame.png                  # 失败帧（来源见 frame_source）
      ui-tree.xml                        # UI 树（失败时尽力采集）
      operation-<label>.png              # 操作过程帧（可选，label 已安全化）
```

`meta.json` 字段（`collector.py:91-105`）：`evidence_id`、`created_at`、`failure{type,message}`、`device{serial,app_package,screen_size,dialog_guard}`、`frame_source{source,capture_lag_ms}`、`artifacts[{name,kind,captured_at}]`、`not_captured[{kind,reason}]`。

`run-manifest.jsonl` 每行（`:109-118`）：`evidence_id`、`created_at`、`device_serial`、`app_package`、`failure_type`、`frame_source`、`artifacts`（文件名列表）、`not_captured`。

读取唯一入口：`read_manifest(artifacts_dir) -> list[dict]`（:190）、`read_evidence_file(artifacts_dir, entry, name) -> bytes`（:207，未登记名拒绝；evidence_id 强制 `^[0-9a-f]{16}$`）。`frame_source.source ∈ {"scrcpy-video","u2",None}`；FAULTED 会话不再调用设备线程；取证超时 `_CAPTURE_TIMEOUT_SECONDS=5.0`（:22）。取证失败**不会覆盖原始测试错误**。

### 7.2 pytest_plugin（pytest11 自动加载）

- 选项仅 3 个（`evidence/pytest_plugin.py:29-49`）：`--mobile-evidence`（opt-in 失败取证）、`--mobile-devices`（候选 serial 列表，优先级高于 TOML）、`--debug-viewer`（opt-in 投屏）。
- 另用 `_optional_getoption`（:55）读取外部 `--mobile-config`——该选项由 `tests/device/conftest.py:16` 定义，**插件本身不注册它**（复用到平台时要自己提供）。
- fixtures：`mobile_session`（:87，session 级池化：`acquire_from_pool` → `dataclasses.replace(artifacts_dir=worker_artifacts_dir)` → `DeviceSession(lease_factory=...)` → `start`，结束 close + 写 run state）、`mobile_adapter`（:132）。
- hooks：`pytest_sessionstart`(:142)、`pytest_runtest_logstart`(:172)、`pytest_sessionfinish`(:177)、`pytest_runtest_makereport`(:230)——`call` 阶段失败且有会话时取证，报告 section 标题 `"mobile-auto-evidence"`（:24），`user_properties` 加 `("mobile_auto_evidence", json)`。

---

## 8. imaging：匹配引擎与模板库

### 8.1 engine 对外函数

`imaging/engine.py`：

| 符号 | 行 | 签名/返回 |
|---|---|---|
| `MatchResult` | :70 | frozen：`x,y,width,height,confidence`；`center` 属性（:83：`x+width//2, y+height//2`） |
| `decode_rgb` | :87 | `(png: bytes, *, what: str) -> np.ndarray`（8-bit RGB；含透明像素/不可解码 → `InvalidTemplate`） |
| `PreparedTemplate` | :141 | frozen：`rgb,gray,hsv` |
| `prepare_template` | :150 | `(template_png: bytes, *, what: str = "模板") -> PreparedTemplate`（灰度标准差 < `GRAY_STDDEV_MIN=2.0` 拒绝） |
| `validate_capture_center` | :168 | `(value) -> tuple[float,float] \| None` |
| `capture_center_from_region` | :193 | `(region, frame_size) -> (nx, ny)`，按屏幕高归一化（Airtest record_pos 同语义） |
| `match_template` | :208 | `(screenshot_png, template_png, *, confidence=None, region=None, source_resolution=None, capture_center=None) -> list[MatchResult]` |
| `match_prepared` | :244 | 同上但模板已 `PreparedTemplate`（免重复解码） |

语义要点：**无匹配返回空列表（查询结果，不是错误）**；非法输入（损坏 PNG、透明蒙版、低纹理、越界 region、超限）显式拒绝。默认阈值 `DEFAULT_CONFIDENCE=0.90`、`MAX_MATCHES=100`、`MAX_PEAKS=2000`、`NMS_IOU=0.30`（:46-51）。`source_resolution` 与当前截图不一致 → 有界多尺度（粗 0.05 / 细 0.01，长边 800 降采样，`_SCALE_*` :59-63）；`capture_center` 提供且无显式 region → 先预测区域，未命中回退全区域（`_PRIOR_MARGIN_MIN=150`，:66）。

### 8.2 TemplateStore 不变式（平台做模板管理必须遵守）

布局（`imaging/store.py:1-16`）：`manifest.json`（逻辑名 → 当前版本，`os.replace` 原子切换）+ `versions/<version_id>/image.png` + `versions/<version_id>/meta.json`（`schema_version=2`）。

硬不变量：

1. 图片与元数据**成对完整写入并校验通过**后，清单才原子切换；任一步失败旧版本保持可见——不存在"新图配旧摘要"的中间态（:8-9）。
2. 更新在**资产级文件锁**（`root/locks/assets.lock`，`_AssetWriteLock` :287）内先校验旧摘要（乐观锁）（:10）。
3. **旧版本与证据永不自动删除**（:10）。
4. `load()`（:92）三重一致校验：`png sha256 == meta.image_sha256 == manifest image_sha256`、尺寸一致、`capture_center` 合法；否则 `InvalidTemplate`（:102-115）。
5. 逻辑名必须是 POSIX 相对路径、`.png` 结尾、拒绝穿越（`validate_logical_path` :56-69）；版本 id 为 32 位 hex（`_ID_RE` :35）。
6. 同名 `create` → `DuplicateTemplate`（409 语义）；`update(logical, png, expected_old_sha256, ...)` 旧摘要不符 → `StaleHandle`（:161-178）。

`LoadedTemplate`（:44-53）：`logical, version_id, png, sha256, width, height, meta`。

---

## 9. config.py：配置模型

- 优先级（`config.py:1-5, 239-310`）：**显式构造参数 > 环境变量 > TOML > 默认值**；未知 TOML 键直接 `ConfigurationError`（:324-326）；相对 `assets_dir`/`artifacts_dir` 基于配置文件所在目录（无配置时基于 cwd），返回绝对路径（:303-307）。
- 环境变量只有 3 个（:29-31）：`MOBILE_DEVICE_SERIAL`、`MOBILE_APP_PACKAGE`、`MOBILE_APP_ACTIVITY`。
- TOML 允许键 15 个（`_TOML_FIELDS` :33-51）：`device_serial, device_pool, app_package, app_activity, assets_dir, artifacts_dir, launch_ready_target, allowed_deeplink_schemes, dialog_guard, wait_timeout, poll_interval, port, screenshot_source, injection_source, stream_backend`。
- `MobileConfig` 是 frozen dataclass（:70），字段与默认（:70-97）：

| 字段 | 默认 |
|---|---|
| `device_serial` | `None` |
| `device_pool` | `()` |
| `app_package` / `app_activity` | `None` |
| `assets_dir` | `Path("assets")` |
| `artifacts_dir` | `Path("artifacts")` |
| `launch_ready_target` | `None`（Target） |
| `allowed_deeplink_schemes` | `()` |
| `dialog_guard` | `()`（仅 u2_selector + 必须带非空 packageName，:206-236） |
| `wait_timeout` | `10.0` |
| `poll_interval` | `0.5` |
| `port` | `8765` |
| `screenshot_source` | `"auto"`（auto/u2/scrcpy，:53） |
| `injection_source` | `"auto"`（同枚举，:54） |
| `stream_backend` | `"upstream"`（wetest/upstream，:55） |

`load_config(config_path=None, *, ...15 个关键字)`（:239）。**没有热更新、没有远程配置、没有多设备并发度参数。**

---

## 10. stream：视频流/控制通道

### 10.1 channel_factory 选择逻辑

`stream/__init__.py:15-29`：

```python
def channel_factory(backend="wetest", *, channel_factory_override=None):
    if channel_factory_override is not None: return channel_factory_override  # 测试/绑定注入优先
    if backend == "upstream": return UpstreamChannel
    if backend == "wetest":   return ScrcpyChannel
    raise ConfigurationError(...)
```

注意默认参数是 `"wetest"`，但 `MobileConfig.stream_backend` 默认 `"upstream"`（调用方显式传配置值，`core/session.py:250-253`）。

### 10.2 双后端差异

| 维度 | `channel.ScrcpyChannel`(wetest) | `upstream.UpstreamChannel` |
|---|---|---|
| server 资产 | `stream/assets/scrcpy-server`（206042 B，wetest 修改版，协议号 1.2.4） | `stream/assets/scrcpy-server-upstream.jar`（733930 B，官方 v5.0.1） |
| 设备端路径 | `/data/local/tmp/ma-scrcpy`（:37），另推 `/data/local/tmp/udt/libjpeg-turbo.so`（:40） | `/data/local/tmp/ma-scrcpy`（:44） |
| 版本常量 | 启动日志 `version: 3.3.2.11`（PROVENANCE.md:26） | `_SERVER_VERSION="5.0.1"`（:46） |
| 截图 | `capture_png` 用 CAPTURE 消息 + turbojpeg（需 libjpeg-turbo.so） | `capture_png` 从解码帧出图；**分辨率=流分辨率** |
| Android 兼容 | Android <17 | Android 16 QPR2+/17（含 #6362 崩溃修复） |
| 公共面 | `started/healthy/start/stop/latest_frame/capture_png/screen_size/refresh_screen_size/touch*/tap/press_key/wake/swipe` | 同左（`upstream.py:109-464`） |

两实现**同接口**，`DeviceSession` 只依赖 `healthy()/stop()/capture_png()/tap()/swipe()/press_key()/wake()/screen_size()` 等（`stream/supervisor.py:30-34` 的 `_Channel` Protocol 只约束 `healthy/stop`）。

### 10.3 supervisor 保活/自愈（一句话级）

- `ServerSupervisor`（`stream/supervisor.py:55`）：每进程每设备一个；**引用计数保活**（`acquire_user`/`release_user`），最后一个用户离开后空闲 `IDLE_STOP_SECONDS=30.0` 自停；`get()` 给轮询方（尽力而为、失败/退避窗口返回 None），`require()` 给设备队列线程（不健康即重建、启动失败如实抛）；失败推进指数退避 `RETRY_BACKOFF_INIT=2.0` → `RETRY_BACKOFF_MAX=30.0`；`peek_healthy()` 不启动不回收；`atexit` 兜底关停全部活跃通道（:40-52）。
- 自愈 `stream/selfheal.py`：启动失败时枚举设备端残留 server（**双前缀**：wetest `ma-<宿主pid模>-<序号>` comm；上游 `app_process` cmdline 里 `scid=<8hex>` → socket `scrcpy_<scid>`），用 `tasklist` 求本机存活 pid 模值集合，**只杀宿主已死的**（fail-safe：最坏结果是漏清，不会误杀）；活跃表 `LIVE_PREFIXES` 由通道 start 登记/teardown 移除；无可清残留时返回手动清理指引（`kill_stale_servers` :119-171）。
- 通道不健康属**能力降级信号**，不触碰会话状态机（supervisor.py:12-13）。

---

## 11. 随包资产、依赖、测试分层

### 11.1 随包资产

| 资产 | 路径 | 版本/来源 |
|---|---|---|
| ADB | `tools/adb/`（adb.exe / AdbWinApi.dll / AdbWinUsbApi.dll / NOTICE.txt / source.properties） | `Pkg.Revision=37.0.1`（platform-tools 的 adb 子集）；`find_adb_binary` 首选（`core/backend.py:43-51`） |
| scrcpy server(wetest) | `src/mobile_auto/stream/assets/scrcpy-server` | 206042 B，sha256 `6a805e76…dcb2`，来自 `wetest-scrcpy==0.3.8` wheel（PROVENANCE.md:5） |
| libjpeg-turbo | `src/mobile_auto/stream/assets/libjpeg-turbo.so` | 2458736 B，sha256 `b26ab7d3…e952`，同上（PROVENANCE.md:6） |
| scrcpy server(upstream) | `src/mobile_auto/stream/assets/scrcpy-server-upstream.jar` | 733930 B，sha256 `764eb6f7…c536`，官方 v5.0.1 发布物（Apache-2.0，PROVENANCE.md:7） |
| 资产登记 | `src/mobile_auto/stream/assets/PROVENANCE.md` | 逐文件字节/SHA256/来源；提取脚本 `scripts/fetch_scrcpy_server.py` |
| 模板资产 | 仓库内 `assets/manifest.json` + `assets/versions/<32hex>/{image.png,meta.json}` + `assets/locks/assets.lock` | schema v2；旧版本永不删 |

许可证提醒：`wetest-scrcpy` PyPI 元数据未标 License、无公开源码仓库；`stream` 为条件交付 extras，**内网/平台接入前需合规复核**（PROVENANCE.md:28-29、README）。

### 11.2 测试分层（各层跑什么）

| 层 | 位置 | 跑什么 | 前置 |
|---|---|---|---|
| unit | `tests/unit/`（44 个 `test_*.py` + `conftest.py`/`fakes.py`） | 适配器/会话/租约/池/配置/选择器/图像引擎/viewer/stream 的纯逻辑，全部用 fake 后端与 fake adb | 无设备、无网络 |
| contract | `tests/contract/test_contract.py` | 15 方法"存在 + 异步 + 签名形状 + `platform`"核对；内网接入时用真实绑定层替换契约对象 | 无设备 |
| integration | `tests/integration/`（`test_lease_contention.py`、`test_perf_gate_adapter.py`） | 真实 **Windows 文件锁**上的租约争用语义；`PerfDeviceGate` 三种模式 | 无真机（用 tmp 目录当 lease_dir） |
| device | `tests/device/`（14 个 device 测试文件 + `conftest.py`） | 真机端到端：首流程/操作矩阵/图像流/证据插件/可靠性 30x/通道/模板棚/拾取/投屏/性能联动 | `pytest -m device --mobile-config tests/device/local.toml`；无配置或设备则 **skip 不计通过**；`tests/device/local.toml` 存在于仓库（含真实环境值，未读取内容） |

---

## 12. UI + 性能联动：既有半成品（重要）

三个未跟踪文件构成"UI 驱动 + 性能采集 + 门禁判读"的现成接缝，**已是可运行设计但未纳入构建**：

### 12.1 `src/mobile_auto/_perf_gate.py`（72 行，未跟踪）

模块 docstring（:1-13）声明依赖方向 **mobile_auto → mobile_perf**（ADR-0001），把本包整生命周期 `DeviceLease` 桥接为 `mobile_perf.gate.DeviceGate` 短事务协议：

```python
class PerfDeviceGate:                                  # :30
    def __init__(self, leases: dict[str, DeviceLease] | None = None, *, lease_dir=None)  # :37
    def borrow(self, serial, *, purpose: str, timeout_s: float = 10.0) -> AbstractContextManager[None]  # :43
```

三种模式（:43-56）：
- **嵌入模式**：`leases` 预置的 serial 且 `lease.held` → 返回 `nullcontext()` 重入放行（序列化由宿主会话队列保证，适配器不碰租约）；
- **独立模式**：命中不到 → 新建 `DeviceLease(serial, lease_dir=..., purpose=purpose)` 短事务 acquire，退出经 `_ShortBorrow.__exit__` 释放（:59-69）；
- **被其他进程占用** → `DeviceBusy` 转 `mobile_perf.gate.GateBusyError`，fast-fail（:52-55）。

注入方式（:12）：`PerfKit(gate=PerfDeviceGate(leases={serial: session._lease}))`。`__all__ = ["PerfDeviceGate"]`（:72）。注意 `timeout_s` 参数**签名保留但未使用**（fast-fail 语义）。`_perf_gate.py:20` 直接 `from mobile_perf.gate import GateBusyError`，而 **`pyproject.toml`/`requirements-lock.txt` 均无 `mobile_perf` 依赖、本 workspace 也不存在该包目录**（`ls D:\workspace\claudecode-test` 只有 moblie-auto 等目录）→ 现状是"导入即失败"的半成品。

### 12.2 `tests/integration/test_perf_gate_adapter.py`（53 行，未跟踪）

用 tmp_path 当 lease_dir，真实 Windows 文件锁验证三件事：

1. `test_borrow_acquires_and_releases_short_transaction`（:17）：借用期间外部 `DeviceLease.acquire()` 抛 `DeviceBusy`；退出后立刻可获取（不排队）。
2. `test_borrow_converts_device_busy_to_gate_busy`（:29）：他人持有时 `borrow` 抛 `GateBusyError`。
3. `test_embed_mode_passthrough_when_host_lease_held`（:40）：宿主租约存在时重入放行、不额外取锁、退出不影响宿主租约。

### 12.3 `tests/device/test_perf_linkage_device.py`（107 行，未跟踪）

真机联动用例 `test_ui_swipe_collect_and_gate_judgement`（:68），零人工干预流程：

- `perf_gate` fixture（:30）：从 `mobile_session._lease` 构造 `PerfDeviceGate(leases={session.config.device_serial: lease})`；无租约则 skip。
- `perf` fixture（:39）：`PerfKit(serial=..., runs_dir=tmp/runs, db_path=tmp/data/perf.db, gate=perf_gate, device_profile=..., keep_runs=10)` + `PerfFixture(kit, request)`（与 `--mobile-perf` 钩子同一 `perf.session` 接缝）。
- 驱动：`mobile_session.submit(op)` 内经 u2 后端上滑 400px（`_swipe_up` :55，docstring 明说"scrcpy 通道与 swipe 手势的适配缺口是宿主既有问题"）。
- 判读：第一轮 `perf.session(TARGET_PACKAGE="tv.danmaku.bili", items=["CPU","Memory"], host_run_id="linkage-baseline")` 采基线 + `scope.mark`；`save_baseline(...)` 后第二轮带 `baseline` + `thresholds={"mem_pss_mb":("lt",600,"fail"), "cpu_process_pct":("lt",95,"fail")}` + `min_samples=3`，断言 `result.verdict.verdict ∈ {passed, failed}` 且 `verdict.checks` 非空。

平台含义：**"UI 动作 + 性能采集窗口 + 阈值门禁"的接缝已存在且已跑通设计**，缺的是 `mobile_perf` 依赖纳入、把该用例变成平台作业模板、以及 perf 数据入库。

---

## 13. 平台接入面（能力 → 复用方式 → 平台需补）

| 能力 | 复用方式 | 平台需补什么 |
|---|---|---|
| 契约驱动 UI 自动化（14 个已实现方法 + 3 个坐标手势） | **进程内 import**（`MobileAdapter(DeviceSession)`，全异步） | 任务/用例编排层、步骤 DSL、断言与重试策略、结果模型 |
| 真机连接与会话（u2 + ADB） | **必须同机**（USB / adb 网络连接；ADB 走随包 `tools/adb` 37.0.1） | 设备农场：多机注册、serial 分配、USB 口/网络 adb 管理、断线重连策略 |
| 跨进程设备租约 | 进程内 import + **必须同机**（`%USERPROFILE%\.mobile-auto\leases` 的 Windows 文件区域锁，仅 Windows） | 平台租约中心（DB/RPC）作为权威 + 本地锁兜底；Linux/容器需重写 `lease.py` 的 `msvcrt` 分支为 `fcntl.flock` |
| 失败证据（pytest 插件 + collector + manifest） | 进程内（插件自动加载；`read_manifest`/`read_evidence_file` 读）或 HTTP（viewer `/api/v1/evidence*`） | 归档上传/对象存储、证据索引入平台 DB、报告与用例绑定、保留策略 |
| viewer 只读浏览（设备/状态/证据/租约/运行态） | **HTTP，同机 127.0.0.1**（Host/Origin 硬编码回环） | 反向代理 + 鉴权/租户隔离/TLS；跨机器需改 bind 与白名单（属改目标仓库代码） |
| viewer 快照 / 模板制作 / 拾取 / 定位校验 | **HTTP，同机** | 模板审批流、模板跨环境同步（当前是本地目录 + 摘要校验）、权限 |
| viewer 实时预览/投屏（WS `/api/v1/preview`） | **WS，同机** | 平台侧 WS 转发/多用户限流（目标仓库每设备上限 4 客户端）、媒体网关；快照仅内存（3 张/120s）需平台存档 |
| 受控直接注入（touch/swipe/key/wake） | **HTTP，同机 + 必须先 `POST /api/v1/control` 显式开启** | 权限模型、操作审计（目标仓库无鉴权、仅 50ms 节流）、与自动化任务的互斥 |
| 图像模板匹配引擎（`match_template`/`match_prepared`/`capture_center_*`） | **进程内 import**（纯函数，依赖 extras `image`） | 阈值/策略配置 UI、匹配结果可视化（viewer 已有 validate 端点可复用） |
| 模板资产库（不可变版本 + 摘要校验 + 原子清单） | 进程内 `TemplateStore` 或 HTTP | 版本治理/审批、跨机器分发（当前文件目录，无远端同步） |
| 视频流通道（wetest / upstream scrcpy） | **必须同机**（推设备端 server + 本地 socket） | 媒体转发、多 viewer 合流、通道故障可视化；upstream 为默认 |
| 性能联动门禁（`_perf_gate` + linkage 用例） | 进程内 import（**依赖外部 `mobile_perf`**） | 把 `mobile_perf` 纳入依赖与构建、perf 数据入库、门禁阈值配置化 |
| CLI `doctor` / `serve` | 进程启动（`mobile-auto doctor|serve`，退出码 0/1/2） | 健康检查接入（doctor 报告可解析）、服务编排 |
| 配置模型（frozen dataclass + TOML + 3 环境变量） | 进程内构造（`load_config`/`MobileConfig`） | 平台配置中心、运行时参数下发、多设备并发度（当前无该参数） |

**不可跨机器**（复用即失效）：跨进程租约（本机文件锁）、scrcpy 通道（本机 adb + 本地 socket）、viewer 内存快照库、ADB 真机连接。

---

## 14. 缺口 / 风险清单（平台方案必须显式处理）

1. **无作业/套件/运行组织层**：目标仓库只有 pytest + evidence JSONL + `artifacts/runs` 心跳；没有 Run/Suite/Job/Step 模型（平台自建）。
2. **无鉴权**：viewer 无 token/账号；`POST /api/v1/control` 可被本机任意进程开启直接控制（仅有 Origin/Host 回环校验）。
3. **只 bind 回环**：`viewer/server.py:69`、`cli.py:215` 硬编码 `127.0.0.1`；Host/Origin 白名单也硬编码回环（`viewer/app.py:1485,1490`）→ 远程访问必须改代码或前置网关（网关无法绕过 Origin 校验的 WS 也可以，但需 Host 改写）。
4. **租约仅 Windows**（`core/lease.py:72`），且不跨用户/不跨机器；`holder.json` 残留语义需平台侧解释。
5. **快照库纯内存**（`viewer/store.py:16-21`）：重启丢失，最多 3 张未冻结、冻结 600s；平台要历史回溯须自建存储。
6. **`extract_list` 未实现**（契约占位，`tests/contract/test_contract.py:35-37` 断言不存在）。
7. **`_perf_gate`/联动测试为未跟踪半成品**，且 `mobile_perf` 既非依赖也不在本 workspace（§12.1）→ 构建/安装后导入即 `ImportError`；联动用例、perf 上报目前不可在 CI 交付。
8. **多设备并发**：`DeviceSession` 单设备单 worker 串行；`pool.acquire_from_pool` 只是"候选列表逐个试锁"，无优先级/排队/公平性，全忙时 60s 超时。
9. **无结构化事件/审计流**：只有失败证据与 run state 心跳；成功用例的操作流水、耗时分解需要平台另采。
10. **无热配置/远程配置**：`MobileConfig` frozen，改参需重建会话。
11. **许可证与离线交付**：`wetest-scrcpy` 无 License 声明、`stream` 为条件 extras；`docs/offline-install.md` 有离线安装待核查项（未逐条核实）。
12. **文档明确"交付形态为源码，不打包 wheel"**（README）→ 平台复用应走 `pip install -e` 或 `PYTHONPATH`，不能依赖 PyPI 制品。

### 未核实项

- viewer 只读截屏（`POST /api/v1/snapshots`）是否经过租约门控：仅确认写注入路径用 `_LeaseGuard`（`viewer/app.py:1007`），未逐行追踪 capture 路径。
- `docs/` 下 `validation.md`、`platform-prototype/`、`agents/` 的完整内容未读（本节结论不依赖它们）。
- `tests/device/local.toml` 存在但未读取（含真实环境值）。
- `_perf_gate.py` 的"未跟踪"状态来自 Lead 的任务说明（本任务禁止 git 操作，未自行验证）；`tests/device/test_perf_linkage_device.py`、`tests/integration/test_perf_gate_adapter.py` 同理。
