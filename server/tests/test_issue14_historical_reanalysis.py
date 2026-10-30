"""工单 14：历史缺 original 的显式重分析（真实 PG，定向测试）。

覆盖的验收点（AC-GATE-02）：

- 已终态且数据可用的历史运行，即使缺 original，也可显式追加判定，但只能落
  reanalysis——"原始判定"意味着执行时点的首轮结论，事后补造等于伪造；
- 原 outcome 一行不改；报告持续显示 original 缺失，不补造；
- 未完成的运行试算 → 409 并说明缺项；重复请求幂等；
- 显式指定跨档案基线：判定照做但给 profile_mismatch，不伪造可比来源。
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests._p3_common import CLIENT_HEADERS, TEST_DB, reset_db_engine, requires_db
from tests._p3_common import make_run as make_run
from tests._p3_common import p3_project as project
from tests._p3_common import sync_engine as sync_engine

pytestmark = requires_db

PROFILE_SPEC = {"os": "android", "os_version": "13", "resolution": "1080x2400", "model": "pixel7"}


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


def _setup(engine, project: dict, run_id: str, *, value: float = 150.0) -> str:
    """可规范化的档案 + performance 组件 + 真实指标。"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE resource_profiles SET spec = CAST(:spec AS jsonb)"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"spec": json.dumps(PROFILE_SPEC), "id": project["profile_id"]},
        )
    component_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO run_components (id, project_id, run_id, kind, adapter_key,"
                "                            adapter_version, state, outcome, summary)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         'performance', 'mobile_perf', '1.0', 'completed', 'passed',"
                "         '{}'::jsonb)"
            ),
            {"id": component_id, "pid": project["project_id"], "rid": run_id},
        )
        conn.execute(
            text(
                "INSERT INTO metric_summaries (id, project_id, component_id, metric_key,"
                "                              metric_version, unit, scope, window_key,"
                "                              statistic, sample_count, value, missing_reason)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:cid AS uuid),"
                "         'mem_pss_mb', '1.0', 'MB', 'component', :win, 'median',"
                "         180, :value, NULL)"
            ),
            {"pid": project["project_id"], "cid": component_id,
             "win": f"{run_id}:mem"[:40], "value": value},
        )
    return component_id


def _add_policy(engine, project: dict) -> str:
    policy_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO gate_policies (id, project_id, application_id, name, version, rules)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         'pytest-policy', 1, '{\"mem_pss_mb\": [\"lt\", 240, \"fail\"]}'::jsonb)"
            ),
            {"id": policy_id, "pid": project["project_id"], "aid": project["application_id"]},
        )
    return policy_id


def _add_baseline(engine, project: dict, *, profile_id: str, component_id: str,
                  source_run_id: str | None = None) -> str:
    baseline_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO baselines (id, project_id, application_id, environment_id,"
                "                       suite_version_id, profile_id, source_component_id,"
                "                       name, version, metrics_snapshot)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         CAST(:eid AS uuid), CAST(:svid AS uuid), CAST(:prof AS uuid),"
                "         CAST(:cid AS uuid), :name, 1, CAST(:snapshot AS jsonb))"
            ),
            {
                "id": baseline_id,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "eid": project["environment_id"],
                "svid": project["suite_version_id"],
                "prof": profile_id,
                "cid": component_id,
                "name": "baseline-" + uuid.uuid4().hex[:6],
                # 默认基线解析要求快照带 source_run_id（_snapshot_run_ids）
                "snapshot": json.dumps(
                    {"metrics": {"mem_pss_mb": {"value": 100.0, "source_run_id": source_run_id}}}
                ),
            },
        )
    return baseline_id


def _evaluate(client, run_id: str, **payload) -> dict:
    body = {"request_key": payload.pop("request_key", "eval-" + uuid.uuid4().hex)}
    body.update(payload)
    return client.post(f"/api/v1/runs/{run_id}/gate-evaluations", json=body)


def test_completed_run_without_original_gets_reanalysis_not_fabricated_original(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    component_id = _setup(sync_engine, project, run_id)
    policy_id = _add_policy(sync_engine, project)
    _add_baseline(sync_engine, project, profile_id=project["profile_id"],
                  component_id=component_id, source_run_id=run_id)

    response = _evaluate(client, run_id, policy_id=policy_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "reanalysis", "终态运行补判定不得补造 original"
    assert body["verdict"] == "passed"

    # 原 outcome 一行不改（本来是 passed 的行保持原值）
    with sync_engine.connect() as conn:
        outcome = conn.execute(
            text("SELECT outcome FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar_one()
    assert outcome == "passed"

    # 分析页持续显示 original 缺失，且默认不兜底到这次试算
    analysis = client.get("/api/v1/analyses", params={"run_id": run_id}).json()
    assert analysis["original_missing"] is True
    assert analysis["verdict"] is None
    assert body["id"] in {item["id"] for item in analysis["evaluations"]}


def test_trial_on_unfinished_run_is_rejected_with_missing_info(client, project, make_run, sync_engine):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))
    _setup(sync_engine, project, run_id)
    response = _evaluate(client, run_id)
    assert response.status_code == 409, response.text
    assert "running" in response.text


def test_repeated_reanalysis_request_is_idempotent(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    component_id = _setup(sync_engine, project, run_id)
    policy_id = _add_policy(sync_engine, project)
    _add_baseline(sync_engine, project, profile_id=project["profile_id"],
                  component_id=component_id, source_run_id=run_id)

    request_key = "reanalysis-" + uuid.uuid4().hex
    first = _evaluate(client, run_id, request_key=request_key, policy_id=policy_id)
    second = _evaluate(client, run_id, request_key=request_key, policy_id=policy_id)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    with sync_engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM gate_evaluations"
                " WHERE project_id = CAST(:pid AS uuid) AND request_key = :key"
            ),
            {"pid": project["project_id"], "key": request_key},
        ).scalar_one()
    assert count == 1


def test_cross_profile_baseline_is_not_faked_as_comparable(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    component_id = _setup(sync_engine, project, run_id)
    policy_id = _add_policy(sync_engine, project)
    with sync_engine.begin() as conn:
        other_profile = str(
            conn.execute(
                text(
                    "INSERT INTO resource_profiles (id, project_id, platform, name, fingerprint, spec)"
                    " VALUES (gen_random_uuid(), CAST(:pid AS uuid), 'android', 'other',"
                    "         :fp, CAST(:spec AS jsonb)) RETURNING id"
                ),
                {
                    "pid": project["project_id"],
                    "fp": uuid.uuid4().hex + uuid.uuid4().hex,
                    "spec": json.dumps(
                        {"os": "android", "os_version": "14",
                         "resolution": "1440x3120", "model": "pixel8"}
                    ),
                },
            ).scalar_one()
        )
    # 基线来源是另一台（另一档案的）运行：判定的可比性按 baseline run 的档案核对
    other_run = make_run(state="completed", request_key=str(uuid.uuid4()))
    _setup(sync_engine, project, other_run, value=100.0)
    with sync_engine.begin() as conn:
        conn.execute(
            text("UPDATE test_runs SET profile_id = CAST(:p AS uuid) WHERE id = CAST(:r AS uuid)"),
            {"p": other_profile, "r": other_run},
        )

    response = _evaluate(client, run_id, policy_id=policy_id, baseline_run_id=other_run)
    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["verdict"] == "not_tested", "跨档案不得给出通过/失败"
    assert body["reason_code"] == "profile_mismatch", body
