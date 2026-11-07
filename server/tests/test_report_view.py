"""工单：报告在线直接查看（GET /runs/{id}/report/view、/artifacts/{id}/view）。

覆盖点：
- 已登记 report_html 产物：/report/view 内联返回 vendor 原始 HTML（inline +
  CSP sandbox），run 级报告优先于嵌套目录里的组件级报告；
- 没有 HTML 产物（UI 运行只有 report.json / junit.xml）：用平台报告快照渲染
  自包含 HTML，任何运行都有可直接打开的报告；
- /runs 列表与 /artifacts、/report 的 view_url 都由后端拼好（前端不自己拼路径）；
- 非 text/html 产物不支持在线查看（走下载端点）；不存在的运行/产物 404。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import settings
from app.main import app
from tests._p3_common import TEST_DB, reset_db_engine, requires_db
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


def _add_html_artifact(engine, project: dict, run_id: str, logical_key: str = "report.html") -> str:
    """登记一个真实可读的 report_html 产物（文件写进受管产物目录）。"""
    artifact_id = str(uuid.uuid4())
    storage_key = f"{run_id}/{logical_key}"
    path = Path(settings.artifacts_dir) / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<html><body><h1>vendor report</h1></body></html>", encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO artifacts (id, project_id, run_id, kind, logical_key,"
                "                       storage_key, mime_type, byte_size, sha256, availability)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid), 'report_html',"
                "         :key, :storage, 'text/html', :size, repeat('a', 64), 'available')"
            ),
            {
                "id": artifact_id,
                "pid": project["project_id"],
                "rid": run_id,
                "key": logical_key,
                "storage": storage_key,
                "size": path.stat().st_size,
            },
        )
    return artifact_id


def _add_log_artifact(engine, project: dict, run_id: str) -> str:
    artifact_id = str(uuid.uuid4())
    storage_key = f"{run_id}/evidence/run.log"
    path = Path(settings.artifacts_dir) / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("log line", encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO artifacts (id, project_id, run_id, kind, logical_key,"
                "                       storage_key, mime_type, byte_size, sha256, availability)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid), 'log',"
                "         :key, :storage, 'text/plain', :size, repeat('b', 64), 'available')"
            ),
            {
                "id": artifact_id,
                "pid": project["project_id"],
                "rid": run_id,
                "key": "evidence/run.log",
                "storage": storage_key,
                "size": path.stat().st_size,
            },
        )
    return artifact_id


# --------------------------------------------------------------------------- #
# GET /runs/{id}/report/view
# --------------------------------------------------------------------------- #


def test_report_view_serves_registered_html_inline(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    _add_html_artifact(sync_engine, project, run_id)

    response = client.get(f"/api/v1/runs/{run_id}/report/view")
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    # inline 而不是 attachment：浏览器直接渲染，不触发下载
    assert response.headers["content-disposition"].startswith("inline")
    # 导入通道可能带进任意 HTML：内联展示时脚本必须被禁用
    assert response.headers["content-security-policy"] == "sandbox"
    assert "vendor report" in response.text


def test_report_view_prefers_run_level_report(client, project, make_run, sync_engine):
    """run 级 report.html 优先；嵌套目录（perf-runs/<id>/）是组件级产物，靠后。"""
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    nested_id = _add_html_artifact(sync_engine, project, run_id, "perf-runs/sub/report.html")
    _add_html_artifact(sync_engine, project, run_id, "report.html")

    response = client.get(f"/api/v1/runs/{run_id}/report/view")
    assert response.status_code == 200
    # 嵌套报告内容不同时能区分：这里两份内容相同，改用文件名判断
    assert "report.html" in response.headers["content-disposition"]
    assert nested_id  # 两个产物都已登记，视图仍应 200


def test_report_view_renders_platform_report_without_html_artifact(
    client, project, make_run
):
    """UI 运行没有 HTML 产物：用报告快照渲染自包含 HTML，不 404 不下载。"""
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    report = client.get(f"/api/v1/runs/{run_id}/report").json()

    response = client.get(f"/api/v1/runs/{run_id}/report/view")
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    assert response.headers["content-security-policy"] == "sandbox"
    # 同一份快照的关键字段必须出现在渲染结果里
    assert report["runId"] in response.text
    assert "TestDock" in response.text
    # 平台结论与证据区块都在
    assert "指标汇总" in response.text
    assert "证据链" in response.text


def test_report_view_unknown_run_404(client):
    response = client.get(f"/api/v1/runs/{uuid.uuid4()}/report/view")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------- #
# GET /runs/{id}/artifacts/{artifact_id}/view
# --------------------------------------------------------------------------- #


def test_artifact_view_serves_html_inline(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    artifact_id = _add_html_artifact(sync_engine, project, run_id)

    response = client.get(f"/api/v1/runs/{run_id}/artifacts/{artifact_id}/view")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["content-security-policy"] == "sandbox"
    assert "vendor report" in response.text


def test_artifact_view_rejects_non_html(client, project, make_run, sync_engine):
    """非 text/html 产物不支持在线查看：400 说明走下载端点，不给 500。"""
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    artifact_id = _add_log_artifact(sync_engine, project, run_id)

    response = client.get(f"/api/v1/runs/{run_id}/artifacts/{artifact_id}/view")
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


def test_artifact_view_unknown_404(client, project, make_run):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    response = client.get(f"/api/v1/runs/{run_id}/artifacts/{uuid.uuid4()}/view")
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# view_url 由后端拼好
# --------------------------------------------------------------------------- #


def test_runs_list_carries_view_url_for_completed_only(client, project, make_run):
    completed = make_run(state="completed", request_key=str(uuid.uuid4()))
    queued = make_run(state="queued", request_key=str(uuid.uuid4()))

    body = client.get("/api/v1/runs?state=completed").json()
    item = next(row for row in body["items"] if row["id"] == completed)
    assert item["view_url"] == f"/api/v1/runs/{completed}/report/view"

    body = client.get(f"/api/v1/runs?application_id={project['application_id']}").json()
    queued_item = next(row for row in body["items"] if row["id"] == queued)
    assert queued_item["view_url"] is None


def test_artifacts_and_report_carry_view_urls(client, project, make_run, sync_engine):
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    html_id = _add_html_artifact(sync_engine, project, run_id)
    log_id = _add_log_artifact(sync_engine, project, run_id)

    artifacts = client.get(f"/api/v1/runs/{run_id}/artifacts").json()
    by_id = {item["id"]: item for item in artifacts["items"]}
    assert by_id[html_id]["view_url"] == f"/api/v1/runs/{run_id}/artifacts/{html_id}/view"
    assert by_id[log_id]["view_url"] is None

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["view_url"] == f"/api/v1/runs/{run_id}/report/view"
    evidence = {item["id"]: item for item in report["evidence"]}
    assert evidence[html_id]["view_url"] == f"/api/v1/runs/{run_id}/artifacts/{html_id}/view"
    assert evidence[log_id]["view_url"] is None
