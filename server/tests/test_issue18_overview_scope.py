"""工单 18：工作台 scope 与告警入口（真实 PG，定向测试）。

覆盖：scope 同时约束统计与"需要关注"（AC-OV-01）；无判定样本时 pass_rate 为
null（不显示伪造 0%）；未知 scope 422。定位入口（新建/模块卡/告警卡跳报告）
是前端行为，tsc 通过 + 链接指向 #/reports；接口失败/无告警的呈现由既有
Notice/Empty 组件覆盖。
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


def test_overview_scope_constrains_counts(client, project, make_run, sync_engine):
    passed_android = make_run(state="completed", request_key=str(uuid.uuid4()))
    with sync_engine.begin() as conn:
        conn.execute(
            text("UPDATE test_runs SET outcome = 'passed' WHERE id = CAST(:id AS uuid)"),
            {"id": passed_android},
        )

    all_scope = client.get("/api/v1/overview").json()
    android_scope = client.get("/api/v1/overview", params={"scope": "android"}).json()
    web_scope = client.get("/api/v1/overview", params={"scope": "web"}).json()

    assert android_scope["passed"] >= 1
    assert android_scope["passed"] <= all_scope["passed"]
    assert web_scope["run_total"] == 0
    assert web_scope["passed"] == 0
    assert web_scope["needs_attention"] == 0
    assert web_scope["application_total"] == 0


def test_overview_pass_rate_is_null_without_judged_samples(client):
    """全新库分母为 0：pass_rate 必须是 null，不能伪造 0%。"""
    response = client.get("/api/v1/overview", params={"scope": "ios"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pass_rate"] is None
    assert body["passed"] == 0 and body["failed"] == 0


def test_overview_rejects_unknown_scope(client):
    response = client.get("/api/v1/overview", params={"scope": "harmony"})
    assert response.status_code == 422, response.text
