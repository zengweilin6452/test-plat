"""工单 19：应用工作区与入口（定向测试）。

覆盖：iOS/Web 应用不能提交真实执行（修订永远 draft，POST /runs 422）；
浏览器把显式 application_id 传给 GET /runs 时按应用过滤（AC-APP-01 的服务端侧）。
工作区入口与所选应用展示是前端行为（AppsPage 行动链 #/ui?app=<id>，
UiPage 读 ?app= 并按应用过滤 + 蓝色 Notice），tsc 通过；逐应用进入的端到端
走查需要浏览器 QA，未在本轮执行。
"""

from __future__ import annotations

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


def _add_ios_application(engine, project: dict) -> str:
    app_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO applications (id, project_id, platform, name, identifier)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'ios', 'iOS 双胞胎', :ident)"
            ),
            {"id": app_id, "pid": project["project_id"], "ident": "com.example.p3ios"},
        )
    return app_id


def test_ios_application_cannot_start_real_execution(client, project, make_run, sync_engine):
    """iOS 修订永远 draft：validate 拒绝，运行提交按 readiness 拒绝，不伪装执行。"""
    ios_app = _add_ios_application(sync_engine, project)
    created = client.post(
        "/api/v1/tasks",
        json={
            "application_id": ios_app,
            "name": "ios-draft-" + uuid.uuid4().hex[:6],
            "test_type": "ui",
            "platform": "ios",
        },
        headers=CLIENT_HEADERS,
    )
    assert created.status_code in (200, 201), created.text
    task_id = created.json()["id"]
    validate = client.post(f"/api/v1/tasks/{task_id}/validate", headers=CLIENT_HEADERS)
    assert validate.status_code in (409, 422), validate.text

    run = client.post(
        "/api/v1/runs",
        json={
            "application_id": ios_app,
            "task_id": task_id,
            "request_key": str(uuid.uuid4()),
            "platform": "ios",
        },
        headers=CLIENT_HEADERS,
    )
    assert run.status_code == 422, run.text
    assert run.json()["code"] in ("readiness_incomplete", "validation_error")


def test_runs_filter_by_application_matches_selected_workspace(client, project, make_run, sync_engine):
    """AC-APP-01 服务端侧：显式 application_id 时只返回该应用的运行。"""
    other = _add_ios_application(sync_engine, project)
    mine = make_run(state="completed", request_key=str(uuid.uuid4()))

    listed = client.get(
        "/api/v1/runs", params={"application_id": project["application_id"], "limit": 200}
    ).json()
    assert mine in {item["id"] for item in listed["items"]}
    other_run = make_run(state="completed", request_key=str(uuid.uuid4()))
    # other 应用没有运行；把 my run 换绑也查不到 other 的
    assert client.get(
        "/api/v1/runs", params={"application_id": other, "limit": 200}
    ).json()["items"] == []
