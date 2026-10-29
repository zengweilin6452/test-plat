"""工单 02：手动设备检查只读、busy 零访问、失败不自愈（真实 PG + 替身 adb）。

替身 adb 把每次 argv 追加到 JSONL；测试据此断言：
- 平台直接路径只发只读命令，没有 tcpip/connect/install/settings 等；
- 设备被租约占用时，检查在领租约阶段返回 409，adb 日志为空；
- 必需服务读取失败时如实返回 blocking，不触发任何自愈命令。
"""

from __future__ import annotations

import json
import sys
import uuid

import pytest
from sqlalchemy import text

from tests._p3_common import CLIENT_HEADERS, requires_db
from tests._p3_common import api_client as client  # noqa: F401 - fixture 复用
from tests._p3_common import make_run as make_run  # noqa: F401 - fixture 复用
from tests._p3_common import p3_project as p3_project  # noqa: F401 - fixture 复用
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - fixture 复用

pytestmark = requires_db

#: 任何 argv token 命中即视为“写设备/自愈”命令。
FORBIDDEN_TOKENS = frozenset(
    {
        "tcpip",
        "connect",
        "install",
        "uninstall",
        "settings",
        "monkey",
        "input",
        "reboot",
        "remount",
        "push",
    }
)

FAKE_ADB_PY = r'''
import json, os, sys, time

args = sys.argv[1:]
with open(os.environ["FAKE_ADB_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": args}) + "\n")

cfg = json.load(open(os.environ["FAKE_ADB_CONFIG"], encoding="utf-8"))
fail = cfg.get("fail") or {}


def maybe_fail(name):
    if name in fail:
        sys.exit(int(fail[name]))


if args[:2] == ["devices", "-l"]:
    print("List of devices attached")
    for device in cfg.get("devices", []):
        print(device["serial"] + "\t" + device.get("state", "device"))
    sys.exit(0)

if args and args[0] == "-s":
    command = args[3] if len(args) > 3 else ""
    if command.startswith("getprop"):
        probe = cfg["probe"]
        print(probe["brand"])
        print(probe["manufacturer"])
        print(probe["model"])
        print(probe["os_version"])
        print(probe["sdk"])
        print("Physical size: " + probe["resolution"])
        sys.exit(0)
    if command == "dumpsys battery":
        maybe_fail("battery")
        print(cfg.get("battery", "AC powered: true\nUSB powered: false\nlevel: 88"))
        sys.exit(0)
    if command == "dumpsys accessibility":
        maybe_fail("accessibility")
        print(cfg.get("accessibility", "Bound services:\n  Service[label=Demo]"))
        sys.exit(0)
    if command == "dumpsys activity activities":
        maybe_fail("activity")
        print(cfg.get("activity", "mResumedActivity: ActivityRecord{1 com.example/.Main}"))
        sys.exit(0)
    if command == "date +%s":
        maybe_fail("date")
        print(int(time.time()))
        sys.exit(0)
    if command.startswith("pm list packages"):
        maybe_fail("packages")
        print(cfg.get("packages", "package:com.example"))
        sys.exit(0)
    sys.exit(2)

sys.exit(2)
'''


@pytest.fixture
def project(p3_project, sync_engine):
    """测试结束先清租约再清 device_checks，避免项目删除撞外键。"""
    yield p3_project
    with sync_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM resource_leases WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": p3_project["project_id"]},
        )
        conn.execute(
            text("DELETE FROM device_checks WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": p3_project["project_id"]},
        )


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    script = tmp_path / "fake_adb.py"
    script.write_text(FAKE_ADB_PY, encoding="utf-8")
    bat = tmp_path / "adb.bat"
    bat.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    config = tmp_path / "adb.json"
    log = tmp_path / "adb-calls.jsonl"
    config.write_text(json.dumps({"devices": []}), encoding="utf-8")
    monkeypatch.setenv("TESTDOCK_ADB", str(bat))
    monkeypatch.setenv("FAKE_ADB_CONFIG", str(config))
    monkeypatch.setenv("FAKE_ADB_LOG", str(log))

    def configure(**overrides):
        data = {"devices": []}
        data.update(overrides)
        config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def calls():
        if not log.exists():
            return []
        return [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    return type("FakeAdb", (), {"configure": staticmethod(configure), "calls": staticmethod(calls)})


def _device_config(project: dict, **overrides):
    resource = project["resources"][0]
    data = {
        "devices": [{"serial": resource["serial"], "state": "device"}],
        "probe": {
            "brand": "Demo",
            "manufacturer": "Demo",
            "model": "Demo-1",
            "os_version": "15",
            "sdk": "35",
            "resolution": "1080x2400",
        },
    }
    data.update(overrides)
    return data


def _assert_read_only(calls: list[dict]) -> None:
    assert calls, "检查必须实际读取设备（替身 adb 应记录到命令）"
    tokens = [token.lower() for call in calls for token in call["argv"]]
    forbidden = sorted(FORBIDDEN_TOKENS & set(tokens))
    assert not forbidden, f"检查发出了禁止命令: {forbidden}; argv={calls}"


def _readiness(client, resource_id: str, **body):
    return client.post(
        f"/api/v1/resources/{resource_id}/readiness",
        json=body,
        headers=CLIENT_HEADERS,
    )


def test_manual_readiness_is_read_only_and_releases_lease(
    client, project, fake_adb, sync_engine
):
    fake_adb.configure(**_device_config(project))
    response = _readiness(
        client, project["resource_id"], test_type="ui", app_package="com.example"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is True
    assert body["test_type"] == "ui"
    assert body["blocking"] == []
    names = {check["name"] for check in body["checks"]}
    assert {"connection", "identity", "battery", "accessibility", "clock"} <= names
    assert body["lease_released"] is True

    _assert_read_only(fake_adb.calls())

    with sync_engine.connect() as conn:
        live = conn.execute(
            text(
                "SELECT count(*) FROM resource_leases"
                " WHERE project_id = CAST(:pid AS uuid) AND released_at IS NULL"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
        assert live == 0
        state, result = conn.execute(
            text(
                "SELECT state, result FROM device_checks"
                " WHERE project_id = CAST(:pid AS uuid)"
                " ORDER BY created_at DESC LIMIT 1"
            ),
            {"pid": project["project_id"]},
        ).one()
    assert state == "finished"
    assert result["ready"] is True


def test_busy_device_is_not_probed(client, project, fake_adb, make_run, sync_engine):
    fake_adb.configure(**_device_config(project))
    run_id = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET resource_id = CAST(:rid AS uuid),"
                " profile_id = CAST(:fid AS uuid)"
                " WHERE id = CAST(:run AS uuid)"
            ),
            {
                "rid": project["resource_id"],
                "fid": project["profile_id"],
                "run": run_id,
            },
        )
        conn.execute(
            text(
                "INSERT INTO resource_leases"
                " (id, project_id, resource_id, run_id, fencing_token, holder_id, expires_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:run AS uuid), 1, 'runner', now() + interval '60 seconds')"
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": project["project_id"],
                "rid": project["resource_id"],
                "run": run_id,
            },
        )

    response = _readiness(client, project["resource_id"], test_type="ui")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "device_busy"
    assert fake_adb.calls() == [], "busy 设备在领租约失败后不得访问 adb"

    with sync_engine.connect() as conn:
        checks = conn.execute(
            text(
                "SELECT count(*) FROM device_checks"
                " WHERE project_id = CAST(:pid AS uuid)"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
    assert checks == 0, "领租约失败时检查行应随事务回滚"


def test_readiness_failure_is_reported_without_self_healing(
    client, project, fake_adb, sync_engine
):
    fake_adb.configure(**_device_config(project, fail={"accessibility": 1}))
    response = _readiness(client, project["resource_id"], test_type="ui")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is False
    assert any(item["check"] == "accessibility" for item in body["blocking"])
    calls = fake_adb.calls()
    _assert_read_only(calls)
    accessibility_attempts = sum(
        1 for call in calls if call["argv"][-1] == "dumpsys accessibility"
    )
    assert accessibility_attempts == 1, "检查失败不得自动重试或触发自愈"

    with sync_engine.connect() as conn:
        live = conn.execute(
            text(
                "SELECT count(*) FROM resource_leases"
                " WHERE project_id = CAST(:pid AS uuid) AND released_at IS NULL"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
    assert live == 0, "检查失败也必须释放租约"


def test_sync_platform_direct_path_is_read_only(client, project, fake_adb):
    """平台直接 adb 路径（sync 的 devices -l + getprop）也只发只读命令。"""
    fake_adb.configure(**_device_config(project))
    response = client.post(
        "/api/v1/resources/sync",
        json={"project_id": project["project_id"]},
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 200, response.text
    _assert_read_only(fake_adb.calls())


def test_resources_view_exposes_check_lease(client, project, sync_engine):
    check_id = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO device_checks"
                " (id, project_id, resource_id, kind, test_type, holder_id, state, expires_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         'readiness', 'ui', 'manual', 'running', now() + interval '60 seconds')"
            ),
            {
                "id": check_id,
                "pid": project["project_id"],
                "rid": project["resource_id"],
            },
        )
        conn.execute(
            text(
                "INSERT INTO resource_leases"
                " (id, project_id, resource_id, check_id, fencing_token, holder_id, expires_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         CAST(:cid AS uuid), 1, 'manual', now() + interval '60 seconds')"
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": project["project_id"],
                "rid": project["resource_id"],
                "cid": check_id,
            },
        )

    response = client.get(
        "/api/v1/resources", params={"project_id": project["project_id"]}
    )
    assert response.status_code == 200, response.text
    item = next(
        row for row in response.json()["items"] if row["id"] == project["resource_id"]
    )
    assert item["busy"] is True
    assert item["lease"]["check_id"] == check_id
