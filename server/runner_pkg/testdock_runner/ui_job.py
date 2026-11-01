"""UI 作业：本地锁 -> vendor DeviceSession -> pytest -> 产物收集（§10.2）。

顺序（不可调换，§7.1 释放顺序的镜像）
------------------------------------
1. **先**抢本地 vendor 锁（DeviceLease + LocalDeviceLock）。失败 = 设备被别的
   runner 占着，直接 fail(3, local_lease_busy)：此时还没碰设备，也没有 DB 结果
   要写，所以安全。
2. 抢到了再跑 pytest。这样即使 API 侧的 DB 租约已经 fence 给了别人，也绝不会
   出现"两个 runner 同时在设备上操作"。
3. 收尾顺序：停设备（close session）-> 释放 vendor 锁 -> 上报 complete/fail。
   API 收到终态才释放 DB 租约，所以 DB 租约的持有时间 >= 设备锁的持有时间，
   任何时刻 DB 认为"没人用"的设备，本地锁也一定已经放掉了。
"""

from __future__ import annotations

import os
import queue
import threading
import signal
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifacts import (
    EVIDENCE_DIR,
    JUNIT_XML,
    RUN_MANIFEST,
    collect_layout,
    read_junit,
    write_report_json,
)
from .env import Deadline, RunnerContext, ensure_vendor_on_path, fake_enabled
from .protocol import emit_stage, emit_text
from .vendor_lock import DeviceBusy, LocalDeviceLock

DEFAULT_TEST_PATHS = ("tests",)
#: 有固定副本时 pytest 的默认目标就是副本根（不是 server/tests）
COPY_ROOT_TARGET = "."

#: 固定副本缺失/不是目录：立即阻断，绝不回退 server/ 或可变来源
SUITE_ROOT_UNAVAILABLE = "execution_copy_unavailable"
#: 显式目标越出副本边界（绝对路径 / 盘符 / `..` 穿越 / 符号链接逃逸）
SUITE_PATH_OUT_OF_BOUNDS = "suite_path_out_of_bounds"


class SuiteCopyError(RuntimeError):
    """固定副本不可信：携带原因码，供 UiJobResult.reason 与事件追溯。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class UiJobOptions:
    run_id: str
    artifacts_dir: Path
    serial: str = ""
    revision_id: str | None = None
    task_id: str | None = None
    timeout: float = 1800.0
    test_paths: list[str] = field(default_factory=list)
    fake: bool = False
    vendor_dir: Path | None = None
    app_package: str = ""
    app_activity: str = ""
    perf: dict[str, Any] = field(default_factory=dict)
    #: 固定代码副本根（派发时由 dispatcher 复验后写进 spawn 配置）
    suite_root: Path | None = None
    suite_version_id: str | None = None
    #: 该版本 code_copy 的树摘要（只用于追溯与对账，复验在派发侧完成）
    suite_sha256: str | None = None


@dataclass
class UiJobResult:
    exit_code: int
    reason: str
    message: str = ""
    junit: dict[str, Any] = field(default_factory=dict)
    cases: list[dict[str, Any]] = field(default_factory=list)
    layout: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    fence_lost: bool = False
    timed_out: bool = False
    outcome: str | None = None
    components: list[dict[str, Any]] = field(default_factory=list)


def resolve_suite_root(options: UiJobOptions) -> Path:
    """解析并校验固定副本根；缺失/不是目录抛 SuiteCopyError。

    真实执行（非 fake）必须先拿到一个可用的副本目录：调用方不得在失败时退回
    `server/` 或来源目录，否则等于悄悄运行了另一份代码。
    """
    if options.suite_root is None or not str(options.suite_root).strip():
        raise SuiteCopyError(
            SUITE_ROOT_UNAVAILABLE, "运行未提供固定代码副本（suite_root）"
        )
    raw = Path(options.suite_root)
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise SuiteCopyError(
            SUITE_ROOT_UNAVAILABLE, f"固定代码副本不可用：{raw}"
        ) from exc
    if not resolved.is_dir():
        raise SuiteCopyError(
            SUITE_ROOT_UNAVAILABLE, f"固定代码副本不是目录：{raw}"
        )
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    """path 是否在 root 之下（Windows 大小写不敏感，纯词法）。"""
    child = os.path.normcase(os.path.abspath(str(path)))
    parent = os.path.normcase(os.path.abspath(str(root)))
    if child == parent:
        return True
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # 不同盘符
        return False


def _suite_targets(root: Path, test_paths: list[str]) -> list[str]:
    """副本内的 pytest 目标：默认副本根；显式目标必须相对且在副本边界内。

    拒绝绝对路径、盘符与 `..` 穿越（resolve 后再做包含性检查，符号链接逃逸同样
    落在这里）。返回相对副本根的 posix 路径，供 argv / junit 与事件追溯。
    """
    wanted = [str(item).strip() for item in (test_paths or []) if str(item or "").strip()]
    if not wanted:
        return [COPY_ROOT_TARGET]
    targets: list[str] = []
    for text in wanted:
        candidate = Path(text)
        if candidate.is_absolute() or os.path.splitdrive(text)[0] or ".." in candidate.parts:
            raise SuiteCopyError(
                SUITE_PATH_OUT_OF_BOUNDS, f"测试目标越出固定代码副本：{text}"
            )
        resolved = (root / candidate).resolve()
        if not _is_within(resolved, root):
            raise SuiteCopyError(
                SUITE_PATH_OUT_OF_BOUNDS, f"测试目标越出固定代码副本：{text}"
            )
        relative = resolved.relative_to(root)
        targets.append(relative.as_posix() if relative.as_posix() else COPY_ROOT_TARGET)
    return targets or [COPY_ROOT_TARGET]


def resolve_test_paths(options: UiJobOptions) -> list[str]:
    """pytest 目标：有固定副本时只在副本内解析；无副本时保留 fake/vendor 兜底。"""
    root = resolve_suite_root(options) if options.suite_root is not None else None
    if root is not None:
        return _suite_targets(root, list(options.test_paths))
    if options.test_paths:
        return list(options.test_paths)
    if fake_enabled(options.fake):
        vendor_tests = _vendor_unit_tests(options.vendor_dir)
        if vendor_tests is not None:
            return [str(vendor_tests)]
    return list(DEFAULT_TEST_PATHS)


def require_suite_copy_targets(options: UiJobOptions) -> tuple[Path, list[str]]:
    """真实执行的前置校验：副本可用 + 目标在副本边界内（UI 与 joint 共用）。

    返回 (副本绝对路径, 相对目标)；任一不满足抛 SuiteCopyError，调用方据此阻断，
    绝不回退 server/ 或可变来源目录。
    """
    root = resolve_suite_root(options)
    return root, _suite_targets(root, list(options.test_paths))


def _vendor_unit_tests(vendor_dir: Path | None) -> Path | None:
    guess = Path(vendor_dir) if vendor_dir else Path(__file__).resolve().parents[3] / "vendor"
    candidate = guess / "mobile_auto" / "tests"
    return candidate if candidate.is_dir() else None


def _evidence_plugin_preloaded() -> bool:
    """vendor 插件是否已通过 pytest11 入口点自动加载（如本机 editable 安装）。

    入口点已加载同一模块时再显式 `-p mobile_auto.evidence.pytest_plugin`，
    pytest 会报 "Plugin already registered under a different name" 直接崩；
    但 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 时入口点不生效，仍需显式 -p。
    """
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "").strip() in ("1", "true", "yes", "on"):
        return False
    try:
        import importlib.metadata

        return any(
            ep.name == "mobile-auto-evidence"
            and ep.value == "mobile_auto.evidence.pytest_plugin"
            for ep in importlib.metadata.entry_points(group="pytest11")
        )
    except Exception:
        return False


def build_pytest_command(
    *,
    serial: str,
    artifacts_dir: Path,
    test_paths: list[str],
    revision_id: str | None = None,
) -> list[str]:
    """§10.2 第 4 步的命令，参数顺序与文档一致。"""
    junit = Path(artifacts_dir) / JUNIT_XML
    argv = [
        sys.executable,
        "-m",
        "pytest",
    ]
    if not _evidence_plugin_preloaded():
        argv += ["-p", "mobile_auto.evidence.pytest_plugin"]
    argv += [
        "--mobile-evidence",
        "--mobile-devices",
        serial or "fake-serial",
        "-p",
        "testdock_runner.pytest_plugin",
        # 平台只读纪律：套件不能通过 pytest.ini / addopts 隐式打开
        # mobile-perf（其 perf.session 会调用 PerfKit.ensure_ready 自愈）。
        "-p",
        "no:mobile-perf",
        "-o",
        "addopts=",
        "--junit-xml",
        str(junit),
        "-p",
        "no:cacheprovider",
        "-q",
    ]
    argv.extend(test_paths or list(DEFAULT_TEST_PATHS))
    return argv


def build_pytest_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """构造 pytest 子进程环境：不继承调用方注入的插件/参数。

    PYTEST_ADDOPTS 会在命令行参数之前生效，套件或宿主可以借此重新打开
    --mobile-perf；PYTEST_PLUGINS 则会隐式加载插件。两者都从环境中移除，
    插件阻断由 build_pytest_command 的 `-p no:mobile-perf` 兜底。
    """
    env = dict(base if base is not None else os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    return env


def _lock_dir() -> Path:
    override = os.environ.get("TESTDOCK_DEVICE_LOCK_DIR")
    if override:
        return Path(override)
    root = Path(__file__).resolve().parents[3]
    return root / ".runtime" / "device-locks"


def _acquire_local_locks(serial: str, *, run_id: str, vendor: bool = True) -> tuple[Any, LocalDeviceLock]:
    """先 vendor DeviceLease（有 vendor 时），再本地跨进程锁。"""
    vendor_lease: Any = None
    real_serial = bool(serial) and serial != "fake-serial" and not serial.startswith("fake")
    if real_serial and vendor:
        ensure_vendor_on_path()
        try:
            from mobile_auto.core.lease import DeviceLease
        except Exception:  # noqa: BLE001 - 没有 vendor 就只靠本地锁
            DeviceLease = None
        if DeviceLease is not None:
            vendor_lease = DeviceLease(serial, worker="run:%s" % run_id, purpose="ui")
            try:
                vendor_lease.acquire()
            except Exception as exc:  # noqa: BLE001
                raise DeviceBusy(serial, None) from exc
    lock = LocalDeviceLock(serial=serial or "fake-serial", lock_dir=_lock_dir(), pid=os.getpid())
    try:
        lock.acquire()
    except DeviceBusy:
        if vendor_lease is not None:
            _quiet(lambda: vendor_lease.release())
        raise
    return vendor_lease, lock


def _quiet(call: Any) -> None:
    try:
        call()
    except Exception:  # noqa: BLE001
        pass


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """超时/取消时的兜底杀：Windows 上 taskkill /T 连带子孙进程（§10.1）。"""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        pass
    _quiet(lambda: process.wait(timeout=5));
    if process.poll() is None:
        _quiet(process.kill)


def run_ui_job(options: UiJobOptions, context: RunnerContext) -> UiJobResult:
    """执行一次 UI 作业。**总是**在返回前释放本地锁。"""
    artifacts_dir = Path(options.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    serial = options.serial or "fake-serial"

    # 0) 真实执行先确认固定副本可用（fake 模式不跑 pytest，保留其兜底路径）。
    #    放在抢设备锁之前：副本不可用是平台侧事实，不该先占设备再失败。
    if not fake_enabled(options.fake):
        try:
            require_suite_copy_targets(options)
        except SuiteCopyError as exc:
            emit_text(exc.code, detail=exc.message)
            return UiJobResult(exit_code=3, reason=exc.code, message=exc.message)

    # 1) 本地锁（在碰设备之前）
    context.set_stage("lease", 10, stage=1)
    emit_stage("lease", 10)
    try:
        vendor_lease, lock = _acquire_local_locks(options.serial, run_id=options.run_id, vendor=False)
    except DeviceBusy as exc:
        emit_text("local_lease_busy", detail=str(exc))
        return UiJobResult(exit_code=3, reason="local_lease_busy", message=str(exc))

    session: Any = None
    try:
        # 2) fence 边界：拿锁之后再确认一次 DB 租约还是我们的
        if not context.check_fence():
            return UiJobResult(exit_code=5, reason="fence_mismatch", fence_lost=True)
        context.set_stage("ready", 20, stage=1)
        emit_stage("ready", 20)

        if fake_enabled(options.fake):
            return _run_fake(options, context, artifacts_dir, serial)

        # 设备会话和 vendor 租约由 pytest 子进程的 mobile_session fixture 持有，
        # 父进程只持本地锁，避免父子进程重复争抢同一 vendor 租约。
        return _run_pytest(options, context, artifacts_dir, serial)
    finally:
        # 释放顺序：停设备 -> 释放 vendor 锁 -> 释放本地锁（DB 租约由 API 释放）
        if session is not None:
            _quiet(session.close)
        if vendor_lease is not None:
            _quiet(vendor_lease.release)
        lock.release()


def _open_session(serial: str, artifacts_dir: Path, options: UiJobOptions) -> Any:
    from mobile_auto.core.session import DeviceSession

    from mobile_auto.config import MobileConfig

    session = DeviceSession(MobileConfig(
        device_serial=serial, artifacts_dir=artifacts_dir,
        app_package=options.app_package or None, app_activity=options.app_activity or None,
    ))
    session.start()
    return session


def _run_fake(
    options: UiJobOptions,
    context: RunnerContext,
    artifacts_dir: Path,
    serial: str,
) -> UiJobResult:
    from .fake import run_fake_job

    context.set_stage("pytest", 40, stage=2)
    emit_stage("pytest", 40, fake=True)
    wanted = os.environ.get("TESTDOCK_FAKE_OUTCOME", "passed").strip().lower()
    outcome = "failed" if wanted == "failed" else "passed"
    summary = run_fake_job(artifacts_dir=artifacts_dir, serial=serial, outcome=outcome)
    context.set_stage("archive", 90, stage=3)
    emit_stage("archive", 90)
    write_report_json(artifacts_dir, {"fake": True, "outcome": outcome, **summary})
    layout = collect_layout(artifacts_dir)
    emit_text("artifacts", files=len(layout["files"]))
    return UiJobResult(
        exit_code=0 if outcome == "passed" else 2,
        reason="fake_%s" % outcome,
        junit=summary["junit"],
        cases=summary["cases"],
        layout=layout,
    )


def _run_pytest(
    options: UiJobOptions,
    context: RunnerContext,
    artifacts_dir: Path,
    serial: str,
) -> UiJobResult:
    # 产物、junit、env 全部用绝对路径：pytest 的 cwd 是固定副本，相对路径会
    # 落进副本里（污染摘要，也让报告找不到产物）。
    artifacts_dir = Path(artifacts_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if options.suite_root is not None:
        try:
            suite_root, targets = require_suite_copy_targets(options)
        except SuiteCopyError as exc:
            emit_text(exc.code, detail=exc.message)
            return UiJobResult(exit_code=3, reason=exc.code, message=exc.message)
    else:  # 直接调用（测试替身/fake 兜底）：真实派发已在 run_ui_job 阻断
        suite_root, targets = None, resolve_test_paths(options)
    argv = build_pytest_command(
        serial=serial,
        artifacts_dir=artifacts_dir,
        test_paths=targets,
        revision_id=options.revision_id,
    )
    # 追溯：本次执行实际用的套件版本、树摘要与相对目标。
    emit_text(
        "suite_copy",
        suite_version_id=options.suite_version_id or "",
        tree_sha256=options.suite_sha256 or "",
        suite_root=str(suite_root) if suite_root else "",
        targets=list(targets),
    )
    emit_stage(
        "pytest", 40, argv=argv, cwd=str(suite_root) if suite_root else ""
    )
    problems = _plugin_problems()
    if problems:
        emit_text("plugin_unavailable", detail=problems)
        return UiJobResult(exit_code=3, reason="plugin_unavailable", message=problems)
    context.set_stage("pytest", 40, stage=2)
    deadline = Deadline(options.timeout)
    env = build_pytest_env()
    import json
    env["TESTDOCK_JOB_CONFIG"] = json.dumps({
        "serial": serial, "artifacts_dir": str(artifacts_dir),
        "app_package": options.app_package, "app_activity": options.app_activity,
        "revision_id": options.revision_id,
        "suite_root": str(suite_root) if suite_root else "",
        "suite_version_id": options.suite_version_id or "",
        "suite_tree_sha256": options.suite_sha256 or "",
    })
    process = subprocess.Popen(
        argv,
        cwd=str(suite_root) if suite_root else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name != "nt",
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def read_output():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_output, name="pytest-output", daemon=True)
    reader.start()
    cancelled = False
    timed_out = False
    try:
        assert process.stdout is not None
        while True:
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line:
                emit_text("pytest: %s" % line.rstrip())
            if context.cancelled():
                cancelled = True
                _terminate_process_tree(process)
                break
            if context.fence_lost_now():
                _terminate_process_tree(process)
                return UiJobResult(exit_code=5, reason="fence_mismatch", fence_lost=True)
            if deadline.expired:
                timed_out = True
                _terminate_process_tree(process)
                break
    finally:
        _quiet(lambda: process.wait(timeout=10));
        if process.poll() is None:
            _terminate_process_tree(process)
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()

    context.set_stage("archive", 90, stage=3)
    emit_stage("archive", 90)
    junit = read_junit(artifacts_dir / JUNIT_XML)
    layout = collect_layout(artifacts_dir)
    result = UiJobResult(
        exit_code=process.returncode if process.returncode is not None else 3,
        reason="completed",
        junit=junit.as_dict(),
        cases=junit.cases,
        layout=layout,
        cancelled=cancelled,
        timed_out=timed_out,
    )
    if cancelled:
        result.exit_code = 4
        result.reason = "cancelled"
    elif timed_out:
        result.exit_code = 3
        result.reason = "timeout"
    elif junit.parse_error:
        result.exit_code = 3
        result.reason = "junit_parse_error"
    elif process.returncode not in (0, 1, 5):
        result.exit_code = 3
        result.reason = "pytest_error"
    elif junit.present:
        result.exit_code = 2 if junit.failed else 0
        result.outcome = junit.outcome() or "not_tested"
        result.reason = "case_failure" if junit.failed else ("passed" if result.outcome == "passed" else "no_tests")
    elif result.exit_code != 0:
        result.reason = "pytest_error"
    return result


def _plugin_problems() -> str:
    """检查 vendor 的 pytest 插件是否可导入（没有 vendor 时必须 3 退出而不是崩）。"""
    import importlib.util

    spec = importlib.util.find_spec("mobile_auto.evidence.pytest_plugin")
    if spec is None:
        return "mobile_auto.evidence.pytest_plugin not importable (PYTHONPATH=vendor/mobile_auto/src?)"
    return ""


__all__ = [
    "COPY_ROOT_TARGET",
    "DEFAULT_TEST_PATHS",
    "EVIDENCE_DIR",
    "RUN_MANIFEST",
    "SUITE_PATH_OUT_OF_BOUNDS",
    "SUITE_ROOT_UNAVAILABLE",
    "SuiteCopyError",
    "UiJobOptions",
    "UiJobResult",
    "build_pytest_command",
    "build_pytest_env",
    "require_suite_copy_targets",
    "resolve_suite_root",
    "resolve_test_paths",
    "run_ui_job",
]
