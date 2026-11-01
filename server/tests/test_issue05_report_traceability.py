"""工单 05：报告可追溯套件版本与固定代码副本（真实 PG，定向测试）。

覆盖的验收点（spec 故事 17、AC-REP-01/02/03）：

- 报告包含构建、修订、套件版本、代码副本树摘要、资源档案与证据；
- 固定副本缺失/损坏导致未执行的运行不伪造套件结论；
- 证据 available/missing/expired 分别呈现，仅 available 有下载入口；
- 失败运行可定位失败截图/日志/断言，缺失说明原因；
- 导出与页面同源；历史报告不被重新发现/改来源改写。

所有断言只走 HTTP 公共接口（GET /report、/report/export、/artifacts、
/artifacts/{id}/download），不读报告内部实现。
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import runtime
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


# --------------------------------------------------------------------------- #
# 套件版本 + 固定副本摘要（AC-REP-01）
# --------------------------------------------------------------------------- #


def test_report_includes_suite_version_and_code_copy(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    body = _report(client, run_id)

    with sync_engine.connect() as conn:
        manifest = conn.execute(
            text("SELECT manifest FROM suite_versions WHERE id = CAST(:id AS uuid)"),
            {"id": project["suite_version_id"]},
        ).scalar_one()
    code_copy = manifest["code_copy"]

    assert body["revision"]["suite_version_id"] == project["suite_version_id"]
    suite = body["suite"]
    assert suite["id"] == project["suite_version_id"]
    assert suite["version"] == 1
    assert suite["source_ref"] == "local"
    assert suite["source_commit"] == "local"
    # 树摘要直接来自不可变的 suite_versions.manifest，不是现算来源目录
    assert suite["code_copy"]["tree_sha256"] == code_copy["tree_sha256"]
    assert suite["code_copy"]["file_count"] == code_copy["file_count"]
    assert suite["code_copy"]["root_rel"] == code_copy["root_rel"]


def test_report_marks_absent_suite_and_code_copy_as_null(
    client, project, make_run, sync_engine
):
    """旧修订没绑套件 / 旧版本没有副本摘要：报告明说 null，不拿别的版本冒充。"""
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    draft_revision = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        # readiness='draft' 允许空 build / 空 suite（0001 的 CHECK 语义）
        conn.execute(
            text(
                "INSERT INTO task_revisions (id, project_id, application_id, task_id,"
                "                           revision, environment_id, build_id,"
                "                           suite_version_id, test_type, readiness, config,"
                "                           created_by)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         CAST(:tid AS uuid), 2, CAST(:eid AS uuid), NULL, NULL,"
                "         'ui', 'draft', '{}'::jsonb, 'pytest')"
            ),
            {
                "id": draft_revision,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "tid": project["task_id"],
                "eid": project["environment_id"],
            },
        )
        conn.execute(
            text("UPDATE test_runs SET revision_id = CAST(:rid AS uuid) WHERE id = CAST(:id AS uuid)"),
            {"rid": draft_revision, "id": run_id},
        )

    body = _report(client, run_id)
    assert body["revision"]["suite_version_id"] is None
    assert body["suite"] is None
    assert body["build"] is None


def test_suite_without_code_copy_manifest_reports_null_copy(
    client, project, make_run, sync_engine
):
    """套件版本存在但 manifest 没有 code_copy（旧版本）：code_copy 为 null。"""
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    legacy_version = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO suite_versions (id, project_id, application_id, suite_id,"
                "                            version, source_ref, source_commit, manifest)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         CAST(:sid AS uuid), 2, 'old-ref', 'old-commit',"
                "         '{\"schema_version\": 1, \"case_count\": 1}'::jsonb)"
            ),
            {
                "id": legacy_version,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "sid": project["suite_id"],
            },
        )
        conn.execute(
            text(
                "UPDATE task_revisions SET suite_version_id = CAST(:svid AS uuid)"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"svid": legacy_version, "id": project["revision_id"]},
        )

    body = _report(client, run_id)
    assert body["suite"]["id"] == legacy_version
    assert body["suite"]["version"] == 2
    assert body["suite"]["source_ref"] == "old-ref"
    assert body["suite"]["code_copy"] is None


# --------------------------------------------------------------------------- #
# 证据三态与下载门控（AC-REP-03）
# --------------------------------------------------------------------------- #


def _insert_artifact(
    engine,
    project: dict,
    run_id: str,
    *,
    logical_key: str,
    storage_key: str,
    availability: str = "available",
    expires_at_sql: str | None = None,
    kind: str = "log",
) -> str:
    artifact_id = str(uuid.uuid4())
    expiry = f"CAST('{expires_at_sql}' AS timestamptz)" if expires_at_sql else "NULL"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO artifacts (id, project_id, run_id, kind, logical_key,"
                "                       storage_key, mime_type, byte_size, sha256,"
                "                       availability, expires_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         :kind, :key, :storage, 'text/plain', 12, repeat('a', 64),"
                f"         :avail, {expiry})"
            ),
            {
                "id": artifact_id,
                "pid": project["project_id"],
                "rid": run_id,
                "kind": kind,
                "key": logical_key,
                "storage": storage_key,
                "avail": availability,
            },
        )
    return artifact_id


def test_evidence_row_without_file_is_missing_not_fake_download(
    client, project, make_run, sync_engine
):
    """行写着 available 但磁盘文件已不在：报告必须降级为 missing，且不给下载入口。"""
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    artifact_id = _insert_artifact(
        sync_engine,
        project,
        run_id,
        logical_key="evidence/cleaned.log",
        storage_key=f"{run_id}/evidence/cleaned.log",
    )

    body = _report(client, run_id)
    item = next(e for e in body["evidence"] if e["id"] == artifact_id)
    assert item["availability"] == "missing"
    assert item["unavailable_reason"] == "file_missing"
    assert item["download_url"] is None

    listing = client.get(f"/api/v1/runs/{run_id}/artifacts").json()
    listed = next(e for e in listing["items"] if e["id"] == artifact_id)
    assert listed["availability"] == "missing"
    assert listed["download_url"] is None, "缺失证据不能给下载入口"

    assert client.get(f"/api/v1/runs/{run_id}/artifacts/{artifact_id}/download").status_code == 404


def test_evidence_past_retention_is_expired_with_reason(
    client, project, make_run, sync_engine
):
    """保留期已到：报告与清单都呈现 expired + 原因，且没有下载入口。"""
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    artifact_id = _insert_artifact(
        sync_engine,
        project,
        run_id,
        logical_key="evidence/old.log",
        storage_key=f"{run_id}/evidence/old.log",
        expires_at_sql="2000-01-01T00:00:00Z",
    )

    body = _report(client, run_id)
    item = next(e for e in body["evidence"] if e["id"] == artifact_id)
    assert item["availability"] == "expired"
    assert item["unavailable_reason"] == "retention_expired"
    assert item["download_url"] is None

    listed = next(
        e
        for e in client.get(f"/api/v1/runs/{run_id}/artifacts").json()["items"]
        if e["id"] == artifact_id
    )
    assert listed["availability"] == "expired"
    assert listed["unavailable_reason"] == "retention_expired"
    assert listed["download_url"] is None
    assert client.get(f"/api/v1/runs/{run_id}/artifacts/{artifact_id}/download").status_code == 404


def test_registration_records_retention_expiry(
    client, project, make_run, tmp_path, monkeypatch
):
    """配置保留期后，正常登记就要写 expires_at——否则 expired 永远不可达。"""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "artifact_retention_days", 7)
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))
    directory = Path(settings.artifacts_dir) / run_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run.log").write_text("hello", encoding="utf-8")

    asyncio.run(
        runtime.finalize_run(
            run_id=run_id,
            state="completed",
            outcome=None,
            artifacts_dir=directory,
            release_lease_reason="pytest",
        )
    )

    listed = client.get(f"/api/v1/runs/{run_id}/artifacts").json()["items"]
    logs = [item for item in listed if item["logical_key"] == "run.log"]
    assert logs, listed
    assert logs[0]["availability"] == "available"
    assert logs[0]["expires_at"], "配置保留期后登记必须写 expires_at"
    assert logs[0]["download_url"]


# --------------------------------------------------------------------------- #
# 失败运行：截图 / 日志 / 断言（AC-REP-04）
# --------------------------------------------------------------------------- #

JUNIT_FAILED = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0">
  <testcase classname="tests.test_login" name="test_ok" time="0.1"/>
  <testcase classname="tests.test_login" name="test_checkout" time="0.2">
    <failure message="AssertionError: total mismatch">assert 1 == 2</failure>
  </testcase>
</testsuite></testsuites>
"""


def test_failed_run_report_locates_screenshot_log_and_assertions(
    client, project, make_run, tmp_path, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))
    directory = Path(settings.artifacts_dir) / run_id
    evidence_dir = directory / "evidence"
    evidence_dir.mkdir(parents=True)
    (directory / "junit.xml").write_text(JUNIT_FAILED, encoding="utf-8")
    png = evidence_dir / "failure-frame.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (evidence_dir / "run.log").write_text("step1\nstep2\n", encoding="utf-8")

    asyncio.run(
        runtime.finalize_run(
            run_id=run_id,
            state="completed",
            outcome=None,
            artifacts_dir=directory,
            release_lease_reason="pytest",
        )
    )

    body = _report(client, run_id)
    assert body["verdict"] == "failed"
    assert body["junit"]["failed"] == 1, "断言失败信息必须能在报告里定位"

    evidence = {item["logical_key"]: item for item in body["evidence"]}
    shot = evidence["evidence/failure-frame.png"]
    log = evidence["evidence/run.log"]
    assert shot["kind"] == "screenshot"
    assert shot["availability"] == "available"
    assert shot["download_url"]
    assert log["kind"] == "log"
    assert log["download_url"]

    download = client.get(f"/api/v1/runs/{run_id}/artifacts/{shot['id']}/download")
    assert download.status_code == 200
    assert download.content == b"\x89PNG\r\n\x1a\nfake"

    # 断言信息：报告给计数，junit.xml 作为证据可下载（含失败用例与消息）
    junit_artifact = evidence["junit.xml"]
    assert junit_artifact["download_url"]
    junit_download = client.get(
        f"/api/v1/runs/{run_id}/artifacts/{junit_artifact['id']}/download"
    )
    assert junit_download.status_code == 200
    assert "AssertionError: total mismatch" in junit_download.text

    # 产物目录被清理（保留期到期/清扫）后：报告如实降级为 missing 并给原因
    png.unlink()
    after = _report(client, run_id)
    gone = next(e for e in after["evidence"] if e["id"] == shot["id"])
    assert gone["availability"] == "missing"
    assert gone["unavailable_reason"] == "file_missing"
    assert gone["download_url"] is None


# --------------------------------------------------------------------------- #
# 报告只读：重新发现 / 改来源不改写历史（AC-REP-05）
# --------------------------------------------------------------------------- #


def test_rediscovery_new_suite_version_does_not_rewrite_history(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    before = _report(client, run_id)
    assert before["suite"]["code_copy"]["tree_sha256"]

    # 重新发现 = 新增 suite_version 行（旧行不可变）；来源目录内容变化体现在新行
    new_version = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO suite_versions (id, project_id, application_id, suite_id,"
                "                            version, source_ref, source_commit, manifest)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         CAST(:sid AS uuid), 9, 'main', 'newsha', CAST(:manifest AS jsonb))"
            ),
            {
                "id": new_version,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "sid": project["suite_id"],
                "manifest": json.dumps(
                    {
                        "schema_version": 1,
                        "case_count": 2,
                        "code_copy": {
                            "tree_sha256": "b" * 64,
                            "file_count": 2,
                            "root_rel": "rediscovered-copy",
                        },
                    }
                ),
            },
        )

    after = _report(client, run_id)
    assert after["suite"] == before["suite"], "历史报告引用的版本与摘要不得被新版本改写"
    assert after["revision"]["suite_version_id"] == project["suite_version_id"]

    exported = json.loads(client.get(f"/api/v1/runs/{run_id}/report/export").text)
    assert exported["suite"] == before["suite"], "导出与页面报告必须同源"
    assert exported["revision"]["suite_version_id"] == project["suite_version_id"]


def test_rerun_traces_same_suite_without_touching_history(
    client, project, make_run, sync_engine
):
    original = make_run(state="completed", request_key=str(uuid.uuid4()))
    before = _report(client, original)

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

    rerun_report = _report(client, rerun_id)
    assert rerun_report["suite"] == before["suite"]
    assert _report(client, original) == before, "重跑不改写原运行的历史报告"


# --------------------------------------------------------------------------- #
# 固定副本缺失/损坏导致未执行：报告不伪造套件结论（AC-REP-02）
# --------------------------------------------------------------------------- #


def test_unexecuted_run_with_missing_copy_has_no_suite_verdict(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="errored", request_key=str(uuid.uuid4()))
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET reason_code = 'execution_copy_missing',"
                "       not_tested_reason = '固定代码副本缺失，未执行'"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"id": run_id},
        )

    body = _report(client, run_id)
    # 引用版本可以展示（"打算用哪个版本"），但绝不能有套件结论或断言计数
    assert body["suite"]["id"] == project["suite_version_id"]
    assert body["verdict"] is None, "未执行的运行不得伪造通过/失败"
    assert body["reason"] == "execution_copy_missing"
    assert body["reasonText"] == "固定代码副本缺失，未执行"
    assert body["components"] == []
    assert body["junit"] == {}, "未执行时不得出现用例计数"
    assert body["evidence"] == []


# --------------------------------------------------------------------------- #
# 检索 / 游标分页仍能打开完整报告（AC-REP-06）
# --------------------------------------------------------------------------- #


def test_paginated_search_still_opens_full_report(client, project, make_run):
    ids = [
        make_run(state="completed", request_key=str(uuid.uuid4())) for _ in range(3)
    ]
    walked: list[dict] = []
    cursor = None
    for _ in range(10):
        params = {"state": "completed", "q": project["suffix"], "limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/api/v1/runs", params=params, headers=CLIENT_HEADERS).json()
        walked.extend(page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]

    assert len(walked) == len(ids), "超过一页的集合应能沿游标走完"
    assert {item["id"] for item in walked} == set(ids)

    last = walked[-1]
    body = _report(client, last["id"])
    assert body["runId"] == last["display_id"]
    assert body["suite"]["code_copy"]["tree_sha256"]



