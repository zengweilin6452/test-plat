"""工单 06：声明式性能场景（duration_s 10–3600 整数、items 非空）同口径校验。

同一份规则必须同时落在两处入口，任一入口放宽都会让「10 秒起步」变成口头约定：

1. 任务修订就绪（``app.domain.task.check_readiness``）：validate 前拒绝越界或
   与套件版本场景不一致的配置，不把非法场景留到派发后才炸；
2. runner 采集入口（``testdock_runner.debug_job.run_perf_job``）：执行前再拦一次，
   拒绝 ``invalid_perf_config``，不夹紧、不猜默认值。

另守住：套件版本场景（``manifest.scenario`` / ``manifest.performance``）与修订
``config.perf`` 是两份声明，读写优先级由 ``suite.resolve_scenario`` 一处决定，
不一致时显式拒绝而不是静默覆盖。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/runner_pkg"))

from app.domain import suite as suite_domain  # noqa: E402
from app.domain import task as task_domain  # noqa: E402

SCENARIO = {"duration_s": 60, "items": ["CPU", "Memory", "FPS"]}
CODE_COPY = {
    "schema_version": 1,
    "copy_id": "copy-issue06",
    "root_rel": "copy-issue06",
    "tree_sha256": "a" * 64,
}


def _typed_manifest(
    test_type: str = "performance", scenario: dict | None = None
) -> dict:
    """套件发布口产出的类型化清单（performance 不伪造 cases）。"""
    joint = test_type == "joint"
    return suite_domain.build_typed_manifest(
        test_type,
        node_ids=["tests/test_a.py::test_one"] if joint else [],
        scenario=dict(SCENARIO if scenario is None else scenario),
        ui_timeout_s=600 if joint else None,
        extra={"code_copy": dict(CODE_COPY)} if joint else None,
    )


def _readiness(
    test_type: str = "performance",
    *,
    perf: dict | None | object = ...,
    manifest: dict | None = None,
) -> task_domain.ReadinessReport:
    """按 validate 路由的真实入参形状调用 readiness。"""
    manifest = manifest if manifest is not None else _typed_manifest(test_type)
    config: dict = {}
    if perf is ...:
        config["perf"] = dict(SCENARIO)
    elif perf is not None:
        config["perf"] = dict(perf)  # type: ignore[arg-type]
    revision = {
        "suite_version_id": "sv-issue06",
        "test_type": test_type,
        "build_id": "build-issue06",
        "config": config,
    }
    return task_domain.check_readiness(
        revision=revision,
        platform="android",
        application_platform="android",
        suite_version={"manifest": manifest},
        case_total=suite_domain.case_total(manifest),
        suite_test_type=test_type,
    )


def _problems(report: task_domain.ReadinessReport) -> str:
    return " | ".join(list(report.missing) + list(report.invalid))


# --------------------------------------------------------------------------- #
# 修订就绪：声明式场景的边界
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("duration", [10, 60, 3600])
def test_readiness_accepts_declared_scenario_inside_window(duration):
    scenario = {"duration_s": duration, "items": ["CPU"]}
    report = _readiness(perf=scenario, manifest=_typed_manifest(scenario=scenario))
    assert report.ok, _problems(report)


@pytest.mark.parametrize("duration", [0, 5, 9, 3601, 7200])
def test_readiness_rejects_duration_outside_10_to_3600(duration):
    scenario = {"duration_s": duration, "items": ["CPU"]}
    # 清单本身合法，只有修订配置越界：越界必须由 config.perf 这一侧被指出。
    report = _readiness(perf=scenario, manifest=_typed_manifest())
    assert not report.ok
    assert any("config.perf" in item and "duration_s" in item for item in report.invalid), (
        _problems(report)
    )


@pytest.mark.parametrize(
    "scenario",
    [
        {"duration_s": 60.5, "items": ["CPU"]},
        {"duration_s": "60", "items": ["CPU"]},
        {"duration_s": True, "items": ["CPU"]},
        {"duration_s": 60, "items": []},
        {"duration_s": 60, "items": ["CPU", "  "]},
        {"duration_s": 60},
        {},
    ],
)
def test_readiness_rejects_malformed_scenario(scenario):
    report = _readiness(perf=scenario, manifest=_typed_manifest())
    assert not report.ok
    assert any("config.perf" in item for item in report.invalid), _problems(report)


def test_readiness_rejects_revision_scenario_conflicting_with_suite_version():
    """套件版本声明与修订配置不一致：拒绝，不静默用其中一份。"""
    revision_scenario = {"duration_s": 120, "items": ["CPU"]}
    report = _readiness(
        perf=revision_scenario,
        manifest=_typed_manifest(scenario={"duration_s": 60, "items": ["CPU"]}),
    )
    assert not report.ok
    assert any("不一致" in item for item in report.invalid), _problems(report)


def test_joint_readiness_uses_same_scenario_window():
    report = _readiness(
        "joint", perf={"duration_s": 5, "items": ["CPU"]}, manifest=_typed_manifest("joint")
    )
    assert not report.ok
    assert any("config.perf" in item for item in report.invalid), _problems(report)


def test_ui_readiness_does_not_require_perf_scenario():
    manifest = suite_domain.build_typed_manifest(
        "ui",
        node_ids=["tests/test_a.py::test_one"],
        extra={"code_copy": dict(CODE_COPY)},
    )
    report = _readiness("ui", perf=None, manifest=manifest)
    assert report.ok, _problems(report)


# --------------------------------------------------------------------------- #
# resolve_scenario：两份声明的合并优先级（唯一真源）
# --------------------------------------------------------------------------- #
def test_resolve_scenario_prefers_matching_suite_manifest():
    perf, source = suite_domain.resolve_scenario(
        test_type="performance", manifest=_typed_manifest(), revision_perf=dict(SCENARIO)
    )
    assert perf == SCENARIO
    assert source == "suite_manifest"


def test_resolve_scenario_uses_revision_when_manifest_declares_none():
    manifest = {"schema_version": 1, "case_count": 0, "cases": []}
    perf, source = suite_domain.resolve_scenario(
        test_type="performance", manifest=manifest, revision_perf=dict(SCENARIO)
    )
    assert perf == SCENARIO
    assert source == "revision"


def test_resolve_scenario_uses_joint_performance_block():
    perf, source = suite_domain.resolve_scenario(
        test_type="joint", manifest=_typed_manifest("joint"), revision_perf=None
    )
    assert perf == SCENARIO
    assert source == "suite_manifest"


def test_resolve_scenario_rejects_conflict():
    with pytest.raises(suite_domain.PerfScenarioConflict) as excinfo:
        suite_domain.resolve_scenario(
            test_type="performance",
            manifest=_typed_manifest(scenario={"duration_s": 60, "items": ["CPU"]}),
            revision_perf={"duration_s": 60, "items": ["Memory"]},
        )
    assert "items" in str(excinfo.value)


def test_resolve_scenario_returns_none_when_nothing_declared():
    perf, source = suite_domain.resolve_scenario(
        test_type="performance", manifest={}, revision_perf=None
    )
    assert perf is None
    assert source is None


# --------------------------------------------------------------------------- #
# runner 采集入口：同一份 10–3600 / items 规则，拒绝而不是夹紧
# --------------------------------------------------------------------------- #
class _FakeClock:
    """让 10 秒以上的采集窗在毫秒内走完：时间只在 runner 自己的循环里加速。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += max(seconds, 1.0)


def _patch_perf_kit(monkeypatch, tmp_path: Path) -> list[tuple[str, dict]]:
    """替身 PerfKit + 本地锁，全程不访问 ADB 或真机。"""
    import mobile_perf
    from testdock_runner import debug_job, ui_job

    calls: list[tuple[str, dict]] = []
    report = {"runId": "perf-issue06", "items": ["CPU"], "metricsSummary": {}}

    class Scope:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.report = report

    class Kit:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def collect(self, **kwargs):
            calls.append(("collect", kwargs))
            return Scope()

    monkeypatch.setattr(mobile_perf, "PerfKit", Kit)
    monkeypatch.setattr(
        ui_job,
        "_acquire_local_locks",
        lambda *a, **k: (None, SimpleNamespace(release=lambda: calls.append(("release", {})))),
    )
    monkeypatch.setattr(debug_job, "time", _FakeClock())
    return calls


def _perf_options(tmp_path: Path, perf: dict):
    from testdock_runner import ui_job

    options = ui_job.UiJobOptions(run_id="perf-issue06", artifacts_dir=tmp_path, serial="test-only")
    options.app_package = "com.example.perf"
    options.perf = perf
    return options


@pytest.mark.parametrize(
    "perf",
    [
        {"duration_s": 9, "items": ["CPU"]},
        {"duration_s": 3601, "items": ["CPU"]},
        {"duration_s": 60.5, "items": ["CPU"]},
        {"duration_s": "60", "items": ["CPU"]},
        {"duration_s": True, "items": ["CPU"]},
        {"duration_s": 60, "items": []},
        {"duration_s": 60, "items": ["CPU", 1]},
        {"duration_s": 60},
    ],
)
def test_run_perf_job_rejects_scenario_outside_declared_window(tmp_path, monkeypatch, perf):
    from testdock_runner import debug_job
    from testdock_runner.env import RunnerContext

    calls = _patch_perf_kit(monkeypatch, tmp_path)
    context = RunnerContext(run_id="perf-issue06", fencing_token=1, artifacts_dir=tmp_path)
    result = debug_job.run_perf_job(_perf_options(tmp_path, perf), context)

    assert result.exit_code == 3
    assert result.reason == "invalid_perf_config", (result.reason, result.message)
    assert calls == [], "场景非法时不得打开采集"
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("duration", [10, 3600])
def test_run_perf_job_accepts_scenario_at_window_bounds(tmp_path, monkeypatch, duration):
    from testdock_runner import debug_job
    from testdock_runner.env import RunnerContext

    calls = _patch_perf_kit(monkeypatch, tmp_path)
    context = RunnerContext(run_id="perf-issue06", fencing_token=1, artifacts_dir=tmp_path)
    result = debug_job.run_perf_job(
        _perf_options(tmp_path, {"duration_s": duration, "items": ["CPU"]}), context
    )

    assert result.exit_code == 0, (result.reason, result.message)
    assert calls[1][1]["items"] == ["CPU"], "采集项必须原样传给 vendor"
    assert result.outcome == "not_tested"


def test_runner_window_matches_platform_rule():
    """跨进程镜像不漂移：runner 的边界常量与平台 domain 逐项一致。"""
    from testdock_runner import perf_config

    assert perf_config.PERF_DURATION_MIN_S == suite_domain.DURATION_MIN_S
    assert perf_config.PERF_DURATION_MAX_S == suite_domain.DURATION_MAX_S
    for scenario in (
        {"duration_s": 9, "items": ["CPU"]},
        {"duration_s": 3601, "items": ["CPU"]},
        {"duration_s": 10, "items": ["CPU"]},
        {"duration_s": 3600, "items": ["CPU"]},
        {"duration_s": 60, "items": []},
        {"duration_s": 60.5, "items": ["CPU"]},
    ):
        assert bool(perf_config.scenario_problems(scenario)) == bool(
            suite_domain.scenario_problems(scenario)
        ), scenario

