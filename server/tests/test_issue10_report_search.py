"""工单 10：完成报告检索与游标分页（真实 PG，定向测试）。

覆盖的验收点（spec §9.3、AC-REP-01、AC-FILTER-01）：

- 完成报告列表只含 completed；errored/cancelled 的部分证据不混入；
- q 在完整过滤集合里按文字包含匹配 display_id / 任务名 / 应用名，
  输入不解释为 SQL 通配符；
- 组合过滤 + 游标翻页：目标报告在截断范围外仍可翻页或检索到，翻页不重不漏；
- 游标绑定过滤条件与创建水位：换过滤条件带旧游标、非法游标 → 422。
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

BULK_COUNT = 210


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


def _bulk_completed(engine, project: dict, count: int, *, revision_id: str | None = None,
                    test_type: str = "ui", outcome: str = "passed") -> list[str]:
    """直插一批 completed 运行（不经 API，只为造出"超过一页"的完整集合）。"""
    revision_id = revision_id or project["revision_id"]
    suffix = "%s-%s" % (project["suffix"], uuid.uuid4().hex[:6])
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "INSERT INTO test_runs (id, project_id, application_id, platform, revision_id,"
                "                      request_key, state, config_snapshot, created_by,"
                "                      resource_id, profile_id, created_at, started_at, ended_at, outcome)"
                " SELECT gen_random_uuid(), CAST(:pid AS uuid), CAST(:aid AS uuid), 'android',"
                "        CAST(:rid AS uuid), 'bulk-' || g || '-" + suffix + "', 'completed',"
                "        CAST(:config AS jsonb), 'pytest', CAST(:res AS uuid), CAST(:prof AS uuid),"
                "        now() - interval '1 hour', now() - interval '30 minutes', now(), :outcome"
                "   FROM generate_series(CAST(:first AS integer), CAST(:last AS integer)) g"
                " RETURNING id"
            ),
            {
                "pid": project["project_id"],
                "aid": project["application_id"],
                "rid": revision_id,
                "config": "{}",
                "res": project["resource_id"],
                "prof": project["profile_id"],
                "outcome": outcome,
                "first": 1,
                "last": count,
            },
        ).all()
    return [str(row[0]) for row in rows]


def _add_performance_revision(engine, project: dict) -> str:
    revision_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO task_revisions (id, project_id, application_id, task_id,"
                "                           revision, environment_id, build_id, suite_version_id,"
                "                           test_type, readiness, config, created_by)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),"
                "         CAST(:tid AS uuid), 3, CAST(:eid AS uuid), CAST(:bid AS uuid),"
                "         CAST(:svid AS uuid), 'performance', 'validated', '{}'::jsonb, 'pytest')"
            ),
            {
                "id": revision_id,
                "pid": project["project_id"],
                "aid": project["application_id"],
                "tid": project["task_id"],
                "eid": project["environment_id"],
                "bid": project["build_id"],
                "svid": project["suite_version_id"],
            },
        )
    return revision_id


def _list(client, **params) -> dict:
    response = client.get("/api/v1/runs", params=params, headers=CLIENT_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _walk_all(client, **params) -> list[dict]:
    """沿游标把整个过滤集合走完，返回 items（顺序 = 服务端顺序）。"""
    items: list[dict] = []
    cursor = None
    for _ in range(20):  # 防御：游标死循环直接失败
        page = _list(client, cursor=cursor, **params) if cursor else _list(client, **params)
        items.extend(page["items"])
        if not page["has_more"]:
            return items
        cursor = page["next_cursor"]
    raise AssertionError("游标翻页 20 页仍未尽头，疑似死循环")


# --------------------------------------------------------------------------- #
# completed 过滤与证据隔离
# --------------------------------------------------------------------------- #


def test_only_completed_enters_report_list(client, project, make_run, sync_engine):
    completed_id = _bulk_completed(sync_engine, project, 2)[0]
    errored = make_run(state="errored", request_key=str(uuid.uuid4()))
    running = make_run(state="running", request_key=str(uuid.uuid4()))

    items = _walk_all(client, state="completed", limit=200)
    ids = {item["id"] for item in items}
    assert completed_id in ids
    assert errored not in ids and running not in ids
    assert all(item["state"] == "completed" for item in items if item["id"] == completed_id)


def test_errored_run_with_evidence_stays_out_of_report_list(client, project, make_run, sync_engine):
    """errored 运行带产物也不得进入完成报告列表（证据走详情/产物接口）。"""
    errored = make_run(state="errored", request_key=str(uuid.uuid4()))
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO artifacts (id, project_id, run_id, kind, logical_key,"
                "                       storage_key, mime_type, byte_size, sha256, availability)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid), 'log',"
                "         'partial-evidence', 'logs/x.log', 'text/plain', 10,"
                "         repeat('a', 64), 'available')"
            ),
            {"pid": project["project_id"], "rid": errored},
        )
    items = _walk_all(client, state="completed", limit=200)
    assert errored not in {item["id"] for item in items}


# --------------------------------------------------------------------------- #
# 搜索、组合过滤与游标分页
# --------------------------------------------------------------------------- #


def test_target_report_beyond_truncation_is_reachable(client, project, sync_engine):
    """AC-REP-01：210 份 completed，目标在最旧一页；按 display_id 搜索直达。"""
    ids = _bulk_completed(sync_engine, project, BULK_COUNT)
    with sync_engine.connect() as conn:
        target_no = conn.execute(
            text("SELECT min(display_no) FROM test_runs WHERE id = ANY(:ids)"),
            {"ids": [uuid.UUID(i) for i in ids]},
        ).scalar_one()
    target_display = "RUN-%04d" % int(target_no)

    # 搜索直达：不用翻 5 页
    direct = _walk_all(client, state="completed", q=target_display, limit=50)
    assert target_display in {item["display_id"] for item in direct}
    assert all(item["application"]["name"].endswith(project["suffix"]) for item in direct)

    # 不用搜索也要能翻页翻到：走完整个集合，不重不漏
    walked = _walk_all(client, state="completed", limit=50)
    walked_ids = [item["id"] for item in walked]
    assert set(ids) <= set(walked_ids)
    assert len(walked_ids) == len(set(walked_ids)), "翻页出现重复"


def test_combined_filter_is_consistent_across_pages(client, project, sync_engine):
    """AC-FILTER-01：q + test_type + state 组合过滤，翻页边界处不漏不混。"""
    perf_revision = _add_performance_revision(sync_engine, project)
    perf_run = _bulk_completed(
        sync_engine, project, 3, revision_id=perf_revision
    )  # test_type=performance
    ui_ids = _bulk_completed(sync_engine, project, 60)  # test_type=ui

    perf_only = _walk_all(client, state="completed", test_type="performance", limit=50)
    assert {item["id"] for item in perf_only} == set(perf_run)
    assert all(item["test_type"] == "performance" for item in perf_only)

    ui_pages: list[list[dict]] = [[]]
    cursor = None
    for _ in range(5):
        page = (
            _list(client, state="completed", test_type="ui", q=project["suffix"], limit=25)
            if cursor is None
            else _list(
                client, state="completed", test_type="ui", q=project["suffix"],
                limit=25, cursor=cursor,
            )
        )
        ui_pages[-1].extend(page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    walked_ui = [item["id"] for page in ui_pages for item in page]
    assert set(ui_ids) <= set(walked_ui)
    assert not set(perf_run) & set(walked_ui), "模块过滤不得混入另一模块的运行"


def test_q_is_literal_not_a_wildcard(client, project, sync_engine):
    """q 里的 % 和 _ 按字面匹配，不得解释为 SQL 通配表达式。"""
    _bulk_completed(sync_engine, project, 2)
    everything = _list(client, state="completed", q="%", limit=200)
    assert everything["items"] == [], "q=% 不得匹配全部"
    underscore = _list(client, state="completed", q="_", limit=200)
    assert underscore["items"] == [], "q=_ 不得匹配全部"


def test_cursor_is_bound_to_filters_and_rejects_garbage(client, project, sync_engine):
    _bulk_completed(sync_engine, project, 55)

    page = _list(client, state="completed", q=project["suffix"], limit=50)
    assert page["has_more"] is True and page["next_cursor"]

    # 换过滤条件带旧游标：422，不静默混页
    mismatched = client.get(
        "/api/v1/runs",
        params={"state": "completed", "limit": 50, "cursor": page["next_cursor"]},
        headers=CLIENT_HEADERS,
    )
    assert mismatched.status_code == 400, mismatched.text
    assert mismatched.json()["code"] == "validation_error"

    # 非法游标：422
    for garbage in ("not-a-cursor", "###", "e30="):  # e30= 是 {} 的 base64
        bad = client.get(
            "/api/v1/runs",
            params={"state": "completed", "q": project["suffix"], "limit": 50, "cursor": garbage},
            headers=CLIENT_HEADERS,
        )
        assert bad.status_code == 400, (garbage, bad.text)

    # 合法游标正常翻页
    next_page = _list(
        client, state="completed", q=project["suffix"], limit=50, cursor=page["next_cursor"]
    )
    assert next_page["items"]
    assert {item["id"] for item in next_page["items"]}.isdisjoint(
        {item["id"] for item in page["items"]}
    )


def test_state_filter_validates_seven_states(client, project):
    bad = client.get("/api/v1/runs", params={"state": "nope"}, headers=CLIENT_HEADERS)
    # 请求形状/取值拒绝沿用本仓库的 400 validation_error（与 ticket 08 同口径）
    assert bad.status_code == 400, bad.text
    assert bad.json()["code"] == "validation_error"
