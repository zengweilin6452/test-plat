"""调试 viewer 生命周期与 PerfKit 性能采集。"""
from __future__ import annotations

import socket
import time
from pathlib import Path
from urllib.parse import urlparse

from .artifacts import collect_layout, write_report_json
from .env import Deadline, RunnerContext, ensure_vendor_on_path, fake_enabled
from .perf_config import scenario_problems
from .perf_recovery import clear_stale_perf_recording
from .protocol import emit_stage, emit_text
from . import ui_job
from .ui_job import UiJobOptions, UiJobResult

FAKE_VIEWER_PORT = 58000


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_viewer(options: UiJobOptions):
    ensure_vendor_on_path(options.vendor_dir)
    from mobile_auto.config import MobileConfig
    from mobile_auto.viewer.server import start_debug_viewer

    return start_debug_viewer(MobileConfig(
        device_serial=options.serial or None,
        app_package=options.app_package or None,
        app_activity=options.app_activity or None,
        artifacts_dir=Path(options.artifacts_dir),
        port=min(_free_port(), 65515),
    ))


def run_debug_job(options: UiJobOptions, context: RunnerContext) -> UiJobResult:
    Path(options.artifacts_dir).mkdir(parents=True, exist_ok=True)
    viewer = None
    lock = None
    try:
        _, lock = ui_job._acquire_local_locks(options.serial, run_id=options.run_id, vendor=False)
        if not context.check_fence():
            return UiJobResult(5, "fence_mismatch", fence_lost=True)
        context.set_stage("debug", 10, stage=2)
        port = FAKE_VIEWER_PORT
        if not fake_enabled(options.fake):
            viewer = _start_viewer(options)
            port = urlparse(viewer.url).port
        if context.control is not None:
            reply = context.control.ready(port=port, fencing_token=context.fencing_token)
            if not reply.get("ok"):
                return UiJobResult(3, "viewer_unavailable")
        context.set_stage("debug", 50, stage=2)
        deadline = Deadline(options.timeout)
        while True:
            if context.cancelled():
                return UiJobResult(4, "cancelled", cancelled=True)
            if not context.check_fence():
                return UiJobResult(5, "fence_mismatch", fence_lost=True)
            if deadline.expired:
                return UiJobResult(3, "timeout", timed_out=True)
            time.sleep(0.2)
    except ui_job.DeviceBusy as exc:
        return UiJobResult(3, "local_lease_busy", message=str(exc))
    except Exception as exc:
        emit_text("viewer_unavailable", error=type(exc).__name__, detail=str(exc)[:300])
        return UiJobResult(3, "viewer_unavailable", message=str(exc))
    finally:
        if viewer is not None:
            viewer.stop()
        if lock is not None:
            lock.release()


def run_perf_job(options: UiJobOptions, context: RunnerContext) -> UiJobResult:
    """PerfKit 负责 start/stop/pull/report；宿主轮询取消、租约和超时。"""
    ensure_vendor_on_path(options.vendor_dir)
    from mobile_perf import PerfKit

    artifacts_dir = Path(options.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if fake_enabled(options.fake):
        write_report_json(artifacts_dir, {"fake": True, "items": [], "metricsSummary": {}})
        return UiJobResult(0, "gate_policy_missing", outcome="not_tested",
                           components=[{"kind": "performance", "state": "completed",
                                        "outcome": "not_tested", "reason_code": "gate_policy_missing"}],
                           layout=collect_layout(artifacts_dir))
    try:
        perf = options.perf or {}
        # 与平台 domain（套件发布 / 修订 readiness）同一口径：duration_s 10–3600
        # 整数秒、items 非空字符串列表。越界拒绝（invalid_perf_config），不夹紧、
        # 不回落默认值——否则"平台拒绝、runner 悄悄改写"两边各说各话。
        problems = scenario_problems(perf)
        if problems:
            raise ValueError("；".join(problems))
        duration = int(perf["duration_s"])
        items = list(perf["items"])
        if not options.serial or not options.app_package:
            raise ValueError("性能采集需要 serial 和 app_package")
    except (TypeError, ValueError, KeyError) as exc:
        return UiJobResult(3, "invalid_perf_config", message=str(exc))

    vendor_lease = lock = None
    deadline = Deadline(options.timeout)
    interrupted = None
    try:
        vendor_lease, lock = ui_job._acquire_local_locks(options.serial, run_id=options.run_id)
        if not context.check_fence():
            return UiJobResult(5, "fence_mismatch", fence_lost=True)
        vendor_root = Path(options.vendor_dir) if options.vendor_dir else Path(__file__).resolve().parents[3] / "vendor"
        # 运行准备不调用 PerfKit.ensure_ready：它的 Keeper.run() 在离线/doctor
        # 失败时会执行 adb tcpip / connect 自愈，违反规格 §6.6。只读预检由平台
        # readiness 入口在派发前完成；这里只负责采集窗口本身。
        # foreground_restore=False 阻止采集收口时额外还原前台。
        kit = PerfKit(serial=options.serial, repo_root=vendor_root / "mobile_perf",
                      runs_dir=artifacts_dir / "perf", db_path=artifacts_dir / "perf.sqlite3",
                      keep_runs=1, keep_days=36500, foreground_restore=False)
        # 上一个 runner 被强杀时 SoloPi 录制可能仍在设备端 active；不先清理，
        # perf-start 会直接报 "already active"（RUN-0014/0015 真机回归）。
        # 替身 Kit 不触设备，跳过；真实 PerfKit 必有 adb_path。
        kit_adb = getattr(kit, "adb_path", None)
        if kit_adb is not None:
            clear_stale_perf_recording(
                serial=options.serial,
                adb_path=Path(kit_adb),
                repo_root=vendor_root / "mobile_perf",
            )
        context.set_stage("ready", 20, stage=1)
        context.set_stage("collect", 40, stage=2)
        emit_stage("collect", 40)
        with kit.collect(target=options.app_package, items=items, host_run_id=options.run_id,
                         runs_dir=artifacts_dir / "perf") as scope:
            stop_at = time.monotonic() + duration
            while time.monotonic() < stop_at:
                if context.cancelled():
                    interrupted = UiJobResult(4, "cancelled", cancelled=True)
                    break
                if context.fence_lost_now() or not context.check_fence():
                    interrupted = UiJobResult(5, "fence_mismatch", fence_lost=True)
                    break
                if deadline.expired:
                    interrupted = UiJobResult(3, "timeout", timed_out=True)
                    break
                time.sleep(min(0.2, max(0, stop_at - time.monotonic())))
        report = scope.report
        if not isinstance(report, dict):
            raise RuntimeError("PerfKit 未返回报告")
        write_report_json(artifacts_dir, report)
        if interrupted is not None:
            interrupted.layout = collect_layout(artifacts_dir)
            return interrupted
        if not context.check_fence():
            return UiJobResult(5, "fence_mismatch", fence_lost=True)
        context.set_stage("archive", 90, stage=3)
        return UiJobResult(0, "gate_policy_missing", outcome="not_tested",
                           components=[{"kind": "performance", "state": "completed",
                                        "outcome": "not_tested", "reason_code": "gate_policy_missing"}],
                           layout=collect_layout(artifacts_dir))
    except ui_job.DeviceBusy as exc:
        return UiJobResult(3, "local_lease_busy", message=str(exc))
    except Exception as exc:
        return UiJobResult(3, "perf_collect_failed", message=str(exc), layout=collect_layout(artifacts_dir))
    finally:
        if vendor_lease is not None:
            vendor_lease.release()
        if lock is not None:
            lock.release()


__all__ = ["run_debug_job", "run_perf_job"]
