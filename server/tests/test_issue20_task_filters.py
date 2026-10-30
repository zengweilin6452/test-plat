"""工单 20：任务中心过滤（定向测试）。

覆盖：run_state 按**关联运行的 state** 过滤任务（不与 lifecycle/readiness 混用），
未知值 422；q / test_type 组合仍可用。URL 恢复与切 scope 重置是前端行为
（过滤条件落在 URL ?q/?test_type/?run_state，tsc 通过；浏览器导航走查未做）。
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


def test_task_filter_by_run_state(client, project, make_run, sync_engine):
    running = make_run(state="running", request_key=str(uuid.uuid4()))
    completed = make_run(state="completed", request_key=str(uuid.uuid4()))

    def task_ids(params: dict) -> set[str]:
        body = client.get("/api/v1/tasks", params=params)
        assert body.status_code == 200, body.text
        return {item["id"] for item in body.json()["items"]}

    assert project["task_id"] in task_ids({"run_state": "completed"})
    # 先 running 后 completed：最近一次运行是 completed（过滤器按"最近一次运行"）
    assert project["task_id"] not in task_ids({"run_state": "running"})
    assert project["task_id"] not in task_ids({"run_state": "queued"})


def test_task_filter_rejects_unknown_run_state(client, project):
    response = client.get("/api/v1/tasks", params={"run_state": "failed"})
    # failed 是结论不是运行态（七态之外）→ 400 validation_error
    assert response.status_code == 400, response.text
    assert "run_state" in response.text


def test_task_filter_combination(client, project, make_run):
    make_run(state="running", request_key=str(uuid.uuid4()))
    body = client.get(
        "/api/v1/tasks",
        params={"run_state": "running", "q": "task-" + project["suffix"]},
    ).json()
    assert {item["id"] for item in body["items"]} == {project["task_id"]}
