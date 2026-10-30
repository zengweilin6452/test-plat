"""运行收敛入库与导入通道的真实 PostgreSQL 回归（不启动设备 runner）。

守住三条本轮修复的语义：
1. finalize 到 completed 时，组件 / 用例 / 性能摘要必须一起入库，不能只有状态；
2. 有性能组件但没有门禁策略时，运行结论是 not_tested + gate_policy_missing，
   绝不因为"跑完了"就写成 passed；
3. 重复 finalize 幂等，不重复插入组件、指标或判定。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from tests._p3_common import CLIENT_HEADERS, TEST_DB, reset_db_engine, requires_db
from tests._p3_common import api_client as api_client  # noqa: PLW0127 - 夹具复用
from tests._p3_common import make_run as make_run  # noqa: PLW0127 - 夹具复用
from tests._p3_common import p3_project as project  # noqa: PLW0127 - 夹具复用
from tests._p3_common import sync_engine as sync_engine  # noqa: PLW0127 - 夹具复用

pytestmark = requires_db

JUNIT_PASSED = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="0" errors="0" skipped="0">
  <testcase classname="tests.test_smoke" name="test_a" time="0.1"/>
  <testcase classname="tests.test_smoke" name="test_b" time="0.2"/>
</testsuite></testsuites>
"""

JUNIT_FAILED = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0">
  <testcase classname="tests.test_smoke" name="test_a" time="0.1"/>
  <testcase classname="tests.test_smoke" name="test_b" time="0.2">
    <failure message="boom">AssertionError: boom</failure>
  </testcase>
</testsuite></testsuites>
"""

PERF_REPORT = {
    "runId": "vendor-run-1",
    "deviceProfile": "android-13|1080x2400|pixel-7-pro",
    "startedAt": "2026-10-25T10:00:00",
    "stoppedAt": "2026-10-25T10:01:00",
    "items": ["CPU"],
    "metricsSummary": {
        "cpu_process_pct": {"unit": "%", "median": 20.0, "sampleCount": 30},
    },
}

PERF_COMPONENT = {
    "kind": "performance",
    "state": "completed",
    "outcome": "not_tested",
    "reason_code": "gate_policy_missing",
}


def _write_artifacts(directory: Path, *, junit: str, report: dict | None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "junit.xml").write_text(junit, encoding="utf-8")
    if report is not None:
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8"
        )
    return directory


def _finalize(run_id: str, artifacts_dir: Path, extra_event: dict | None = None):
    from app import runtime

    reset_db_engine(TEST_DB)
    return asyncio.run(
        runtime.finalize_run(
            run_id=run_id,
            state="completed",
            outcome=None,
            artifacts_dir=artifacts_dir,
            release_lease_reason="pytest",
            extra_event=extra_event,
        )
    )


def _run_row(engine, run_id: str) -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("SELECT * FROM test_runs WHERE id = CAST(:id AS uuid)"), {"id": run_id}
            ).mappings().one()
        )


def _components(engine, run_id: str) -> list[dict]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT id, kind, state, outcome, reason_code FROM run_components "
                    "WHERE run_id = CAST(:id AS uuid) ORDER BY kind"
                ),
                {"id": run_id},
            ).mappings()
        ]


def _count(engine, sql: str, params: dict) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql), params).scalar_one())


# --------------------------------------------------------------------------- #
# finalize：结果入库 + 三态合并
# --------------------------------------------------------------------------- #
def test_completed_perf_run_records_metrics_and_gate_without_policy(
    project, make_run, sync_engine, tmp_path
):
    run_id = make_run(state="running", request_key="fin-perf-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_PASSED, report=PERF_REPORT)

    result = _finalize(run_id, artifacts, {"components": [PERF_COMPONENT], "cases": []})

    assert result.state == "completed"
    # 没有门禁策略：跑完了也不能算 passed，必须三态里的 not_tested 并带原因
    assert result.outcome == "not_tested"
    row = _run_row(sync_engine, run_id)
    assert row["state"] == "completed"
    assert row["outcome"] == "not_tested"
    assert row["reason_code"] == "gate_policy_missing"
    assert row["not_tested_reason"] == "gate_policy_missing"

    components = _components(sync_engine, run_id)
    assert [c["kind"] for c in components] == ["performance"]
    assert components[0]["outcome"] == "not_tested"
    assert components[0]["reason_code"] == "gate_policy_missing"

    metrics = _count(
        sync_engine,
        "SELECT count(*) FROM metric_summaries WHERE component_id = CAST(:cid AS uuid)",
        {"cid": str(components[0]["id"])},
    )
    assert metrics > 0, "report.json 的 metricsSummary 必须落成 metric_summaries 行"
    cpu = _count(
        sync_engine,
        "SELECT count(*) FROM metric_summaries WHERE component_id = CAST(:cid AS uuid) "
        "AND metric_key = 'cpu_process_pct' AND statistic = 'median' AND value = 20.0",
        {"cid": str(components[0]["id"])},
    )
    assert cpu == 1

    evaluations = _count(
        sync_engine,
        "SELECT count(*) FROM gate_evaluations WHERE component_id = CAST(:cid AS uuid) "
        "AND mode = 'original' AND verdict = 'not_tested' "
        "AND reason_code = 'gate_policy_missing'",
        {"cid": str(components[0]["id"])},
    )
    assert evaluations == 1, "首次判定必须落 original 行（缺策略也留证据）"

    artifacts_rows = _count(
        sync_engine,
        "SELECT count(*) FROM artifacts WHERE run_id = CAST(:id AS uuid)",
        {"id": run_id},
    )
    assert artifacts_rows >= 2

    with sync_engine.connect() as conn:
        finish = conn.execute(
            text(
                "SELECT payload FROM run_events WHERE run_id = CAST(:id AS uuid) "
                "AND event_type IN ('finish','error') ORDER BY sequence DESC LIMIT 1"
            ),
            {"id": run_id},
        ).scalar_one()
    assert finish["state"] == "completed"
    assert finish["outcome"] == "not_tested", "finish 事件必须反映门禁后的最终结论"


def test_corrupt_report_json_does_not_break_finalize(project, make_run, sync_engine, tmp_path):
    """report.json 半截写入曾是独立审查发现的 MEDIUM：finalize 不能因此 500，
    也不能把缺失指标伪装成 0。"""
    run_id = make_run(state="running", request_key="fin-corrupt-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_PASSED, report=None)
    (artifacts / "report.json").write_text('{"metricsSummary": {', encoding="utf-8")

    result = _finalize(run_id, artifacts, {"components": [PERF_COMPONENT], "cases": []})

    assert result.state == "completed"
    row = _run_row(sync_engine, run_id)
    assert row["state"] == "completed"
    assert row["outcome"] == "not_tested"
    assert row["reason_code"] == "gate_policy_missing"

    components = _components(sync_engine, run_id)
    assert [c["kind"] for c in components] == ["performance"]
    metrics = _count(
        sync_engine,
        "SELECT count(*) FROM metric_summaries WHERE component_id = CAST(:cid AS uuid)",
        {"cid": str(components[0]["id"])},
    )
    assert metrics == 0, "损坏的报告不能落成任何指标行（缺失由 missing_reason 表达）"


def test_finalize_is_idempotent_for_results(project, make_run, sync_engine, tmp_path):
    run_id = make_run(state="running", request_key="fin-idem-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_PASSED, report=PERF_REPORT)
    first = _finalize(run_id, artifacts, {"components": [PERF_COMPONENT], "cases": []})
    assert first.state == "completed"
    components = _components(sync_engine, run_id)
    metrics_before = _count(
        sync_engine,
        "SELECT count(*) FROM metric_summaries WHERE component_id = CAST(:cid AS uuid)",
        {"cid": str(components[0]["id"])},
    )

    second = _finalize(run_id, artifacts, {"components": [PERF_COMPONENT], "cases": []})
    assert second.already_terminal is True
    assert _count(
        sync_engine,
        "SELECT count(*) FROM run_components WHERE run_id = CAST(:id AS uuid)",
        {"id": run_id},
    ) == 1
    assert _count(
        sync_engine,
        "SELECT count(*) FROM metric_summaries WHERE component_id = CAST(:cid AS uuid)",
        {"cid": str(components[0]["id"])},
    ) == metrics_before
    assert _count(
        sync_engine,
        "SELECT count(*) FROM gate_evaluations WHERE component_id = CAST(:cid AS uuid)",
        {"cid": str(components[0]["id"])},
    ) == 1


def test_ui_run_records_cases_and_derives_outcome_from_junit(project, make_run, sync_engine, tmp_path):
    run_id = make_run(state="running", request_key="fin-ui-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_FAILED, report=None)
    cases = [
        {"case_key": "tests.test_smoke::test_a", "outcome": "passed", "duration_ms": 100},
        {
            "case_key": "tests.test_smoke::test_b",
            "outcome": "failed",
            "duration_ms": 200,
            "error_summary": "AssertionError: boom",
        },
    ]
    result = _finalize(
        run_id,
        artifacts,
        {"components": [{"kind": "ui", "state": "completed", "outcome": "failed"}], "cases": cases},
    )

    assert result.state == "completed"
    assert result.outcome == "failed"
    row = _run_row(sync_engine, run_id)
    assert row["outcome"] == "failed"
    assert row["not_tested_reason"] is None

    components = _components(sync_engine, run_id)
    assert [c["kind"] for c in components] == ["ui"]
    assert components[0]["outcome"] == "failed"
    stored = _count(
        sync_engine,
        "SELECT count(*) FROM case_results WHERE component_id = CAST(:cid AS uuid)",
        {"cid": str(components[0]["id"])},
    )
    assert stored == 2
    failed = _count(
        sync_engine,
        "SELECT count(*) FROM case_results WHERE component_id = CAST(:cid AS uuid) "
        "AND outcome = 'failed'",
        {"cid": str(components[0]["id"])},
    )
    assert failed == 1
    # 没有性能组件就不该凭空产生门禁判定
    assert _count(
        sync_engine,
        "SELECT count(*) FROM gate_evaluations WHERE component_id = CAST(:cid AS uuid)",
        {"cid": str(components[0]["id"])},
    ) == 0


def test_report_endpoint_returns_artifact_metrics(
    project, make_run, sync_engine, api_client, tmp_path, monkeypatch
):
    from app.config import settings

    # 报告端点按 settings.artifacts_dir 反查产物，这里把数据目录指到 tmp_path，
    # 避免在仓库 data/ 下留下测试产物。
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    run_id = make_run(state="running", request_key="fin-report-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(
        Path(settings.artifacts_dir) / run_id, junit=JUNIT_PASSED, report=PERF_REPORT
    )
    result = _finalize(run_id, artifacts, {"components": [PERF_COMPONENT], "cases": []})
    assert result.state == "completed"

    response = api_client.get(f"/api/v1/runs/{run_id}/report", headers=CLIENT_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    # 报告里的编号是持久展示编号（工单 09），精确身份仍是 UUID
    assert body["id"] == run_id
    detail = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert body["runId"] == detail["display_id"]
    assert body["runId"].startswith("RUN-")
    assert body["metricsSummary"]["cpu_process_pct"]["median"] == 20.0
    assert body["junit"]["tests"] == 2
    assert body["verdict"] == "not_tested"
    assert body["reason"] == "gate_policy_missing"


# --------------------------------------------------------------------------- #
# POST /runs/import：降级通道必须真的能落到 completed 并留下证据
# --------------------------------------------------------------------------- #
def _import_body(project: dict, source_dir: Path, **overrides) -> dict:
    body = {
        "application_id": project["application_id"],
        "task_id": project["task_id"],
        "request_key": "import-" + uuid.uuid4().hex[:8],
        "platform": "android",
        "source_dir": str(source_dir),
        "device": {"resource_id": project["resource_id"]},
    }
    body.update(overrides)
    return body


def test_import_rejects_missing_or_unknown_source_dir(api_client, project, tmp_path):
    response = api_client.post("/api/v1/runs/import", json={}, headers=CLIENT_HEADERS)
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "validation_error"

    response = api_client.post(
        "/api/v1/runs/import",
        json=_import_body(project, tmp_path / "not-here"),
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 400, response.text


def test_import_requires_a_device_because_completed_runs_are_bound(
    api_client, project, sync_engine, tmp_path
):
    """completed 行受 ck_test_runs_state_executing_needs_resource 约束，导入必须带设备。"""
    source = _write_artifacts(tmp_path / "vendor", junit=JUNIT_PASSED, report=PERF_REPORT)
    body = _import_body(project, source)
    body.pop("device")
    response = api_client.post("/api/v1/runs/import", json=body, headers=CLIENT_HEADERS)
    assert response.status_code == 400, response.text
    assert "device" in response.json()["message"]
    with sync_engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM test_runs WHERE request_key = :k"),
            {"k": body["request_key"]},
        ).scalar_one() == 0


def test_import_records_artifacts_metrics_and_gate(
    api_client, project, sync_engine, tmp_path, monkeypatch
):
    from app.config import settings

    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    source = _write_artifacts(tmp_path / "vendor-run", junit=JUNIT_PASSED, report=PERF_REPORT)

    response = api_client.post(
        "/api/v1/runs/import", json=_import_body(project, source), headers=CLIENT_HEADERS
    )
    assert response.status_code == 201, response.text
    body = response.json()
    run_id = body["id"]
    assert body["state"] == "completed"
    assert body["outcome"] == "not_tested", "没有策略时导入运行也不能算通过"
    assert body["artifacts"] >= 2

    row = _run_row(sync_engine, run_id)
    assert row["state"] == "completed"
    assert row["resource_id"] is not None
    assert row["started_at"] is not None
    assert row["ended_at"] is not None
    assert row["outcome"] == "not_tested"
    assert row["reason_code"] == "gate_policy_missing"

    components = _components(sync_engine, run_id)
    assert [c["kind"] for c in components] == ["performance"]
    assert _count(
        sync_engine,
        "SELECT count(*) FROM metric_summaries WHERE component_id = CAST(:cid AS uuid) "
        "AND metric_key = 'cpu_process_pct'",
        {"cid": str(components[0]["id"])},
    ) > 0

    # 产物必须搬进受管目录，否则下载与报告读取都会落空
    copied = data_dir / "artifacts" / run_id / "report.json"
    assert copied.is_file(), "导入产物应复制到 settings.artifacts_dir/<run_id>"
    with sync_engine.connect() as conn:
        storage_keys = conn.execute(
            text("SELECT storage_key FROM artifacts WHERE run_id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalars().all()
    assert all(key.startswith(f"{run_id}/") for key in storage_keys), storage_keys

    report = api_client.get(f"/api/v1/runs/{run_id}/report", headers=CLIENT_HEADERS)
    assert report.status_code == 200, report.text
    payload = report.json()
    assert payload["mode"] == "imported"
    assert payload["metricsSummary"]["cpu_process_pct"]["median"] == 20.0
    assert payload["verdict"] == "not_tested"

    # 同一 request_key 再导入一次：返回既有运行，不重复登记产物
    again = api_client.post(
        "/api/v1/runs/import",
        json=_import_body(project, source, request_key=_request_key_of(sync_engine, run_id)),
        headers=CLIENT_HEADERS,
    )
    assert again.status_code == 200, again.text
    assert again.json()["id"] == run_id
    assert again.json()["duplicate"] is True
    assert _count(
        sync_engine,
        "SELECT count(*) FROM artifacts WHERE run_id = CAST(:id AS uuid)",
        {"id": run_id},
    ) == len(storage_keys)


def _request_key_of(engine, run_id: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT request_key FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar_one()

