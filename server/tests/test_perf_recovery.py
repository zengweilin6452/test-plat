"""性能采集启动前的残留录制兜底（RUN-0014/0015 回归）。

上一次 runner 异常退出时，SoloPi 的设备端录制可能仍在 recording；下一次
``perf-start`` 会直接报 ``A performance recording is already active``。
这里守住 runner 侧的恢复语义：先查状态，有残留就停，停不掉则明确失败。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/runner_pkg"))

from testdock_runner import perf_recovery  # noqa: E402


def _fake_solo(monkeypatch, handler):
    calls: list[list[str]] = []

    def run_harness(args, **kwargs):
        calls.append(list(args))
        return handler(args, kwargs)

    module = types.ModuleType("mobile_perf")
    module.solo = SimpleNamespace(run_harness=run_harness)
    monkeypatch.setitem(sys.modules, "mobile_perf", module)
    return calls


def _args(**overrides):
    return {
        "serial": "SERIAL",
        "adb_path": Path("adb.exe"),
        "repo_root": Path("mobile_perf"),
        **overrides,
    }


def test_inactive_recording_is_noop(monkeypatch):
    calls = _fake_solo(
        monkeypatch,
        lambda args, kwargs: SimpleNamespace(
            success=True, data={"active": False, "state": "idle"}
        ),
    )

    assert perf_recovery.clear_stale_perf_recording(**_args()) is None
    assert calls == [["perf-status"]]


def test_active_recording_is_stopped_before_new_collect(monkeypatch):
    calls = _fake_solo(
        monkeypatch,
        lambda args, kwargs: (
            SimpleNamespace(
                success=True,
                data={
                    "active": True,
                    "state": "recording",
                    "sessionId": "sess-1",
                    "targetPackage": "com.example.app",
                },
            )
            if args[0] == "perf-status"
            else SimpleNamespace(
                success=True,
                data={"active": False, "state": "stopped", "sessionId": "sess-1"},
            )
        ),
    )

    recovered = perf_recovery.clear_stale_perf_recording(**_args())

    assert recovered is not None
    assert recovered.session_id == "sess-1"
    assert recovered.stopped is True
    assert calls[0] == ["perf-status"]
    assert calls[1][:3] == ["perf-stop", "--session-id", "sess-1"]
    assert "--output" not in calls[1]


def test_active_recording_without_session_id_fails_closed(monkeypatch):
    _fake_solo(
        monkeypatch,
        lambda args, kwargs: SimpleNamespace(
            success=True, data={"active": True, "state": "recording"}
        ),
    )

    with pytest.raises(RuntimeError, match="sessionId"):
        perf_recovery.clear_stale_perf_recording(**_args())


def test_stop_failure_fails_closed(monkeypatch):
    _fake_solo(
        monkeypatch,
        lambda args, kwargs: (
            SimpleNamespace(
                success=True,
                data={"active": True, "state": "recording", "sessionId": "sess-1"},
            )
            if args[0] == "perf-status"
            else SimpleNamespace(success=False, data={"error": "stop failed"})
        ),
    )

    with pytest.raises(RuntimeError, match="perf-stop 失败"):
        perf_recovery.clear_stale_perf_recording(**_args())


def test_status_probe_failure_is_reported_but_does_not_block_start(monkeypatch):
    calls: list[list[str]] = []

    def broken(args, **kwargs):
        calls.append(list(args))
        raise RuntimeError("status transport down")

    module = types.ModuleType("mobile_perf")
    module.solo = SimpleNamespace(run_harness=broken)
    monkeypatch.setitem(sys.modules, "mobile_perf", module)

    assert perf_recovery.clear_stale_perf_recording(**_args()) is None
    assert calls == [["perf-status"]]


def test_run_perf_job_recovers_before_opening_collect(tmp_path, monkeypatch):
    """runner 接线：先清理残留录制，再进入 PerfKit.collect。"""
    from testdock_runner import debug_job, ui_job
    from testdock_runner.env import RunnerContext

    events: list[str] = []
    report = {"runId": "recover-before-collect", "items": ["CPU"], "metricsSummary": {}}

    class Scope:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.report = report

    class FakeKit:
        adb_path = tmp_path / "adb.exe"

        def __init__(self, **kwargs):
            events.append("init")

        def collect(self, **kwargs):
            events.append("collect")
            return Scope()

    class FastClock:
        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += max(seconds, 1.0)

    fake_perf = types.ModuleType("mobile_perf")
    fake_perf.PerfKit = FakeKit
    monkeypatch.setitem(sys.modules, "mobile_perf", fake_perf)
    monkeypatch.setattr(
        debug_job,
        "clear_stale_perf_recording",
        lambda **kwargs: events.append("recover"),
    )
    monkeypatch.setattr(debug_job, "time", FastClock())
    monkeypatch.setattr(
        ui_job,
        "_acquire_local_locks",
        lambda *args, **kwargs: (None, SimpleNamespace(release=lambda: None)),
    )

    options = ui_job.UiJobOptions(
        run_id="recover-before-collect",
        artifacts_dir=tmp_path,
        serial="SERIAL",
    )
    options.app_package = "com.example.app"
    options.perf = {"duration_s": 10, "items": ["CPU"]}
    context = RunnerContext(
        run_id="recover-before-collect", fencing_token=1, artifacts_dir=tmp_path
    )

    result = debug_job.run_perf_job(options, context)

    assert result.exit_code == 0, result.message
    assert events == ["init", "recover", "collect"]


def test_joint_start_collect_recovers_before_perf_start(tmp_path, monkeypatch):
    """联动采集启动前同样先清理残留录制。"""
    from testdock_runner import joint_job
    from testdock_runner.ui_job import UiJobOptions

    events: list[str] = []

    class FakeKit:
        adb_path = tmp_path / "adb.exe"

        def __init__(self, **kwargs):
            events.append("init")

        def collect(self, spec=None, **kwargs):
            events.append("collect")
            return FakeScope()

    class FakeScope:
        def __enter__(self):
            return self

        def finalize(self):
            return {}

    class FakeSpec:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    package = types.ModuleType("mobile_perf")
    kit_module = types.ModuleType("mobile_perf.kit")
    kit_module.PerfKit = FakeKit
    session_module = types.ModuleType("mobile_perf.session")
    session_module.SessionSpec = FakeSpec
    package.kit = kit_module
    package.session = session_module
    monkeypatch.setitem(sys.modules, "mobile_perf", package)
    monkeypatch.setitem(sys.modules, "mobile_perf.kit", kit_module)
    monkeypatch.setitem(sys.modules, "mobile_perf.session", session_module)
    monkeypatch.setattr(joint_job, "ensure_vendor_on_path", lambda vendor: None)
    monkeypatch.setattr(
        joint_job,
        "clear_stale_perf_recording",
        lambda **kwargs: events.append("recover"),
    )

    options = UiJobOptions(
        run_id="joint-recover",
        artifacts_dir=tmp_path,
        serial="SERIAL",
        app_package="com.example.app",
    )
    joint_job._start_perf_collect(options)

    assert events == ["init", "recover", "collect"]
