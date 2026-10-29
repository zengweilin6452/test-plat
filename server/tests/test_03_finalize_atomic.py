"""工单 03：finalizing 原子收敛（真实 PostgreSQL，不启动设备 runner）。

守住 §9.4 / AC-CONTRACT-05 的可运行事实：
1. 原始判定、组件结论、整体终态与 finish 事件在同一事务提交；
2. 判定失败 -> 整个事务回滚，不出现 completed、也不留下半套组件/产物/original；
3. 重试后恰好一条 original；并发 finalize 只产生一个终态；
4. performance/joint 的 completed 必须有性能组件与 original，否则 errored；
5. errored/cancelled 保留已上报的组件与用例事实，整体 outcome 为空。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from tests._p3_common import TEST_DB, reset_db_engine, requires_db
from tests._p3_common import make_run as make_run  # noqa: PLW0127 - 夹具复用
from tests._p3_common import p3_project as project  # noqa: PLW0127 - 夹具复用
from tests._p3_common import sync_engine as sync_engine  # noqa: PLW0127 - 夹具复用

pytestmark = requires_db

JUNIT_PASSED = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites><testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="tests.test_smoke" name="test_a" time="0.1"/>
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


def _set_test_type(engine, project_row: dict, test_type: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE task_revisions SET test_type = :t WHERE id = CAST(:id AS uuid)"
            ),
            {"t": test_type, "id": project_row["revision_id"]},
        )


def _finalize(run_id: str, artifacts_dir: Path, *, state: str = "completed",
              extra_event: dict | None = None, outcome: str | None = None):
    from app import runtime

    reset_db_engine(TEST_DB)
    return asyncio.run(
        runtime.finalize_run(
            run_id=run_id,
            state=state,
            outcome=outcome,
            artifacts_dir=artifacts_dir,
            release_lease_reason="pytest",
            extra_event=extra_event,
        )
    )


def _row(engine, run_id: str) -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("SELECT * FROM test_runs WHERE id = CAST(:id AS uuid)"),
                {"id": run_id},
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


def _original_count(engine, run_id: str) -> int:
    return _count(
        engine,
        "SELECT count(*) FROM gate_evaluations e "
        "JOIN run_components rc ON rc.id = e.component_id "
        "WHERE rc.run_id = CAST(:id AS uuid) AND e.mode = 'original'",
        {"id": run_id},
    )


# --------------------------------------------------------------------------- #
# 原子收敛
# --------------------------------------------------------------------------- #
def test_completed_perf_run_converges_original_component_state_and_event(
    project, make_run, sync_engine, tmp_path
):
    _set_test_type(sync_engine, project, "performance")
    run_id = make_run(state="running", request_key="atomic-ok-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_PASSED, report=PERF_REPORT)

    result = _finalize(
        run_id,
        artifacts,
        extra_event={"components": [PERF_COMPONENT], "cases": []},
    )

    assert result.state == "completed"
    assert result.outcome == "not_tested"
    row = _row(sync_engine, run_id)
    assert row["state"] == "completed"
    assert row["outcome"] == "not_tested"
    assert row["reason_code"] == "gate_policy_missing"

    components = _components(sync_engine, run_id)
    assert [c["kind"] for c in components] == ["performance"]
    assert components[0]["outcome"] == "not_tested"
    assert components[0]["reason_code"] == "gate_policy_missing"
    assert _original_count(sync_engine, run_id) == 1

    with sync_engine.connect() as conn:
        finish = conn.execute(
            text(
                "SELECT payload FROM run_events WHERE run_id = CAST(:id AS uuid) "
                "AND event_type IN ('finish','error') ORDER BY sequence DESC LIMIT 1"
            ),
            {"id": run_id},
        ).scalar_one()
    assert finish["state"] == "completed"
    assert finish["outcome"] == "not_tested"
    assert finish["artifact_count"] >= 2


def test_gate_failure_rolls_back_everything_then_retry_succeeds(
    project, make_run, sync_engine, tmp_path, monkeypatch
):
    _set_test_type(sync_engine, project, "performance")
    run_id = make_run(state="running", request_key="atomic-fail-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_PASSED, report=PERF_REPORT)

    from app.routers import analyses

    original = analyses.evaluate_run_original

    async def boom(*args, **kwargs):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(analyses, "evaluate_run_original", boom)
    with pytest.raises(RuntimeError, match="gate exploded"):
        _finalize(
            run_id,
            artifacts,
            extra_event={"components": [PERF_COMPONENT], "cases": []},
        )

    # 整个事务回滚：没有 completed、组件、产物、original、finish 事件
    row = _row(sync_engine, run_id)
    assert row["state"] == "running"
    assert row["outcome"] is None
    assert _components(sync_engine, run_id) == []
    assert _original_count(sync_engine, run_id) == 0
    assert _count(
        sync_engine,
        "SELECT count(*) FROM artifacts WHERE run_id = CAST(:id AS uuid)",
        {"id": run_id},
    ) == 0
    assert _count(
        sync_engine,
        "SELECT count(*) FROM run_events WHERE run_id = CAST(:id AS uuid) "
        "AND event_type IN ('finish','error')",
        {"id": run_id},
    ) == 0

    # 重试成功：恰好一条 original，不重复组件
    monkeypatch.setattr(analyses, "evaluate_run_original", original)
    result = _finalize(
        run_id,
        artifacts,
        extra_event={"components": [PERF_COMPONENT], "cases": []},
    )
    assert result.state == "completed"
    assert len(_components(sync_engine, run_id)) == 1
    assert _original_count(sync_engine, run_id) == 1


def test_performance_run_without_performance_component_is_errored(
    project, make_run, sync_engine, tmp_path
):
    _set_test_type(sync_engine, project, "performance")
    run_id = make_run(state="running", request_key="atomic-noperf-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_PASSED, report=None)

    result = _finalize(
        run_id,
        artifacts,
        extra_event={
            "components": [{"kind": "ui", "state": "completed", "outcome": "passed"}],
            "cases": [],
        },
    )

    assert result.state == "errored"
    assert result.outcome is None
    row = _row(sync_engine, run_id)
    assert row["state"] == "errored"
    assert row["outcome"] is None
    assert _original_count(sync_engine, run_id) == 0
    # 不能出现 completed 缺 original 的新性能运行
    assert row["state"] != "completed"


def test_concurrent_finalize_creates_single_original(
    project, make_run, sync_engine, tmp_path
):
    _set_test_type(sync_engine, project, "performance")
    run_id = make_run(state="running", request_key="atomic-conc-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_PASSED, report=PERF_REPORT)

    from app import runtime

    reset_db_engine(TEST_DB)

    async def both():
        return await asyncio.gather(
            runtime.finalize_run(
                run_id=run_id,
                state="completed",
                artifacts_dir=artifacts,
                release_lease_reason="pytest",
                extra_event={"components": [PERF_COMPONENT], "cases": []},
            ),
            runtime.finalize_run(
                run_id=run_id,
                state="completed",
                artifacts_dir=artifacts,
                release_lease_reason="pytest",
                extra_event={"components": [PERF_COMPONENT], "cases": []},
            ),
        )

    results = asyncio.run(both())
    states = sorted(result.state for result in results)
    assert states == ["completed", "completed"]
    assert sum(1 for result in results if result.already_terminal) == 1
    assert _original_count(sync_engine, run_id) == 1
    assert len(_components(sync_engine, run_id)) == 1


def test_errored_run_preserves_component_and_case_facts(
    project, make_run, sync_engine, tmp_path
):
    _set_test_type(sync_engine, project, "ui")
    run_id = make_run(state="running", request_key="atomic-err-" + uuid.uuid4().hex[:8])
    artifacts = _write_artifacts(tmp_path, junit=JUNIT_PASSED, report=None)
    cases = [
        {"case_key": "tests.test_smoke::test_a", "outcome": "passed", "duration_ms": 100}
    ]

    result = _finalize(
        run_id,
        artifacts,
        state="errored",
        extra_event={
            "components": [
                {"kind": "ui", "state": "completed", "outcome": "failed"},
                {"kind": "performance", "state": "errored", "reason_code": "collector_crashed"},
            ],
            "cases": cases,
        },
    )

    assert result.state == "errored"
    assert result.outcome is None
    row = _row(sync_engine, run_id)
    assert row["state"] == "errored"
    assert row["outcome"] is None

    components = _components(sync_engine, run_id)
    by_kind = {c["kind"]: c for c in components}
    assert by_kind["ui"]["state"] == "completed"
    assert by_kind["ui"]["outcome"] == "failed"
    assert by_kind["performance"]["state"] == "errored"
    assert by_kind["performance"]["outcome"] is None
    assert by_kind["performance"]["reason_code"] == "collector_crashed"
    assert _count(
        sync_engine,
        "SELECT count(*) FROM case_results WHERE component_id = CAST(:cid AS uuid)",
        {"cid": str(by_kind["ui"]["id"])},
    ) == 1
    assert _original_count(sync_engine, run_id) == 0
