# 平台执行环境约束实测报告（pytest / 落盘路径 / adb）

> 审查对象：`D:/workspace/claudecode-test/moblie-auto`（mobile-auto 0.1.0）与 `D:/workspace/claudecode-test/moblie-xn`（mobile-perf），以及「在 DSH 沙箱内能否跑它们的测试、需要注入哪些路径类环境变量」这一执行环境前提。
> 方法：两个既有项目全程只读（未写入、未安装、未改配置），把 `src + tests + pyproject.toml` 复制到 `testplat-auto/.probe/env-inv/` 副本上实测；命令与输出全部来自本次会话（2026-10-25，pwsh 7.6.8）。
> 执行人：inv-auto（Team Lead 调研员），task-4。
> 标注约定：「实测」= 本文附命令与输出；「未确认」= 本次没验证到，不得当结论使用。

---

## 0. 结论摘要（先看这里）

| # | 结论 | 证据 |
| --- | --- | --- |
| 1 | pytest 在 DSH 沙箱里失败的**根因不是 `%TEMP%`、也不是 `--basetemp`**，而是：凡以 `mode=0o700` 创建的目录在沙箱内**一律不可访问**——`mkdir` 成功、随后 `scandir`/写文件/`rmdir` 全部 `WinError 5`，且事后 `chmod 0o777` 也报 `WinError 5`（目录一旦这样建出来就修不回来）。 | §2.1 直接探针 |
| 2 | 只重定向 `USERPROFILE/HOME/TMP/TEMP` 对测试结果**零影响**（三组计数完全一致）；再叠加 `--basetemp` 也不改变用例计数，只会让会话收尾抛 `PermissionError`。 | §1.2 矩阵表 |
| 3 | 沙箱内能让测试真跑起来的办法只有一个：把 `os.mkdir` 的 mode 强制成 `0o777`（探针插件 `fixplugin`）。修复后 auto 512 项 **509 passed / 2 failed / 1 skipped**，perf 426 项 **417 passed / 9 failed**，全部剩项与沙箱无关。 | §1.3、§2.4 |
| 4 | 平台结论：vendor 回归与平台集成测试**默认放宿主 shell / CI 跑**；若确需在沙箱内跑，平台必须自带 pytest 插件（等价 fixplugin，但只作用于 basetemp 子树）并强制 `-p no:cacheprovider`。 | §5 |
| 5 | 本机**当前有真机在线**：`749622c9`（小米 2206123SC / mayfly）。`device` 标记用例会真的操作这台机器，必须显式 `serial`；盘点/CI 阶段不应跑 device 套件。 | §4.1 |

> 对 `docs/plan/development-plan.md` 的提示：§12.1 第 1 条与 F17 把原因写成「`%TEMP%` `WinError 5`，`--basetemp` 亦失败」，方向对但**结论过强**——沙箱内并非绝对跑不了，加上 mode 修正后 auto 只剩 2 个 fail。建议改为「tmp 目录 mode=0o700 不可访问；env 重定向无效；沙箱内需插件兜底、否则放宿主跑」，详见 §5.5。

---

## 1. 实验方法与环境基线

### 1.1 环境与副本

| 项 | 值 |
| --- | --- |
| Python（测试用） | `D:/python312/python.exe`，Python 3.12.10（实测 `python -V`） |
| pytest | 9.1.1（实测 `python -m pytest --version`） |
| 另一套解释器 | `D:/workspace/claudecode-test/moblie-auto/.venv/Scripts/python.exe`，Python 3.12.10，以 editable 方式装了 mobile-auto 0.1.0 与 adbutils 2.12.0 / uiautomator2 / numpy 2.5.4 / opencv-python-headless 5.0.0.93 / pillow 13.0.0 / fastapi 0.161.1 / av 19.0.2 / pytest-asyncio 1.4.0 |
| 副本根 | `D:/workspace/claudecode-test/testplat-auto/.probe/env-inv/` |

副本清单（实测）：

```text
.probe/env-inv/
  auto-full/   moblie-auto 全量副本，451 文件 20.4MB（robocopy 排除 .git .venv .scratch artifacts dist 各缓存 downloads perf-output runs solopi-master.tar.gz）
  perf-full/   moblie-xn 全量副本，1032 文件 55.3MB（同上排除策略）
  home/ tmp/   重定向后的 USERPROFILE/HOME 与 TEMP/TMP
  fixplugin.py 探针专用 pytest 插件（仅本地探测，不是交付物）
  run_matrix.ps1  logs/{auto,perf}-{a,b,c}.txt + junit-*.xml   矩阵复现脚本与原始日志
```

说明：副本是必须的——源仓库只读，且沙箱会在仓库内留下 `.pytest_cache`/临时目录。矩阵阶段统一用项目 venv 解释器（`moblie-auto/.venv/Scripts/python.exe`）；§1.3 的 fixplugin 复测用系统解释器 `D:\python312\python.exe`，两者同为 3.12.10 + pytest 9.1.1，结论不受影响。`PYTHONPATH=<副本>/src` 已验证 `import mobile_auto` 解析到副本（editable 安装的 finder 不会抢走）。

### 1.2 三组环境矩阵（a/b/c）与结果

矩阵脚本 `D:/workspace/claudecode-test/testplat-auto/.probe/env-inv/run_matrix.ps1`（36 行，实测逐字复现）：

```powershell
$root='D:\workspace\claudecode-test\testplat-auto\.probe\env-inv'
$py='D:\workspace\claudecode-test\moblie-auto\.venv\Scripts\python.exe'
# (a) 默认环境：USERPROFILE/HOME=C:\Users\williamzeng，TEMP=TMP=<系统 Temp>
# (b) USERPROFILE/HOME=$root\home，TEMP=TMP=$root\tmp
# (c) (b) + --basetemp=$root\bt-<repo>-c
& $py -m pytest tests/unit tests/contract -q --no-header --tb=no --junitxml "$root\logs\junit-$repo-$cfg.xml"
```

| 组合 | auto（收集 512 项） | perf（收集 426 项） | 现象 |
| --- | --- | --- | --- |
| (a) 默认环境 | 261 passed / 166 error / 85 failed，exit 1 | 225 / 198 / 3，exit 1 | `tmp_path` 类用例全挂 |
| (b) HOME/TEMP 指向 workspace 内 | 261 / 166 / 85，exit 1 | 225 / 198 / 3，exit 1 | **计数与 (a) 完全相同** |
| (c) (b) + `--basetemp` | 261 / 166 / 85，exit 1 | 225 / 198 / 3，exit 1 | 用例计数不变，会话收尾再崩一次（§2.2） |

> 逐字结论：**改环境变量、加 `--basetemp` 都救不了**。原始日志：`.probe/env-inv/logs/auto-a.txt` ~ `perf-c.txt`。

### 1.3 沙箱内跑通的方式：把目录 mode 强制成 0o777

探针插件 `.probe/env-inv/fixplugin.py`（13 行，实测全文）：

```python
"""Local-sandbox-only probe plugin: force dir modes to 0o777 (0o700 dirs are inaccessible here)."""
import os

_orig_mkdir = os.mkdir


def _mkdir(path, mode=0o777, *args, **kwargs):
    return _orig_mkdir(path, 0o777, *args, **kwargs)


def pytest_configure(config):
    os.mkdir = _mkdir
    os.makedirs = os.makedirs
```

（最后一行是探针遗留的空操作，不代表任何语义；`os.makedirs` 内部调用的是模块级 `os.mkdir`，所以改一个就够。）

效果（实测）：

| 对象 | 未加插件 | 加 fixplugin + `PYTHONUTF8=1` + HOME/TEMP 重定向 + `--basetemp` |
| --- | --- | --- |
| auto 裁剪副本（512 项） | 261 p / 166 e / 85 f | **496 passed / 15 failed / 1 skipped / 0 error** |
| perf 裁剪副本（426 项） | 225 / 198 / 3 | 414 passed / 12 failed / 0 error |
| auto-full 全量副本（512 项） | — | **509 passed / 2 failed / 1 skipped / 0 error** |
| perf-full 全量副本（426 项） | — | **417 passed / 9 failed / 0 error** |

裁剪副本 → 全量副本修好的失败项，说明「跑 vendor 回归必须用完整仓库副本」：

- auto `tests/unit/test_debug_viewer.py` 4 个：`UnicodeDecodeError: 'gbk' codec can't decode byte 0xac in position 9: illegal multibyte sequence` → 设 `PYTHONUTF8=1` 即修复（与本机 GBK 默认编码有关，不是逻辑问题）。
- auto `test_dual_pane_logic` 2 个：依赖仓库内 node 前端套件文件，裁剪副本缺失。
- perf `tests/unit/test_adb.py::test_bundled_fallback_when_no_explicit_and_no_env`、`test_solo.py::test_harness_entry_points_at_repo_snapshot`、`tests/contract/test_harness_boundary.py::test_real_harness_entry_is_importable_only_in_subprocess`：需要仓库内 `SoloPi/` 快照文件。

---

## 2. 失败根因（逐条证据）

### 2.1 直接证据：`mkdir(mode=0o700)` 建出来的目录在沙箱内不可访问

探针脚本 `.probe/env-inv/rc.py`（直接调 os 层，不经 pytest）：

```python
os.mkdir(d, 0o700); print(st_mode); os.scandir(d) / open(d/'f.txt','w') / os.rmdir(d)
os.mkdir(d2, 0o777); 同上
```

实测输出（逐字）：

```text
mkdir '...\bt-rootcause\d700' mode=0o700 -> OK, st_mode=0o777
  scandir -> PermissionError: [WinError 5] [WinError 5] 拒绝访问。: '...\bt-rootcause\d700'
  open-write -> PermissionError: [WinError None] [Errno 13] Permission denied: '...\bt-rootcause\d700\f.txt'
  rmdir -> PermissionError: [WinError 5] [WinError 5] 拒绝访问。: '...\bt-rootcause\d700'
mkdir '...\bt-rootcause\d777' mode=0o777 -> OK, st_mode=0o777
  scandir -> OK
  open-write -> OK
  rmdir -> OSError: [WinError 145] 目录不是空的。: '...\bt-rootcause\d777'
```

注意 `st_mode` 读回来都是 `0o777`（沙箱在 Windows 上并不真实映射 POSIX 权限位），但 **0o700 那一份实际 ACL 拒绝了本进程**。补充探针 `.probe/env-inv/rc2.py`（实测）：

```text
after mkdir 0o700: scandir ERR PermissionError [WinError 5] 拒绝访问。
os.chmod(d, 0o777) -> PermissionError: [WinError 5] 拒绝访问。: '...\fixed'
```

即 **目录建坏之后无法从进程内修复**（`chmod` 也被拒），只能在创建时就不要用 0o700。这就是「改 env / 改 basetemp 无效」的物理原因。

### 2.2 pytest 侧证据：tmpdir 全部用 `mkdir(mode=0o700)`，收尾再崩一次

pytest 9.1.1 源码中，tmp 目录创建处处写死 0o700（`D:/python312/Lib/site-packages/_pytest/`）：

| 位置 | 内容 |
| --- | --- |
| `_pytest/tmpdir.py:139` | `p.mkdir(mode=0o700)` |
| `_pytest/tmpdir.py:141` | `make_numbered_dir(root=self.getbasetemp(), prefix=basename, mode=0o700)` |
| `_pytest/tmpdir.py:158` | given `--basetemp` 分支：`basetemp.mkdir(mode=0o700)` |
| `_pytest/tmpdir.py:168` / `172` | `rootdir.mkdir(mode=0o700, exist_ok=True)`（`pytest-of-<user>`） |
| `_pytest/pathlib.py:224` | `def make_numbered_dir(root, prefix, mode: int = 0o700)` |
| `_pytest/pytester.py:1511` / `1532` | `runpytest-` 目录与 basetemp 同样 0o700 |

所以只要走 `tmp_path` / `tmp_path_factory` / `pytester`，沙箱内必挂；`--basetemp` 只是换了个位置建同样的 0o700 目录。

实测异常原文（`python -m pytest tests/unit/test_config.py -q -p no:cacheprovider --tb=long -x --basetemp ...`，无 fixplugin）：

```text
  File "D:\python312\Lib\site-packages\_pytest\tmpdir.py", line 337, in pytest_sessionfinish
    cleanup_dead_symlinks(basetemp)
  File "D:\python312\Lib\site-packages\_pytest\pathlib.py", line 354, in cleanup_dead_symlinks
    for left_dir in root.iterdir():
  File "D:\python312\Lib\pathlib.py", line 1056, in iterdir
    for name in os.listdir(self):
PermissionError: [WinError 5] 拒绝访问。: '...\.probe\env-inv\bt-tmpfail'
```

同一现象在最小复现（`.probe/env-inv/mini/test_t.py`，两个只用 `tmp_path` 的用例）上稳定重现：输出 `EE` + 上述 sessionfinish 崩溃，退出码 1。
补充：`PYTEST_DEBUG_TEMPROOT` 仅换 temproot，仍走 `rootdir.mkdir(mode=0o700)`（tmpdir.py:168），**同样无效**（推断，未单独跑；但按源码可判定）。

### 2.3 `Path.home()` 与租约目录 `~/.mobile-auto/leases`：不是根因，但必须重定向

约定：租约目录是 `Path.home() / '.mobile-auto' / 'leases'`，锁文件名 `<sha256(serial)[:24]>.lock`，伴生 `.holder.json`。

| 项 | 文件:行 | 事实 |
| --- | --- | --- |
| auto 默认租约目录 | `moblie-auto/src/mobile_auto/core/lease.py:27` | `DEFAULT_LEASE_DIR = Path.home() / '.mobile-auto' / 'leases'` |
| auto 租约构造 | `lease.py:30-49` | `DeviceLease(serial, lease_dir=None, *, worker='', purpose='')`；`self._dir = Path(lease_dir) if lease_dir else DEFAULT_LEASE_DIR` |
| auto 锁文件名 | `lease.py:45-47` | `digest = sha256(serial)[:24]`；`<digest>.lock` + `<digest>.holder.json` |
| auto 获取方式 | `lease.py:63-86` | `self._dir.mkdir(parents=True, exist_ok=True)`，`open(..., 'a+b')` + `msvcrt.locking(LK_NBLCK, 1)`；非 Windows 抛 `DeviceUnavailable('设备租约当前仅支持 Windows(plan 7.2)')`（lease.py:71-72） |
| perf 同协议 | `moblie-xn/src/mobile_perf/gate.py:27`、`53-54`、`80-99` | `DEFAULT_LEASE_DIR` 同上；`FileLockGate(lease_dir=None, ...)`；`self._dir = Path(lease_dir) if lease_dir is not None else DEFAULT_LEASE_DIR`；`path = self._dir / f'{digest}.lock'` |

实测（本会话）：

- 真实用户目录**已存在且可访问**：`C:\Users\williamzeng\.mobile-auto\leases` 下有 3+ 组 `.lock/.holder.json`；说明租约写入本身在「宿主 shell」环境没问题。
- 把 `USERPROFILE/HOME` 指到 `.probe/env-inv/home` 后，测试同样在该目录下建出 `.mobile-auto/leases/<digest>.lock`，**正常工作**（实测存在）。
- 当前在线设备 `749622c9` 的 digest = `0d78782d0e78d5e1010e6039`（实测 `sha256('749622c9')[:24]`），对应真实 home 与重定向 home 下的同名锁文件。

结论：`Path.home()` 类写入在沙箱内**可以**通过 `USERPROFILE/HOME` 重定向解决（也应当重定向，避免污染真实用户目录、避免和开发机上人工跑的会话抢锁）；它**不是** 166 error / 85 failed 的来源。

### 2.4 其他失败簇（与沙箱无关，但平台需要知道）

| 失败簇 | 数量 | 原因 | 处理 |
| --- | --- | --- | --- |
| `tests/unit/test_pytest_plugin.py`（pytester 子进程用例） | auto 2 个（`test_flag_off_collects_nothing` 报 `ValueError`、`test_flag_on_writes_evidence_section`）；perf 9 个 | 子进程里依赖 `mobile_auto` / `mobile_perf` 的 **pytest11 入口点**；本机 venv 的入口点没注册（`importlib.metadata.entry_points(group='pytest11')` 只有 `anyio`、`pytest_asyncio`；site-packages 里有损坏的 `~obile_auto-0.1.0.dist-info`，pip 也警告 `Ignoring invalid distribution ~obile_auto`） | 平台侧以 `-p <plugin module>` 显式加载插件；设 `PYTEST_PLUGINS=mobile_auto.evidence.pytest_plugin` 重跑**仍失败** → 是否能在正常安装环境通过，**未确认** |
| GBK 解码 | auto 4 个（`test_debug_viewer`） | Windows 默认 locale 解码 UTF-8 资源 | `PYTHONUTF8=1`（实测修复） |
| 仓库文件缺失 | auto 2（node 前端套件）、perf 3（`SoloPi/` 快照） | 裁剪副本缺文件 | 用完整副本（实测修复） |

### 2.5 沙箱相关未确认项

1. **宿主 shell（非沙箱）里是否完全不需要 fixplugin**：未确认（本会话固定在沙箱内，无法在宿主直接跑）。按 §2.1 机理推断应当不需要。
2. 平台自带插件把 mode 改成 0o777 只作用于 basetemp 子树（而不是全局替换 `os.mkdir`）是否足够：**未确认**，但 §2.1 表明只要目录创建时不用 0o700 即可，作用域收窄不影响结论。
3. `os.mkdir` 被替换后是否影响被测代码自身行为：fixplugin 是全局替换，实测 509/512 通过，未见副作用；生产版应限定路径前缀。

---

## 3. 落盘位置配置项清单（平台需要能全部重定向）

### 3.1 moblie-auto（mobile-auto）

| 落盘对象 | 配置项 / 位置 | 默认值 | 重定向方式 |
| --- | --- | --- | --- |
| 设备 serial | env `MOBILE_DEVICE_SERIAL`（`src/mobile_auto/config.py:29`） | 无 | 环境变量 / TOML `device_serial` / `load_config(device_serial=...)` |
| 包名 / Activity | env `MOBILE_APP_PACKAGE`、`MOBILE_APP_ACTIVITY`（`config.py:30-31`） | 无 | 同上（`app_package` / `app_activity`） |
| 环境变量总表 | `config.py:4-5` 注释 + `_ENV_FIELDS`（`config.py:56-60`） | 只认**这 3 个** | 其余字段没有 env 来源，只能 TOML/显式参数 |
| TOML 键 | `config.py:33-51` `_TOML_FIELDS`，15 个键：`device_serial, device_pool, app_package, app_activity, assets_dir, artifacts_dir, launch_ready_target, allowed_deeplink_schemes, dialog_guard, wait_timeout, poll_interval, port, screenshot_source, injection_source, stream_backend` | — | `load_config(config_path=...)`；未知键抛 `ConfigurationError`（`config.py:313-327` 区域） |
| 资产目录（模板/图片） | `config.py:79` `assets_dir: Path = Path('assets')` | `<config 父目录>/assets` | TOML `assets_dir` 绝对路径 |
| 产物目录（证据/清单/run 状态） | `config.py:80` `artifacts_dir: Path = Path('artifacts')` | `<config 父目录>/artifacts` | TOML `artifacts_dir` 绝对路径 |
| 证据目录 | `evidence/collector.py:54` | `<artifacts_dir>/evidence/<uuid4().hex[:16]>` | 由 `artifacts_dir` 决定 |
| 运行清单 | `evidence/collector.py:119-121`（读 `:190`/`:207`） | `<artifacts_dir>/run-manifest.jsonl`（JSONL 追加） | 同上 |
| 并行 run 状态 | `pool.py:75-78` `worker_artifacts_dir(base, worker) = base/f'xdist-{worker}'`；`pool.py:81-107` | `<artifacts_dir>/runs/<worker|main>.json`（tmp+replace 原子写） | 同上（pytest 插件里 `dataclasses.replace(artifacts_dir=worker_artifacts_dir(...))`，`evidence/pytest_plugin.py:109`/`119`） |
| 租约目录 | `core/lease.py:27`；构造参数 `lease_dir`（`lease.py:30-49`） | `Path.home()/.mobile-auto/leases` | `DeviceLease(..., lease_dir=...)` 或插件注入 `lease_factory`；**无 env / 无 TOML 键** |
| viewer/服务端口 | `config.py:88` `port: int = 8765`；`viewer/server.py:61` 起被占则递增探测 | 8765 | TOML `port` / `load_config(port=...)` |
| adb 可执行文件 | `core/backend.py:43` `_BUNDLED_ADB = Path(__file__).parents[3]/'tools'/'adb'/'adb.exe'`；`backend.py:47-51` 随包优先、其次 adbutils | 仓库 `tools/adb/adb.exe`（37.0.1） | **没有 env 覆盖**；要走别的 adb 只能改代码或让随包文件存在 |
| pytest 插件选项 | `evidence/pytest_plugin.py:29-49`：`--mobile-evidence`（store_true）、`--mobile-devices`（逗号分隔覆盖 `device_pool`）、`--debug-viewer`（store_true）；`--mobile-config` 经 `_optional_getoption` 兜底读取 | 关 | 命令行 |

路径解析规则（重要）：`load_config` 优先级「显式参数 > env > TOML > 默认」（`config.py:239-310`）；`assets_dir`/`artifacts_dir` 若是相对路径，基准是**配置文件父目录**，没有 config_path 时是 `Path.cwd()`，返回前转绝对路径（`config.py:303-307`）。→ 平台只要在 TOML 里写绝对路径（或在特定 cwd 下用默认相对路径），即可完全控制落盘位置。

### 3.2 moblie-xn（mobile-perf）

| 落盘对象 | 配置项 / 位置 | 默认值 | 重定向方式 |
| --- | --- | --- | --- |
| 设备 serial | env `MOBILE_PERF_SERIAL`（`src/mobile_perf/cli.py:145`） | 无 | `--serial` / env / 唯一在线设备兜底（`cli.py:142-148`） |
| adb 可执行文件 | `adb.py:33-56` `resolve_adb(explicit, env, repo_root)`：显式参数 > `MOBILE_PERF_ADB` > `ADB` > 随包 | `<repo_root>/SoloPi/platform-tools/adb.exe`（`adb.py:14`） | `--adb` / env `MOBILE_PERF_ADB` / env `ADB` |
| repo_root（决定下面全部默认路径） | `adb.py:23-25` `default_repo_root() = Path(__file__).resolve().parents[2]` | 仓库根 | `PerfKit(repo_root=...)`（`kit.py:551-553`） |
| run 归档目录 | `kit.py:552`，`collector.py:51-52` `create_run_dir(runs_dir, run_id)=Path(runs_dir)/run_id` | `<repo_root>/runs`；目录名 `run-YYYYMMDD-HHMMSS-<hex4>`（`collector.py:34`） | `PerfKit(runs_dir=...)`、CLI `--runs-dir`（`cli.py:53`/`80`，`cli.py:270`）、pytest `--mobile-perf-runs-dir`（`pytest_plugin.py:42`） |
| SQLite store | `kit.py:553` `self.db_path = db_path`；`store.py:1-10` 默认 `<repo>/data/mobile_perf.db`（WAL、busy_timeout 5s） | `<repo_root>/data/mobile_perf.db` | `PerfKit(db_path=...)`、CLI `--db`（`cli.py:133`）、pytest `--mobile-perf-db`（`pytest_plugin.py:43`） |
| run 保留策略 | `kit.py:38-39` `DEFAULT_KEEP_RUNS=200`、`DEFAULT_KEEP_DAYS=30.0`；`collector.py:279-320` 清理 | 200 / 30 天 | 构造参数 `keep_runs`/`keep_days` |
| 租约目录 | `gate.py:27`；`FileLockGate(lease_dir=None, ...)`（`gate.py:80-99`） | `Path.home()/.mobile-auto/leases` | 构造参数 `lease_dir`（`PerfKit(gate=FileLockGate(lease_dir=...))`）；**无 env** |
| Harness 入口 | `solo.py:21-29` `HARNESS_ENTRY_REL_PATH = SoloPi/solopi-skill/scripts/harness/src/solopi_harness/solopi_ai.py`；`solo.py:58-60` | `<repo_root>/` 下 | `PerfKit(repo_root=...)` / `harness_entry(repo_root=...)`；必须以子进程调用（`solo.py:1-6`，harness import 会改 `sys.path`） |
| pytest 选项 / ini | `pytest_plugin.py:23-63`：`--mobile-perf`、`--mobile-perf-serial`、`--mobile-perf-items`（默认 `CPU,Memory`）、`--mobile-perf-runs-dir`、`--mobile-perf-db`、`--mobile-perf-baseline`、`--mobile-perf-threshold`；ini `mobile_perf_serial` / `mobile_perf_items` / `mobile_perf_thresholds` | 见左 | 命令行 / ini |

### 3.3 平台/Agent 侧的重定向映射建议（把两者都收敛进仓库）

| 外部位置 | 现状 | 平台建议值 |
| --- | --- | --- |
| `~/.mobile-auto/leases` | auto `lease.py:27` / perf `gate.py:27` 硬编码 home | 注入 `lease_dir=data/tmp/leases`（auto 用插件 `lease_factory`，perf 用 `FileLockGate(lease_dir=...)`）——锁文件跨进程共享，必须**同一目录**才互斥 |
| `<repo>/runs`（perf） | `kit.py:552` 默认 | `--runs-dir data/runs`（平台 run 目录下按 run_id 隔离） |
| `<repo>/data/mobile_perf.db` | `store.py:1-10` | `--db data/db/mobile_perf.db`（SQLite 仍留在平台数据目录，便于归档） |
| `<repo>/artifacts`（auto） | `config.py:80` | TOML `artifacts_dir = <平台数据目录>/artifacts`（绝对路径） |
| `<repo>/assets`（auto） | `config.py:79` | 平台仓库 `assets/`，只读共享即可 |
| adb | auto 随包 `tools/adb`（`backend.py:43`）；perf 随包 `SoloPi/platform-tools`（`adb.py:14`） | 平台 vendor 目录里各保留一份副本；perf 侧可 `--adb` 指向 auto 同款 37.0.1，避免两套 server 冲突（两者都走 `adb` 默认端口 5037 的**同一个 server**） |

---

## 4. adb 实测

### 4.1 可执行性与当前设备

```powershell
PS> & 'D:\workspace\claudecode-test\moblie-auto\tools\adb\adb.exe' version
Android Debug Bridge version 1.0.41
Version 37.0.1-15733141
Installed as D:\workspace\claudecode-test\moblie-auto\tools\adb\adb.exe
Running on Windows 10.0.26200
# exit 0（实测）
```

```text
PS> adb devices
List of devices attached
749622c9        device

PS> adb devices -l
749622c9               device product:mayfly model:2206123SC device:mayfly transport_id:19
```

**风险提示（必须写进平台方案）**：本机当前真的连着一台小米 2206123SC（`mayfly`）。两个项目的 `device` 标记用例会直接操作它（安装/点击/录屏/性能采集）；任何自动执行必须显式 `serial`，并且盘点/CI 阶段不要跑 `-m device`。

### 4.2 无设备 / 坏 serial 的报错路径

空 server 实验（独立端口 5999，不影响 5037 上正在用的真机）：

```text
PS> adb -P 5999 start-server
* daemon not running; starting now at tcp:5999
* daemon started successfully
PS> adb -P 5999 devices
List of devices attached          # 无设备，exit 0

PS> adb -s NOPE shell echo hi
adb.exe: device 'NOPE' not found
# exit 1
```

库层（venv 解释器实测）：

| 调用 | 场景 | 结果 |
| --- | --- | --- |
| `adbutils.AdbClient.device_list()` | server 在、无设备 | `[]` |
| `AdbClient.device()` | 同上 | `adbutils.errors.AdbError: Can't find any android device/emulator` |
| `AdbClient.device('NOPE')` | 同上 | **不校验**，直接返回 `AdbDevice(serial='NOPE')`；错误延迟到真正发命令 |
| `adbutils`（端口 5999 未起 server） | 无 server | `adbutils.errors.AdbConnectionError: connect to adb server failed: [WinError 10061] 由于目标计算机积极拒绝，无法连接。`（栈顶 `adbutils/_adb.py:69 _create_socket`） |
| `uiautomator2.connect('NOPE')` | 设备不存在 | `uiautomator2.exceptions.ConnectError: device NOPE not online` |

平台含义：runner 起跑前必须自己判定「设备在不在」——`adb devices` 返回空列表**不是错误**（exit 0），`adbutils.device(serial)` 也**不会**校验；只有真正发命令才炸。建议用 `adb devices -l` 解析 + 把设备 `state` 判为 `device` 才算在线，与 `core/backend.py:63-97 parse_adb_devices/list_adb_devices` 的做法一致。

### 4.3 adb server 是宿主全局的（不可按项目隔离）

两个项目最终都连 `127.0.0.1:5037` 的同一个 adb server（auto 走随包 `adb.exe`，perf 走随包 `SoloPi/platform-tools/adb.exe`，adbutils 也连默认端口）。`HOME` 重定向后 adb 仍能连上既有 server（实测：重定向 home 下没有生成 `.android` 目录，命令照常工作）。→ 平台不要试图「各自起一个 server」，端口冲突/设备状态共享会互相污染；用不同 adb 二进制没问题，server 仍应只有一个（或显式 `-P` 指定）。

---

## 5. 平台测试与 Agent 运行的目录 / 环境变量清单

### 5.1 变量清单（建议直接固化进 `scripts/pytest_platform.ps1` / `scripts/run_vendor_tests.ps1`）

| 变量名 | 用途 | 建议值（相对平台仓库根） | 影响模块 |
| --- | --- | --- | --- |
| `PYTHONUTF8` | 避免 GBK 解码（实测修好 auto 4 个用例） | `1` | pytest / 所有 Python 子进程 |
| `PYTHONIOENCODING` | 子进程输出编码 | `utf-8` | pytest / 日志采集 |
| `USERPROFILE` | `Path.home()` 的来源（Windows） | `<repo>/data/tmp/home` | auto `lease.py:27`、perf `gate.py:27` |
| `HOME` | 同上（跨平台兜底） | 同 `USERPROFILE` | 同上 |
| `TEMP` / `TMP` | 临时目录 | `<repo>/data/tmp` | pytest / adb / u2 / scrcpy 临时文件 |
| `PYTEST_DEBUG_TEMPROOT` | pytest temproot（**不能解决 0o700 问题**，仅用于收敛位置） | `<repo>/data/tmp` | pytest |
| `MOBILE_DEVICE_SERIAL` | auto 目标设备 | 显式 serial（如 `749622c9`） | auto 配置 `config.py:29` |
| `MOBILE_APP_PACKAGE` / `MOBILE_APP_ACTIVITY` | auto 目标应用 | 任务内真值 | auto `config.py:30-31` |
| `MOBILE_PERF_SERIAL` | perf 目标设备 | 显式 serial | perf `cli.py:145` |
| `MOBILE_PERF_ADB` / `ADB` | perf adb 覆盖 | vendor 内 adb 绝对路径 | perf `adb.py:41-51` |
| `PYTHONPATH` | vendor 包导入（不 pip install 时） | `<repo>/vendor/mobile-auto/src;<repo>/vendor/mobile-perf/src` | vendor 两个包 |
| `--basetemp` | pytest 临时根 | `<repo>/data/tmp/pytest` | pytest（仅收敛位置，不修权限） |
| `-p no:cacheprovider` | 不写 `.pytest_cache`、不建 `pytest-cache-files-*`（实测：加后 cwd 无残留目录） | 必加 | pytest |
| 平台插件（`-p testplat_sandbox`） | **仅沙箱内需要**：把 basetemp 子树内目录创建 mode 改成 0o777 | 由 `TESTPLAT_SANDBOX=1` 开关 | pytest（vendor 回归 & 平台单测） |

### 5.2 目录清单（建议布局，尚未在平台仓库落地）

| 目录 | 内容 | 由谁写 |
| --- | --- | --- |
| `data/tmp/` | TEMP/TMP、pytest basetemp | pytest、adb、u2 |
| `data/tmp/home/` | 重定向 HOME（`.mobile-auto/leases` 落这里） | auto/perf 租约 |
| `data/runs/<run_id>/` | 平台 run 工作目录（vendor 产物归档在这里） | runner |
| `data/runs/<run_id>/artifacts/` | auto 证据（`evidence/<id>/`、`run-manifest.jsonl`、`runs/*.json`） | auto |
| `data/runs/<run_id>/perf/runs/<runId>/` | perf run 目录（CSV 等） | perf collector |
| `data/db/` | `mobile_perf.db`（perf SQLite）、平台自身 DB | perf store / 平台 |
| `data/tmp/leases/` | 跨进程设备租约锁（**必须全局唯一**） | auto lease / perf gate |

### 5.3 可复制的正确命令（沙箱内兜底版，实测通过）

```powershell
$Probe = 'D:\workspace\claudecode-test\testplat-auto\.probe\env-inv'
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
$env:USERPROFILE = "$Probe\home"; $env:HOME = "$Probe\home"
$env:TEMP = "$Probe\tmp"; $env:TMP = "$Probe\tmp"
$env:PYTHONPATH = "$Probe\auto-full\src;$Probe"   # 后者提供 fixplugin.py
Set-Location "$Probe\auto-full"
D:\python312\python.exe -m pytest tests\unit tests\contract -q `
  -p fixplugin -p no:cacheprovider --basetemp "$Probe\bt-auto"
```

perf 同构（`$env:PYTHONPATH = "$Probe\perf-full\src;$Probe"`，`Set-Location "$Probe\perf-full"`）。实测结果：auto 509 passed / 2 failed / 1 skipped；perf 417 passed / 9 failed（剩项见 §2.4）。

**平台正式版建议**：不要复制 fixplugin 到仓库根（它是全局 `os.mkdir` 替换），而是写 `tests/_support/pytest_sandbox_tmp.py`：`pytest_configure` 里包装 `_pytest.tmpdir` 用到的 `os.mkdir`，仅当路径位于 `config.option.basetemp` 之下才改成 0o777，由 `TESTPLAT_SANDBOX=1` 开启；沙箱外默认不启用。

### 5.4 运行位置决策表

| 场景 | 建议位置 | 理由 |
| --- | --- | --- |
| vendor 回归（两包 `tests/unit` + `tests/contract`） | **宿主 shell 或 CI**（脚本 `scripts/run_vendor_tests.ps1` 注入 §5.1 变量） | 不依赖沙箱兼容层，结果最可信；沙箱内即使通过也多了插件变量 |
| 平台单测（无 DB、无真机） | 沙箱内可跑，前提是 `-p no:cacheprovider` + 插件兜底；否则放宿主 | 见 §1.3 实测 |
| 平台集成（真 PG / 真机） | **宿主/CI 专用 runner** | 需要端口监听、DB 子进程、真机 |
| 盘点/静态检查 | 沙箱内 | 无副作用 |

### 5.5 对 `development-plan.md` 的修正建议（供 Lead 采纳）

| 位置 | 现状 | 建议改为 |
| --- | --- | --- |
| `development-plan.md:77`（F17）与 §12.1 第 1 条（`:574`） | 「DSH 沙箱内 pytest 无法运行（`%TEMP%` `WinError 5`，`--basetemp` 亦失败）」 | 「根因是 pytest 用 `mode=0o700` 建 tmp 目录，沙箱内该目录不可访问且 chmod 修不回；env 重定向与 `--basetemp` 都无效。宿主/CI 直接跑；沙箱内需 `TESTPLAT_SANDBOX=1` 插件把 mode 改 0o777（实测 auto 509/512 通过）＋ `-p no:cacheprovider`」 |
| `:219` `run_vendor_tests.sh` / `:575` `scripts/pytest_platform.sh` | bash 脚本 | 本会话 bash 通道不可用（`ops_bash` 报 `EXECUTOR_UNAVAILABLE`；Git `bash.exe` 在 DSH 沙箱内启动失败 `couldn't create signal pipe, Win32 error 5`），建议同时提供 `.ps1`，或明确只在宿主 bash 用 |
| 环境注入 | `TMP/TEMP/HOME/USERPROFILE → data/tmp` | 再加 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`-p no:cacheprovider`、租约目录统一 `data/tmp/leases`（否则 auto/perf 各按 home 算，仍能互斥，但不受仓库控制） |

---

## 附录 A：本报告用到的探测资产（均在 `.probe/`，非交付物）

| 路径 | 作用 |
| --- | --- |
| `.probe/env-inv/run_matrix.ps1` | (a)(b)(c) 矩阵复现，输出 `logs/*.txt` |
| `.probe/env-inv/fixplugin.py` | 0o777 目录兜底插件（13 行） |
| `.probe/env-inv/rc.py` / `rc2.py` / `rc3.py` / `rc4.py` | mkdir 0o700 探针、chmod 探针、租约目录检查、digest 计算 |
| `.probe/env-inv/auto-full/`、`perf-full/` | 全量副本（复测用） |
| `.probe/env-inv/logs/` | 原始日志 + junit XML |
| `.probe/env-inv/tmpfail2.txt`、`mini-out.txt` | 失败原文（sessionfinish traceback） |

## 附录 B：未确认项汇总

1. 宿主 shell（无沙箱）下是否完全无需 fixplugin —— 未确认（本会话无法在宿主执行）。
2. `tests/unit/test_pytest_plugin.py` 的 11 个失败（auto 2 + perf 9）在「入口点正常注册」的安装环境下是否通过 —— 未确认（本机 venv 元数据损坏）。
3. 平台插件限定 basetemp 子树是否足够 —— 未确认（机理上足够，未实现验证）。
4. `pytest 9.1.1` 是本机版本；pytest 8.x 的 tmpdir 同样使用 0o700（按本机源码，**未确认**旧版本是否一致）。

---

_本报告只做事实盘点与接口签名级描述，不含实现代码；两个既有项目全程只读。_
