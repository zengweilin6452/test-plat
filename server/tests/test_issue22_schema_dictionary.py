"""工单 22：数据库字典覆盖当前迁移 head（定向测试）。

覆盖：字典包含 0002+ 追加的结构（task_request_keys 表、last_seen_at、
cancel_requested_at、display_no 列），分组徽章计数与表清单一致、无重复；
生成器只读迁移源码（不连业务库）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def test_schema_doc_covers_current_migration_head(client):
    response = client.get("/api/v1/schema")
    assert response.status_code == 200
    body = response.json()
    tables = {table["name"]: table for table in body["tables"]}

    # 0005/0006/0007 的结构事实必须出现
    assert "task_request_keys" in tables, "0005 的表必须在字典里"
    run_columns = {column["name"] for column in tables["test_runs"]["columns"]}
    assert {"cancel_requested_at", "cancel_requested_by", "display_no"} <= run_columns
    resource_columns = {column["name"] for column in tables["execution_resources"]["columns"]}
    assert "last_seen_at" in resource_columns


def test_schema_groups_are_consistent_with_tables(client):
    body = client.get("/api/v1/schema").json()
    names = [table["name"] for table in body["tables"]]
    assert len(names) == len(set(names)), "字典不得有重复表"
    grouped = [name for group in body["groups"] for name in group["tables"]]
    assert len(grouped) == len(set(grouped)), "分组不得重复登记同一张表"
    for group in body["groups"]:
        assert group["count"] == len(group["tables"])
        for name in group["tables"]:
            assert name in tables_set(body), f"{name} 在分组里但不在表清单"
    for name in tables_set(body):
        assert any(name in group["tables"] for group in body["groups"]), (
            f"{name} 不属于任何分组"
        )


def tables_set(body: dict) -> set[str]:
    return {table["name"] for table in body["tables"]}
