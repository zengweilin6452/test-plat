"""工单 01：执行侧真正消费固定代码副本（suite_root）。

守住的可运行事实（全部离线，临时目录 + 替身，不碰真机）：

1. `spawn.build_spec` 把副本根与套件版本身份（id / 树摘要）翻成 runner argv；
2. pytest 子进程以固定副本为 cwd：相对导入、本地模块与 pytest.ini 都在副本内解析，
   产物（junit）写进 artifacts 而不是副本；
3. 版本发布后来源被改坏，再次执行仍跑原副本内容；
4. 副本缺失 / 不是目录 → execution_copy_unavailable；目标绝对路径或 `..` 越界 →
   suite_path_out_of_bounds，都不回退 server/ 或来源目录；
5. joint 复用同一条 UiJobOptions 接线，不出现第二套目标解析；
6. 运行开始时发 suite_copy 事件，记录 suite_version_id / tree_sha256 / 目标。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/runner_pkg"))
from testdock_runner import ui_job  # noqa: E402
from testdock_runner.env import RunnerContext, ensure_vendor_on_path  # noqa: E402

ensure_vendor_on_path(ROOT / "vendor")

SUITE_SHA = "b" * 64

#: 放在固定副本里的用例：证明 cwd、相对导入、pytest.ini 都来自副本。
COPY_TEST = '''\
from pathlib import Path

import helper


def test_copy_marker(request):
    import_root = Path(__file__).resolve().parent.parent
    assert Path.cwd().resolve() == import_root
    assert helper.VALUE == "copy-v1"
    inipath = request.config.inipath
    assert inipath is not None and inipath.name == "pytest.ini"
    assert "copy-ini-marker" in inipath.read_text(encoding="utf-8")
'''


def _write_suite(directory: Path, *, value: str = "copy-v1") -> None:
    (directory / "tests").mkdir(parents=True, exist_ok=True)
    (directory / "pytest.ini").write_text(
        "[pytest]\n# copy-ini-marker\naddopts =\n", encoding="utf-8"
    )
    (directory / "tests" / "helper.py").write_text(
        f'VALUE = "{value}"\n', encoding="utf-8"
    )
    (directory / "tests" / "test_marker.py").write_text(COPY_TEST, encoding="utf-8")


@pytest.fixture
def fixed_copy(tmp_path, monkeypatch):
    """来源 -> discover 固定副本；同时把锁目录与子进程 PYTHONPATH 指到测试内。"""
    from app.integrations import discover

    copies = tmp_path / "copies"
    copies.mkdir()
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(copies))
    monkeypatch.setenv("TESTDOCK_DEVICE_LOCK_DIR", str(tmp_path / "device-locks"))
    # 子进程必须能 import runner 插件与 vendor 插件（与 spawn.build_env 同口径）
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(
            [
                str(ROOT / "server/runner_pkg"),
                str(ROOT / "vendor/mobile_auto/src"),
                str(ROOT / "vendor/mobile_perf/src"),
            ]
        ),
    )
    source_dir = tmp_path / "source"
    _write_suite(source_dir)
    source = discover.resolve_source(str(source_dir), trusted_roots=[tmp_path])
    copy_root, code_copy = discover.copy_source(source)
    return SimpleNamespace(
        source=source_dir, copy_root=copy_root, code_copy=code_copy, tmp=tmp_path
    )


def _options(copy_root, artifacts_dir: Path, **overrides) -> ui_job.UiJobOptions:
    options = ui_job.UiJobOptions(
        run_id="run-issue01",
        artifacts_dir=artifacts_dir,
        serial="",
        suite_root=Path(copy_root) if copy_root is not None else None,
        suite_version_id="sv-issue01",
        suite_sha256=SUITE_SHA,
    )
    for key, value in overrides.items():
        setattr(options, key, value)
    return options


def _context(artifacts_dir: Path) -> RunnerContext:
    return RunnerContext(run_id="run-issue01", fencing_token=1, artifacts_dir=artifacts_dir)


# --------------------------------------------------------------------------- #
# argv 透传
# --------------------------------------------------------------------------- #
def test_spawn_argv_carries_suite_copy_identity(tmp_path, monkeypatch):
    from app.config import settings
    from app.runner import spawn
    from testdock_runner.__main__ import _job_options, build_parser

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    suite_root = tmp_path / "copies" / "copy-abc"
    spec = spawn.build_spec(
        run_id="run-issue01",
        config={
            "module": "ui",
            "suite_root": str(suite_root),
            "suite_version_id": "sv-issue01",
            "suite_sha256": SUITE_SHA,
        },
        lease={"serial": "not-a-real-device", "fencing_token": 1},
    )
    argv = spec.argv
    assert "--suite-root" in argv
    assert argv[argv.index("--suite-root") + 1] == str(suite_root)
    assert argv[argv.index("--suite-version") + 1] == "sv-issue01"
    assert argv[argv.index("--suite-sha256") + 1] == SUITE_SHA

    options = _job_options(build_parser().parse_args(argv[3:]))
    assert Path(options.suite_root) == suite_root
    assert options.suite_version_id == "sv-issue01"
    assert options.suite_sha256 == SUITE_SHA


# --------------------------------------------------------------------------- #
# pytest 以副本为工作目录
# --------------------------------------------------------------------------- #
def test_pytest_runs_inside_copy_after_live_source_is_broken(fixed_copy, tmp_path):
    artifacts = tmp_path / "artifacts"
    # 版本发布后来源被改坏：执行必须仍读原副本，而不是可变来源目录
    (fixed_copy.source / "tests" / "helper.py").write_text(
        'VALUE = "live-v2"\n', encoding="utf-8"
    )
    (fixed_copy.source / "tests" / "test_marker.py").write_text(
        "def test_broken():\n    assert False\n", encoding="utf-8"
    )

    result = ui_job.run_ui_job(_options(fixed_copy.copy_root, artifacts), _context(artifacts))

    assert result.exit_code == 0, (result.reason, result.message)
    assert result.outcome == "passed"
    assert any("test_copy_marker" in case["case_key"] for case in result.cases)
    junit = artifacts / "junit.xml"
    assert junit.is_file()
    assert not Path(junit).resolve().is_relative_to(Path(fixed_copy.copy_root).resolve())


def test_explicit_relative_target_stays_inside_copy(fixed_copy, tmp_path):
    (fixed_copy.copy_root / "tests" / "test_second.py").write_text(
        "def test_second_fails():\n    assert False\n", encoding="utf-8"
    )
    artifacts = tmp_path / "artifacts"
    options = _options(
        fixed_copy.copy_root, artifacts, test_paths=["tests/test_marker.py"]
    )
    result = ui_job.run_ui_job(options, _context(artifacts))
    assert result.exit_code == 0, (result.reason, result.message)
    assert result.junit["tests"] == 1
    assert all("test_second" not in case["case_key"] for case in result.cases)


def test_resolve_test_paths_defaults_to_copy_root(fixed_copy, tmp_path):
    artifacts = tmp_path / "artifacts"
    assert ui_job.resolve_test_paths(_options(fixed_copy.copy_root, artifacts)) == ["."]
    relative = ui_job.resolve_test_paths(
        _options(fixed_copy.copy_root, artifacts, test_paths=["tests/test_marker.py"])
    )
    assert relative == ["tests/test_marker.py"]


def test_suite_copy_event_records_version_digest_and_targets(fixed_copy, tmp_path, monkeypatch):
    events: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        ui_job, "emit_text", lambda name, **extra: events.append(("text", name, extra))
    )
    monkeypatch.setattr(
        ui_job,
        "emit_stage",
        lambda name, progress, **extra: events.append(
            ("stage", name, {"progress": progress, **extra})
        ),
    )
    artifacts = tmp_path / "artifacts"
    result = ui_job.run_ui_job(_options(fixed_copy.copy_root, artifacts), _context(artifacts))
    assert result.outcome == "passed"

    suite_events = [item for item in events if item[1] == "suite_copy"]
    assert suite_events, "运行开始必须发 suite_copy 事件"
    _, _, payload = suite_events[0]
    assert payload["suite_version_id"] == "sv-issue01"
    assert payload["tree_sha256"] == SUITE_SHA
    assert payload["targets"] == ["."]

    pytest_stages = [item for item in events if item[1] == "pytest"]
    assert pytest_stages and pytest_stages[0][2]["cwd"] == str(
        Path(fixed_copy.copy_root).resolve()
    )


# --------------------------------------------------------------------------- #
# 阻断：副本缺失 / 目标越界
# --------------------------------------------------------------------------- #
def test_missing_suite_root_blocks_without_running_pytest(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    monkeypatch.setattr(
        ui_job,
        "build_pytest_command",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("不得启动 pytest")),
    )
    options = _options(None, artifacts)
    result = ui_job.run_ui_job(options, _context(artifacts))
    assert result.exit_code == 3
    assert result.reason == "execution_copy_unavailable"
    assert not (artifacts / "junit.xml").exists()


def test_suite_root_that_is_not_a_directory_is_blocked(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    missing = tmp_path / "copies" / "gone"
    options = _options(missing, artifact_dir)
    result = ui_job.run_ui_job(options, _context(artifact_dir))
    assert result.exit_code == 3
    assert result.reason == "execution_copy_unavailable"

    file_root = tmp_path / "copies" / "not-a-dir"
    file_root.parent.mkdir(parents=True, exist_ok=True)
    file_root.write_text("not a directory", encoding="utf-8")
    file_options = _options(file_root, artifact_dir)
    file_result = ui_job.run_ui_job(file_options, _context(artifact_dir))
    assert file_result.exit_code == 3
    assert file_result.reason == "execution_copy_unavailable"


@pytest.mark.parametrize(
    "bad_target",
    ["../outside", "tests/../../outside", str(ROOT / "server"), "C:\\Windows"],
)
def test_out_of_bounds_targets_are_blocked(fixed_copy, tmp_path, bad_target):
    artifacts = tmp_path / "artifacts"
    options = _options(fixed_copy.copy_root, artifacts, test_paths=[bad_target])
    result = ui_job.run_ui_job(options, _context(artifacts))
    assert result.exit_code == 3
    assert result.reason == "suite_path_out_of_bounds"
    assert not (artifacts / "junit.xml").exists()


def test_absolute_target_inside_copy_is_still_rejected(fixed_copy, tmp_path):
    """显式目标必须是相对路径：绝对路径即使落在副本内也拒绝（目标口径唯一）。"""
    artifacts = tmp_path / "artifacts"
    absolute = str((fixed_copy.copy_root / "tests" / "test_marker.py").resolve())
    options = _options(fixed_copy.copy_root, artifacts, test_paths=[absolute])
    result = ui_job.run_ui_job(options, _context(artifacts))
    assert result.exit_code == 3
    assert result.reason == "suite_path_out_of_bounds"


# --------------------------------------------------------------------------- #
# joint 走同一接线
# --------------------------------------------------------------------------- #
def test_joint_reuses_suite_copy_wiring(fixed_copy, tmp_path, monkeypatch):
    from testdock_runner import joint_job

    monkeypatch.setattr(joint_job, "_start_perf_collect", lambda options: None)
    artifacts = tmp_path / "artifacts"
    result = joint_job.run_joint_job(
        _options(fixed_copy.copy_root, artifacts), _context(artifacts)
    )
    assert result.exit_code == 0, (result.reason, result.message)
    assert result.outcome == "passed"
    assert any("test_copy_marker" in case["case_key"] for case in result.cases)
    assert (artifacts / "junit.xml").is_file()


def test_joint_blocks_out_of_bounds_target_before_collecting(fixed_copy, tmp_path, monkeypatch):
    from testdock_runner import joint_job

    started = []
    monkeypatch.setattr(
        joint_job, "_start_perf_collect", lambda options: started.append(options)
    )
    artifacts = tmp_path / "artifacts"
    options = _options(fixed_copy.copy_root, artifacts, test_paths=["../outside"])
    result = joint_job.run_joint_job(options, _context(artifacts))
    assert result.exit_code == 3
    assert result.reason == "suite_path_out_of_bounds"
    assert started == [], "目标不可用时不应先启动性能采集"
