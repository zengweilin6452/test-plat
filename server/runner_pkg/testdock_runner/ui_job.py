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
import signal
import subprocess
import sys
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


def resolve_test_paths(options: UiJobOptions) -> list[str]:
    """pytest 目标：显式 --test-path > 指定 test_paths > tests。"""
    if options.test_paths:
        return list(options.test_paths)
    if fake_enabled(options.fake):
        vendor_tests = _vendor_unit_tests(options.vendor_dir)
        if vendor_tests is not None:
            return [str(vendor_tests)]
    return list(DEFAULT_TEST_PATHS)


def _vendor_unit_tests(vendor_dir: Path | None) -> Path | None:
    guess = Path(vendor_dir) if vendor_dir else Path(__file__).resolve().parents[3] / "vendor"
    candidate = guess / "mobile_auto" / "tests"
    return candidate if candidate.is_dir() else None


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
        "-p",
        "mobile_auto.evidence.pytest_plugin",
        "--mobile-evidence",
        "--mobile-devices",
        serial or "fake-serial",
        "--mobile-artifacts-dir",
        str(artifacts_dir),
        "--junit-xml",
        str(junit),
        "-p",
        "no:cacheprovider",
        "-q",
    ]
    if revision_id:
        argv.extend(["--mobile-revision", str(revision_id)])
    argv.extend(test_paths or list(DEFAULT_TEST_PATHS))
    return argv


def _lock_dir() -> Path:
    override = os.environ.get("TESTDOCK_DEVICE_LOCK_DIR")
    if override:
        return Path(override)
    root = Path(__file__).resolve().parents[3]
    return root / ".runtime" / "device-locks"


def _acquire_local_locks(serial: str, *, run_id: str) -> tuple[Any, LocalDeviceLock]:
    """先 vendor DeviceLease（有 vendor 时），再本地跨进程锁。"""
    vendor_lease: Any = None
    real_serial = bool(serial) and serial != "fake-serial" and not serial.startswith("fake")
    if real_serial:
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
    lock = LocalDeviceLock(serial=serial or "fake-serial", lock_dir=_lock_dir())
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

    # 1) 本地锁（在碰设备之前）
    context.set_stage("lease", 10, stage=1)
    emit_stage("lease", 10)
    try:
        vendor_lease, lock = _acquire_local_locks(options.serial, run_id=options.run_id)
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

        # 3) vendor 设备会话（真机路径）
        try:
            session = _open_session(serial, artifacts_dir, options)
        except Exception as exc:  # noqa: BLE001
            emit_text("device_unavailable", detail=str(exc))
            return UiJobResult(exit_code=3, reason="device_unavailable", message=str(exc))
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

    session = DeviceSession(
        serial=serial,
        artifacts_dir=str(artifacts_dir),
        device_serial=serial,
        app_package="com.example.xinghe",
        app_activity="",
        assets_dir="",
        launch_ready_target="",
        allowed_deeplink_schemes=(),
        dialog_guard=(),
    )
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
    argv = build_pytest_command(
        serial=serial,
        artifacts_dir=artifacts_dir,
        test_paths=resolve_test_paths(options),
        revision_id=options.revision_id,
    )
    emit_stage("pytest", 40, argv=argv)
    problems = _plugin_problems()
    if problems:
        emit_text("plugin_unavailable", detail=problems)
        return UiJobResult(exit_code=3, reason="plugin_unavailable", message=problems)
    context.set_stage("pytest", 40, stage=2)
    deadline = Deadline(options.timeout)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    cancelled = False
    timed_out = False
    try:
        assert process.stdout is not None
        for line in process.stdout:
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
            _quiet(process.kill)

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
    elif junit.present:
        result.exit_code = 2 if junit.failed else 0
        result.reason = "case_failure" if junit.failed else "passed"
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
    "DEFAULT_TEST_PATHS",
    "EVIDENCE_DIR",
    "RUN_MANIFEST",
    "UiJobOptions",
    "UiJobResult",
    "build_pytest_command",
    "resolve_test_paths",
    "run_ui_job",
]
