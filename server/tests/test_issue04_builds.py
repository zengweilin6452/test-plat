"""工单 04：构建登记与设备身份核对（真实 PG + 替身 adb）。

覆盖的验收点：
- AC-INPUT-01：同 key 同身份复用；不同身份 409 且原记录不变。
- AC-BUILD-01：业务 version 与实测 versionName 冲突时拒绝确认。
- 固定基准后不从另一设备自动重新学习；正式执行前复核。
- 核对记录包含设备、时间、预期、观测、结果；报告等级不称 APK 摘要已验证。
- 身份读取与 readiness 共用 device_checks / resource_leases 互斥通道；
  busy 时零 adb 访问；只发只读命令。
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

FORBIDDEN_TOKENS = frozenset(
    {"tcpip", "connect", "install", "uninstall", "settings", "monkey", "input", "reboot", "push"}
)

FAKE_ADB_PY = r'''
import json, os, sys

args = sys.argv[1:]
with open(os.environ["FAKE_ADB_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": args}) + "\n")

cfg = json.load(open(os.environ["FAKE_ADB_CONFIG"], encoding="utf-8"))

if args[:2] == ["devices", "-l"]:
    print("List of devices attached")
    for device in cfg.get("devices", []):
        print(device["serial"] + "\t" + device.get("state", "device"))
    sys.exit(0)

if args and args[0] == "-s":
    command = args[3] if len(args) > 3 else ""
    if command.startswith("dumpsys package"):
        package = command.split()[-1]
        entry = (cfg.get("packages") or {}).get(package)
        if entry is None:
            print("Unable to find package: " + package)
            sys.exit(0)
        if entry.get("fail"):
            sys.exit(int(entry["fail"]))
        print("Packages:")
        print("  Package [" + package + "] (abc):")
        if "versionCode" in entry:
            print("    versionCode=" + str(entry["versionCode"]) + " minSdk=24")
        if "versionName" in entry:
            print("    versionName=" + str(entry["versionName"]))
        sys.exit(0)

sys.exit(2)
'''


@pytest.fixture
def project(p3_project, sync_engine):
    """先清租约与检查行，再让 p3_project 按外键顺序删项目。"""
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
    config.write_text(json.dumps({"devices": [], "packages": {}}), encoding="utf-8")
    monkeypatch.setenv("TESTDOCK_ADB", str(bat))
    monkeypatch.setenv("FAKE_ADB_CONFIG", str(config))
    monkeypatch.setenv("FAKE_ADB_LOG", str(log))

    def configure(**overrides):
        data = {"devices": [], "packages": {}}
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


def _package(project: dict) -> str:
    return f"com.example.p3{project['suffix']}"


def _device_config(project: dict, *, index: int = 0, version_name: str = "1.2.3",
                   version_code: str = "42", package_name: str | None = None,
                   packages: dict | None = None) -> dict:
    resource = project["resources"][index]
    package = package_name or _package(project)
    return {
        "devices": [{"serial": resource["serial"], "state": "device"}],
        "packages": packages
        if packages is not None
        else {package: {"versionName": version_name, "versionCode": version_code}},
    }


def _register(client, project: dict, **overrides):
    body = {
        "application_id": project["application_id"],
        "version": "1.2.3",
        "build_key": "ci-1001",
        "source_commit": "abc123",
        "sha256": "a" * 64,
    }
    body.update(overrides)
    return client.post("/api/v1/builds", json=body, headers=CLIENT_HEADERS)


def _build_id(response) -> str:
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def _check(client, build_id: str, resource_id: str, **body):
    payload = {"resource_id": resource_id}
    payload.update(body)
    return client.post(
        f"/api/v1/builds/{build_id}/identity-checks",
        json=payload,
        headers=CLIENT_HEADERS,
    )


def _confirm(client, build_id: str, check_id: str):
    return client.post(
        f"/api/v1/builds/{build_id}/confirm-identity",
        json={"check_id": check_id},
        headers=CLIENT_HEADERS,
    )


def _assert_read_only(calls: list[dict]) -> None:
    assert calls, "身份读取必须实际访问设备（替身 adb 应记录到命令）"
    tokens = [token.lower() for call in calls for token in call["argv"]]
    forbidden = sorted(FORBIDDEN_TOKENS & set(tokens))
    assert not forbidden, f"身份读取发出了禁止命令: {forbidden}; argv={calls}"
    for call in calls:
        argv = call["argv"]
        if len(argv) > 3 and argv[2] == "shell":
            assert argv[3].startswith("dumpsys package "), f"只允许只读 dumpsys package: {argv}"


# --------------------------------------------------------------------------- #
# AC-INPUT-01：登记幂等与冲突
# --------------------------------------------------------------------------- #


def test_register_build_reuses_same_identity_and_conflicts_on_different_identity(
    client, project, sync_engine
):
    first = _register(client, project)
    assert first.status_code == 201, first.text
    created = first.json()
    assert created["build_key"] == "ci-1001"
    assert created["version"] == "1.2.3"
    assert created["identity_state"] == "pending"
    assert created["apk_digest_verified"] is False

    again = _register(client, project)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == created["id"]
    assert again.json()["duplicate"] is True

    conflict = _register(client, project, version="9.9.9")
    assert conflict.status_code == 409, conflict.text
    body = conflict.json()
    assert body["code"] == "build_identity_conflict"
    assert body["details"]["existing_build_id"] == created["id"]
    assert "version" in body["details"]["fields"]

    with sync_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT version, build_key, source_commit, sha256 FROM app_builds"
                " WHERE project_id = CAST(:pid AS uuid) AND build_key = 'ci-1001'"
            ),
            {"pid": project["project_id"]},
        ).all()
    assert len(rows) == 1, "冲突不得新增记录"
    assert rows[0].version == "1.2.3", "冲突不得改写原记录"


def test_register_build_enforces_application_scope_and_sha256(client, project, sync_engine):
    missing = _register(client, project, application_id=str(uuid.uuid4()))
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "not_found"

    bad_digest = _register(client, project, sha256="NOT-HEX")
    assert bad_digest.status_code == 422, bad_digest.text
    assert bad_digest.json()["code"] == "validation_error"

    # INV-09：application 与 build 的 project 归属由服务端从应用推导，
    # 请求体没有可伪造的 project_id（extra=forbid）。
    spoof = _register(client, project, project_id=str(uuid.uuid4()))
    assert spoof.status_code == 422, spoof.text


def test_build_listing_includes_declared_identity_and_verification_note(client, project):
    _build_id(_register(client, project))
    response = client.get(
        "/api/v1/builds", params={"application_id": project["application_id"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    build = body["items"][0]
    assert build["identity_state"] == "pending"
    assert build["baseline"] is None
    assert build["apk_digest_verified"] is False
    note = build["verification_note"]
    assert "未验证" in note and "APK" in note
    assert "APK 摘要已验证" not in note


# --------------------------------------------------------------------------- #
# 身份核对：只读、互斥、记录完整
# --------------------------------------------------------------------------- #


def test_identity_check_is_read_only_and_records_expected_observed(
    client, project, fake_adb, sync_engine
):
    build_id = _build_id(_register(client, project))
    fake_adb.configure(**_device_config(project))
    resource = project["resources"][0]

    response = _check(client, build_id, resource["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "match"
    assert body["execution_allowed"] is True
    assert body["identity_state"] == "pending"
    assert body["verification_level"] == "package_identity_observed"
    assert body["apk_digest_verified"] is False
    assert body["resource"]["id"] == resource["id"]
    assert body["resource"]["serial"] == resource["serial"]
    assert body["checked_at"]
    assert body["expected"] == {
        "package_name": _package(project),
        "version_name": "1.2.3",
        "version_code": None,
    }
    assert body["observed"] == {
        "package_name": _package(project),
        "version_name": "1.2.3",
        "version_code": 42,
    }
    assert {item["name"] for item in body["items"]} == {
        "package_name",
        "version_name",
        "version_code",
    }

    _assert_read_only(fake_adb.calls())

    with sync_engine.connect() as conn:
        state, result, kind = conn.execute(
            text(
                "SELECT state, result, kind FROM device_checks"
                " WHERE project_id = CAST(:pid AS uuid)"
                " ORDER BY created_at DESC LIMIT 1"
            ),
            {"pid": project["project_id"]},
        ).one()
        live = conn.execute(
            text(
                "SELECT count(*) FROM resource_leases"
                " WHERE project_id = CAST(:pid AS uuid) AND released_at IS NULL"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
    assert (state, kind) == ("finished", "identity")
    assert result["check_id"] == body["check_id"]
    assert live == 0, "核对结束必须释放租约"

    listing = client.get(
        "/api/v1/builds", params={"application_id": project["application_id"]}
    ).json()["items"][0]
    assert listing["latest_check"]["check_id"] == body["check_id"]
    assert listing["latest_check"]["result"] == "match"


def test_busy_device_is_not_probed(client, project, fake_adb, make_run, sync_engine):
    build_id = _build_id(_register(client, project))
    fake_adb.configure(**_device_config(project))
    run_id = make_run(state="queued", request_key=str(uuid.uuid4()), project=project)
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_runs SET resource_id = CAST(:rid AS uuid),"
                " profile_id = CAST(:fid AS uuid) WHERE id = CAST(:run AS uuid)"
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

    response = _check(client, build_id, project["resource_id"])
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


def test_unreadable_identity_fields_block(client, project, fake_adb):
    build_id = _build_id(_register(client, project))
    # 包存在但 versionName 读不到：关键字段不可读 -> unknown + blocking。
    fake_adb.configure(
        **_device_config(
            project,
            packages={_package(project): {"versionCode": "42"}},
        )
    )
    response = _check(client, build_id, project["resource_id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "unknown"
    assert body["execution_allowed"] is False
    assert any(item["name"] == "version_name" and item["status"] == "unknown" for item in body["items"])
    assert any(item["check"] == "version_name" for item in body["blocking"])

    _assert_read_only(fake_adb.calls())


def test_uninstalled_package_is_conflict(client, project, fake_adb):
    build_id = _build_id(_register(client, project))
    fake_adb.configure(**_device_config(project, packages={}))
    response = _check(client, build_id, project["resource_id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "conflict"
    assert body["execution_allowed"] is False
    assert any(item["check"] == "package_name" for item in body["blocking"])


# --------------------------------------------------------------------------- #
# AC-BUILD-01：versionName 冲突拒绝确认
# --------------------------------------------------------------------------- #


def test_version_name_conflict_rejects_confirmation(client, project, fake_adb, sync_engine):
    build_id = _build_id(_register(client, project, version="1.2.3"))
    fake_adb.configure(**_device_config(project, version_name="9.9.9"))
    check = _check(client, build_id, project["resource_id"])
    assert check.status_code == 200, check.text
    assert check.json()["result"] == "conflict"

    rejected = _confirm(client, build_id, check.json()["check_id"])
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "build_identity_not_confirmed"
    assert any(
        item["check"] == "version_name"
        for item in rejected.json()["details"]["blocking"]
    )

    listing = client.get(
        "/api/v1/builds", params={"application_id": project["application_id"]}
    ).json()["items"][0]
    assert listing["identity_state"] == "pending"
    assert listing["baseline"] is None


def test_unreadable_check_rejects_confirmation(client, project, fake_adb):
    build_id = _build_id(_register(client, project))
    fake_adb.configure(
        **_device_config(project, packages={_package(project): {"versionCode": "42"}})
    )
    check = _check(client, build_id, project["resource_id"]).json()
    rejected = _confirm(client, build_id, check["check_id"])
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["details"]["result"] == "unknown"


# --------------------------------------------------------------------------- #
# 固定基准：显式确认、幂等、不从另一设备自动学习
# --------------------------------------------------------------------------- #


def test_confirm_identity_fixes_baseline_and_is_idempotent(client, project, fake_adb, sync_engine):
    build_id = _build_id(_register(client, project))
    fake_adb.configure(**_device_config(project))
    check = _check(client, build_id, project["resource_id"]).json()

    confirmed = _confirm(client, build_id, check["check_id"])
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["identity_state"] == "confirmed"
    assert body["verification_level"] == "package_identity_observed"
    assert body["apk_digest_verified"] is False
    assert body["baseline"]["package_name"] == _package(project)
    assert body["baseline"]["version_name"] == "1.2.3"
    assert body["baseline"]["version_code"] == 42
    assert body["baseline"]["resource"]["id"] == project["resource_id"]
    assert body["baseline"]["check_id"] == check["check_id"]

    repeat = _confirm(client, build_id, check["check_id"])
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["baseline"] == body["baseline"], "重复相同确认必须幂等"

    with sync_engine.connect() as conn:
        metadata = conn.execute(
            text(
                "SELECT metadata FROM app_builds WHERE id = CAST(:bid AS uuid)"
            ),
            {"bid": build_id},
        ).scalar_one()
    assert metadata["identity"]["state"] == "confirmed"
    assert metadata["identity"]["baseline"]["version_code"] == 42


def test_confirmed_build_is_not_relearned_from_another_device(client, project, fake_adb):
    build_id = _build_id(_register(client, project))
    device_a, device_b = project["resources"][0], project["resources"][1]

    fake_adb.configure(**_device_config(project, index=0, version_code="42"))
    check_a = _check(client, build_id, device_a["id"]).json()
    assert _confirm(client, build_id, check_a["check_id"]).status_code == 200

    # 另一台设备装了同 versionName、不同 versionCode：与固定基准冲突，不自动改写。
    fake_adb.configure(**_device_config(project, index=1, version_code="43"))
    check_b = _check(client, build_id, device_b["id"])
    assert check_b.status_code == 200, check_b.text
    body_b = check_b.json()
    assert body_b["result"] == "conflict"
    assert body_b["execution_allowed"] is False
    assert any(item["check"] == "version_code" for item in body_b["blocking"])

    rejected = _confirm(client, build_id, body_b["check_id"])
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "build_identity_not_confirmed"
    assert rejected.json()["details"]["reason"] == "baseline_already_confirmed"

    listing = client.get(
        "/api/v1/builds", params={"application_id": project["application_id"]}
    ).json()["items"][0]
    assert listing["baseline"]["resource"]["id"] == device_a["id"]
    assert listing["baseline"]["version_code"] == 42, "基准不得从另一设备静默更新"

    # 同身份的另一台设备：核对通过，但基准仍固定在原设备。
    fake_adb.configure(**_device_config(project, index=1, version_code="42"))
    check_b_same = _check(client, build_id, device_b["id"]).json()
    assert check_b_same["result"] == "match"
    idempotent = _confirm(client, build_id, check_b_same["check_id"])
    assert idempotent.status_code == 200, idempotent.text
    assert idempotent.json()["baseline"]["resource"]["id"] == device_a["id"]


def test_pre_run_recheck_blocks_unconfirmed_and_rechecks_confirmed(client, project, fake_adb):
    build_id = _build_id(_register(client, project))
    fake_adb.configure(**_device_config(project))

    pending = _check(client, build_id, project["resource_id"], purpose="pre_run")
    assert pending.status_code == 422, pending.text
    assert pending.json()["code"] == "build_identity_not_confirmed"
    assert fake_adb.calls() == [], "未固定基准时正式执行复核应在访问设备前拒绝"

    check = _check(client, build_id, project["resource_id"]).json()
    assert _confirm(client, build_id, check["check_id"]).status_code == 200

    ok = _check(client, build_id, project["resource_id"], purpose="pre_run")
    assert ok.status_code == 200, ok.text
    assert ok.json()["result"] == "match"
    assert ok.json()["execution_allowed"] is True

    fake_adb.configure(**_device_config(project, version_code="99"))
    blocked = _check(client, build_id, project["resource_id"], purpose="pre_run")
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["result"] == "conflict"
    assert blocked.json()["execution_allowed"] is False


def test_superseded_check_cannot_be_confirmed(client, project, fake_adb):
    build_id = _build_id(_register(client, project))
    fake_adb.configure(**_device_config(project))
    first = _check(client, build_id, project["resource_id"]).json()
    second = _check(client, build_id, project["resource_id"]).json()
    assert first["check_id"] != second["check_id"]

    rejected = _confirm(client, build_id, first["check_id"])
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["details"]["reason"] == "superseded"

    accepted = _confirm(client, build_id, second["check_id"])
    assert accepted.status_code == 200, accepted.text


def test_identity_scope_is_enforced(client, project, fake_adb, sync_engine):
    build_id = _build_id(_register(client, project))

    # 跨项目设备：不能读取另一个项目的资源。
    other_project_id = str(uuid.uuid4())
    other_node_id = str(uuid.uuid4())
    other_profile_id = str(uuid.uuid4())
    other_resource_id = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, code, name)"
                " VALUES (CAST(:id AS uuid), :code, 'Other')"
            ),
            {"id": other_project_id, "code": "p3test-other-" + uuid.uuid4().hex[:8]},
        )
        conn.execute(
            text(
                "INSERT INTO execution_nodes (id, project_id, name, agent_version, status)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'other-node', 'pytest', 'online')"
            ),
            {"id": other_node_id, "pid": other_project_id},
        )
        conn.execute(
            text(
                "INSERT INTO resource_profiles"
                " (id, project_id, platform, name, fingerprint, spec)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'android', 'other-profile',"
                "         :fp, '{}'::jsonb)"
            ),
            {
                "id": other_profile_id,
                "pid": other_project_id,
                "fp": uuid.uuid4().hex + uuid.uuid4().hex,
            },
        )
        conn.execute(
            text(
                "INSERT INTO execution_resources"
                " (id, project_id, node_id, profile_id, platform, resource_key, kind, status)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:nid AS uuid),"
                "         CAST(:fid AS uuid), 'android', :key, 'device', 'ready')"
            ),
            {
                "id": other_resource_id,
                "pid": other_project_id,
                "nid": other_node_id,
                "fid": other_profile_id,
                "key": "OTHER-" + uuid.uuid4().hex[:6],
            },
        )

    cross = _check(client, build_id, other_resource_id)
    assert cross.status_code == 404, cross.text
    assert fake_adb.calls() == [], "跨项目资源不得触发设备访问"

    # iOS/Web 应用没有 Android 安装包身份可读。
    ios_app_id = str(uuid.uuid4())
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO applications (id, project_id, platform, name, identifier)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'ios', 'iOS App', :ident)"
            ),
            {
                "id": ios_app_id,
                "pid": project["project_id"],
                "ident": "com.example.ios" + uuid.uuid4().hex[:6],
            },
        )
    ios_build = _build_id(_register(client, project, application_id=ios_app_id, build_key="ios-1"))
    unsupported = _check(client, ios_build, project["resource_id"])
    assert unsupported.status_code == 422, unsupported.text
    assert unsupported.json()["code"] == "identity_unsupported"

    # 清理另一项目（无从属运行数据，按外键顺序删资源 / 节点 / 档案 / 项目）。
    with sync_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM execution_resources WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": other_project_id},
        )
        conn.execute(
            text("DELETE FROM execution_nodes WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": other_project_id},
        )
        conn.execute(
            text("DELETE FROM resource_profiles WHERE project_id = CAST(:pid AS uuid)"),
            {"pid": other_project_id},
        )
        conn.execute(
            text("DELETE FROM projects WHERE id = CAST(:pid AS uuid)"),
            {"pid": other_project_id},
        )
