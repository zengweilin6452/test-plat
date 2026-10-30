"""工单 13：原始判定冻结（真实 PG，定向测试）。

覆盖的验收点（AC-GATE-01、AC-CONTRACT-05 的判定侧、显式版本失效、跨档案不回退、
重试幂等）：

- 排队即固定默认策略：排队期间新增策略版本，不改变该次执行的判定依据；
- 显式指定失效策略版本 → 404，不偷偷替换成最新；
- 无同档案基线时记录缺失（baseline_missing），不回退跨档案；
- 同 request_key 重试幂等；original 只有一条（部分唯一索引兜底）。
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


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


PROFILE_SPEC = {"os": "android", "os_version": "13", "resolution": "1080x2400", "model": "pixel7"}


def _usable_profile(engine, project: dict) -> None:
    """把夹具档案行补成可规范化的 spec（默认 '{}' 无法参与同档案匹配）。"""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE resource_profiles SET spec = CAST(:spec AS jsonb) WHERE id = CAST(:id AS uuid)"),
            {"spec": json.dumps(PROFILE_SPEC), "id": project["profile_id"]},
        )


def _add_policy(engine, project: dict, version: int) -> str:
    policy_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO gate_policies (id, project_id, application_id, name, version, rules)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         'pytest-policy', :version, CAST(:rules AS jsonb))"
            ),
            {
                "id": policy_id,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "version": version,
                "rules": json.dumps({"mem_pss_mb": ["lt", 240 if version == 1 else 1, "fail"]}),
            },
        )
    return policy_id


def _setup_perf(engine, project: dict, run_id: str, value: float = 150.0) -> str:
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
            {"pid": project["project_id"], "cid": component_id, "win": f"{run_id}:mem"[:40], "value": value},
        )
    return component_id


def _add_baseline(engine, project: dict, *, profile_id: str, source_run_id: str,
                  component_id: str | None = None) -> str:
    """baselines.source_component_id NOT NULL：必须指向真实组件行（插行即成功）。"""
    assert component_id, "必须传 _setup_perf 返回的真实组件 id"
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
                "snapshot": json.dumps(
                    {
                        "metrics": {
                            "mem_pss_mb": {"value": 100.0, "source_run_id": source_run_id}
                        }
                    }
                ),
            },
        )
    return baseline_id


def _evaluate(client, run_id: str, **payload) -> dict:
    body = {"request_key": payload.pop("request_key", "eval-" + uuid.uuid4().hex)}
    body.update(payload)
    response = client.post(f"/api/v1/runs/{run_id}/gate-evaluations", json=body)
    assert response.status_code in (200, 201, 404), response.text
    return response


def test_queue_time_policy_snapshot_survives_new_version(client, project, make_run, sync_engine):
    v1 = _add_policy(sync_engine, project, 1)
    run_id = make_run(
        state="completed",
        request_key=str(uuid.uuid4()),
        config_snapshot={"gate_policy": {"id": v1, "version": 1, "rules": {"mem_pss_mb": ["lt", 240]}}},
    )
    _usable_profile(sync_engine, project)
    component_id = _setup_perf(sync_engine, project, run_id)

    _add_baseline(sync_engine, project, profile_id=project["profile_id"],
                  source_run_id=run_id, component_id=component_id)
    # 排队后上线了 v2（更严的阈值）：这次执行的判定依据仍是 v1
    _add_policy(sync_engine, project, 2)
    response = _evaluate(client, run_id)
    assert response.status_code in (200, 201)
    body = response.json()
    assert body["policy_id"] == v1, "排队期间新增策略版本不得改写执行快照"
    assert body["verdict"] == "passed", "v1 阈值 lt 240，150 应通过"

    # 换个新运行（新快照）才用 v2
    run_id2 = make_run(
        state="completed",
        request_key=str(uuid.uuid4()),
        config_snapshot={},
    )
    _setup_perf(sync_engine, project, run_id2)
    body2 = _evaluate(client, run_id2).json()
    assert body2["verdict"] == "not_tested" or body2["policy_id"] != v1


def test_explicit_stale_policy_version_is_404_not_substituted(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    _setup_perf(sync_engine, project, run_id)
    response = _evaluate(client, run_id, policy_id=str(uuid.uuid4()))
    assert response.status_code == 404, response.text


def test_no_same_profile_baseline_records_missing_not_cross_profile(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    _usable_profile(sync_engine, project)
    component_id = _setup_perf(sync_engine, project, run_id)
    _add_policy(sync_engine, project, 1)

    # 唯一的基线属于另一个真实档案（不同 spec）：不得回退跨档案，应记录 baseline_missing
    with sync_engine.begin() as conn:
        other_profile = str(
            conn.execute(
                text(
                    "INSERT INTO resource_profiles (id, project_id, platform, name, fingerprint, spec)"
                    " VALUES (gen_random_uuid(), CAST(:pid AS uuid), 'android', 'other-profile',"
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
    _add_baseline(
        sync_engine, project, profile_id=other_profile, source_run_id=run_id,
        component_id=component_id,
    )
    response = _evaluate(client, run_id)
    body = response.json()
    assert body["verdict"] == "not_tested"
    assert body["reason_code"] == "baseline_missing", body


def test_same_profile_baseline_is_used_and_retry_is_idempotent(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    _usable_profile(sync_engine, project)
    component_id = _setup_perf(sync_engine, project, run_id)
    _add_policy(sync_engine, project, 1)
    _add_baseline(
        sync_engine, project, profile_id=project["profile_id"], source_run_id=run_id,
        component_id=component_id,
    )

    request_key = "eval-retry-" + uuid.uuid4().hex
    first = _evaluate(client, run_id, request_key=request_key)
    assert first.status_code == 201
    second = _evaluate(client, run_id, request_key=request_key)
    assert second.status_code == 200, "重试必须命中同一行而不是新建"
    assert first.json()["id"] == second.json()["id"]

    # 每个性能组件只有一条 original（重试不追加）
    with sync_engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM gate_evaluations e"
                " JOIN run_components rc ON rc.id = e.component_id"
                " WHERE rc.run_id = CAST(:rid AS uuid) AND e.mode = 'original'"
            ),
            {"rid": run_id},
        ).scalar_one()
    assert count == 1


def test_submit_run_captures_policy_snapshot(client, project, sync_engine):
    policy_id = _add_policy(sync_engine, project, 1)
    created = client.post(
        "/api/v1/runs",
        json={
            "application_id": project["application_id"],
            "task_id": project["task_id"],
            "request_key": str(uuid.uuid4()),
            "platform": "android",
        },
        headers=CLIENT_HEADERS,
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    with sync_engine.connect() as conn:
        snapshot = conn.execute(
            text("SELECT config_snapshot FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar_one()
    gate_policy = (snapshot or {}).get("gate_policy")
    assert gate_policy and gate_policy["id"] == policy_id
    assert gate_policy["rules"], "快照必须带规则副本供审计"
