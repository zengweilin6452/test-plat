"""runner 子进程：spawn / 行读取 / 转发 / 终止（development-plan.md §10.1）。

三条设计约束
------------
1. **环境必须被洗干净**：runner 里跑 pytest，会 import 宿主的 site-packages；
   但 vendor 的依赖必须来自 vendor/*/src，TMP/HOME 必须落在仓库内（否则 6 个月
   后有人发现 C: 满了）。所以 spawn 时显式覆盖 TMP/TEMP/HOME/USERPROFILE/
   PYTHONPATH/PYTHONIOENCODING —— 注意是**覆盖**不是追加，PYTHONPATH 追加会让
   宿主上已安装的 mobile_auto（开发机 editable 安装）抢在 vendor 前面被 import，
   那是最难查的一类"本地能跑 CI 不能跑"。

2. **stdout 是结构化事件流**：每行一个 JSON。API 侧逐行读、写 run_events、
   并推给 WS。非 JSON 行不丢弃，包成 {"t":"text"} 事件 —— runner 里任何 print(
   调试语句）都要能在日志里看到。

3. **杀进程要杀进程树**：runner 会再起 pytest / adb 子进程，Windows 上只 kill
   父进程会留下孤儿占着设备。所以用 taskkill /T /F。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings
from ..domain import control as control_mod

logger = logging.getLogger(__name__)

class RunnerProcess:
    """Popen 的异步等待适配，同时支持 Windows Selector 与 Proactor。"""

    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        self.pid = process.pid

    @property
    def returncode(self):
        return self.process.poll()

    async def wait(self):
        return await asyncio.to_thread(self.process.wait)

    def kill(self):
        self.process.kill()


#: 运行中进程表：run_id -> 进程句柄。API 进程内唯一真源，用于 cancel/kill。
_PROCESSES: dict[str, RunnerProcess] = {}
#: 每个 run 的读日志任务（取消时取消它）
_TAIL_TASKS: dict[str, asyncio.Task[Any]] = {}

#: 等进程退出的默认超时（正常跑完由 runner 自己上报，这里只是兜底）
EXIT_TIMEOUT_SECONDS = 3600
#: joint 总超时在 UI 上限之外保留的缓冲（准备/停采/归档各有界，D11）
JOINT_TOTAL_TIMEOUT_MARGIN_S = 900
#: 取消后的宽限期（§10.1：10s 不退出就 taskkill /T /F）
CANCEL_GRACE_SECONDS = 10


@dataclass
class SpawnSpec:
    """一次 spawn 的完整参数（便于测试构造与日志落盘）。"""

    argv: list[str]
    env: dict[str, str]
    cwd: str
    log_path: Path
    stdout_path: Path


def fake_runner_enabled() -> bool:
    """TESTDOCK_FAKE_RUNNER=1 时用假 runner（无真机也能全流程跑通）。"""
    return os.environ.get("TESTDOCK_FAKE_RUNNER", "").strip() in ("1", "true", "yes", "on")


def _runtime_tmp() -> Path:
    if fake_runner_enabled():
        return Path(settings.tmp_dir)
    return Path(settings.tmp_dir)


def build_env(*, run_id: str, project_root: Path | None = None) -> dict[str, str]:
    """构造 runner 的干净环境。

    基线从 os.environ 拷贝（PATH/SystemRoot 之类必须保留，否则 python 起不来），
    再显式覆盖关键项。故意**不**继承宿主 PYTHONPATH。
    """
    root = Path(project_root or settings.repo_root)
    tmp = _runtime_tmp()
    tmp.mkdir(parents=True, exist_ok=True)
    vendor = root / "vendor"
    # runner_pkg 是本仓库的 src 布局包（server/runner_pkg/testdock_runner），
    # 必须排在最前：`python -m testdock_runner` 靠它解析；vendor 两个 src 随后。
    runner_src = Path(__file__).resolve().parents[2] / "runner_pkg"
    python_path = os.pathsep.join(
        [
            str(runner_src),
            str(vendor / "mobile_auto" / "src"),
            str(vendor / "mobile_perf" / "src"),
        ]
    )
    # PYTEST_ADDOPTS / PYTEST_PLUGINS 会把宿主或套件的插件/参数带进 runner 的
    # pytest 子进程；运行准备必须只读，不能借此隐式打开 mobile-perf 自愈。
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS")
    }
    env.update(
        {
            "TMP": str(tmp),
            "TEMP": str(tmp),
            "TMPDIR": str(tmp),
            "HOME": str(tmp),
            "USERPROFILE": str(tmp),
            "PYTHONPATH": python_path,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "TESTDOCK_RUN_ID": run_id,
        }
    )
    return env


def artifacts_dir_for(run_id: str) -> Path:
    return Path(settings.artifacts_dir) / str(run_id)


def log_path_for(run_id: str) -> Path:
    return Path(settings.runner_logs_dir) / ("%s.log" % run_id)


def build_spec(
    *,
    run_id: str,
    config: Mapping[str, Any],
    lease: Mapping[str, Any],
    control_url: str | None = None,
    control_token: str | None = None,
) -> SpawnSpec:
    """把 run 配置翻译成 `python -m testdock_runner ui|perf|debug ...`。"""
    mode = str(config.get("module") or config.get("kind") or "ui")
    if mode not in ("ui", "perf", "debug", "joint"):
        mode = "ui"
    serial = lease.get("serial") or config.get("serial")
    artifacts_dir = artifacts_dir_for(run_id)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_path_for(run_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    argv: list[str] = [
        str(settings.runner_python),
        "-m",
        "testdock_runner",
        mode,
        "--run-id", str(run_id),
        "--artifacts-dir", str(artifacts_dir),
        "--control-url", control_url or ("http://%s:%d" % (settings.host, settings.port)),
        "--fencing-token", str(lease.get("fencing_token") or 0),
    ]
    if serial:
        argv += ["--serial", str(serial)]
    if config.get("revision_id"):
        argv += ["--revision", str(config["revision_id"])]
    if config.get("task_id"):
        argv += ["--task-id", str(config["task_id"])]
    timeout = config.get("timeout_s") or settings.run_timeout_s
    ui_timeout = 0
    if mode == "joint":
        # D11：UI 上限独立字段（10–3600），总超时必须给 UI 窗留出准备/归档缓冲，
        # 不能让总 deadline 把合法的 3600 秒执行窗截断（AC-CONTRACT-06）。
        from ..domain.joint_policy import clamp_ui_timeout

        ui_timeout = clamp_ui_timeout(config.get("ui_timeout_s"))
        argv += ["--ui-timeout", str(ui_timeout)]
        timeout = max(int(timeout or 0), ui_timeout + JOINT_TOTAL_TIMEOUT_MARGIN_S)
    argv += ["--timeout", str(int(timeout))]
    if config.get("test_paths"):
        paths = config["test_paths"]
        if isinstance(paths, str):
            paths = [paths]
        for path in paths:
            argv += ["--test-path", str(path)]
    if config.get("app_package") or config.get("package_name"):
        argv += ["--app-package", str(config.get("app_package") or config["package_name"])]
    if config.get("app_activity"):
        argv += ["--app-activity", str(config["app_activity"])]
    if config.get("perf"):
        argv += ["--perf-config", json.dumps(config["perf"], ensure_ascii=False)]
    # 固定代码副本：runner 以它为 pytest 的 cwd，并只在副本边界内解析目标。
    # 套件版本 id 与树摘要随行，供事件/报告追溯「本次实际执行的套件版本」。
    if config.get("suite_root"):
        argv += ["--suite-root", str(config["suite_root"])]
    if config.get("suite_version_id"):
        argv += ["--suite-version", str(config["suite_version_id"])]
    if config.get("suite_sha256"):
        argv += ["--suite-sha256", str(config["suite_sha256"])]
    if fake_runner_enabled():
        argv.append("--fake")

    env = build_env(run_id=run_id)
    # control token 走环境变量而非命令行：argv 在同机任何进程的枚举下都可见
    # （Windows Get-CimInstance Win32_Process / Linux /proc/*/cmdline）。
    env[control_mod.ENV_CONTROL_TOKEN] = control_token or ""
    if fake_runner_enabled():
        env["TESTDOCK_FAKE_RUNNER"] = "1"
        fake_outcome = str(config.get("fake_outcome") or "passed")
        env["TESTDOCK_FAKE_OUTCOME"] = "failed" if fake_outcome == "failed" else "passed"

    return SpawnSpec(
        argv=argv,
        env=env,
        cwd=str(settings.repo_root / "server"),
        log_path=log_path,
        stdout_path=log_path,
    )


async def spawn_runner(
    *,
    run_id: str,
    config: Mapping[str, Any],
    lease: Mapping[str, Any],
    control_url: str | None = None,
    control_token: str | None = None,
    start_tail: bool = True,
) -> int:
    """拉起 runner 子进程，返回 pid。

    标准输出/错误都写进 data/runner-logs/<run_id>.log（§10.1 要求"完整日志"），
    **同时**由 _tail 任务逐行读出来转发事件 —— 用管道而不用文件轮询，
    是因为文件轮询在 Windows 上有缓冲竞态，容易丢最后几行（恰恰是最重要的
    崩溃现场）。
    """
    spec = build_spec(
        run_id=run_id,
        config=config,
        lease=lease,
        control_url=control_url,
        control_token=control_token,
    )
    existing = _PROCESSES.get(run_id)
    if existing is not None and existing.returncode is None:
        raise RuntimeError("run %s 已有存活 runner（pid=%s）" % (run_id, existing.pid))

    # stdout 直接写日志文件（§10.1 要求完整日志，管道被 API 读走就没人写日志了），
    # 事件转发走 _tail_stdout 的增量读文件任务。
    log_file = open(spec.log_path, "ab")
    try:
        process = RunnerProcess(subprocess.Popen(
            spec.argv, cwd=spec.cwd, env=spec.env,
            stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        ))
    finally:
        log_file.close()
    _PROCESSES[run_id] = process
    if start_tail:
        _TAIL_TASKS[run_id] = asyncio.create_task(
            _tail_stdout(run_id, process, spec.log_path), name="runner-tail-%s" % run_id
        )
    return int(process.pid or 0)


async def _tail_stdout(run_id: str, process: RunnerProcess, log_path: Path) -> None:
    """增量读 runner 日志文件：解析 JSON 行 -> run_events -> WS 广播。

    runner 的 stdout 直接落到 log_path（完整日志），这里只做 tail：记录读取偏移，
    每 0.2s 看文件有没有新内容。比管道可靠——进程被 taskkill 时管道里最后几行常常
    读不到，而文件一定已经写上去了。
    """
    from ..db import get_sessionmaker
    from ..domain import events as events_mod
    from ..ws import hub as hub_mod

    sessionmaker = get_sessionmaker()
    offset = 0
    buffer = b""
    sequence = 0
    project_id: str | None = None
    while True:
        running = process.returncode is None
        try:
            with open(log_path, "rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
        except OSError:
            chunk = b""
        if chunk:
            offset += len(chunk)
            buffer += chunk
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r")
                event = _parse_line(line)
                if event is None:
                    continue
                sequence += 1
                if project_id is None:
                    project_id = await _project_of(run_id)
                if not project_id:
                    continue
                try:
                    async with sessionmaker() as session:
                        async with session.begin():
                            written = await events_mod.append_event(
                                session,
                                project_id=project_id,
                                run_id=run_id,
                                source_key="runner",
                                source_event_id=events_mod.event_id_for(
                                    "runner", run_id, sequence
                                ),
                                event_type=str(event.get("t") or "text"),
                                payload=event,
                            )
                    hub_mod.publish_threadsafe(
                        str(run_id),
                        {
                            "type": "event",
                            "kind": str(event.get("t") or "text"),
                            "name": str(event.get("name") or ""),
                            # 幂等命中时 written 为空（重复事件不推第二次）
                            "sequence": written[0]["sequence"] if written else None,
                            "at": None,
                        },
                    )
                except Exception:  # noqa: BLE001 - 转发失败不影响 runner
                    logger.exception("run %s 事件转发失败", run_id)
        if not running and not chunk:
            break
        await asyncio.sleep(0.2)

    # 冲掉最后一行（没有换行结尾的打印）
    if buffer.strip():
        line = buffer.decode("utf-8", errors="replace").strip()
        logger.info("runner %s 尾巴: %s", run_id, line[:500])

    code = await process.wait()
    _PROCESSES.pop(run_id, None)
    _TAIL_TASKS.pop(run_id, None)
    logger.info("runner %s 退出 code=%s", run_id, code)
    try:
        await _finalize_after_exit(run_id, code)
    except Exception:  # noqa: BLE001
        logger.exception("run %s 退出后收敛失败", run_id)


async def _project_of(run_id: str) -> str | None:
    from ..db import get_sessionmaker

    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            row = (
                await session.execute(text_project_sql(), {"id": run_id})
            ).scalar_one_or_none()
            return str(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def text_project_sql():
    from sqlalchemy import text

    return text("SELECT project_id FROM test_runs WHERE id = :id")


def event_num(event: Mapping[str, Any]) -> Any:
    return event.get("seq") or event.get("n") or json.dumps(event, sort_keys=True, ensure_ascii=False)[:200]


def _parse_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    if not stripped.startswith("{"):
        return {"t": "text", "name": stripped[:500]}
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return {"t": "text", "name": stripped[:500]}
    if not isinstance(parsed, dict):
        return {"t": "text", "name": stripped[:500]}
    return parsed


async def _finalize_after_exit(run_id: str, code: int | None) -> None:
    """runner 退出但没上报终态（崩溃/被 kill）时由 API 兜底收敛。

    这是"进程退出"这条路径上的安全网：正常路径里 runner 会先调
/internal/runs/{id}/complete 或 /fail，这里看到 run 已经终态就直接跳过。
    """
    from .. import runtime as runtime_mod
    from ..db import get_sessionmaker
    from ..domain import runs as runs_mod
    from ..integrations.mobile_auto import map_exit_code

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(text_project_state_sql(), {"id": run_id})
        ).mappings().first()
    if row is None:
        from ..routers.debug import _close_session
        await _close_session(run_id, reason="runner_exit")
        return
    if row["state"] in runs_mod.TERMINAL_STATES:
        return
    mapped = map_exit_code(code)
    state, outcome, reason = mapped.state, mapped.outcome, mapped.reason_code
    if state != runs_mod.STATE_COMPLETED and row["cancel_requested_at"] is not None:
        # 用户已受理取消、进程是被我们 taskkill 掉的：这是取消收敛，不是设备/
        # 基础设施掉线。映射成 errored 会把"用户取消"写成"运行出错"。
        state, outcome, reason = runs_mod.STATE_CANCELLED, None, "cancel_requested"
    await runtime_mod.finalize_run(
        run_id=run_id,
        state=state,
        outcome=outcome,
        reason=reason,
        project_id=str(row["project_id"]),
        artifacts_dir=None if state == runs_mod.STATE_ERRORED else artifacts_dir_for(run_id),
        release_lease_reason=(
            "cancel_requested" if state == runs_mod.STATE_CANCELLED else "runner_exit"
        ),
        extra_event={"exit_code": code},
    )


def text_project_state_sql():
    from sqlalchemy import text

    return text(
        "SELECT project_id, state, cancel_requested_at FROM test_runs WHERE id = :id"
    )


async def _pid_from_events(run_id: str) -> int | None:
    """runner 在 ack 事件里上报 pid；进程表丢了也能据此 taskkill。"""
    from sqlalchemy import text

    from ..db import get_sessionmaker

    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT payload FROM run_events WHERE run_id = :id "
                        "ORDER BY sequence DESC LIMIT 50"
                    ),
                    {"id": run_id},
                )
            ).scalars().all()
    except Exception:  # noqa: BLE001
        return None
    for payload in rows:
        if not isinstance(payload, Mapping):
            continue
        pid = payload.get("pid")
        if isinstance(pid, int) and pid > 0:
            return pid
    return None


def get_process(run_id: str) -> RunnerProcess | None:
    process = _PROCESSES.get(run_id)
    if process is not None and process.returncode is None:
        return process
    return None


def running_run_ids() -> list[str]:
    return [rid for rid, p in _PROCESSES.items() if p.returncode is None]


async def terminate_run_process(run_id: str, *, force: bool = True) -> bool:
    """kill runner 进程树。返回是否**确实**杀掉了一个活进程。

    Windows 上必须 taskkill /T /F：runner 会再起 pytest / adb，只 TERMINATE 父
    进程会留下孤儿继续占设备（development-plan.md §10.1）。

    返回值进的是 cancel 事件的 `runner_terminated` 与取消响应：不能无条件写
    True。taskkill 返回非 0（进程已消失 / 无权限）且随后也没观测到退出时，
    如实返回 False —— 否则"已终止"是个谎，排查会被带偏。
    """
    process = get_process(run_id)
    pid = process.pid if process is not None else None
    if pid is None:
        # 进程表里没有（API 重启过 / tail 任务已收尾）：从 run_events 的 ack 里找 pid
        pid = await _pid_from_events(run_id)
    if pid is None:
        return False
    killed = False
    if os.name == "nt":
        try:
            completed = await asyncio.to_thread(
                subprocess.run, ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            )
            killed = getattr(completed, "returncode", 1) == 0
        except Exception:  # noqa: BLE001
            logger.exception("taskkill %s 失败", pid)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            killed = True
        except Exception:  # noqa: BLE001
            try:
                process.kill()
                killed = True
            except Exception:  # noqa: BLE001
                killed = False
    if process is not None:
        # 进程退出是比 taskkill 退出码更硬的证据（例如 taskkill 与进程退出的
        # 竞态：taskkill 报 "not found" 时进程恰好已经死了）。
        try:
            await asyncio.wait_for(process.wait(), 10)
            killed = True
        except TimeoutError:
            logger.warning("runner %s 未在 10s 内退出", pid)
    _PROCESSES.pop(run_id, None)
    return killed


async def wait_for_exit(run_id: str, timeout: float = EXIT_TIMEOUT_SECONDS) -> int | None:
    process = _PROCESSES.get(run_id)
    if process is None:
        return None
    try:
        return await asyncio.wait_for(process.wait(), timeout)
    except TimeoutError:
        await terminate_run_process(run_id)
        return None


def tail_log(run_id: str, *, lines: int = 200) -> list[str]:
    path = log_path_for(run_id)
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return raw[-lines:]


__all__ = [
    "CANCEL_GRACE_SECONDS",
    "EXIT_TIMEOUT_SECONDS",
    "SpawnSpec",
    "artifacts_dir_for",
    "build_env",
    "build_spec",
    "fake_runner_enabled",
    "get_process",
    "log_path_for",
    "running_run_ids",
    "spawn_runner",
    "tail_log",
    "terminate_run_process",
    "wait_for_exit",
]
