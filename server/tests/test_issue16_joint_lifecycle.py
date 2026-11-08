"""工单 16/07：joint 生命周期与结果矩阵（fake runner + 真实契约，定向测试）。

覆盖的验收点（D8/D11、AC-JOINT-01/02/03、AC-CONTRACT-06）：

- 两个组件（ui + performance）共享一次运行、一次资源独占（单 spawn、单租约）；
- UI 一返回立即停采：采集窗口记录真实时间戳，不补采；
- 结果矩阵：UI 断言失败 → completed/failed；采集启动失败 → errored 且
  UI=cancelled"前置采集失败未执行"；UI 达 ui_timeout_s → errored 记超时；
- AC-CONTRACT-06：ui_timeout 允许到 3600，spawn 的总超时必须留出缓冲不被截断；
- joint 不降级为 ui：spawn argv 保留 joint。

工单 07 补齐的缺口（本文件对应回归用例）：

- ui_timeout_s 是真实 pytest deadline（不再只是窗口描述）；
- UI 超时也先停采并收口 report.json（窗口覆盖 UI，不补采）；
- 派发合并 suite_versions.manifest.ui_timeout_s（生产不再恒用默认 600）；
- collectWindow 经 GET /report 可见；
- 联动同样走固定副本校验（与 01 同一套 UiJobOptions 接线）。
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app as fastapi_app
from tests._p3_common import TEST_DB, reset_db_engine

from app.domain.joint_policy import clamp_ui_timeout
from app.main import app  # noqa: F401 - TestClient 需要
from app.runner.spawn import JOINT_TOTAL_TIMEOUT_MARGIN_S, build_spec
from tests._p3_common import CLIENT_HEADERS, requires_db
from tests._p3_common import make_run as make_run
from tests._p3_common import p3_project as project
from tests._p3_common import sync_engine as sync_engine

pytestmark = requires_db


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(fastapi_app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


def _joint_options(tmp_path, **overrides):
    from runner_pkg.testdock_runner.ui_job import UiJobOptions

    options = UiJobOptions(
        run_id=str(uuid.uuid4()),
        artifacts_dir=tmp_path / "artifacts",
        fake=True,
        test_paths=[],
        timeout=1800.0,
    )
    for key, value in overrides.items():
        setattr(options, key, value)
    return options


def _runner_context(tmp_path):
    from runner_pkg.testdock_runner.env import RunnerContext

    return RunnerContext(
        run_id="pytest",
        fencing_token=0,
        artifacts_dir=tmp_path / "artifacts",
        control=None,
    )


# --------------------------------------------------------------------------- #
# runner 侧：joint 作业语义
# --------------------------------------------------------------------------- #


def test_joint_job_reports_two_components_with_real_collect_window(tmp_path, monkeypatch):
    from runner_pkg.testdock_runner.joint_job import run_joint_job

    monkeypatch.delenv("TESTDOCK_FAKE_PERF", raising=False)
    monkeypatch.delenv("TESTDOCK_FAKE_UI_TIMEOUT", raising=False)
    options = _joint_options(tmp_path)
    result = run_joint_job(options, _runner_context(tmp_path))

    kinds = {component["kind"] for component in result.components}
    assert kinds == {"ui", "performance"}, "joint 必须产出两个组件"
    assert result.exit_code in (0, 2)

    report = json.loads(
        (options.artifacts_dir / "report.json").read_text(encoding="utf-8")
    )
    window = report["collectWindow"]
    assert window["collect_started_at"] <= window["ui"]["started_at"]
    assert window["ui"]["ended_at"] <= window["collect_stopped_at"], (
        "采集必须在 UI 结束后立即停止，时间戳上不得出现 UI 之后还在采集"
    )


def test_joint_collect_start_failure_yields_errored_matrix(tmp_path, monkeypatch):
    from runner_pkg.testdock_runner.joint_job import run_joint_job

    monkeypatch.setenv("TESTDOCK_FAKE_PERF", "collect_start_failed")
    result = run_joint_job(_joint_options(tmp_path), _runner_context(tmp_path))

    assert result.reason == "perf_collect_start_failed"
    assert result.exit_code != 0
    by_kind = {component["kind"]: component for component in result.components}
    assert by_kind["ui"]["state"] == "cancelled"
    assert by_kind["ui"]["reason_code"] == "collect_start_failed_ui_not_started"
    assert by_kind["performance"]["state"] == "errored"


def test_joint_ui_timeout_yields_timeout_error(tmp_path, monkeypatch):
    from runner_pkg.testdock_runner.joint_job import run_joint_job

    monkeypatch.setenv("TESTDOCK_FAKE_UI_TIMEOUT", "1")
    result = run_joint_job(_joint_options(tmp_path), _runner_context(tmp_path))

    assert result.reason == "ui_timeout"
    by_kind = {component["kind"]: component for component in result.components}
    assert by_kind["ui"]["state"] == "errored"
    assert by_kind["performance"]["state"] == "cancelled"


def test_ui_timeout_clamped_to_spec_range():
    assert clamp_ui_timeout(None) == 600
    assert clamp_ui_timeout(5) == 10
    assert clamp_ui_timeout(9999) == 3600
    assert clamp_ui_timeout("junk") == 600


def test_joint_ui_window_caps_ui_execution_deadline(tmp_path):
    """ui_timeout_s 必须是真实执行上限，而不是只写在窗口描述里（工单 07）。"""
    from runner_pkg.testdock_runner.ui_job import (
        UiJobOptions,
        resolve_execution_deadline,
    )

    joint = UiJobOptions(
        run_id=str(uuid.uuid4()),
        artifacts_dir=tmp_path / "artifacts",
        timeout=1800.0,
        ui_timeout_s=120,
    )
    assert resolve_execution_deadline(joint) == 120.0

    plain_ui = UiJobOptions(
        run_id=str(uuid.uuid4()),
        artifacts_dir=tmp_path / "artifacts",
        timeout=1800.0,
    )
    assert resolve_execution_deadline(plain_ui) == 1800.0, "普通 UI 运行仍用总超时"


def test_joint_ui_timeout_stops_collection_and_records_window(tmp_path, monkeypatch):
    """UI 超时也必须先停采并写 report.json：窗口覆盖 UI，不留断头采集。"""
    from runner_pkg.testdock_runner.joint_job import run_joint_job

    monkeypatch.delenv("TESTDOCK_FAKE_PERF", raising=False)
    monkeypatch.setenv("TESTDOCK_FAKE_UI_TIMEOUT", "1")
    options = _joint_options(tmp_path, ui_timeout_s=45)
    result = run_joint_job(options, _runner_context(tmp_path))

    assert result.reason == "ui_timeout"
    by_kind = {component["kind"]: component for component in result.components}
    assert by_kind["ui"]["state"] == "errored"
    assert by_kind["performance"]["state"] == "cancelled"

    report = json.loads(
        (options.artifacts_dir / "report.json").read_text(encoding="utf-8")
    )
    window = report["collectWindow"]
    assert window["ui"]["timeout_s"] == 45
    assert window["collect_started_at"] <= window["ui"]["started_at"]
    assert window["ui"]["ended_at"] <= window["collect_stopped_at"], (
        "超时收口后不得继续采集，窗口必须停在 UI 结束之后"
    )


def test_joint_real_ui_timeout_finalizes_collect_scope(tmp_path, monkeypatch):
    """真实路径的 UI 超时分支必须先 finalize 采集，再回报 errored。"""
    from runner_pkg.testdock_runner import joint_job
    from runner_pkg.testdock_runner.ui_job import UiJobResult

    scope = type(
        "_Scope",
        (),
        {
            "finalized": False,
            "finalize": lambda self: setattr(self, "finalized", True) or {},
        },
    )()
    monkeypatch.setattr(joint_job, "_start_perf_collect", lambda options: scope)
    monkeypatch.setattr(
        joint_job,
        "run_ui_job",
        lambda options, context: UiJobResult(
            exit_code=3, reason="timeout", timed_out=True
        ),
    )
    copy_root = tmp_path / "copy"
    copy_root.mkdir()
    options = _joint_options(
        tmp_path,
        fake=False,
        suite_root=copy_root,
        app_package="com.example.joint",
        ui_timeout_s=30,
    )

    result = joint_job.run_joint_job(options, _runner_context(tmp_path))

    assert result.reason == "ui_timeout"
    assert scope.finalized is True, "UI 结束时必须停止采集，不能把采集窗口留到进程退出"
    report = json.loads(
        (options.artifacts_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report["collectWindow"]["ui"]["timeout_s"] == 30


def test_joint_collect_stop_failure_keeps_ui_result_but_reports_perf_errored(
    tmp_path, monkeypatch
):
    """停采抛错不得把性能组件写成 completed：UI 结果保留，性能如实报错。"""
    from runner_pkg.testdock_runner import joint_job
    from runner_pkg.testdock_runner.ui_job import UiJobResult

    class BrokenScope:
        def finalize(self):
            raise RuntimeError("vendor stop failed")

    monkeypatch.setattr(joint_job, "_start_perf_collect", lambda options: BrokenScope())
    monkeypatch.setattr(
        joint_job,
        "run_ui_job",
        lambda options, context: UiJobResult(
            exit_code=0,
            reason="completed",
            outcome="passed",
            components=[
                {"kind": "ui", "state": "completed", "outcome": "passed"}
            ],
        ),
    )
    copy_root = tmp_path / "copy"
    copy_root.mkdir()
    options = _joint_options(
        tmp_path,
        fake=False,
        suite_root=copy_root,
        app_package="com.example.joint",
    )

    result = joint_job.run_joint_job(options, _runner_context(tmp_path))

    by_kind = {component["kind"]: component for component in result.components}
    assert result.exit_code == 0, "UI 成功不得因为停采失败被改写"
    assert by_kind["ui"] == {
        "kind": "ui",
        "state": "completed",
        "outcome": "passed",
    }
    assert by_kind["performance"] == {
        "kind": "performance",
        "state": "errored",
        "reason_code": "perf_collect_stop_failed",
    }
    assert "性能采集停止失败" in result.message
    # 采集窗口仍要收口写盘，不能因为 finalize 抛错就丢失窗口
    report = json.loads(
        (options.artifacts_dir / "report.json").read_text(encoding="utf-8")
    )
    assert "collectWindow" in report


def test_joint_collect_stop_failure_with_empty_message_still_errors_perf(
    tmp_path, monkeypatch
):
    """异常消息为空时也不得把停采失败当成成功（str(exc) 空串是假值）。"""
    from runner_pkg.testdock_runner import joint_job
    from runner_pkg.testdock_runner.ui_job import UiJobResult

    class SilentBrokenScope:
        def finalize(self):
            raise TimeoutError()

    monkeypatch.setattr(
        joint_job, "_start_perf_collect", lambda options: SilentBrokenScope()
    )
    monkeypatch.setattr(
        joint_job,
        "run_ui_job",
        lambda options, context: UiJobResult(
            exit_code=0,
            reason="completed",
            outcome="passed",
            components=[{"kind": "ui", "state": "completed", "outcome": "passed"}],
        ),
    )
    copy_root = tmp_path / "copy"
    copy_root.mkdir()
    options = _joint_options(
        tmp_path, fake=False, suite_root=copy_root, app_package="com.example.joint"
    )

    result = joint_job.run_joint_job(options, _runner_context(tmp_path))

    by_kind = {component["kind"]: component for component in result.components}
    assert by_kind["performance"] == {
        "kind": "performance",
        "state": "errored",
        "reason_code": "perf_collect_stop_failed",
    }
    assert "TimeoutError" in result.message


def test_joint_perf_kit_writes_sqlite_under_artifacts(tmp_path, monkeypatch):
    """联动采集的 SQLite 必须落在运行产物目录，不能写只读 vendor 目录。"""
    import sys
    import types

    from runner_pkg.testdock_runner import joint_job

    captured: dict = {}

    class FakeKit:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def collect(self, spec=None, **kwargs):
            captured["spec"] = spec
            captured["collect_kwargs"] = kwargs
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

    options = _joint_options(
        tmp_path,
        fake=False,
        serial="serial-1",
        app_package="com.example.joint",
    )
    joint_job._start_perf_collect(options)

    db_path = options.artifacts_dir / "perf.sqlite3"
    assert captured["db_path"] == str(db_path)
    assert db_path.is_relative_to(options.artifacts_dir)
    assert captured["runs_dir"] == str(options.artifacts_dir / "perf-runs")


def test_joint_collect_start_failure_never_starts_ui(tmp_path, monkeypatch):
    """采集启动失败时 UI 根本不执行，也不得留下采集窗口。"""
    from runner_pkg.testdock_runner import joint_job

    monkeypatch.setenv("TESTDOCK_FAKE_PERF", "collect_start_failed")
    monkeypatch.delenv("TESTDOCK_FAKE_UI_TIMEOUT", raising=False)
    started: list[object] = []

    def _forbidden(*args, **kwargs):
        started.append(args)
        raise AssertionError("采集启动失败时不得执行 UI")

    monkeypatch.setattr(joint_job, "run_ui_job", _forbidden)
    options = _joint_options(tmp_path)
    result = joint_job.run_joint_job(options, _runner_context(tmp_path))

    assert started == []
    assert result.reason == "perf_collect_start_failed"
    assert not (options.artifacts_dir / "report.json").exists(), (
        "没有采集就没有采集窗口，不得补写一份假的"
    )


def test_joint_case_failure_is_completed_failed_not_runner_fault(tmp_path, monkeypatch):
    """断言失败是 completed/failed，两个组件各自保留真实结论。"""
    from runner_pkg.testdock_runner.joint_job import run_joint_job

    monkeypatch.delenv("TESTDOCK_FAKE_PERF", raising=False)
    monkeypatch.delenv("TESTDOCK_FAKE_UI_TIMEOUT", raising=False)
    monkeypatch.setenv("TESTDOCK_FAKE_OUTCOME", "failed")
    options = _joint_options(tmp_path)
    result = run_joint_job(options, _runner_context(tmp_path))

    assert result.exit_code == 2, "用例失败不是 runner 故障"
    by_kind = {component["kind"]: component for component in result.components}
    assert by_kind["ui"]["state"] == "completed"
    assert by_kind["ui"]["outcome"] == "failed"
    assert by_kind["performance"]["state"] == "completed"
    assert (options.artifacts_dir / "report.json").is_file()


def test_joint_without_fixed_copy_blocks_before_collecting(tmp_path, monkeypatch):
    """联动复用 01 的固定副本接线：没有副本时既不占设备也不开采集。"""
    from runner_pkg.testdock_runner import joint_job

    started: list[object] = []
    monkeypatch.setattr(
        joint_job, "_start_perf_collect", lambda options: started.append(options)
    )
    options = _joint_options(tmp_path, fake=False, suite_root=None, app_package="com.example")
    result = joint_job.run_joint_job(options, _runner_context(tmp_path))

    assert result.exit_code == 3
    assert result.reason == "execution_copy_unavailable"
    assert started == [], "副本不可用是平台侧事实，不该先占设备与采集"
    by_kind = {component["kind"]: component for component in result.components}
    assert by_kind["performance"]["state"] == "cancelled"


def test_joint_out_of_bounds_target_blocks_before_collecting(tmp_path, monkeypatch):
    """联动与 UI 共用同一目标解析：越界目标同样在采集前阻断。"""
    from runner_pkg.testdock_runner import joint_job

    started: list[object] = []
    monkeypatch.setattr(
        joint_job, "_start_perf_collect", lambda options: started.append(options)
    )
    copy_root = tmp_path / "copy"
    (copy_root / "tests").mkdir(parents=True)
    options = _joint_options(
        tmp_path,
        fake=False,
        suite_root=copy_root,
        test_paths=["../outside"],
        app_package="com.example",
    )
    result = joint_job.run_joint_job(options, _runner_context(tmp_path))

    assert result.exit_code == 3
    assert result.reason == "suite_path_out_of_bounds"
    assert started == []


# --------------------------------------------------------------------------- #
# spawn 侧：不降级 + 执行窗不被总 deadline 截断
# --------------------------------------------------------------------------- #


def test_spawn_keeps_joint_mode_and_gives_ui_window_headroom(project):
    config = {
        "module": "joint",
        "ui_timeout_s": 3600,
        "revision_id": project["revision_id"],
        "task_id": project["task_id"],
    }
    spec = build_spec(
        run_id=str(uuid.uuid4()),
        config=config,
        lease={"serial": "not-real", "fencing_token": 1},
    )
    assert "joint" in spec.argv, "joint 不得静默降级为 ui"
    ui_timeout = int(spec.argv[spec.argv.index("--ui-timeout") + 1])
    total = int(spec.argv[spec.argv.index("--timeout") + 1])
    assert ui_timeout == 3600
    assert total >= ui_timeout + JOINT_TOTAL_TIMEOUT_MARGIN_S, (
        "总 deadline 必须为 UI 执行窗留出准备/归档缓冲（AC-CONTRACT-06）"
    )


# --------------------------------------------------------------------------- #
# 平台侧：结果矩阵收敛（完整 finalize 路径）
# --------------------------------------------------------------------------- #


def _add_joint_revision(engine, project: dict) -> str:
    revision_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO task_revisions (id, project_id, application_id, task_id,"
                "                           revision, environment_id, build_id, suite_version_id,"
                "                           test_type, readiness, config, created_by)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         CAST(:tid AS uuid), 9, CAST(:eid AS uuid), CAST(:bid AS uuid),"
                "         CAST(:svid AS uuid), 'joint', 'validated',"
                "         CAST(:config AS jsonb), 'pytest')"
            ),
            {
                "id": revision_id,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "tid": project["task_id"],
                "eid": project["environment_id"],
                "bid": project["build_id"],
                "svid": project["suite_version_id"],
                "config": json.dumps({"ui_timeout_s": 600}),
            },
        )
    return revision_id


def _joint_run(engine, project: dict) -> str:
    revision_id = _add_joint_revision(engine, project)
    return _make_run_with_revision(engine, project, revision_id)


def _make_run_with_revision(engine, project: dict, revision_id: str) -> str:
    run_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO test_runs (id, project_id, application_id, platform, revision_id,"
                "                      request_key, state, config_snapshot, created_by,"
                "                      resource_id, profile_id, started_at, ended_at, outcome)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), 'android',"
                "         CAST(:rid AS uuid), :key, 'running', '{}'::jsonb, 'pytest',"
                "         CAST(:res AS uuid), CAST(:prof AS uuid), now(), NULL, NULL)"
            ),
            {
                "id": run_id,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "rid": revision_id,
                "key": "joint-" + uuid.uuid4().hex,
                "res": project["resource_id"],
                "prof": project["profile_id"],
            },
        )
    return run_id


def _complete(
    client,
    run_id: str,
    components: list[dict],
    junit: dict,
    artifacts_dir=None,
) -> dict:
    payload = {
        "outcome": None,
        "components": components,
        "junit": junit,
    }
    if artifacts_dir is not None:
        payload["artifacts_dir"] = str(artifacts_dir)
    response = client.post(
        f"/internal/runs/{run_id}/complete",
        json=payload,
        headers={"X-Control-Token": client.app.state.control_token},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _components_of(engine, run_id: str) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT kind, state, outcome, reason_code FROM run_components"
                " WHERE run_id = CAST(:rid AS uuid) ORDER BY kind"
            ),
            {"rid": run_id},
        ).mappings().all()
    return {row["kind"]: dict(row) for row in rows}


def test_matrix_ui_assertion_failure_is_completed_failed(client, project, sync_engine):
    """UI 断言失败 = completed/failed；性能组件保留（gate 缺策略记 not_tested），不吞掉。"""
    run_id = _joint_run(sync_engine, project)
    _complete(
        client,
        run_id,
        components=[
            {"kind": "ui", "state": "completed", "outcome": "failed"},
            {"kind": "performance", "state": "completed"},
        ],
        junit={"tests": 3, "failures": 1, "errors": 0, "skipped": 0},
    )
    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT state, outcome, reason_code FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).mappings().one()
    assert row["state"] == "completed"
    assert row["outcome"] == "failed", "断言失败不是 runner 故障，整体按 failed 收敛"
    components = _components_of(sync_engine, run_id)
    assert components["ui"]["outcome"] == "failed"
    assert "performance" in components, "性能组件必须保留，不得只显示整体"


def test_matrix_perf_stop_failure_keeps_ui_result_and_not_tested(
    client, project, sync_engine
):
    """停采失败：UI 结果保留，整体不得伪装 passed；性能组件必须是 errored。"""
    run_id = _joint_run(sync_engine, project)
    _complete(
        client,
        run_id,
        components=[
            {"kind": "ui", "state": "completed", "outcome": "passed"},
            {
                "kind": "performance",
                "state": "errored",
                "reason_code": "perf_collect_stop_failed",
            },
        ],
        junit={"tests": 2, "failures": 0, "errors": 0, "skipped": 0},
    )
    with sync_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT state, outcome, reason_code FROM test_runs"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"id": run_id},
        ).mappings().one()
    assert row["state"] == "completed"
    assert row["outcome"] == "not_tested", "性能采集失败不得让整体结论变成 passed"
    assert row["reason_code"] == "perf_collect_stop_failed"
    components = _components_of(sync_engine, run_id)
    assert components["ui"]["outcome"] == "passed", "UI 结果必须保留"
    assert components["performance"]["state"] == "errored"
    assert components["performance"]["reason_code"] == "perf_collect_stop_failed"


def test_matrix_collect_start_failure_is_errored_with_cancelled_ui(client, project, sync_engine):
    run_id = _joint_run(sync_engine, project)
    response = client.post(
        f"/internal/runs/{run_id}/fail",
        json={
            "error_code": "perf_collect_start_failed",
            "message": "性能采集启动失败，UI 未执行",
            "stage": "perf_collect_start",
            "components": [
                {"kind": "ui", "state": "cancelled",
                 "reason_code": "collect_start_failed_ui_not_started"},
                {"kind": "performance", "state": "errored",
                 "reason_code": "perf_collect_start_failed"},
            ],
        },
        headers={"X-Control-Token": client.app.state.control_token},
    )
    assert response.status_code == 200, response.text
    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT state, outcome FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).mappings().one()
    assert row["state"] == "errored"
    assert row["outcome"] is None, "采集启动失败不得产生任何结论"
    components = _components_of(sync_engine, run_id)
    assert components["ui"]["state"] == "cancelled"
    assert components["ui"]["reason_code"] == "collect_start_failed_ui_not_started"
    assert components["performance"]["state"] == "errored"


def test_matrix_ui_timeout_is_errored_not_failed(client, project, sync_engine):
    run_id = _joint_run(sync_engine, project)
    response = client.post(
        f"/internal/runs/{run_id}/fail",
        json={
            "error_code": "ui_timeout",
            "message": "UI 执行达到 ui_timeout_s 上限",
            "stage": "ui",
            "components": [
                {"kind": "ui", "state": "errored", "reason_code": "ui_timeout"},
                {"kind": "performance", "state": "cancelled",
                 "reason_code": "collect_stopped_at_ui_timeout"},
            ],
        },
        headers={"X-Control-Token": client.app.state.control_token},
    )
    assert response.status_code == 200, response.text
    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT state, outcome FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).mappings().one()
    assert row["state"] == "errored"
    assert row["outcome"] is None
    components = _components_of(sync_engine, run_id)
    assert components["ui"]["reason_code"] == "ui_timeout"


def test_matrix_cancelled_joint_keeps_components_without_outcome(client, project, sync_engine):
    """取消是真实状态：两个组件如实记 cancelled，整体 outcome 必须为 NULL。"""
    run_id = _joint_run(sync_engine, project)
    response = client.post(
        f"/internal/runs/{run_id}/fail",
        json={
            "error_code": "cancelled",
            "message": "用户取消",
            "stage": "cancelled",
            "components": [
                {"kind": "ui", "state": "cancelled", "reason_code": "cancel_requested"},
                {"kind": "performance", "state": "cancelled",
                 "reason_code": "cancel_requested"},
            ],
        },
        headers={"X-Control-Token": client.app.state.control_token},
    )
    assert response.status_code == 200, response.text
    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT state, outcome FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).mappings().one()
    assert row["state"] == "cancelled"
    assert row["outcome"] is None
    components = _components_of(sync_engine, run_id)
    assert {kind: item["state"] for kind, item in components.items()} == {
        "ui": "cancelled",
        "performance": "cancelled",
    }


# --------------------------------------------------------------------------- #
# 派发：manifest.ui_timeout_s 合订 + 单条资源租约
# --------------------------------------------------------------------------- #
@pytest.fixture
def joint_spawns(monkeypatch):
    """替换真实 spawn，只观察派发配置（真机留给工单 10）。"""
    from app.runner import dispatch_runner

    reset_db_engine(TEST_DB)
    calls: list[dict] = []

    async def spawn(**kwargs):
        calls.append(kwargs)
        return 424242

    monkeypatch.setattr(dispatch_runner, "_spawner", spawn)
    yield calls
    reset_db_engine(TEST_DB)


def _joint_revision_with_manifest_ui_timeout(engine, project: dict, seconds: int) -> None:
    """把修订/清单改成 joint，ui_timeout_s 只写在 manifest（生产口径）。"""
    with engine.begin() as conn:
        manifest = conn.execute(
            text("SELECT manifest FROM suite_versions WHERE id = CAST(:sid AS uuid)"),
            {"sid": project["suite_version_id"]},
        ).scalar_one()
        manifest = dict(manifest or {})
        manifest.update(
            {
                "test_type": "joint",
                "performance": {"duration_s": 90, "items": ["CPU"]},
                "ui_timeout_s": seconds,
            }
        )
        conn.execute(
            text(
                "UPDATE suite_versions SET manifest = CAST(:manifest AS jsonb)"
                " WHERE id = CAST(:sid AS uuid)"
            ),
            {"manifest": json.dumps(manifest), "sid": project["suite_version_id"]},
        )
        conn.execute(
            text(
                "UPDATE task_revisions SET test_type = 'joint', config = '{}'::jsonb"
                " WHERE id = CAST(:rid AS uuid)"
            ),
            {"rid": project["revision_id"]},
        )


def test_dispatch_joint_merges_manifest_ui_timeout(
    project, make_run, sync_engine, joint_spawns
):
    """生产修订不带 ui_timeout_s：派发必须从 manifest 合订，否则恒为默认 600。"""
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    _joint_revision_with_manifest_ui_timeout(sync_engine, project, 120)
    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        config_snapshot={
            "module": "joint",
            "perf": {"duration_s": 90, "items": ["CPU"]},
            "requested_resource_id": project["resource_id"],
        },
    )
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is True, outcome.reason

    config = joint_spawns[0]["config"]
    assert config["ui_timeout_s"] == 120, "UI 执行窗必须来自套件版本清单"
    assert config["suite_root"], "联动同样必须带固定副本（工单 01 接线）"
    spec = build_spec(
        run_id=run_id, config=config, lease=joint_spawns[0]["lease"]
    )
    assert spec.argv[spec.argv.index("--ui-timeout") + 1] == "120"
    assert spec.argv[spec.argv.index("--suite-root") + 1] == config["suite_root"]


def test_joint_dispatch_holds_one_lease_for_both_components(
    project, make_run, sync_engine, joint_spawns
):
    """一次联动运行只有一条资源租约：UI 与性能共享同一独占期。"""
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    _joint_revision_with_manifest_ui_timeout(sync_engine, project, 600)
    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        config_snapshot={
            "module": "joint",
            "perf": {"duration_s": 90, "items": ["CPU"]},
            "requested_resource_id": project["resource_id"],
        },
    )
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is True, outcome.reason
    assert len(joint_spawns) == 1, "联动只拉起一个 runner（不拆成两次执行）"

    with sync_engine.connect() as conn:
        leases = conn.execute(
            text(
                "SELECT resource_id, released_at FROM resource_leases"
                " WHERE run_id = CAST(:rid AS uuid)"
            ),
            {"rid": run_id},
        ).mappings().all()
    assert len(leases) == 1, "同一独占期只得一条租约，UI 与性能共用"
    assert leases[0]["released_at"] is None, "派发后租约仍在独占期内"
    assert str(leases[0]["resource_id"]) == project["resource_id"]
    assert joint_spawns[0]["lease"]["resource_id"] == project["resource_id"]


# --------------------------------------------------------------------------- #
# 报告：collectWindow 必须经 GET /report 可见（工单 07 缺陷 4）
# --------------------------------------------------------------------------- #
def test_report_exposes_collect_window(client, project, sync_engine, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    run_id = _joint_run(sync_engine, project)
    artifacts_dir = settings.artifacts_dir / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    window = {
        "collect_started_at": "2026-01-01T00:00:00+00:00",
        "collect_stopped_at": "2026-01-01T00:02:10+00:00",
        "ui": {
            "started_at": "2026-01-01T00:00:05+00:00",
            "ended_at": "2026-01-01T00:02:00+00:00",
            "timeout_s": 120,
        },
    }
    (artifacts_dir / "report.json").write_text(
        json.dumps(
            {
                "runId": run_id,
                "mode": "original",
                "metricsSummary": {
                    "mem_pss_mb": {"unit": "MB", "median": 268.0, "sampleCount": 12}
                },
                "collectWindow": window,
                "prototype": False,
            }
        ),
        encoding="utf-8",
    )
    _complete(
        client,
        run_id,
        components=[
            {"kind": "ui", "state": "completed", "outcome": "passed"},
            {"kind": "performance", "state": "completed"},
        ],
        junit={"tests": 3, "failures": 0, "errors": 0, "skipped": 0},
        artifacts_dir=artifacts_dir,
    )

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["collectWindow"] == window, (
        "报告必须能看到采集起止与 UI 执行窗，而不是只有 metricsSummary"
    )


def test_report_prefers_run_level_report_over_nested_perf_report(
    client, project, sync_engine, tmp_path, monkeypatch
):
    """真机缺陷回归：性能采集真正启动后会多出 perf-runs/<run>/report.json。

    平台按 logical_key 排序取"第一个 report.json"，嵌套的 vendor 报告会抢先，
    把 run 级 report.json 里的 collectWindow 挤掉。run 级报告必须优先。
    """
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    run_id = _joint_run(sync_engine, project)
    artifacts_dir = settings.artifacts_dir / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    window = {
        "collect_started_at": "2026-01-01T00:00:00+00:00",
        "collect_stopped_at": "2026-01-01T00:02:10+00:00",
        "ui": {
            "started_at": "2026-01-01T00:00:05+00:00",
            "ended_at": "2026-01-01T00:02:00+00:00",
            "timeout_s": 120,
        },
    }
    (artifacts_dir / "report.json").write_text(
        json.dumps(
            {
                "runId": run_id,
                "metricsSummary": {"cpu_process_pct": {"median": 1.5}},
                "collectWindow": window,
            }
        ),
        encoding="utf-8",
    )
    nested = artifacts_dir / "perf-runs" / run_id
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "report.json").write_text(
        json.dumps({"runId": run_id, "metricsSummary": {"cpu_process_pct": {"median": 9.9}}}),
        encoding="utf-8",
    )
    _complete(
        client,
        run_id,
        components=[
            {"kind": "ui", "state": "completed", "outcome": "passed"},
            {"kind": "performance", "state": "completed"},
        ],
        junit={"tests": 3, "failures": 0, "errors": 0, "skipped": 0},
        artifacts_dir=artifacts_dir,
    )

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["collectWindow"] == window, "run 级报告里的采集窗口不能被嵌套报告挤掉"
    assert report["metricsSummary"]["cpu_process_pct"]["median"] == 1.5


def test_report_collect_window_is_null_when_absent(client, project, sync_engine):
    run_id = _joint_run(sync_engine, project)
    _complete(
        client,
        run_id,
        components=[
            {"kind": "ui", "state": "completed", "outcome": "passed"},
            {"kind": "performance", "state": "completed"},
        ],
        junit={"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
    )
    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["collectWindow"] is None, "没有采集窗口就明说没有，不编造"


def test_ui_timeout_failure_still_registers_collect_window(
    client, project, sync_engine, tmp_path, monkeypatch
):
    """超时收口的 report.json 也要登记：errored 运行同样能说明采集覆盖了 UI。"""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    run_id = _joint_run(sync_engine, project)
    artifacts_dir = settings.artifacts_dir / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    window = {
        "collect_started_at": "2026-01-01T00:00:00+00:00",
        "collect_stopped_at": "2026-01-01T00:01:05+00:00",
        "ui": {
            "started_at": "2026-01-01T00:00:03+00:00",
            "ended_at": "2026-01-01T00:01:00+00:00",
            "timeout_s": 30,
        },
    }
    (artifacts_dir / "report.json").write_text(
        json.dumps(
            {
                "runId": run_id,
                "mode": "original",
                "metricsSummary": {},
                "collectWindow": window,
                "prototype": False,
            }
        ),
        encoding="utf-8",
    )
    response = client.post(
        f"/internal/runs/{run_id}/fail",
        json={
            "error_code": "ui_timeout",
            "message": "UI 执行达到 ui_timeout_s 上限",
            "stage": "ui",
            "artifacts_dir": str(artifacts_dir),
            "components": [
                {"kind": "ui", "state": "errored", "reason_code": "ui_timeout"},
                {"kind": "performance", "state": "cancelled",
                 "reason_code": "collect_stopped_at_ui_timeout"},
            ],
        },
        headers={"X-Control-Token": client.app.state.control_token},
    )
    assert response.status_code == 200, response.text

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["status"] == "errored"
    assert report["verdict"] is None, "非 completed 不得有 outcome"
    assert report["collectWindow"] == window


def test_perf_collect_scope_is_entered_before_ui_runs(monkeypatch, tmp_path):
    """真机缺陷回归：`kit.collect()` 只构造作用域，必须 `__enter__` 才开采集。

    旧实现直接把未进入的作用域交给 finalize，UI 跑完才在 stop 时报
    `'NoneType' object has no attribute 'stop'`——联动的性能采集其实从未启动，
    报告却写成"性能组件 completed / not_tested"。这里用假 PerfKit 钉住入口。
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server/runner_pkg"))
    from testdock_runner import joint_job
    from testdock_runner.env import ensure_vendor_on_path
    from testdock_runner.ui_job import UiJobOptions

    ensure_vendor_on_path(Path(__file__).resolve().parents[2] / "vendor")
    import mobile_perf.kit as kit_mod
    calls: list[str] = []

    class FakeScope:
        report = {"metricsSummary": {"cpu_process_pct": {"median": 1.0}}}

        def __enter__(self):
            calls.append("enter")
            return self

        def finalize(self):
            calls.append("finalize")
            return self.report

    class FakeKit:
        def __init__(self, **kwargs):
            calls.append("kit")

        def collect(self, spec=None, **kwargs):
            calls.append("collect")
            return FakeScope()

    monkeypatch.setattr(kit_mod, "PerfKit", FakeKit)
    options = UiJobOptions(
        run_id="run-real-scope",
        artifacts_dir=tmp_path,
        serial="serial",
        app_package="com.example.app",
        perf={"items": ["CPU"]},
    )

    scope = joint_job._start_perf_collect(options)

    assert calls == ["kit", "collect", "enter"], calls
    assert joint_job._stop_collection(scope) == (FakeScope.report, None)
    assert calls == ["kit", "collect", "enter", "finalize"], calls
