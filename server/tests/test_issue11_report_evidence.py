"""工单 11：报告详情、证据与导出（真实 PG，定向测试）。

覆盖的验收点（spec §9.3、AC-REP-03、AC-REP-04）：

- 报告追溯修订、构建、运行时档案；缺失字段明确为 null，不用设备 serial 冒充档案；
- 证据 available 可下载，expired/missing 不提供假下载入口；storage_key 不出报告；
- 导出与报告快照同一份内容，稳定文件名，不含凭据或宿主路径；
- 跑完改策略/档案不改写历史报告；重跑创建新运行并保留 parent_run_id 关联。
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


def _report(client, run_id: str) -> dict:
    response = client.get(f"/api/v1/runs/{run_id}/report")
    assert response.status_code == 200, response.text
    return response.json()


def _add_artifact(engine, project: dict, run_id: str, availability: str) -> str:
    artifact_id = str(uuid.uuid4())
    storage_key = "host-only-" + availability
    if availability == "available":
        # 工单 05 起 availability 按磁盘复核：available 行必须有真实文件，
        # 否则读的时候降级为 missing（这里写进受管产物目录）。
        from pathlib import Path

        from app.config import settings

        storage_key = f"{run_id}/evidence/available.log"
        path = Path(settings.artifacts_dir) / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("available evidence", encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO artifacts (id, project_id, run_id, kind, logical_key,"
                "                       storage_key, mime_type, byte_size, sha256, availability)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid), 'log',"
                "         :key, :storage, 'text/plain', 12, repeat('a', 64), :avail)"
            ),
            {
                "id": artifact_id,
                "pid": project["project_id"],
                "rid": run_id,
                "key": "evidence/" + availability + ".log",
                "storage": storage_key,
                "avail": availability,
            },
        )
    return artifact_id


# --------------------------------------------------------------------------- #
# 追溯原输入（AC-REP-04）
# --------------------------------------------------------------------------- #


def test_report_traces_revision_build_and_profile(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    body = _report(client, run_id)

    assert body["revision"]["id"] == project["revision_id"]
    assert body["build"]["version"] == "1.0.0"
    assert body["build"]["build_key"]
    assert body["environmentId"] == project["environment_id"]
    assert body["resourceProfile"]["fingerprint"], "档案必须带不可变指纹"
    assert body["resourceProfile"]["spec"] == {}
    assert body["deviceProfile"] and body["deviceProfile"] != body["resourceName"], (
        "deviceProfile 是档案名，不能拿设备 serial 冒充"
    )


def test_report_marks_missing_fields_without_faking(client, project, make_run, sync_engine):
    errored = make_run(state="errored", request_key=str(uuid.uuid4()))
    # 夹具对终态行统一绑了资源；这条用例专门验证"没有档案"的呈现，拆掉绑定
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET resource_id = NULL, profile_id = NULL, started_at = NULL"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"id": errored},
        )
    body = _report(client, errored)

    assert body["resourceProfile"] is None, "没有档案就明说，不得用 serial 顶替"
    assert body["deviceProfile"] is None
    assert body["resourceId"] is None
    assert body["revision"]["id"] == project["revision_id"]
    assert body["evidence"] == []


def test_policy_change_after_run_does_not_rewrite_original_verdict(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    component_id = str(uuid.uuid4())
    policy_id = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO run_components (id, project_id, run_id, kind, adapter_key,"
                "                            adapter_version, state, outcome, summary)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid), 'ui',"
                "         'pytest-ui', '1', 'completed', 'passed', '{}'::jsonb)"
            ),
            {"id": component_id, "pid": project["project_id"], "rid": run_id},
        )
        conn.execute(
            text(
                "INSERT INTO gate_policies (id, project_id, application_id, name, version, rules)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         'pytest-policy', 1, '{\"mem_pss_mb\": [\"lt\", 240]}'::jsonb)"
            ),
            {"id": policy_id, "pid": project["project_id"], "aid": project["application_id"]},
        )
        conn.execute(
            text(
                "INSERT INTO gate_evaluations (id, project_id, component_id, policy_id,"
                "                              mode, request_key, verdict, reason_code, checks)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:cid AS uuid),"
                "         CAST(:pol AS uuid), 'original', :key, 'failed', 'threshold_failed',"
                "         '[{\"metric\":\"mem_pss_mb\"}]'::jsonb)"
            ),
            {"pid": project["project_id"], "cid": component_id, "pol": policy_id, "key": "ge-" + run_id},
        )

    before = _report(client, run_id)
    assert before["gateEvaluations"][0]["verdict"] == "failed"
    assert before["gateEvaluations"][0]["mode"] == "original"

    # 跑完改策略：历史报告的原始判定一行不改
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE gate_policies SET rules = '{\"mem_pss_mb\": [\"lt\", 1]}'::jsonb"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"id": policy_id},
        )
    after = _report(client, run_id)
    assert after["gateEvaluations"] == before["gateEvaluations"]


# --------------------------------------------------------------------------- #
# 证据可用性与导出（AC-REP-03）
# --------------------------------------------------------------------------- #


def test_evidence_availability_gates_download_entry(
    client, project, make_run, sync_engine, tmp_path, monkeypatch
):
    from app.config import settings

    # 证据可用性按 settings.artifacts_dir 复核，产物写进 tmp，不落到仓库 data/
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    available_id = _add_artifact(sync_engine, project, run_id, "available")
    _add_artifact(sync_engine, project, run_id, "missing")
    _add_artifact(sync_engine, project, run_id, "expired")

    body = _report(client, run_id)
    by_key = {item["logical_key"]: item for item in body["evidence"]}
    assert by_key["evidence/available.log"]["download_url"]
    assert by_key["evidence/missing.log"]["download_url"] is None
    assert by_key["evidence/expired.log"]["download_url"] is None

    # 下载端点对 missing/expired 拒绝，不提供假入口
    missing_download = client.get(f"/api/v1/runs/{run_id}/artifacts/{by_key['evidence/missing.log']['id']}/download")
    assert missing_download.status_code == 404, missing_download.text

    # storage_key（宿主存储路径）不出报告
    assert "host-only-" not in json.dumps(body, ensure_ascii=False)


def test_export_matches_report_snapshot(
    client, project, make_run, sync_engine, tmp_path, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    _add_artifact(sync_engine, project, run_id, "available")
    _report(client, run_id)

    report = _report(client, run_id)
    response = client.get(f"/api/v1/runs/{run_id}/report/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert 'filename="TestDock-' in response.headers["content-disposition"]
    assert report["runId"] in response.headers["content-disposition"]

    exported = json.loads(response.text)
    exported.pop("vendorReports", None), exported.pop("junit", None)
    report.pop("vendorReports"), report.pop("junit")
    exported.pop("evaluatedAt"), report.pop("evaluatedAt")
    assert exported == report, "导出必须与报告快照一致"


def test_rerun_creates_new_run_linked_to_original(client, project, make_run, sync_engine):
    original = make_run(state="completed", request_key=str(uuid.uuid4()))
    original_row = dict(
        sync_engine.connect()
        .execute(
            text("SELECT * FROM test_runs WHERE id = CAST(:id AS uuid)"), {"id": original}
        )
        .mappings()
        .one()
    )

    response = client.post(
        "/api/v1/runs",
        json={
            "application_id": project["application_id"],
            "task_id": project["task_id"],
            "revision_id": project["revision_id"],
            "request_key": str(uuid.uuid4()),
            "platform": "android",
            "parent_run_id": original,
        },
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 201, response.text
    rerun_id = response.json()["id"]
    assert rerun_id != original

    with sync_engine.connect() as conn:
        parent = conn.execute(
            text("SELECT parent_run_id FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": rerun_id},
        ).scalar_one()
    assert str(parent) == original

    # 原记录一行不改：状态、request_key、结论都保持
    with sync_engine.connect() as conn:
        row = dict(
            conn.execute(
                text("SELECT * FROM test_runs WHERE id = CAST(:id AS uuid)"),
                {"id": original},
            )
            .mappings()
            .one()
        )
    assert row == original_row
