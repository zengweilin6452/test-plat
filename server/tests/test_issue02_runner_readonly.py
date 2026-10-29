"""工单 02：运行准备不触发 vendor 自愈，插件隐式 ensure_ready 被阻断。

证据分三层：
- PerfKit.ensure_ready 在 runner 里不再被调用，且构造时关闭前台还原；
- pytest 命令显式清空 ini addopts 并禁用 mobile-perf 插件，套件无法通过
  pytest.ini / 命令行 addopts 隐式开启采集；
- runner/spawn 的环境不继承 PYTEST_ADDOPTS / PYTEST_PLUGINS 注入。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/runner_pkg"))

from testdock_runner import ui_job  # noqa: E402
from testdock_runner.env import RunnerContext  # noqa: E402


def test_perf_job_never_calls_vendor_ensure_ready(tmp_path, monkeypatch):
    import mobile_perf

    from testdock_runner.debug_job import run_perf_job

    calls: list[tuple[str, dict]] = []
    report = {"runId": "perf-test", "items": ["CPU"], "metricsSummary": {}}

    class Scope:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.report = report

    class Kit:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def ensure_ready(self):
            raise AssertionError("运行准备不得调用 PerfKit.ensure_ready（会 tcpip/connect 自愈）")

        def collect(self, **kwargs):
            calls.append(("collect", kwargs))
            return Scope()

    monkeypatch.setattr(mobile_perf, "PerfKit", Kit)
    monkeypatch.setattr(
        ui_job,
        "_acquire_local_locks",
        lambda *a, **k: (
            None,
            SimpleNamespace(release=lambda: calls.append(("release", {}))),
        ),
    )
    options = ui_job.UiJobOptions(
        run_id="perf-test", artifacts_dir=tmp_path, serial="test-only"
    )
    options.app_package = "com.example.perf"
    options.perf = {"duration_s": 0.01, "items": ["CPU"]}
    context = RunnerContext(run_id="perf-test", fencing_token=1, artifacts_dir=tmp_path)

    result = run_perf_job(options, context)

    assert result.exit_code == 0, result.message
    assert [call[0] for call in calls] == ["init", "collect", "release"]
    assert calls[0][1]["foreground_restore"] is False


def test_pytest_command_blocks_suite_addopts_and_mobile_perf(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "pytest.ini").write_text(
        "[pytest]\naddopts = --mobile-perf\n", encoding="utf-8"
    )
    (suite / "conftest.py").write_text(
        "def pytest_configure(config):\n"
        "    assert not config.getoption('--mobile-perf', default=False)\n",
        encoding="utf-8",
    )
    (suite / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n", encoding="utf-8"
    )

    command = ui_job.build_pytest_command(
        serial="not-a-real-device",
        artifacts_dir=tmp_path,
        test_paths=[str(suite)],
    )
    assert "addopts=" in command
    assert "no:mobile-perf" in command

    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "server/runner_pkg"), str(ROOT / "vendor/mobile_auto/src")]
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        command,
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pytest_env_drops_plugin_injection(monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "--mobile-perf")
    monkeypatch.setenv("PYTEST_PLUGINS", "mobile_perf.pytest_plugin")

    env = ui_job.build_pytest_env()

    assert "PYTEST_ADDOPTS" not in env
    assert "PYTEST_PLUGINS" not in env


def test_spawn_env_drops_plugin_injection(monkeypatch):
    from app.runner import spawn

    monkeypatch.setenv("PYTEST_ADDOPTS", "--mobile-perf")
    monkeypatch.setenv("PYTEST_PLUGINS", "mobile_perf.pytest_plugin")

    env = spawn.build_env(run_id="readonly-env-test")

    assert "PYTEST_ADDOPTS" not in env
    assert "PYTEST_PLUGINS" not in env
