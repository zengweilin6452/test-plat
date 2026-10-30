"""工单 16：joint 生命周期与结果矩阵（fake runner，定向测试）。

覆盖的验收点（D8/D11、AC-JOINT-01/02/03、AC-CONTRACT-06）：

- 两个组件（ui + performance）共享一次运行、一次资源独占（单 spawn、单租约）；
- UI 一返回立即停采：采集窗口记录真实时间戳，不补采；
- 结果矩阵：UI 断言失败 → completed/failed；采集启动失败 → errored 且
  UI=cancelled"前置采集失败未执行"；UI 达 ui_timeout_s → errored 记超时；
- AC-CONTRACT-06：ui_timeout 允许到 3600，spawn 的总超时必须留出缓冲不被截断；
- joint 不降级为 ui：spawn argv 保留 joint。
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


def _complete(client, run_id: str, components: list[dict], junit: dict) -> dict:
    response = client.post(
        f"/internal/runs/{run_id}/complete",
        json={
            "outcome": None,
            "components": components,
            "junit": junit,
        },
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
