"""P1-04：用户侧写操作统一要求 X-TestDock-Client: web（428 前置条件）。

盘点口径（与实现同步维护）：所有用户侧 POST / PUT / PATCH / DELETE 都必须声明
require_client_header（app/dependencies.py，自 routers/tasks.py 上移）；
/internal/* 是 Runner 协议面，走 X-Control-Token，不适用本守卫。

历史缺陷（本次回归钉死）：
- applications / projects / legacy_review 曾用 `Depends(client_header_required)`
  —— 那是**返回**错误对象的工厂，作为依赖永远不会抛出，等于假守卫；
- gate-evaluations / baselines / gate-policies / runs(import,cancel,create) /
  debug 模板与代理等写端点完全没有声明守卫。
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests._p3_common import CLIENT_HEADERS, TEST_DB, reset_db_engine, requires_db

pytestmark = requires_db


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    reset_db_engine(TEST_DB)


_RUN = str(uuid.uuid4())
_ID = str(uuid.uuid4())

#: (method, path) —— path 里的占位符已替换为不存在的 uuid：
#: 守卫（428）在路由处理与数据库访问之前生效，404/400/422 都说明守卫已放行。
WRITE_ENDPOINTS: list[tuple[str, str]] = [
    ("POST", "/api/v1/runs"),
    ("POST", f"/api/v1/runs/{_RUN}/cancel"),
    ("POST", "/api/v1/runs/import"),
    ("POST", f"/api/v1/runs/{_RUN}/gate-evaluations"),
    ("POST", "/api/v1/projects"),
    ("PATCH", f"/api/v1/projects/{_ID}"),
    ("POST", f"/api/v1/projects/{_ID}/archive"),
    ("POST", f"/api/v1/projects/{_ID}/restore"),
    ("POST", "/api/v1/applications"),
    ("PATCH", f"/api/v1/applications/{_ID}"),
    ("POST", f"/api/v1/applications/{_ID}/archive"),
    ("POST", f"/api/v1/applications/{_ID}/restore"),
    ("POST", "/api/v1/baselines"),
    ("POST", "/api/v1/builds"),
    ("POST", f"/api/v1/builds/{_ID}/identity-checks"),
    ("POST", f"/api/v1/builds/{_ID}/confirm-identity"),
    ("POST", "/api/v1/debug-sessions"),
    ("DELETE", f"/api/v1/debug-sessions/{_ID}"),
    ("POST", f"/api/v1/debug-sessions/{_ID}/control"),
    ("POST", f"/api/v1/debug-sessions/{_ID}/control/heartbeat"),
    ("POST", f"/api/v1/debug-sessions/{_ID}/input/key"),
    ("POST", f"/api/v1/debug-sessions/{_ID}/snapshots"),
    ("POST", f"/api/v1/debug-sessions/{_ID}/locators/validate"),
    ("POST", "/api/v1/templates"),
    ("POST", "/api/v1/templates/validate-crop"),
    ("POST", "/api/v1/templates/validate"),
    ("PUT", "/api/v1/templates/some-template"),
    ("PUT", f"/api/v1/gate-policies/{_ID}"),
    ("POST", "/api/v1/gate-policies"),
    ("POST", "/api/v1/legacy-review/apply"),
    ("POST", "/api/v1/resources/sync"),
    ("POST", f"/api/v1/resources/{_ID}/readiness"),
    ("POST", "/api/v1/suites"),
    ("POST", f"/api/v1/suites/{_ID}/versions"),
    ("POST", f"/api/v1/suites/{_ID}/discover"),
    ("POST", "/api/v1/tasks"),
    ("PATCH", f"/api/v1/tasks/{_ID}"),
    ("POST", f"/api/v1/tasks/{_ID}/validate"),
    ("POST", f"/api/v1/tasks/{_ID}/archive"),
    ("PATCH", "/api/v1/workspace"),
]


@pytest.mark.parametrize(("method", "path"), WRITE_ENDPOINTS)
def test_write_endpoint_rejects_missing_client_header(client, method: str, path: str):
    response = client.request(method, path, json={})
    assert response.status_code == 428, (method, path, response.status_code, response.text)
    assert response.json()["code"] == "client_header_required"


@pytest.mark.parametrize(("method", "path"), WRITE_ENDPOINTS)
def test_write_endpoint_rejects_wrong_client_header(client, method: str, path: str):
    response = client.request(method, path, json={}, headers={"X-TestDock-Client": "curl"})
    assert response.status_code == 428, (method, path, response.status_code)


@pytest.mark.parametrize(("method", "path"), WRITE_ENDPOINTS)
def test_write_endpoint_allows_correct_client_header(client, method: str, path: str):
    """正确 header 必须越过守卫：后续 400/404/409/422 都可以，唯独不能 428。"""
    response = client.request(method, path, json={}, headers=CLIENT_HEADERS)
    assert response.status_code != 428, (method, path, response.status_code, response.text)


def test_internal_face_does_not_demand_client_header(client):
    """Runner 协议面与用户侧守卫不许混用：无 client header 也按 401 处理。"""
    response = client.post(f"/internal/runs/{uuid.uuid4()}/heartbeat", json={})
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "control_token_invalid"


def test_health_and_list_endpoints_stay_open(client):
    """健康检查与纯查询不强制 header（P1-04 明确例外）。"""
    assert client.get("/api/v1/health").status_code in (200, 503)
    assert client.get("/api/v1/runs").status_code == 200
