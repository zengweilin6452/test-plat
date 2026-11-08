"""Runner 集成契约回归：全部使用临时产物和替身，不访问 ADB 或真机。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/runner_pkg"))
from testdock_runner import ui_job
from testdock_runner.env import RunnerContext, ensure_vendor_on_path

ensure_vendor_on_path(ROOT / "vendor")


def test_pytest_command_uses_registered_options(tmp_path, monkeypatch):
    target = tmp_path / "test_smoke.py"
    target.write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    # 子进程禁用插件自动加载 -> 父进程构命令时必须看到同一开关，才会带上显式 -p
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    command = ui_job.build_pytest_command(serial="not-a-real-device", artifacts_dir=tmp_path,
                                        test_paths=[str(target)], revision_id="revision-1")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "server/runner_pkg"), str(ROOT / "vendor/mobile_auto/src")]),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(command, env=env, cwd=tmp_path, capture_output=True, text=True,
                            encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "junit.xml").is_file()


def test_open_session_uses_mobile_config_and_requested_package(tmp_path, monkeypatch):
    from mobile_auto.core import session as vendor
    captured = {}

    class Session:
        def __init__(self, config):
            captured["config"] = config
        def start(self):
            captured["started"] = True

    monkeypatch.setattr(vendor, "DeviceSession", Session)
    options = ui_job.UiJobOptions(run_id="test", artifacts_dir=tmp_path)
    options.app_package = "com.example.requested"
    ui_job._open_session("requested-serial", tmp_path, options)
    assert captured["config"].device_serial == "requested-serial"
    assert captured["config"].app_package == "com.example.requested"
    assert captured["config"].artifacts_dir == tmp_path
    assert captured["started"]


def test_debug_viewer_has_valid_registry_and_can_stop_without_device(tmp_path):
    from testdock_runner.debug_job import _start_viewer
    import urllib.request
    options = ui_job.UiJobOptions(run_id="debug", artifacts_dir=tmp_path, serial="offline-test-device")
    viewer = _start_viewer(options)
    try:
        with urllib.request.urlopen(viewer.url + "/", timeout=5) as response:
            assert response.status == 200
    finally:
        viewer.stop()


def test_perf_job_collects_and_archives_vendor_report(tmp_path, monkeypatch):
    from testdock_runner import debug_job
    from testdock_runner.debug_job import run_perf_job
    import mobile_perf
    calls = []
    report = {"runId": "perf-test", "items": ["CPU"], "metricsSummary": {
        "cpu_process_pct": {"sampleCount": 2, "median": 12.5}}}

    class Kit:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))
        def ensure_ready(self):
            # 工单 02：运行准备不再调用 vendor 自愈入口
            raise AssertionError("ensure_ready must not be called")
        def collect(self, **kwargs):
            calls.append(("collect", kwargs))
            return Scope()

    class Scope:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.report = report

    class FastClock:
        """工单 06：采集窗有 10 秒下限，用它把窗口在毫秒内走完（不真睡 10 秒）。"""

        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += max(seconds, 1.0)

    monkeypatch.setattr(mobile_perf, "PerfKit", Kit)
    monkeypatch.setattr(ui_job, "_acquire_local_locks", lambda *a, **k: (None, SimpleNamespace(release=lambda: calls.append(("release",)))))
    monkeypatch.setattr(debug_job, "time", FastClock())
    options = ui_job.UiJobOptions(run_id="perf-test", artifacts_dir=tmp_path, serial="test-only")
    options.app_package = "com.example.perf"
    options.perf = {"duration_s": 60, "items": ["CPU"]}
    context = RunnerContext(run_id="perf-test", fencing_token=1, artifacts_dir=tmp_path)
    result = run_perf_job(options, context)
    assert result.exit_code == 0, result.message
    assert [call[0] for call in calls] == ["init", "collect", "release"]
    assert calls[0][1]["foreground_restore"] is False
    assert calls[1][1]["target"] == "com.example.perf"
    assert calls[1][1]["host_run_id"] == "perf-test"
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["metricsSummary"] == report["metricsSummary"]
    assert result.outcome == "not_tested"  # 没有门禁策略不伪装性能通过


def test_silent_pytest_is_stopped_at_timeout(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(ui_job, "build_pytest_command", lambda **kw: [sys.executable, "-c", "import time; time.sleep(60)"])
    monkeypatch.setattr(ui_job, "_plugin_problems", lambda: "")
    options = ui_job.UiJobOptions(run_id="timeout", artifacts_dir=tmp_path, timeout=0.2)
    context = RunnerContext(run_id="timeout", fencing_token=1, artifacts_dir=tmp_path)
    started = time.monotonic()
    result = ui_job._run_pytest(options, context, tmp_path, "offline")
    assert result.timed_out and result.exit_code == 3
    assert time.monotonic() - started < 8


def test_control_auth_loss_loses_fence(tmp_path):
    """API 重启轮换 control.token 后，旧 runner 的控制通道一律 401——
    这是确定性拒绝不是抖动：必须视为丢 fence，让 debug 主循环尽快退出
    并释放本地设备锁（否则孤儿 runner 占锁，设备调试全部 DeviceBusy）。"""
    from testdock_runner.protocol import ControlError

    assert ControlError(401, "control_unauthorized", "").auth_lost is True
    assert ControlError(403, "control_forbidden", "").auth_lost is True
    assert ControlError(500, "boom", "").auth_lost is False
    assert ControlError(409, "fence_mismatch", '{"code":"fence_mismatch"}').fence_mismatch is True

    class AuthLostControl:
        def check_fence(self, token):
            raise ControlError(401, "control_unauthorized", "")

    context = RunnerContext(
        run_id="orphan", fencing_token=1, artifacts_dir=tmp_path, control=AuthLostControl()
    )
    assert context.check_fence() is False
    assert context.fence_lost_now() is True


def test_control_transient_error_keeps_fence(tmp_path):
    """网络抖动（URLError/超时）不是丢租约：仍按持有处理，由心跳/对账兜底。"""
    import urllib.error

    class FlakyControl:
        def check_fence(self, token):
            raise urllib.error.URLError("temporarily unreachable")

    context = RunnerContext(
        run_id="flaky", fencing_token=1, artifacts_dir=tmp_path, control=FlakyControl()
    )
    assert context.check_fence() is True
    assert context.fence_lost_now() is False


def test_spawn_works_without_asyncio_subprocess_support(tmp_path, monkeypatch):
    import asyncio
    from app.runner import spawn
    async def unavailable(*a, **kw):
        raise NotImplementedError("Selector loop")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", unavailable)
    monkeypatch.setattr(spawn, "build_spec", lambda **kw: spawn.SpawnSpec(
        argv=[sys.executable, "-c", "print('local-process-ok')"], env=dict(os.environ),
        cwd=str(tmp_path), log_path=tmp_path / "child.log", stdout_path=tmp_path / "child.log"))
    async def run():
        await spawn.spawn_runner(run_id="local-child", config={}, lease={}, start_tail=False)
        process = spawn.get_process("local-child")
        assert process is not None
        try:
            assert await process.wait() == 0
        finally:
            spawn._PROCESSES.pop("local-child", None)
    asyncio.run(run())
    assert "local-process-ok" in (tmp_path / "child.log").read_text()


def test_result_does_not_promote_skipped_or_infrastructure_failure():
    from testdock_runner.__main__ import _result_outcome
    assert _result_outcome(ui_job.UiJobResult(3, "error", junit={"tests": 1})) == "not_tested"
    assert _result_outcome(ui_job.UiJobResult(0, "skipped", junit={"tests": 1, "skipped": 1})) == "not_tested"
    assert _result_outcome(ui_job.UiJobResult(0, "ok", junit={"tests": 1})) == "passed"


def test_default_vendor_path_is_repository_snapshot(tmp_path):
    from testdock_runner.env import vendor_paths
    assert vendor_paths()[0] == ROOT / "vendor/mobile_auto/src"
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, mobile_auto, mobile_perf\n"
        "print(json.dumps([mobile_auto.__file__, mobile_perf.__file__]))\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        str(ROOT / p) for p in ("vendor/mobile_auto/src", "vendor/mobile_perf/src")),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    result = subprocess.run([sys.executable, str(probe)], env=env, cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    for path in json.loads(result.stdout):
        assert Path(path).is_relative_to(ROOT / "vendor")


def test_spawn_preserves_all_test_paths_and_perf_configuration(tmp_path, monkeypatch):
    from app.runner import spawn
    from app.config import settings
    from testdock_runner.__main__ import build_parser, _job_options
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    spec = spawn.build_spec(run_id="test", config={"module": "perf", "app_package": "com.example.app",
        "test_paths": ["test_a.py", "test_b.py"], "perf": {"duration_s": 20, "items": ["CPU"]}},
        lease={"serial": "not-real", "fencing_token": 1})
    options = _job_options(build_parser().parse_args(spec.argv[3:]))
    assert options.test_paths == ["test_a.py", "test_b.py"]
    assert options.app_package == "com.example.app"
    assert options.perf == {"duration_s": 20, "items": ["CPU"]}


def test_pytest_command_skips_explicit_plugin_when_entrypoint_autoloads(monkeypatch):
    """入口点已自动加载 vendor 插件时，显式 -p 会撞名（Plugin already registered）。"""
    import importlib.metadata

    from testdock_runner import ui_job as ui_job_mod

    ep = SimpleNamespace(name="mobile-auto-evidence", value="mobile_auto.evidence.pytest_plugin")
    monkeypatch.setattr(
        importlib.metadata, "entry_points", lambda group: [ep], raising=True
    )
    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    argv = ui_job_mod.build_pytest_command(
        serial="s", artifacts_dir=Path("."), test_paths=["tests"]
    )
    assert "mobile_auto.evidence.pytest_plugin" not in argv

    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    argv = ui_job_mod.build_pytest_command(
        serial="s", artifacts_dir=Path("."), test_paths=["tests"]
    )
    assert "mobile_auto.evidence.pytest_plugin" in argv


def test_pytest_command_defers_to_suite_owned_mobile_session(tmp_path):
    """客户套件自带 mobile_session / --mobile-config 时，平台插件必须让位。

    Beta Academy 的 conftest 自己注册 --mobile-config 并定义 mobile_session；
    平台插件先注册同名选项会让 pytest 在 conftest 加载时直接 ArgumentError。
    """
    from testdock_runner import ui_job as ui_job_mod

    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(
        "import pytest\n"
        "def pytest_addoption(parser):\n"
        "    parser.addoption('--mobile-config', default=None)\n"
        "@pytest.fixture(scope='session')\n"
        "def mobile_session():\n"
        "    return None\n",
        encoding="utf-8",
    )
    argv = ui_job_mod.build_pytest_command(
        serial="s",
        artifacts_dir=tmp_path,
        test_paths=["."],
        mobile_config=tmp_path / "mobile.toml",
        suite_root=suite,
    )
    assert "testdock_runner.pytest_plugin" not in argv
    assert "--mobile-config" in argv and str(tmp_path / "mobile.toml") in argv

    plain = tmp_path / "plain"
    plain.mkdir()
    plain_argv = ui_job_mod.build_pytest_command(
        serial="s", artifacts_dir=tmp_path, test_paths=["."], suite_root=plain
    )
    assert "testdock_runner.pytest_plugin" in plain_argv
