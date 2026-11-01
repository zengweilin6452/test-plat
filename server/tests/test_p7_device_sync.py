"""设备注册与资源池同步（docs/plan/device-registration.md T8 回归测试）。

adb 交互用假二进制驱动（.bat + Python 脚本读 JSON 配置），覆盖三类状态解析、
同步登记/幂等/offline 收敛/busy 跳过/未识别档案升级/adb 缺失 503/404，
不需要真机。口径单测（指纹、状态映射）不需要数据库。
"""

from __future__ import annotations

import json
import sys
import uuid

import pytest
from sqlalchemy import text

from tests._p3_common import CLIENT_HEADERS, make_project, requires_db
from tests._p3_common import api_client as client  # noqa: F401 - 夹具复用
from tests._p3_common import make_run as make_run  # noqa: F401 - 夹具复用
from tests._p3_common import p3_project as p3_project  # noqa: F401 - 夹具复用
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - 夹具复用

# --------------------------------------------------------------------------- #
# 假 adb：devices -l / -s shell 都读 FAKE_ADB_CONFIG 指向的 JSON
# --------------------------------------------------------------------------- #
FAKE_ADB_PY = """\
import json, os, sys

cfg = json.load(open(os.environ["FAKE_ADB_CONFIG"], encoding="utf-8"))
args = sys.argv[1:]
if args[:2] == ["devices", "-l"]:
    print("List of devices attached")
    print("* daemon started successfully")  # 解析器必须跳过 daemon 行
    for d in cfg.get("devices", []):
        line = d["serial"] + "\\t" + d["state"]
        if d.get("model"):
            line += " usb:1-1 product:demo model:" + d["model"] + " device:demo transport_id:1"
        print(line)
elif args[0] == "-s":
    dev = next((d for d in cfg.get("devices", []) if d["serial"] == args[1]), None)
    probe = dev.get("probe") if dev else None
    if not probe:
        sys.exit(1)
    print(probe["brand"])
    print(probe["manufacturer"])
    print(probe["model"])
    print(probe["os_version"])
    print(probe["sdk"])
    print("Physical size: " + probe["resolution"])
else:
    sys.exit(2)
"""


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    """TESTDOCK_ADB 指向假二进制；返回写入设备清单的函数。"""
    script = tmp_path / "fake_adb.py"
    script.write_text(FAKE_ADB_PY, encoding="utf-8")
    bat = tmp_path / "adb.bat"
    bat.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    cfg_path = tmp_path / "devices.json"
    cfg_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TESTDOCK_ADB", str(bat))
    monkeypatch.setenv("FAKE_ADB_CONFIG", str(cfg_path))

    def _set(devices: list[dict]) -> None:
        cfg_path.write_text(json.dumps({"devices": devices}, ensure_ascii=False), encoding="utf-8")

    return _set


def _dev(serial: str = "84cb2c4e", state: str = "device", probe: dict | None | bool = True) -> dict:
    entry: dict = {"serial": serial, "state": state, "model": "25102RKBEC" if state == "device" else None}
    if probe is True:
        entry["probe"] = {
            "brand": "Redmi",
            "manufacturer": "Xiaomi",
            "model": "25102RKBEC",
            "os_version": "17",
            "sdk": "37",
            "resolution": "1200x2608",
        }
    elif isinstance(probe, dict):
        entry["probe"] = probe
    return entry


def _sync(client, project_id: str | None = None):
    body = {"project_id": project_id} if project_id else {}
    return client.post("/api/v1/resources/sync", json=body, headers=CLIENT_HEADERS)


def _project_rows(sync_engine, project_id: str) -> int:
    with sync_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM execution_resources WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": project_id},
        ).scalar_one()


# --------------------------------------------------------------------------- #
# 口径单测（不需要数据库）
# --------------------------------------------------------------------------- #
def test_adb_parser_covers_three_states(fake_adb):
    from app.integrations import devices

    fake_adb(
        [
            _dev("dev-ok"),
            _dev("dev-unauth", state="unauthorized"),
            _dev("dev-offline", state="offline"),
        ]
    )
    got = devices.list_devices(devices.resolve_adb_path())
    assert [(d.serial, d.state, d.model) for d in got] == [
        ("dev-ok", "device", "25102RKBEC"),
        ("dev-unauth", "unauthorized", None),
        ("dev-offline", "offline", None),
    ]


def test_adb_state_mapping():
    from app.integrations import devices

    assert devices.map_adb_state("device") == "ready"
    assert devices.map_adb_state("unauthorized") == "unauthorized"
    assert devices.map_adb_state("offline") == "offline"
    # recovery/sideload 等不可调度但不谎报离线（D4）
    assert devices.map_adb_state("recovery") == "draining"
    assert devices.map_adb_state("sideload") == "draining"


def test_fingerprint_canonical_and_idempotent():
    from app.domain.profiles import (
        ProfileNormalizationError,
        fingerprint_for,
        spec_from_probe,
    )

    spec = spec_from_probe({"os_version": "17", "screen_resolution": "2608x1200", "model": "25102RKBEC"})
    # 真机实测值（device-registration.md D3.2）规范化后是 android-17|1200x2608|25102rkbec
    from app.domain.profiles import canonical_profile_spec

    canonical = canonical_profile_spec(spec)
    assert canonical["screen_resolution"] == "1200x2608"
    assert canonical["os_version"] == "17"
    assert canonical["model"] == "25102rkbec"
    # 不同写法同一指纹；指纹是 64 位小写十六进制（ck_resource_profiles_fingerprint_hex64）
    again = fingerprint_for({"os_name": "Android", "os_version": "17.0", "screen_resolution": "2608x1200", "model": "25102rkbec"})
    assert fingerprint_for(spec) == again
    assert len(fingerprint_for(spec)) == 64 and fingerprint_for(spec) == fingerprint_for(spec).lower()
    with pytest.raises(ProfileNormalizationError):
        spec_from_probe({"os_version": "17", "screen_resolution": "1200x2608"})  # 缺 model


def test_unknown_profile_fingerprint_stable():
    from app.domain.profiles import unknown_profile_fingerprint, unknown_profile_spec

    fp = unknown_profile_fingerprint("android")
    assert fp == unknown_profile_fingerprint("android")
    assert len(fp) == 64
    assert unknown_profile_spec() == {"unknown": True}


# --------------------------------------------------------------------------- #
# 集成（临时实例 + 假 adb）
# --------------------------------------------------------------------------- #
@requires_db
def test_sync_registers_device_and_is_idempotent(client, p3_project, fake_adb, sync_engine):
    fake_adb([_dev()])
    project_id = p3_project["project_id"]

    first = _sync(client, project_id)
    assert first.status_code == 200, first.text
    body = first.json()
    local = next(n for n in body["nodes"] if n["node_name"] == "本机执行节点")
    assert local["status"] == "ok" and local["seen"] == 1 and local["created"] == 1
    device = local["devices"][0]
    assert device["resource_key"] == "84cb2c4e"
    assert device["status"] == "ready" and device["action"] == "created"
    assert device["profile"]["created"] is True
    assert device["profile"]["name"] == "Redmi 25102RKBEC / Android 17 / 1200x2608"

    listing = client.get("/api/v1/resources", params={"project_id": project_id})
    assert listing.status_code == 200, listing.text
    row = next(i for i in listing.json()["items"] if i["resource_key"] == "84cb2c4e")
    assert row["status"] == "ready"
    assert row["last_seen_at"] is not None
    assert row["profile"]["name"] == "Redmi 25102RKBEC / Android 17 / 1200x2608"

    with sync_engine.connect() as conn:
        profiles_before = conn.execute(
            text("SELECT count(*) FROM resource_profiles WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": project_id},
        ).scalar_one()
    rows_before = _project_rows(sync_engine, project_id)

    second = _sync(client, project_id)
    assert second.status_code == 200, second.text
    local2 = next(n for n in second.json()["nodes"] if n["node_name"] == "本机执行节点")
    assert local2["created"] == 0 and local2["updated"] == 1
    assert local2["devices"][0]["profile"]["created"] is False

    # D4 纪律：同步从不删行、不重复建档
    assert _project_rows(sync_engine, project_id) == rows_before
    with sync_engine.connect() as conn:
        profiles_after = conn.execute(
            text("SELECT count(*) FROM resource_profiles WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": project_id},
        ).scalar_one()
    assert profiles_after == profiles_before


@requires_db
def test_sync_offlines_disappeared_device(client, p3_project, fake_adb):
    project_id = p3_project["project_id"]
    fake_adb([_dev()])
    assert _sync(client, project_id).status_code == 200

    fake_adb([])
    second = _sync(client, project_id)
    assert second.status_code == 200, second.text
    local = next(n for n in second.json()["nodes"] if n["node_name"] == "本机执行节点")
    assert local["offlined"] == 1

    listing = client.get("/api/v1/resources", params={"project_id": project_id})
    row = next(i for i in listing.json()["items"] if i["resource_key"] == "84cb2c4e")
    assert row["status"] == "offline"  # 行保留，只置 offline（D4 永不删行）


@requires_db
def test_sync_skips_busy_device(client, p3_project, fake_adb, sync_engine, make_run):
    project_id = p3_project["project_id"]
    fake_adb([_dev()])
    assert _sync(client, project_id).status_code == 200

    resource_id, profile_id = sync_engine.connect().execute(
        text(
            "SELECT id, profile_id FROM execution_resources"
            " WHERE project_id = CAST(:pid AS uuid) AND resource_key = '84cb2c4e'"
        ),
        {"pid": project_id},
    ).one()
    # ck_resource_leases_run_id_xor_debug_session：租约必须挂 run 或调试会话；
    # 复合外键 (project_id, run_id, resource_id) 要求 run 也绑到这台设备上，
    # ck_test_runs_resource_id_profile_pair 要求 resource/profile 成对。
    run_id = make_run(request_key="p7-busy")
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET state = 'running', resource_id = CAST(:rid AS uuid),"
                " profile_id = CAST(:fid AS uuid), started_at = now()"
                " WHERE id = CAST(:run_id AS uuid)"
            ),
            {"rid": str(resource_id), "fid": str(profile_id), "run_id": run_id},
        )
        conn.execute(
            text(
                "INSERT INTO resource_leases"
                " (id, project_id, resource_id, run_id, fencing_token, holder_id, expires_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run_id AS uuid), 1, 'pytest', now() + interval '10 minutes')"
            ),
            {"id": str(uuid.uuid4()), "pid": project_id, "rid": str(resource_id), "run_id": run_id},
        )

    fake_adb([])
    result = _sync(client, project_id)
    assert result.status_code == 200, result.text
    local = next(n for n in result.json()["nodes"] if n["node_name"] == "本机执行节点")
    assert local["busy_skipped"] == ["84cb2c4e"]
    assert local["offlined"] == 0

    listing = client.get("/api/v1/resources", params={"project_id": project_id})
    row = next(i for i in listing.json()["items"] if i["resource_key"] == "84cb2c4e")
    assert row["status"] == "ready"  # 占用中的设备不改状态（D4 例外）


@requires_db
def test_sync_unauthorized_then_upgrades_profile(client, p3_project, fake_adb, sync_engine):
    project_id = p3_project["project_id"]
    fake_adb([_dev("device-unauth", state="unauthorized")])

    first = _sync(client, project_id)
    assert first.status_code == 200, first.text
    local = next(n for n in first.json()["nodes"] if n["node_name"] == "本机执行节点")
    device = local["devices"][0]
    assert device["status"] == "unauthorized"
    assert device["profile"]["name"] == "未识别设备"
    unknown_profile_id = device["profile"]["id"]

    fake_adb([_dev("device-unauth")])  # 授权完成：能读到真机特征了
    second = _sync(client, project_id)
    assert second.status_code == 200, second.text
    device2 = next(n for n in second.json()["nodes"] if n["node_name"] == "本机执行节点")["devices"][0]
    assert device2["status"] == "ready"
    assert device2["profile"]["name"] == "Redmi 25102RKBEC / Android 17 / 1200x2608"
    assert device2["profile"]["id"] != unknown_profile_id  # D3.3：档案升级，不降级


@requires_db
def test_sync_adb_missing_returns_503(client, p3_project, monkeypatch, tmp_path):
    monkeypatch.setenv("TESTDOCK_ADB", str(tmp_path / "no-such-adb.exe"))
    resp = _sync(client, p3_project["project_id"])
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["code"] == "adb_unavailable"
    assert "no-such-adb.exe" in body["details"]["path"]
    assert "TESTDOCK_ADB" in body["details"]["hint"]


@requires_db
def test_sync_and_resources_reject_unknown_project(client):
    missing = str(uuid.uuid4())
    resp = _sync(client, missing)
    assert resp.status_code == 404 and resp.json()["code"] == "not_found"
    listing = client.get("/api/v1/resources", params={"project_id": missing})
    assert listing.status_code == 404 and listing.json()["code"] == "not_found"


@requires_db
def test_sync_requires_client_header(client, p3_project, fake_adb):
    fake_adb([_dev()])
    resp = client.post("/api/v1/resources/sync", json={})
    assert resp.status_code == 428 and resp.json()["code"] == "client_header_required"


@requires_db
def test_projects_endpoint_lists_project(client, p3_project):
    resp = client.get("/api/v1/projects")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    row = next(p for p in items if p["id"] == p3_project["project_id"])
    assert row["code"] == p3_project["suffix"] or row["name"]
    assert row["archived_at"] is None


@requires_db
def test_sync_writes_are_scoped_to_own_project(client, p3_project, fake_adb, sync_engine):
    """跨项目隔离：不带 project_id 的同步给每个项目登记设备，既有项目行数只按规则变化。"""
    other = make_project(sync_engine, resources=1)
    try:
        rows_before = _project_rows(sync_engine, other["project_id"])
        fake_adb([_dev("cross-project-dev")])
        # 不带 project_id = 所有项目（每项目各自登记自己的设备）
        resp = _sync(client)
        assert resp.status_code == 200, resp.text
        assert _project_rows(sync_engine, other["project_id"]) == rows_before + 1
    finally:
        from tests._p3_common import drop_project

        drop_project(other["project_id"])


@requires_db
def test_sync_with_explicit_node_id_does_not_crash(client, p3_project, fake_adb, sync_engine):
    """真机验收发现的 500：指定 node_id 时 SQL 没取 status，却读取 fixed_node.status。"""
    fake_adb([_dev()])
    project_id = p3_project["project_id"]
    node_id = p3_project["node_id"]
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE execution_nodes SET capabilities = '{\"local\": true, \"adb\": true}'::jsonb"
                " WHERE id = CAST(:nid AS uuid)"
            ),
            {"nid": node_id},
        )

    response = client.post(
        "/api/v1/resources/sync",
        json={"project_id": project_id, "node_id": node_id},
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 200, response.text
    node = response.json()["nodes"][0]
    assert node["node_id"] == node_id
    assert node["status"] == "ok"
