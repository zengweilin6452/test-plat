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
from pathlib import Path

import pytest
from app.main import app  # noqa: F401
from app.runner import dispatch_runner
from app.scheduler import dispatcher
from sqlalchemy import text

from tests._p3_common import TEST_DB, reset_db_engine, requires_db
from tests._p3_common import CLIENT_HEADERS
from tests._p3_common import make_run as make_run  # noqa: F401 - 夹具注册
from tests._p3_common import api_client as client  # noqa: F401
from tests._p3_common import p3_project as project  # noqa: F401
from tests._p3_common import sync_engine as sync_engine  # noqa: F401
from tests._p3_common import p3_project as project
from tests._p3_common import sync_engine as sync_engine

pytestmark = requires_db


@pytest.fixture(autouse=True)
def isolated_code_copies(tmp_path, monkeypatch):
    """把固定副本根收敛到用例临时目录：不往共享 data/ 里堆副本。"""
    root = tmp_path / "code-copies"
    root.mkdir()
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(root))
    yield root


@pytest.fixture
def spawns(monkeypatch):

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


def test_dispatch_records_started_at_and_finalize_keeps_started_before_ended(
    client, project, make_run, sync_engine, spawns, fake_adb, tmp_path
):
    """领取阶段写 started_at，收敛 completed 后 started_at < ended_at。

    2026-11-08 真机验收（release-readiness 02）发现：started_at 留空到收敛，
    由 finalize 在同一事务里回填 now()，与 ended_at 同值——报告耗时恒为 0s，
    started_at 也不再反映真实执行起点。
    """
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

    with sync_engine.connect() as conn:
        started = conn.execute(
            text("SELECT started_at FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar_one()
    assert started is not None, "领取（lease_acquired）必须写入 started_at"

    # 模拟 runner 退出后的收敛事务（独立的、晚于领取的收敛事务）
    from app import runtime

    artifacts = tmp_path / "artifacts-started-at"
    artifacts.mkdir()
    (artifacts / "junit.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<testsuites><testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="t" name="test_a" time="0.1"/>'
        "</testsuite></testsuites>\n",
        encoding="utf-8",
    )
    reset_db_engine(TEST_DB)
    asyncio.run(
        runtime.finalize_run(
            run_id=run_id,
            state="completed",
            artifacts_dir=artifacts,
            release_lease_reason="pytest",
        )
    )
    with sync_engine.connect() as conn:
        ended = conn.execute(
            text("SELECT ended_at FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar_one()
    assert ended is not None
    assert started < ended, "收敛事务晚于领取事务，ended_at 必须严格晚于 started_at"


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


# --------------------------------------------------------------------------- #
# 工单 01：派发把固定副本根 + 套件版本身份交给执行器
# --------------------------------------------------------------------------- #
def _suite_code_copy(conn, suite_version_id: str) -> dict:
    row = conn.execute(
        text(
            "SELECT manifest->'code_copy' FROM suite_versions WHERE id = CAST(:sid AS uuid)"
        ),
        {"sid": suite_version_id},
    ).scalar_one()
    return row if isinstance(row, dict) else json.loads(row)


def test_spawn_config_carries_suite_version_and_tree_digest(
    client, project, make_run, spawns, sync_engine
):
    """派发路径提供 suite_root + suite_version_id + code_copy.tree_sha256。"""
    import asyncio

    from app.integrations import discover

    from app.scheduler.dispatcher import dispatch_one

    with sync_engine.connect() as conn:
        code_copy = _suite_code_copy(conn, project["suite_version_id"])
    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is True, outcome.reason
    config = spawns[0]["config"]
    assert config["suite_root"], "执行配置必须指向固定副本"
    assert Path(config["suite_root"]) == discover.verify_code_copy(code_copy)
    assert config["suite_version_id"] == project["suite_version_id"]
    assert config["suite_sha256"] == code_copy["tree_sha256"]


def test_dispatch_blocked_when_copy_content_tampered(
    client, project, make_run, spawns, sync_engine
):
    """副本内容与树摘要不符：派发前阻断 (errored)，不 spawn、不回退来源目录。"""
    import asyncio

    from app.integrations import discover

    from app.scheduler.dispatcher import dispatch_one

    with sync_engine.connect() as conn:
        code_copy = _suite_code_copy(conn, project["suite_version_id"])
    copy_root = discover.verify_code_copy(code_copy)
    (copy_root / "tests" / "test_smoke.py").write_text(
        "# tampered after publish\n", encoding="utf-8"
    )

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))
    outcome = asyncio.run(dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "execution_copy_missing"
    assert spawns == [], "副本摘要不符不得派发"
    with sync_engine.connect() as conn:
        state = conn.execute(
            text("SELECT state FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).scalar_one()
        live = conn.execute(
            text(
                "SELECT count(*) FROM resource_leases"
                " WHERE released_at IS NULL AND project_id = CAST(:pid AS uuid)"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
    assert state == "errored"
    assert live == 0


def test_cancel_requested_in_dispatch_window_blocks_spawn(
    client, project, make_run, spawns, sync_engine, monkeypatch
):
    """queued->dispatching 提交后、spawn 前被取消：不得再拉起 runner。

    事务提交与 spawn 之间（包含身份复核/模板核对这段耗时）是一个真实窗口：
    取消在这段时间被受理时，旧代码仍会 spawn 一个已经没人要的 runner。派发前
    必须复查 cancel_requested_at/state，把收敛留给取消处理路径。
    """
    import asyncio

    from app.scheduler import dispatcher

    run_id = make_run(state="queued", request_key=str(uuid.uuid4()))

    async def _cancelled_during_window(rid, *, serial):
        # 事务已提交，此时取消被受理（模拟真实窗口）
        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE test_runs SET cancel_requested_at = now()"
                    " WHERE id = CAST(:id AS uuid)"
                ),
                {"id": str(rid)},
            )
        return {"verdict": "skipped", "reason": "no_build", "detail": "测试替身"}

    monkeypatch.setattr(dispatcher, "_verify_build_identity", _cancelled_during_window)

    outcome = asyncio.run(dispatcher.dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "cancel_requested"
    assert spawns == [], "取消已受理时不得 spawn runner"

    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT state, reason_code FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).mappings().one()
        live = conn.execute(
            text(
                "SELECT count(*) FROM resource_leases"
                " WHERE released_at IS NULL AND project_id = CAST(:pid AS uuid)"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
    # 派发侧不写 errored：终态与租约由取消受理路径收敛（当前停在 dispatching，
    # reason_code 仍是领取阶段的 lease_acquired，没有被写成任何错误码）
    assert row["state"] == "dispatching"
    assert row["reason_code"] == "lease_acquired"
    assert live == 1

    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=CLIENT_HEADERS)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "cancelled"
    with sync_engine.connect() as conn:
        live = conn.execute(
            text(
                "SELECT count(*) FROM resource_leases"
                " WHERE released_at IS NULL AND project_id = CAST(:pid AS uuid)"
            ),
            {"pid": project["project_id"]},
        ).scalar_one()
    assert live == 0, "取消收敛后设备必须被释放"
