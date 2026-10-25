# vendor 集成与适配（vendor-integration.md）

> 配套：`docs/plan/development-plan.md` §5、`docs/plan-input/mobile-auto-capability.md`（536 行）、`docs/plan-input/mobile-perf-capability.md`（345 行）。
> 硬规则：**两个源仓库永不写入**；`vendor/**` 只由 `vendor_sync.py` 整体覆盖；平台改造集中在 `server/app/integrations/` 与 `server/runner_pkg/`。

## 1. 复制清单（精确）

| # | 源（只读） | 目标 | 大小 | 理由 |
| --- | --- | --- | --- | --- |
| 1 | `moblie-auto/src/mobile_auto/**` | `vendor/mobile_auto/mobile_auto/**` | ~4.3MB（32 py / 8097 行 + assets） | UI 自动化本体 |
| 2 | `moblie-auto/tools/adb/**` | `vendor/mobile_auto/tools/adb/**` | 9.2MB | `find_adb_binary()` 优先此路径（`backend.py:46-60`），不依赖宿主 PATH |
| 3 | `moblie-auto/pyproject.toml` | `vendor/mobile_auto/pyproject.toml` | — | 可编辑安装 + pytest11 入口 |
| 4 | `moblie-auto/tests/{unit,contract,integration,fixtures}/**` | 同名 | 1.5M+32K+16K+1.6M | 回归基线 |
| 5 | `moblie-auto/docs/{integration.md,validation.md}` | `vendor/mobile_auto/docs/` | 小 | 契约说明留档 |
| 6 | `moblie-xn/src/mobile_perf/**` | `vendor/mobile_perf/mobile_perf/**` | ~1.1MB（21 py + assets 1008K） | 性能采集本体 |
| 7 | `moblie-xn/pyproject.toml` | `vendor/mobile_perf/pyproject.toml` | — | 同上 |
| 8 | `moblie-xn/tests/{unit,contract,integration,fixtures}/**` | 同名 | 304K+20K+16K+168K | 回归基线 |
| 9 | `moblie-xn/dist/solopi/**` | `vendor/mobile_perf/dist/solopi/**` | 7.7MB | SoloPi debug apk + platform-tools（部署前置） |

**不复制**：`tests/device/**`（moblie-auto 7.1MB / moblie-xn 60K）、SoloPi 源码（56MB）、`runs/`（5MB）、`docs/snapshots/`（3.6MB）、`solopi-master.tar.gz`（17.8MB）、`__pycache__`、`.git`、`.venv`。

合计约 **26MB**，全部入 git（apk 与 adb 二进制换取可复现）。

## 2. `VENDOR.lock.json` 与 `vendor_sync.py`

```json
{
  "synced_at": "2026-10-25T13:00:00Z",
  "sources": {
    "mobile_auto": { "path": "D:/workspace/claudecode-test/moblie-auto",
                     "git_commit": "<sha>", "version": "<__version__>" },
    "mobile_perf": { "path": "D:/workspace/claudecode-test/moblie-xn",
                     "git_commit": "<sha>", "version": "<__version__>" }
  },
  "files": { "vendor/mobile_auto/mobile_auto/core/session.py":
               { "sha256": "ab...", "size": 51422, "src": "src/mobile_auto/core/session.py" } }
}
```

| 命令 | 行为 | 退出码 |
| --- | --- | --- |
| `--sync` | 按清单复制（先清空目标子目录，排除表生效），重建锁文件 | 0 |
| `--check` | 只读校验：每文件存在且 sha256 匹配、无多余文件 | 0 一致 / 1 不一致（打印差异） |
| `--diff` | 打印与源仓库差异（供决定是否升级） | 0 |

CI 与发布门禁：`--check` 必须绿。任何手工改 `vendor/**` 都会被它抓出来。

## 3. 可编辑安装与环境注入

```bash
python -m pip install -e vendor/mobile_auto -e vendor/mobile_perf
```

| 注入项 | 值 | 原因 |
| --- | --- | --- |
| `TMP` / `TEMP` / `TMPDIR` | `data/tmp` | 受限账户下 `%TEMP%` 可能不可写（实测 `WinError 5`） |
| `HOME` / `USERPROFILE` | `data/tmp/home` | vendor 租约默认目录 `~/.mobile-auto/leases`（`lease.py:27`）收敛进仓库 |
| `PYTHONPATH` | `vendor/mobile_auto;vendor/mobile_perf` | 免安装也能跑（runner 兜底） |
| `PYTHONIOENCODING` | `utf-8` | 中文日志/路径 |
| `NO_PROXY` | `127.0.0.1,localhost` | 反代与心跳不被代理拦截 |

## 4. 四个适配层文件

### 4.1 `server/app/integrations/mobile_auto.py`

```python
def build_config(*, artifacts_dir: Path, serial: str, package: str) -> MobileConfig:
    # screenshot_source='u2'：全分辨率取证（scrcpy 流分辨率会缩到 max_size=1080）
    # injection_source='auto'，wait_timeout=10.0，poll_interval=0.5
def open_session(cfg: MobileConfig, *, lease_factory) -> DeviceSession: ...
async def with_adapter(session, fn) -> T: ...
```

要点：`DeviceSession(config=cfg, lease_factory=lease_factory)`；`start()` 前必须已持有平台租约（顺序见 §4.4）。

### 4.2 `server/app/integrations/mobile_perf.py`

```python
def build_kit(*, serial: str, runs_dir: Path, adb_path: Path, gate) -> PerfKit:
def metrics_from_report(report: dict) -> list[MetricRow]:
    # 26 键字典：metrics.column_to_metric 翻译；value=NULL 时必带 missing_reason
def verdict_from_judge(report: dict, spec: JudgeSpec) -> VerdictOut:
    # 直接调 judge.judge；not_tested 的中文原因 -> reason_code + reason_text
def normalize_profile(device_profile: str) -> str:
    # 'Android 14 / 1440x3120 / Pixel 7 Pro' -> 'android14|1440x3120|pixel7pro'
```

`normalize_profile` 是 R4 风险的唯一解：vendor 判定只比 `deviceProfile` 字符串，不规范化就会恒 `not_tested`。平台在写 `resource_profiles.profile_key` 与读 vendor `report.deviceProfile` 时都过它，并覆盖 6 种脏写法单测。

### 4.3 `server/app/integrations/viewer_proxy.py`

vendor viewer 三重硬限制（`viewer/app.py:1485,1490`、`server.py:69`）：Host/Origin 只认 `127.0.0.1|localhost|::1`、只 bind 回环、无鉴权。代理方案：

```
浏览器 -> api /api/v1/debug/{sid}/**  -> httpx / websockets -> 127.0.0.1:<vendor_port>/**
                 | 平台校验 debug_session 存活与归属
                 转发时改写 Host: 127.0.0.1:<vendor_port>
                 转发时改写 Origin: http://127.0.0.1:<vendor_port>
```

| 项 | 处理 |
| --- | --- |
| 路径白名单 | `/api/v1/{devices,status,snapshots,templates,control,input,locators,preview,evidence}`；其余 404 |
| WS 帧 | 双向原样转发（text 与 bytes 都支持），不做 JSON 解析 |
| 关闭码 | 透传 vendor 4403/4404/4429，平台侧新增 4410（会话已关闭） |
| 超时 | HTTP 30s；WS 无空闲超时（由会话生命周期控制） |
| 失败隔离 | vendor 进程死 → `debug_sessions.state=lost` + 释放租约 + WS close(1011) |
| 备选（R3） | WS 代理不稳时改 `iframe` 直连 `127.0.0.1:<port>`，代价是失去统一鉴权（仅回环可接受） |

### 4.4 `server/app/integrations/leases.py`（双锁顺序，最容易写错）

```python
class PlatformGate(mobile_perf.gate.DeviceGate):
    def borrow(self, serial, *, purpose='', timeout_s=10.0):
        # 1) 先校验平台 token 仍归本 run（GET /internal/runs/{id}/fence），失配 -> FenceMismatch
        # 2) 再取 vendor 本机锁 FileLockGate().borrow(serial)，失败 -> GateBusyError
        # 3) 两者都拿到才 yield；退出时先放 vendor 锁，再由 api 释放 DB 租约（顺序不可反）
```

| 场景 | 结果 |
| --- | --- |
| fence 失配（进入时） | `errored`，outcome NULL，不碰设备 |
| vendor 锁被占（别的账号/残留进程） | `errored`，`error_code=local_lease_busy`，DB 租约释放 |
| 执行中 fence 失配（租约被回收） | 立即停设备操作、结果丢弃、`errored` |
| runner 崩溃 | reconciler 60s 后释放 DB 租约；vendor 锁随进程死自动放 |
| api 重启 | 旧 token 失效；在跑 runner 心跳 401 → 自行收尾退出 |

## 5. 已知缺陷登记（vendor 缺口 → 平台对策）

| # | vendor 缺口 | 平台对策 | 期 |
| --- | --- | --- | --- |
| V1 | 租约仅 Windows `msvcrt`，非 Windows 抛 `DeviceUnavailable`（`lease.py:72`） | DB 租约权威；容器化时注入 `PortableLease`（fcntl），不改 vendor（`lease_factory` 已支持） | 三期 |
| V2 | `mobile_perf.gate` 非 Windows 完全 passthrough（`gate.py:140`） | PlatformGate 提供真实互斥 | 首期（DB） |
| V3 | `collect` 数分钟窗口内不持锁（每条命令各借一次） | run 全程持平台租约，vendor 锁只作命令级兜底 | 首期 |
| V4 | 性能实时指标推送缺失（`cli.py:366` 仅返回 2） | 只推阶段进度，不推指标值；UI 明确提示采集中、完成后出曲线 | 首期 |
| V5 | `mark()` 无回调 | 不从 vendor 打标；需要时平台自行记 run_events | 二期 |
| V6 | `report.html` 里 marks 不画曲线（`report.py:642`） | 平台按 `marks[].elapsedS` 在趋势图打竖线 | 首期 |
| V7 | `artifacts` 是采集机绝对路径 | 归档改写为根相对 URI（`runs/<run_id>/...`） | 首期 |
| V8 | `report.json schemaVersion=1` 无迁移 | 归档记 schemaVersion，导入按版本分支；未知版本拒绝 | 首期 |
| V9 | `mobile_auto` 无 `extract_list` | 用 `find_elements()`（要求无序号）+ `dump_ui` 兜底 | 首期 |
| V10 | viewer 快照纯内存（重启即失） | 冻结快照立即落 `artifacts` 才持久 | 首期 |
| V11 | viewer 无鉴权/仅回环 | 平台反代 + 会话校验（§4.3） | 首期 |
| V12 | `--mobile-config` 只由 `tests/device/conftest.py` 提供，插件不注册 | runner 生成临时 `conftest.py` 提供该选项 | 首期 |

## 6. 许可与合规

| 组件 | 许可 | 结论 |
| --- | --- | --- |
| `mobile_auto` / `mobile_perf` 源码 | 内部项目许可 | 内部复制，保留源许可文件 |
| `uiautomator2` / `adbutils` / `Pillow` | 开源（MIT / Apache / HPND） | 作为依赖安装，不复制源码 |
| SoloPi APK（`com.alipay.hulu`） | 按上游许可 | 仅内部测试机安装，不再分发；来源与版本记入 lock |
| wetest scrcpy-server / libjpeg-turbo | **待确认** | 内部使用；若需对外分发改用 vendor 内置 `scrcpy-server-upstream.jar` |
| platform-tools（adb） | Apache-2.0 | 随包复制合规 |

## 7. 升级 vendor 流程（三步全绿）

1. `vendor_sync.py --diff` 看清变化。
2. `vendor_sync.py --sync` 更新 `vendor/**` 与 lock。
3. 宿主跑 `run_vendor_tests.sh`（两包 unit+contract 全绿）→ `pytest server/tests -m integration`（适配层签名漂移检测）→ 端到端抽测（UI 1 套件 + 性能 1 采集）。

任一步红：git revert `vendor/**` 与 lock，记录不兼容点。

## 8. 集成验收

1. `vendor_sync.py --check` 绿（含 CI）。
2. `run_vendor_tests.sh` 宿主 100% 通过，日志中 `TMP` 指向 `data/tmp`。
3. `python -c "import mobile_auto, mobile_perf; print(mobile_auto.__version__)"` 可用。
4. 干净环境（PATH 无 adb）下 runner 仍能找到 adb（走 `vendor/mobile_auto/tools/adb/adb.exe`）。
5. 平台起的 debug 会话能经反代拿到 vendor 快照与预览帧。
6. `PlatformGate` 五条异常路径单测全绿。