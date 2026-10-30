"""工单 15：资源就绪计数与占用语义（真实 PG，定向测试）。

覆盖的验收点：

- AC-RES-01：ready+idle / ready+busy / offline / unauthorized / draining 计数准确
  （busy 由未释放租约实时推导，counts 覆盖完整过滤集合）；
- AC-RES-03：readiness 的 test_type 按字面校验（ui/performance/joint），未知值 422；
- AC-RES-02 与 AC-READ-01 的行为（busy 零 adb、只读白名单、失败不自愈）
  已由 test_issue02_readiness.py / test_issue02_leases.py 覆盖，此处只做计数侧回归。
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


def _add_resource(engine, project: dict, status: str) -> str:
    resource_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO execution_resources (id, project_id, node_id, profile_id,"
                "                                 platform, resource_key, kind, status)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:nid AS uuid),"
                "         CAST(:fid AS uuid), 'android', :key, 'device', :status)"
            ),
            {
                "id": resource_id,
                "pid": project["project_id"],
                "nid": project["node_id"],
                "fid": project["profile_id"],
                "key": "P3-" + uuid.uuid4().hex[:10],
                "status": status,
            },
        )
    return resource_id


def _lease(engine, project: dict, resource_id: str, make_run) -> None:
    # resource_leases 外键 (project, run, resource) 必须指向一条真实绑定了该设备的运行
    run_id = make_run(state="completed", request_key=str(uuid.uuid4()))
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET resource_id = CAST(:rid AS uuid),"
                " profile_id = CAST(:prof AS uuid) WHERE id = CAST(:run AS uuid)"
            ),
            {"rid": resource_id, "prof": project["profile_id"], "run": run_id},
        )
        conn.execute(
            text(
                "INSERT INTO resource_leases (id, project_id, resource_id, run_id,"
                "                             fencing_token, holder_id, expires_at)"
                " VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run AS uuid), 1, 'pytest', now() + interval '10 minutes')"
            ),
            {"pid": project["project_id"], "rid": resource_id, "run": run_id},
        )


def _counts(client, project_id: str) -> dict:
    response = client.get("/api/v1/resources", params={"project_id": project_id})
    assert response.status_code == 200, response.text
    return response.json()


def test_resource_counts_cover_all_five_states(client, project, make_run, sync_engine):
    idle = _add_resource(sync_engine, project, "ready")
    busy = _add_resource(sync_engine, project, "ready")
    _add_resource(sync_engine, project, "offline")
    _add_resource(sync_engine, project, "unauthorized")
    _add_resource(sync_engine, project, "draining")
    _lease(sync_engine, project, busy, make_run)

    body = _counts(client, project["project_id"])
    counts = body["counts"]
    # 夹具自带 2 台 ready 设备（其中 1 台 resource_id 被租约引用 → busy）
    assert counts["ready_busy"] >= 1
    assert counts["ready_idle"] >= 1
    assert idle not in [i["id"] for i in body["items"] if i["busy"]]
    assert busy in [i["id"] for i in body["items"] if i["busy"]]
    assert counts["offline"] >= 1
    assert counts["unauthorized"] >= 1
    assert counts["draining"] >= 1
    assert body["ready"] == counts["ready_idle"] + counts["ready_busy"]
    assert counts["ready_idle"] + counts["ready_busy"] + counts["offline"] + counts["unauthorized"] + counts["draining"] == body["total"]
    assert "占用中" in body["summary"]


def test_readiness_rejects_unknown_test_type(client, project):
    response = client.post(
        f"/api/v1/resources/{project['resource_id']}/readiness",
        json={"test_type": "stress"},
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 422, response.text
