"""P6 测试：/api/v1/schema（静态 schema 文档）与 /api/v1/audit-events（只读分页）。

/schema 不查库：schema_doc.json 是构建期产物（scripts/gen_schema_doc.py 用 ast
从 0001_initial.py 抽取），所以纯 TestClient 就能测，不需要数据库。
/audit-events 只读、需要真库，走 _p2_common 的 api_client 夹具。

没有 TESTDOCK_TEST_DATABASE_URL 时集成用例整体 skip（与既有口径一致）。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

# 复用 _p2_common 的 api_client / seed 夹具（见 test_p2_tasks_api.py 同款说明）。
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

pytest_plugins = ("_p2_common",)

from _p2_common import TEST_DB  # noqa: E402

pytestmark = pytest.mark.integration


def test_schema_has_all_tables_with_counts(api_client):
    """/schema 返回当前迁移 head 的全部表；7 组计数一致；泳道/写入流程齐备。"""
    resp = api_client.get("/api/v1/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["table_count"] == len(body["tables"])
    table_names = {t["name"] for t in body["tables"]}
    assert len(table_names) == len(body["tables"])

    # 7 组，每组计数与 tables 清单一致
    assert len(body["groups"]) == 7
    grouped: set[str] = set()
    for group in body["groups"]:
        assert group["count"] == len(group["tables"])
        grouped.update(group["tables"])
        # 每张组内表都必须真实存在
        assert grouped <= table_names
    assert grouped == table_names, "分组必须覆盖全部表且不重复"

    # 4 泳道 + 4 写入流程
    assert len(body["lanes"]) == 4
    assert len(body["flows"]) == 4
    lane_tables = {t for lane in body["lanes"] for t in lane["tables"]}
    assert lane_tables <= table_names
    flow_tables = {t for flow in body["flows"] for step in flow["steps"] for t in step["tables"]}
    assert flow_tables <= table_names


def test_schema_key_fields_and_constraints(api_client):
    """关键字段 / 约束 / 索引存在：抽查 test_runs 与 audit_events。"""
    body = api_client.get("/api/v1/schema").json()
    by_name = {t["name"]: t for t in body["tables"]}

    runs = by_name["test_runs"]
    col_names = {c["name"] for c in runs["columns"]}
    assert {"id", "project_id", "state", "outcome", "parent_run_id", "not_tested_reason"} <= col_names
    # 三态口径的跨列 CHECK 必须被抽取出来（P0-3 修正项）
    check_names = {c["name"] for c in runs["constraints"] if c["kind"] == "check"}
    assert "ck_test_runs_state_outcome_pair" in check_names
    # 队列部分索引
    idx_names = {i["name"] for i in runs["indexes"]}
    assert "runs_queue" in idx_names

    audits = by_name["audit_events"]
    assert {"actor_ref", "action", "entity_type", "changes"} <= {c["name"] for c in audits["columns"]}

    # 每张表都要有中文注释（表与列的 COMMENT 全部来自迁移，含 0004 / 0009 新表）
    assert all(t["comment"] for t in body["tables"])


# --------------------------------------------------------------------------- #
# /api/v1/audit-events：需要真库
# --------------------------------------------------------------------------- #
# audit_events 是纯追加追溯表，平台代码对它只读（写入发生在运维/后续 P 阶段），
# 所以这里直接用 _exec_sync 插桩造数，只验证只读 API 的分页/过滤/排序契约。

from _p2_common import _exec_sync  # noqa: E402


def _insert_audit_events(pid: str, n: int) -> list[str]:
    """给指定项目插 n 条审计事件，返回插入的 id 列表。"""
    ids = []
    for i in range(n):
        row_id = str(uuid.uuid4())
        _exec_sync(
            """
            INSERT INTO audit_events (id, project_id, actor_ref, action, entity_type, entity_id, request_id, changes)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'tester@example.com', 'task.create', 'test_task', CAST(:eid AS uuid), :req, '{}'::jsonb)
            """,
            {"id": row_id, "pid": pid, "eid": str(uuid.uuid4()), "req": "req-" + row_id[:8]},
        )
        ids.append(row_id)
    return ids


def test_audit_events_returns_rows_desc(api_client, seed):
    """/audit-events 只读：插入 3 条后按 created_at DESC（同刻按 id DESC）读回。"""
    pid = seed["project_id"]
    ids = _insert_audit_events(pid, 3)

    resp = api_client.get("/api/v1/audit-events", params={"project_id": pid})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    got_ids = {item["id"] for item in body["items"]}
    assert got_ids == set(ids)
    # 排序：created_at 相同时按 id DESC，第一条应是最晚插入的
    assert body["items"][0]["id"] == ids[-1]
    for item in body["items"]:
        assert item["project_id"] == pid
        assert item["actor_ref"] == "tester@example.com"
        assert item["action"] == "task.create"
        assert isinstance(item["changes"], dict)


def test_audit_events_pagination_and_filter(api_client, seed):
    """limit/offset 分页 + project 过滤只命中本项目。"""
    pid = seed["project_id"]
    _insert_audit_events(pid, 2)

    page = api_client.get(
        "/api/v1/audit-events", params={"project_id": pid, "limit": 1}
    ).json()
    assert page["limit"] == 1 and page["offset"] == 0
    assert len(page["items"]) == 1 and page["total"] == 2

    page2 = api_client.get(
        "/api/v1/audit-events", params={"project_id": pid, "limit": 1, "offset": 1}
    ).json()
    assert page2["items"] and page2["items"][0]["id"] != page["items"][0]["id"]

    # 其它项目（随机 uuid）查不到本项目的事件
    empty = api_client.get(
        "/api/v1/audit-events", params={"project_id": str(uuid.uuid4())}
    ).json()
    assert empty["total"] == 0 and empty["items"] == []
