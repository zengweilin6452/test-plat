"""工单 21：接入页真实示例与能力探测（定向测试）。

覆盖：/health 分开呈现存活与能力（db 实测、vendor 目录、runner 未知 = null），
ok=null 不渲染成失败（前端三态 badge，tsc 通过）；探测只读（SELECT 1 /
目录存在性），不启动运行、不占设备、不输出数据库主机。
接入页能力卡与错误码文案与实际契约一致（人工比对 openapi.json，
CAPS/ERRORS 常量已改为真实端点与错误码）。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from tests._p3_common import TEST_DB, reset_db_engine, requires_db
from tests._p3_common import p3_project as project  # noqa: F401
from tests._p3_common import sync_engine as sync_engine  # noqa: F401
from tests._p3_common import make_run as make_run  # noqa: F401

pytestmark = requires_db


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


def test_health_reports_three_state_capabilities(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] in ("ok", "degraded")
    assert body["db"] in ("ok", "fail")
    assert body["vendor"]["mobile_auto"] in ("present", "incomplete", "missing")
    assert body["vendor"]["mobile_perf"] in ("present", "incomplete", "missing")
    # runner 未知：null（不是 0，也不是失败）
    assert body["runners"]["active"] is None
    # 构建身份：未注入时为 null，注入后如实返回（不猜）
    assert "commit" in body


def test_health_distinguishes_incomplete_vendor_from_present(client, monkeypatch, tmp_path):
    """目录在但缺入口文件时不能报 present（复制中断/版本不符必须可见）。"""
    from app import config

    root = tmp_path / "vendor"
    (root / "mobile_auto").mkdir(parents=True)
    marker = root / "mobile_perf/src/mobile_perf/__init__.py"
    marker.parent.mkdir(parents=True)
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(config.settings, "vendor_dir", root)

    body = client.get("/api/v1/health").json()
    assert body["vendor"]["mobile_auto"] == "incomplete"
    assert body["vendor"]["mobile_perf"] == "present"


def test_health_does_not_leak_database_target(client):
    body = client.get("/api/v1/health").json()
    assert "database_target" not in body
    assert "@" not in str(body), "健康检查不得输出主机拓扑或凭据"


def test_health_is_read_only(client, project, make_run, sync_engine):
    """探测不启动运行、不占设备：调用前后运行数与活动租约数不变。"""
    with sync_engine.connect() as conn:
        before = conn.execute(
            text("SELECT (SELECT count(*) FROM test_runs),"
                 " (SELECT count(*) FROM resource_leases WHERE released_at IS NULL)")
        ).one()
    client.get("/api/v1/health")
    with sync_engine.connect() as conn:
        after = conn.execute(
            text("SELECT (SELECT count(*) FROM test_runs),"
                 " (SELECT count(*) FROM resource_leases WHERE released_at IS NULL)")
        ).one()
    assert tuple(before) == tuple(after)

