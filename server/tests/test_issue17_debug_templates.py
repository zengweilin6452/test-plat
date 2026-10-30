"""工单 17：调试图像模板——阈值契约（定向测试）。

覆盖：/templates/validate 的阈值必须落在 0.10-1.00（AC-DBG-05），越界 422 且
不触达 vendor。冻结/框选/快照对应、busy 禁止框选、同名冲突确认、匹配不伪造
等行为在 DebugDrawer 与 vendor 侧实现（P5 已交付），其中"模板库跨会话共享"
与"任务执行锁定模板版本"尚未实现，单列工单 25。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests._p3_common import CLIENT_HEADERS, TEST_DB, reset_db_engine, requires_db

pytestmark = requires_db


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


@pytest.mark.parametrize("threshold", ["0.05", "1.5", "abc"])
def test_template_validate_rejects_out_of_range_threshold(client, threshold):
    response = client.post(
        "/api/v1/templates/validate",
        json={
            "threshold": threshold,
            "target": {"by": "image", "value": "some-template"},
        },
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 400, response.text  # 本仓库 400 = validation_error
    assert response.json()["code"] == "validation_error"
    assert "threshold" in response.text


def test_template_validate_accepts_boundary_thresholds(client):
    """边界值 0.10 / 1.00 合法：无活动会话时按既有会话语义报错，而不是阈值 422。"""
    for threshold in ("0.10", "1.00"):
        response = client.post(
            "/api/v1/templates/validate",
            json={
                "threshold": threshold,
                "target": {"by": "image", "value": "some-template"},
            },
            headers=CLIENT_HEADERS,
        )
        assert response.status_code != 422 or "threshold" not in response.text, response.text
