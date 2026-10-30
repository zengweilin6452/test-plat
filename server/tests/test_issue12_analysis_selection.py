"""工单 12：性能分析 original 与 reanalysis 选择（真实 PG，定向测试）。

覆盖的验收点（spec §9.4、AC-PERF-01/02/03、AC-CONTRACT-04）：

- 分析默认展示原始判定；只有显式 evaluation_id 才选某条判定（试算）；
- 缺 original 时不自动兜底 reanalysis，明确标记 original_missing；
- 真实指标、样本数与缺失原因正确，不补零；
- 缺策略（gate_policy_missing）与缺基线（baseline_missing）原因可区分。
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


def _setup_component_metrics(engine, project: dict, run_id: str) -> str:
    """一个 performance 组件 + 一条真实指标 + 一条设备不支持的缺失指标。"""
    component_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO run_components (id, project_id, run_id, kind, adapter_key,"
                "                            adapter_version, state, outcome, summary)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         'performance', 'mobile_perf', '1.0', 'completed', 'passed',"
                "         CAST(:summary AS jsonb))"
            ),
            {
                "id": component_id,
                "pid": project["project_id"],
                "rid": run_id,
                "summary": json.dumps({}),
            },
        )
        for key, unit, value, samples, reason in (
            ("mem_pss_mb", "MB", 150.0, 180, None),
            ("gpu_util_pct", "%", None, 0, "device_unsupported"),
        ):
            conn.execute(
                text(
                    "INSERT INTO metric_summaries (id, project_id, component_id, metric_key,"
                    "                              metric_version, unit, scope, window_key,"
                    "                              statistic, sample_count, value, missing_reason)"
                    " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:cid AS uuid),"
                    "         :key, '1.0', :unit, 'component', :win, 'median',"
                    "         :samples, :value, :reason)"
                ),
                {
                    "pid": project["project_id"],
                    "cid": component_id,
                    "key": key,
                    "unit": unit,
                    "win": f"{run_id}:{key}"[:40],
                    "samples": samples,
                    "value": value,
                    "reason": reason,
                },
            )
    return component_id


def _add_evaluation(
    engine, project: dict, component_id: str, *, mode: str, verdict: str, reason: str | None
) -> str:
    evaluation_id = str(uuid.uuid4())
    policy_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO gate_policies (id, project_id, application_id, name, version, rules)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         :name, 1, '{}'::jsonb)"
            ),
            {"id": policy_id, "pid": project["project_id"], "aid": project["application_id"],
             "name": f"policy-{uuid.uuid4().hex[:8]}"},
        )
        conn.execute(
            text(
                "INSERT INTO gate_evaluations (id, project_id, component_id, policy_id,"
                "                              mode, request_key, verdict, reason_code, checks)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:cid AS uuid),"
                "         CAST(:pol AS uuid), :mode, :key, :verdict, :reason, '[]'::jsonb)"
            ),
            {
                "id": evaluation_id,
                "pid": project["project_id"],
                "cid": component_id,
                "pol": policy_id,
                "mode": mode,
                "key": "eval-" + uuid.uuid4().hex,
                "verdict": verdict,
                "reason": reason,
            },
        )
    return evaluation_id


def _analysis(client, **params) -> dict:
    response = client.get("/api/v1/analyses", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_analysis_defaults_to_original_verdict(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    component_id = _setup_component_metrics(sync_engine, project, run_id)
    original_id = _add_evaluation(
        sync_engine, project, component_id, mode="original", verdict="passed", reason=None
    )
    reanalysis_id = _add_evaluation(
        sync_engine, project, component_id, mode="reanalysis", verdict="failed",
        reason="threshold_failed",
    )

    body = _analysis(client, run_id=run_id)
    # 默认原始判定：最新试算不得悄悄顶掉它（AC-CONTRACT-04）
    assert body["verdict"] == "passed"
    assert body["mode"] == "original"
    assert body["selected_evaluation_id"] == original_id
    assert body["original_missing"] is False
    assert {item["mode"] for item in body["evaluations"]} == {"original", "reanalysis"}

    # 显式 evaluation_id 才切换到试算
    picked = _analysis(client, run_id=run_id, evaluation_id=reanalysis_id)
    assert picked["verdict"] == "failed"
    assert picked["mode"] == "reanalysis"

    unknown = client.get("/api/v1/analyses", params={"run_id": run_id, "evaluation_id": str(uuid.uuid4())})
    assert unknown.status_code == 404, unknown.text


def test_analysis_without_original_does_not_fall_back(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    component_id = _setup_component_metrics(sync_engine, project, run_id)
    _add_evaluation(
        sync_engine, project, component_id, mode="reanalysis", verdict="failed",
        reason="threshold_failed",
    )

    body = _analysis(client, run_id=run_id)
    assert body["verdict"] is None, "缺 original 不得兜底到 reanalysis"
    assert body["mode"] is None
    assert body["original_missing"] is True


def test_analysis_reports_real_metrics_without_zero_fill(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    _setup_component_metrics(sync_engine, project, run_id)

    body = _analysis(client, run_id=run_id)
    by_key = {item["metric_key"]: item for item in body["metrics"]}
    assert by_key["mem_pss_mb"]["value"] == 150.0
    assert by_key["mem_pss_mb"]["sample_count"] == 180
    assert by_key["gpu_util_pct"]["value"] is None, "缺失指标绝不补 0"
    assert by_key["gpu_util_pct"]["missing_reason"] == "device_unsupported"
    assert by_key["gpu_util_pct"]["supported"] is False


def test_missing_policy_and_missing_baseline_reasons_are_distinct(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    _setup_component_metrics(sync_engine, project, run_id)

    # 无策略 → gate_policy_missing
    no_policy = client.post(
        f"/api/v1/runs/{run_id}/gate-evaluations",
        json={"request_key": "eval-nopolicy-" + uuid.uuid4().hex},
    )
    assert no_policy.status_code in (200, 201), no_policy.text
    assert no_policy.json()["verdict"] == "not_tested"
    assert no_policy.json()["reason_code"] == "gate_policy_missing"

    # 有策略、无基线 → baseline_missing（不再与缺策略混为同一个原因）
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO gate_policies (id, project_id, application_id, name, version, rules)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         'real-policy', 1, '{\"mem_pss_mb\": [\"lt\", 240]}'::jsonb)"
            ),
            {"pid": project["project_id"], "aid": project["application_id"]},
        )
    run_id2 = make_run(state="completed", request_key=str(uuid.uuid4()))
    _setup_component_metrics(sync_engine, project, run_id2)
    no_baseline = client.post(
        f"/api/v1/runs/{run_id2}/gate-evaluations",
        json={"request_key": "eval-nobaseline-" + uuid.uuid4().hex},
    )
    assert no_baseline.status_code in (200, 201), no_baseline.text
    assert no_baseline.json()["verdict"] == "not_tested"
    assert no_baseline.json()["reason_code"] == "baseline_missing", no_baseline.text
