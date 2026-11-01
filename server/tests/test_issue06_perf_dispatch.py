"""工单 06：套件版本场景与执行配置不漂移 + performance 派发不要求代码副本。

两个真实 PostgreSQL 层面的缺口：

1. 执行输入只读修订 ``config.perf``，套件版本的 ``manifest.scenario`` /
   ``manifest.performance`` 从不参与——两份声明可以长期不一致而无人发现。
   提交运行时应把两者合订成一份并写明来源，不一致直接 422 拒绝；
2. 派发侧对所有运行统一要求 ``code_copy``，但 performance 是声明式场景、
   版本按设计没有代码副本，独立性能运行因此被误判
   ``errored(execution_copy_missing)``。派发必须按 ``test_type`` 区分：
   performance 不要副本，ui / joint 仍必须有，缺了照旧阻断。
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from tests._p3_common import CLIENT_HEADERS, TEST_DB, reset_db_engine, requires_db
from tests._p3_common import api_client as client  # noqa: F401 - 夹具注册
from tests._p3_common import make_run as make_run  # noqa: F401
from tests._p3_common import p3_project as project  # noqa: F401
from tests._p3_common import sync_engine as sync_engine  # noqa: F401

pytestmark = requires_db

SCENARIO = {"duration_s": 90, "items": ["CPU", "Memory"]}


@pytest.fixture(autouse=True)
def isolated_code_copies(tmp_path, monkeypatch):
    """把固定副本根收敛到用例临时目录：不往共享 data/ 里堆副本。"""
    root = tmp_path / "code-copies"
    root.mkdir()
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(root))


@pytest.fixture
def spawns(monkeypatch):
    from app.runner import dispatch_runner

    reset_db_engine(TEST_DB)
    calls: list[dict] = []

    async def spawn(**kwargs):
        calls.append(kwargs)
        return 123456

    monkeypatch.setattr(dispatch_runner, "_spawner", spawn)
    yield calls
    reset_db_engine(TEST_DB)


def _run_body(project: dict, **overrides) -> dict:
    body = {
        "application_id": project["application_id"],
        "task_id": project["task_id"],
        "request_key": str(uuid.uuid4()),
        "platform": "android",
        "module": "performance",
        "device": {"resource_id": project["resource_id"]},
    }
    body.update(overrides)
    return body


def _set_revision(engine, project: dict, *, test_type: str, perf: dict | None) -> None:
    config = {"perf": perf} if perf is not None else {}
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE task_revisions SET test_type = :tt, config = CAST(:config AS jsonb)"
                " WHERE id = CAST(:rid AS uuid)"
            ),
            {"tt": test_type, "config": json.dumps(config), "rid": project["revision_id"]},
        )


def _set_manifest(engine, project: dict, manifest: dict) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE suite_versions SET manifest = CAST(:manifest AS jsonb)"
                " WHERE id = CAST(:sid AS uuid)"
            ),
            {"manifest": json.dumps(manifest), "sid": project["suite_version_id"]},
        )


def _perf_manifest(scenario: dict | None) -> dict:
    from app.domain import suite as suite_domain

    if scenario is None:
        return {"schema_version": 1, "case_count": 0, "cases": []}
    return suite_domain.build_typed_manifest("performance", scenario=scenario)


def _snapshot(engine, run_id: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT config_snapshot, state, reason_code FROM test_runs"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"id": run_id},
        ).mappings().one()
    return dict(row)


# --------------------------------------------------------------------------- #
# 提交：合订两份声明并写明来源
# --------------------------------------------------------------------------- #
def test_submit_merges_suite_manifest_scenario_with_explicit_source(
    client, project, sync_engine
):
    _set_revision(sync_engine, project, test_type="performance", perf=dict(SCENARIO))
    _set_manifest(sync_engine, project, _perf_manifest(SCENARIO))

    response = client.post("/api/v1/runs", json=_run_body(project), headers=CLIENT_HEADERS)
    assert response.status_code == 201, response.text

    snapshot = _snapshot(sync_engine, response.json()["id"])["config_snapshot"]
    assert snapshot["perf"] == SCENARIO
    assert snapshot["perf_source"] == "suite_manifest", "来源必须写明，不能靠猜"


def test_submit_uses_revision_scenario_when_manifest_declares_none(
    client, project, sync_engine
):
    _set_revision(sync_engine, project, test_type="performance", perf=dict(SCENARIO))
    _set_manifest(sync_engine, project, _perf_manifest(None))

    response = client.post("/api/v1/runs", json=_run_body(project), headers=CLIENT_HEADERS)
    assert response.status_code == 201, response.text

    snapshot = _snapshot(sync_engine, response.json()["id"])["config_snapshot"]
    assert snapshot["perf"] == SCENARIO
    assert snapshot["perf_source"] == "revision"


def test_submit_rejects_conflicting_scenario_declarations(client, project, sync_engine):
    _set_revision(
        sync_engine, project, test_type="performance", perf={"duration_s": 120, "items": ["CPU"]}
    )
    _set_manifest(sync_engine, project, _perf_manifest({"duration_s": 60, "items": ["CPU"]}))

    response = client.post("/api/v1/runs", json=_run_body(project), headers=CLIENT_HEADERS)
    assert response.status_code == 400, response.text
    envelope = response.json()
    assert envelope["code"] == "validation_error"
    details = json.dumps(envelope["details"], ensure_ascii=False)
    assert "不一致" in details and "perf" in details
    with sync_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM test_runs WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": project["project_id"]},
        ).scalar_one()
    assert count == 0, "冲突时不得留下 queued 运行"


def test_submit_rejects_revision_scenario_outside_window(client, project, sync_engine):
    _set_revision(
        sync_engine, project, test_type="performance", perf={"duration_s": 5, "items": ["CPU"]}
    )
    _set_manifest(sync_engine, project, _perf_manifest(None))

    response = client.post("/api/v1/runs", json=_run_body(project), headers=CLIENT_HEADERS)
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "validation_error"
    assert "duration_s" in json.dumps(response.json()["details"], ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 派发：performance 不要代码副本，joint 仍必须有
# --------------------------------------------------------------------------- #
def test_performance_run_dispatches_without_code_copy(project, make_run, sync_engine, spawns):
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    _set_revision(sync_engine, project, test_type="performance", perf=dict(SCENARIO))
    _set_manifest(sync_engine, project, _perf_manifest(SCENARIO))

    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        config_snapshot={
            "module": "perf",
            "perf": dict(SCENARIO),
            "perf_source": "suite_manifest",
            "requested_resource_id": project["resource_id"],
        },
    )
    outcome = asyncio.run(dispatch_one(run_id=run_id))

    assert outcome.ok is True, outcome.reason
    assert spawns, "performance 运行必须能派发"
    config = spawns[0]["config"]
    assert config["perf"] == SCENARIO
    assert "suite_root" not in config, "声明式场景没有代码副本，不得伪造副本根"
    row = _snapshot(sync_engine, run_id)
    assert row["state"] == "dispatching"


def test_joint_run_without_code_copy_is_still_blocked(project, make_run, sync_engine, spawns):
    import asyncio

    from app.domain import suite as suite_domain
    from app.scheduler.dispatcher import dispatch_one

    _set_revision(sync_engine, project, test_type="joint", perf=dict(SCENARIO))
    # joint 清单可以声明性能窗口，但**没有** code_copy —— UI 部分无可执行代码
    _set_manifest(
        sync_engine,
        project,
        suite_domain.build_typed_manifest(
            "joint",
            node_ids=["tests/test_smoke.py::test_ok"],
            scenario=SCENARIO,
            ui_timeout_s=600,
        ),
    )

    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        config_snapshot={
            "module": "joint",
            "perf": dict(SCENARIO),
            "requested_resource_id": project["resource_id"],
        },
    )
    outcome = asyncio.run(dispatch_one(run_id=run_id))

    assert outcome.ok is False
    assert outcome.reason == "execution_copy_missing"
    assert spawns == [], "joint 缺 UI 代码副本时不得 spawn"
    row = _snapshot(sync_engine, run_id)
    assert row["state"] == "errored"
    assert row["reason_code"] == "execution_copy_missing"


# --------------------------------------------------------------------------- #
# 端到端：performance 运行只产出性能组件，报告不声称执行 UI 动作
# --------------------------------------------------------------------------- #
def test_performance_run_report_claims_no_ui_execution(
    client, project, sync_engine, spawns, tmp_path, monkeypatch
):
    import asyncio

    from app.config import settings
    from app.scheduler.dispatcher import dispatch_one

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    artifacts_root = tmp_path / "artifacts"
    _set_revision(sync_engine, project, test_type="performance", perf=dict(SCENARIO))
    _set_manifest(sync_engine, project, _perf_manifest(SCENARIO))

    created = client.post("/api/v1/runs", json=_run_body(project), headers=CLIENT_HEADERS)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is True, outcome.reason

    # runner 自己的采集窗口 = 合订后的场景（时长与采集项原样传给 vendor）
    assert spawns[0]["config"]["perf"] == SCENARIO
    artifacts_dir = artifacts_root / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "report.json").write_text(
        json.dumps(
            {
                "runId": run_id,
                "mode": "original",
                "metricsSummary": {
                    "cpu_process_pct": {"unit": "%", "median": 12.5, "sampleCount": 30}
                },
                "thresholdsAtRun": {},
            }
        ),
        encoding="utf-8",
    )

    completed = client.post(
        f"/internal/runs/{run_id}/complete",
        json={
            "fencing_token": spawns[0]["lease"]["fencing_token"],
            "components": [
                {
                    "kind": "performance",
                    "state": "completed",
                    "outcome": "not_tested",
                    "reason_code": "gate_policy_missing",
                }
            ],
            "artifacts_dir": str(artifacts_dir),
        },
        headers={"X-Control-Token": client.app.state.control_token},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "completed"

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert [c["kind"] for c in report["components"]] == ["performance"]
    assert report["junit"] == {}, "独立性能运行没有 UI 用例结果"
    assert report["metricsSummary"]["cpu_process_pct"]["median"] == 12.5
    # 没有门禁策略 -> not_tested（不是通过），原因来自平台判定
    assert report["verdict"] == "not_tested"
    assert report["reason"] == "gate_policy_missing"
    originals = [g for g in report["gateEvaluations"] if g["mode"] == "original"]
    assert len(originals) == 1, "completed 运行必须自带原始判定"
