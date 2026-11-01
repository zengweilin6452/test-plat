"""工单 24：执行接线——运行前身份复核与固定代码副本（真实 PG，定向测试）。

覆盖（工单 04/05 的接线缺口）：

- 派发读取固定代码副本：副本缺失/损坏 → errored(execution_copy_missing)，设备释放；
- 副本可用时 spawn 配置携带 suite_root（执行读副本，不读可变来源）；
- 运行租约内复核构建身份：只读 dumpsys；未学习（pending）→ 不阻断但记录；
  与固定基准冲突 → errored(identity_mismatch)；测试用替身 adb，不访问真机。
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from app.main import app  # noqa: F401
from app.runner import dispatch_runner
from app.scheduler import dispatcher
from sqlalchemy import text

from tests._p3_common import TEST_DB, reset_db_engine, requires_db
from tests._p3_common import make_run as make_run  # noqa: F401 - 夹具注册
from tests._p3_common import api_client as client  # noqa: F401
from tests._p3_common import p3_project as project  # noqa: F401
from tests._p3_common import sync_engine as sync_engine  # noqa: F401
from tests._p3_common import p3_project as project
from tests._p3_common import sync_engine as sync_engine

pytestmark = requires_db


@pytest.fixture
def spawns(monkeypatch):
    from app.config import settings as app_settings

    reset_db_engine(TEST_DB)
    calls = []

    async def spawn(**kwargs):
        calls.append(kwargs)
        return 123456

    monkeypatch.setattr(dispatch_runner, "_spawner", spawn)
    yield calls
    reset_db_engine(TEST_DB)


FAKE_ADB_PY = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_ADB_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": args}) + "\n")
cfg = json.load(open(os.environ["FAKE_ADB_CONFIG"], encoding="utf-8"))
if args[:2] == ["devices", "-l"]:
    print("List of devices attached")
    for device in cfg.get("devices", []):
        print(device["serial"] + "\tdevice")
    sys.exit(0)
if args and args[0] == "-s":
    command = args[3] if len(args) > 3 else ""
    if command.startswith("dumpsys package"):
        package = command.split()[-1]
        entry = (cfg.get("packages") or {}).get(package)
        if entry is None:
            print("Unable to find package: " + package)
        else:
            print("Packages:")
            print("  Package [" + package + "] (abc):")
            if not entry.get("omit_version_code"):
                print("    versionCode=" + str(entry.get("versionCode", 42)) + " minSdk=24")
            if entry.get("versionName"):
                print("    versionName=" + entry["versionName"])
sys.exit(0)
'''


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    script = tmp_path / "fake_adb.py"
    script.write_text(FAKE_ADB_PY, encoding="utf-8")
    bat = tmp_path / "adb.bat"
    bat.write_text(f'@echo off\r\n"{os.sys.executable}" "{script}" %*\r\n', encoding="utf-8")
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


def _learn_identity(engine, project: dict, version_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE app_builds SET metadata = CAST(:meta AS jsonb)"
                " WHERE id = CAST(:bid AS uuid)"
            ),
            {
                "bid": project["build_id"],
                "meta": json.dumps(
                    {
                        "identity": {
                            "state": "confirmed",
                            "baseline": {
                                "package_name": f"com.example.p3{project['suffix']}",
                                "version_name": version_name,
                            },
                        }
                    }
                ),
            },
        )


def test_dispatch_blocked_when_code_copy_missing(client, project, make_run, sync_engine, spawns):
    """副本损坏：派发收敛 errored(execution_copy_missing)，租约释放，不 spawn。"""
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE suite_versions SET manifest = manifest || '{\"code_copy\":"
                " {\"schema_version\": 1, \"root_rel\": \"gone/copies\"}}'::jsonb"
                " WHERE id = CAST(:sid AS uuid)"
            ),
            {"sid": project["suite_version_id"]},
        )
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "execution_copy_missing"


def test_dispatch_happy_path_passes_suite_root_and_verifies_identity(
    client, project, make_run, sync_engine, spawns, fake_adb
):
    """副本可用 + 身份一致：spawn 配置带 suite_root，事件记录复核结论。"""
    _learn_identity(sync_engine, project, "1.0.0")
    fake_adb.configure(
        devices=[{"serial": project["resources"][0]["serial"]}],
        packages={
            f"com.example.p3{project['suffix']}": {"versionName": "1.0.0"}
        },
    )
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is True, outcome.reason
    assert spawns, "spawn 必须发生"
    assert spawns[0]["config"].get("suite_root"), "执行配置必须指向固定副本"
    # 只读命令：白名单内，不含 install/tcpip 等写操作
    tokens = [token.lower() for call in fake_adb.calls() for token in call["argv"]]
    assert not {"install", "tcpip", "connect", "push", "reboot"} & set(tokens)


def test_identity_mismatch_blocks_dispatch(client, project, make_run, sync_engine, spawns, fake_adb):
    """设备上的 versionName 与固定基准不一致：errored(identity_mismatch)，不 spawn。"""
    _learn_identity(sync_engine, project, "9.9.9")
    fake_adb.configure(
        devices=[{"serial": project["resources"][0]["serial"]}],
        packages={f"com.example.p3{project['suffix']}": {"versionName": "1.0.0"}},
    )
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    import asyncio as _a
    from app.scheduler.dispatcher import _verify_build_identity
    probe = _a.run(_verify_build_identity(run_id, serial=project["resources"][0]["serial"]))
    outcome = asyncio.run(dispatch_one())
    assert outcome.ok is False
    assert outcome.reason == "identity_mismatch"
    assert spawns == []
    with sync_engine.connect() as conn:
        state = conn.execute(
            text("SELECT state FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": outcome.run_id},
        ).scalar_one()
        reason_code = conn.execute(
            text("SELECT reason_code FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": outcome.run_id},
        ).scalar_one()
    assert state == "errored"
    # 页面「原因」显示真实原因，而不是笼统的 runner_spawn_failed。
    assert reason_code == "identity_mismatch"
    events = _identity_events(sync_engine, outcome.run_id)
    mismatch = next(e for e in events if e["event_type"] == "identity_mismatch")
    assert mismatch["payload"]["verdict"] == "mismatch"
    assert mismatch["payload"]["execution_allowed"] is False
    assert mismatch["payload"]["apk_digest_verified"] is False
    # 租约必须释放：设备不能被失败运行占死（限定本测试项目，避免共享库串扰）
    with sync_engine.connect() as conn:
        live = conn.execute(
            text(
                "SELECT count(*) FROM resource_leases "
                "WHERE released_at IS NULL AND project_id = CAST(:pid AS uuid)"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
    assert live == 0


def test_identity_pending_does_not_block_dispatch(client, project, make_run, sync_engine, spawns, fake_adb):
    """构建身份未学习：不冒充通过也不阻断，正常派发。"""
    with sync_engine.begin() as conn:
        conn.execute(
            text("UPDATE app_builds SET metadata = '{}'::jsonb WHERE id = CAST(:bid AS uuid)"),
            {"bid": project["build_id"]},
        )
    fake_adb.configure(devices=[{"serial": project["resources"][0]["serial"]}], packages={})
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is True, outcome.reason
    # 不阻断，但事件必须明确写成「未复核」，不能冒充已验证。
    unverified = [
        event for event in _identity_events(sync_engine, run_id)
        if event["event_type"] == "identity_unverified"
    ]
    assert unverified, "pending 身份必须留下未复核事件"
    payload = unverified[0]["payload"]
    assert payload["verdict"] == "skipped"
    assert payload["execution_allowed"] is False
    assert payload["apk_digest_verified"] is False
    assert "未" in str(payload["note"]) and "复核" in str(payload["note"])


def _run_identity_state(engine, run_id: str) -> tuple[str, str | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT state, reason_code FROM test_runs WHERE id = CAST(:id AS uuid)"
            ),
            {"id": run_id},
        ).mappings().one()
    return row["state"], row["reason_code"]


def _identity_events(engine, run_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT event_type, payload FROM run_events"
                " WHERE run_id = CAST(:id AS uuid) ORDER BY sequence"
            ),
            {"id": run_id},
        ).mappings().all()
    return [dict(row) for row in rows]


def test_identity_unreadable_blocks_dispatch_with_readable_reason(
    client, project, make_run, sync_engine, spawns, fake_adb
):
    """设备上包存在但读不到 versionName：必须阻断运行并说明原因，不冒充通过。"""
    _learn_identity(sync_engine, project, "1.0.0")
    fake_adb.configure(
        devices=[{"serial": project["resources"][0]["serial"]}],
        # 包已安装但没有 versionName：只读读取结果不可用。
        packages={f"com.example.p3{project['suffix']}": {"versionCode": 42}},
    )
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "identity_unreadable"
    assert spawns == [], "身份不可读时不得拉起执行进程"
    state, reason_code = _run_identity_state(sync_engine, run_id)
    assert state == "errored"
    assert reason_code == "identity_unreadable"
    # 原因必须可读（指名缺失的字段/包），不能只给一个错误码。
    errored = [
        event for event in _identity_events(sync_engine, run_id)
        if event["event_type"] in ("identity_unreadable", "error")
    ]
    messages = " ".join(str(event["payload"].get("message") or event["payload"].get("detail") or "")
                        for event in errored)
    assert "versionName" in messages or "version_name" in messages, messages
    with sync_engine.connect() as conn:
        live = conn.execute(
            text(
                "SELECT count(*) FROM resource_leases"
                " WHERE released_at IS NULL AND project_id = CAST(:pid AS uuid)"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
    assert live == 0, "阻断后必须释放设备租约"


def test_identity_baseline_package_name_is_validated_before_device_access(
    client, project, make_run, sync_engine, spawns, fake_adb
):
    """基准包名不合法时不得拼进 shell 命令，也不得访问设备。"""
    injected = "com.example.p3" + project["suffix"] + "; reboot"
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE app_builds SET metadata = CAST(:meta AS jsonb)"
                " WHERE id = CAST(:bid AS uuid)"
            ),
            {
                "bid": project["build_id"],
                "meta": json.dumps(
                    {
                        "identity": {
                            "state": "confirmed",
                            "baseline": {"package_name": injected, "version_name": "1.0.0"},
                        }
                    }
                ),
            },
        )
    fake_adb.configure(devices=[{"serial": project["resources"][0]["serial"]}], packages={})
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "identity_unreadable"
    assert fake_adb.calls() == [], "非法包名不得触达 adb"
    state, reason_code = _run_identity_state(sync_engine, run_id)
    assert (state, reason_code) == ("errored", "identity_unreadable")


def test_identity_version_code_unreadable_blocks_instead_of_claiming_verified(
    client, project, make_run, sync_engine, spawns, fake_adb
):
    """基准固定了 versionCode，但设备读不到该字段：不能写成已验证。"""
    package = f"com.example.p3{project['suffix']}"
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE app_builds SET metadata = CAST(:meta AS jsonb)"
                " WHERE id = CAST(:bid AS uuid)"
            ),
            {
                "bid": project["build_id"],
                "meta": json.dumps(
                    {
                        "identity": {
                            "state": "confirmed",
                            "baseline": {
                                "package_name": package,
                                "version_name": "1.0.0",
                                "version_code": 42,
                            },
                        }
                    }
                ),
            },
        )
    fake_adb.configure(
        devices=[{"serial": project["resources"][0]["serial"]}],
        packages={package: {"versionName": "1.0.0", "omit_version_code": True}},
    )
    import asyncio

    from app.scheduler.dispatcher import dispatch_one

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "identity_unreadable"
    assert spawns == [], "关键字段不可读时不得冒充已验证"
    state, reason_code = _run_identity_state(sync_engine, run_id)
    assert (state, reason_code) == ("errored", "identity_unreadable")
    unreadable = next(
        event for event in _identity_events(sync_engine, run_id)
        if event["event_type"] == "identity_unreadable"
    )
    assert "versionCode" in str(unreadable["payload"]["detail"])
    assert unreadable["payload"]["execution_allowed"] is False


