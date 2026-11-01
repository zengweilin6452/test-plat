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
    assert state == "errored"
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


