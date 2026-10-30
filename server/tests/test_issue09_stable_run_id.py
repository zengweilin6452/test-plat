"""工单 09：稳定运行编号（真实 PG）。

覆盖的验收点（spec INV-10 / §9.3、AC-ID-01）：

- 编号持久分配在 `test_runs.display_no` 上，`RUN-0001` 只是格式化，不是查询期现算；
- 新增运行、历史回填/回退（回填更早的数据、删除旧运行）都不改变已有编号；
- 同一运行在列表、详情、WS 快照、任务列表、报告里的编号完全一致；
- UUID 始终是精确身份：展示编号不能当路径参数，也不能替代主键；
- 历史回填只执行一次且幂等（重复执行是空操作）。
"""

from __future__ import annotations

import importlib.util
import os
import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.domain import runs as runs_mod
from app.main import app
from tests._p3_common import CLIENT_HEADERS, TEST_DB, reset_db_engine, requires_db
from tests._p3_common import make_run as make_run
from tests._p3_common import p3_project as project
from tests._p3_common import sync_engine as sync_engine

pytestmark = requires_db

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0007_run_display_no.py"
)
DISPLAY_ID_RE = re.compile(r"^RUN-\d{4,}$")


@pytest.fixture
def client():
    os.environ["TESTDOCK_SCHEDULER"] = "0"
    reset_db_engine(TEST_DB)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    reset_db_engine(TEST_DB)


def _migration_module():
    spec = importlib.util.spec_from_file_location("migration_0007", MIGRATION_PATH)
    assert spec and spec.loader, f"读不到迁移 {MIGRATION_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_run(client, project: dict) -> dict:
    response = client.post(
        "/api/v1/runs",
        json={
            "application_id": project["application_id"],
            "task_id": project["task_id"],
            "request_key": str(uuid.uuid4()),
            "platform": "android",
        },
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _display_of(engine, run_id: str) -> str:
    with engine.connect() as conn:
        no = conn.execute(
            text("SELECT display_no FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar_one()
    return runs_mod.format_display_id(no)


def _listed(client) -> dict[str, str]:
    items = client.get("/api/v1/runs", params={"limit": 200}).json()["items"]
    return {item["id"]: item["display_id"] for item in items}


def test_display_id_is_persisted_unique_and_formatted(client, project, sync_engine):
    created = [_create_run(client, project) for _ in range(3)]
    display_ids = [item["display_id"] for item in created]
    for display_id in display_ids:
        assert DISPLAY_ID_RE.match(display_id), display_id

    with sync_engine.connect() as conn:
        total, distinct, nulls = conn.execute(
            text(
                "SELECT count(*), count(DISTINCT display_no),"
                " count(*) FILTER (WHERE display_no IS NULL) FROM test_runs"
            )
        ).one()
    assert nulls == 0, "编号必须持久落库，不允许空号"
    assert total == distinct, "两个运行不得共用同一编号"

    # 编号来自列，不是查询期现算：详情与库内值一致
    for item in created:
        assert _display_of(sync_engine, item["id"]) == item["display_id"]


def test_numbering_survives_new_runs_and_history_changes(client, project, sync_engine):
    first = _create_run(client, project)
    second = _create_run(client, project)
    before = _listed(client)
    assert before[first["id"]] == first["display_id"]
    assert before[second["id"]] == second["display_id"]

    # 新增运行：只给新运行发号，已有编号不动
    third = _create_run(client, project)
    after_insert = _listed(client)
    for run_id in (first["id"], second["id"]):
        assert after_insert[run_id] == before[run_id]
    assert third["display_id"] not in {before[first["id"]], before[second["id"]]}

    # 历史变更一：把一条运行回填成更早的创建时间（旧算法会整体重排编号）
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET created_at = created_at - interval '10 years'"
                " WHERE id = CAST(:id AS uuid)"
            ),
            {"id": third["id"]},
        )
    after_backdate = _listed(client)
    assert after_backdate == after_insert

    # 历史变更二：删掉最早的那条运行，其余编号不动
    with sync_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM run_events WHERE run_id = CAST(:id AS uuid)"),
            {"id": first["id"]},
        )
        conn.execute(
            text("DELETE FROM test_runs WHERE id = CAST(:id AS uuid)"), {"id": first["id"]}
        )
    after_delete = _listed(client)
    assert after_delete[second["id"]] == before[second["id"]]
    assert after_delete[third["id"]] == after_insert[third["id"]]


def test_display_id_consistent_across_run_list_detail_ws_tasks_and_report(
    client, project, make_run, sync_engine
):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))
    expected = _display_of(sync_engine, run_id)

    listed = next(
        item
        for item in client.get("/api/v1/runs", params={"limit": 200}).json()["items"]
        if item["id"] == run_id
    )
    assert listed["display_id"] == expected

    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["display_id"] == expected

    with client.websocket_connect(f"/api/v1/ws/runs/{run_id}") as socket:
        snapshot = socket.receive_json()
        assert snapshot["run"]["display_id"] == expected

    task = next(
        item
        for item in client.get("/api/v1/tasks").json()["items"]
        if item["id"] == project["task_id"]
    )
    assert task["run"]["id"] == run_id
    assert task["run"]["display_id"] == expected
    assert task["display_id"] == expected, "任务列表里的运行编号必须是同一个字符串"

    report = client.get(f"/api/v1/runs/{run_id}/report").json()
    assert report["runId"] == expected
    assert report["hostRunId"] == expected
    assert report["id"] == run_id, "报告必须同时给出精确 UUID"


def test_uuid_is_the_exact_identity_not_the_display_id(client, project, make_run):
    run_id = make_run(state="running", request_key=str(uuid.uuid4()))
    detail = client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200, detail.text

    # 展示编号不是主键：拿它当路径参数查不到运行
    display_id = detail.json()["display_id"]
    by_display = client.get(f"/api/v1/runs/{display_id}")
    assert by_display.status_code == 404, by_display.text
    assert by_display.json()["code"] == "not_found"


def test_backfill_is_idempotent_and_ordered_by_created_at(sync_engine):
    module = _migration_module()
    backfill = str(module.BACKFILL_SQL)
    # 回填口径与旧的动态算法一致：按 (created_at, id) 升序，且只填空号
    assert "row_number() OVER (ORDER BY created_at, id)" in backfill
    assert "display_no IS NULL" in backfill

    with sync_engine.connect() as conn:
        before = conn.execute(
            text("SELECT id, display_no FROM test_runs ORDER BY id")
        ).all()
    with sync_engine.begin() as conn:
        first = conn.execute(text(backfill))
    with sync_engine.begin() as conn:
        second = conn.execute(text(backfill))
    assert first.rowcount == 0 and second.rowcount == 0, "已有编号的行不得被再次回填"
    with sync_engine.connect() as conn:
        after = conn.execute(text("SELECT id, display_no FROM test_runs ORDER BY id")).all()
    assert [tuple(row) for row in after] == [tuple(row) for row in before]


def test_new_runs_continue_after_the_highest_number(client, project, sync_engine):
    created = _create_run(client, project)
    with sync_engine.connect() as conn:
        highest = conn.execute(text("SELECT max(display_no) FROM test_runs")).scalar_one()
    assert int(created["display_id"].split("-")[1]) == int(highest)

    another = _create_run(client, project)
    assert int(another["display_id"].split("-")[1]) == int(highest) + 1
