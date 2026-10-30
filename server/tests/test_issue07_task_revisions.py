"""工单 07：任务修订、同名冲突与幂等（AC-CONTRACT-01 / AC-CONTRACT-02）。

覆盖：
  - 同应用同名同内容复用原任务；换构建/套件/config 返回 409 task_configuration_conflict，
    details 带 existing_task_id 与差异字段名，且不新增任务或修订
  - 幂等键绑定规范化内容并落库：同键同内容复用（跨进程/重启），同键不同内容 409
    idempotency_conflict 且无副作用
  - PATCH 追加 draft 修订、config 整份替换（不深合并）、省略绑定字段表示不变
  - validate 成功追加 validated 修订，响应中的 revision.id 就是后续执行引用
  - 并发修改返回 stale_version，且不产生多余修订
  - 旧修订与旧运行引用不被回写
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

pytest_plugins = ("_p2_common",)

from _p2_common import CLIENT_HEADERS, TEST_DB, _exec_sync  # noqa: E402

pytestmark = pytest.mark.integration

if not TEST_DB:
    pytest.skip(
        "需要 TESTDOCK_TEST_DATABASE_URL 才能跑工单 07 集成测试",
        allow_module_level=True,
    )


# --------------------------------------------------------------------------- #
# 造数
# --------------------------------------------------------------------------- #
def _payload(seed, **overrides):
    body = {
        "name": "登录冒烟",
        "test_type": "ui",
        "platform": "android",
        "application_id": seed["application_id"],
        "config": {"package_name": "com.example.demo", "app_version": "1.0.0"},
    }
    body.update(overrides)
    return body


def _post(api_client, seed, *, headers=None, params=None, **overrides):
    return api_client.post(
        "/api/v1/tasks",
        json=_payload(seed, **overrides),
        headers=headers or CLIENT_HEADERS,
        params=params or {},
    )


def _create(api_client, seed, **overrides):
    resp = _post(api_client, seed, **overrides)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_build(seed, build_key: str) -> str:
    build_id = str(uuid.uuid4())
    _exec_sync(
        """
        INSERT INTO app_builds (id, project_id, application_id, version, build_key)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), '1.0.0', :key)
        """,
        {
            "id": build_id,
            "pid": seed["project_id"],
            "aid": seed["application_id"],
            "key": build_key,
        },
    )
    return build_id


def _make_ui_suite_version(seed, *, name: str) -> str:
    """给 android 应用造一个 UI 套件与 V1 版本（带用例与固定副本，可过 readiness）。"""
    suite_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    _exec_sync(
        """
        INSERT INTO test_suites (id, project_id, application_id, name, test_type)
        VALUES (CAST(:sid AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), :name, 'ui')
        """,
        {
            "sid": suite_id,
            "pid": seed["project_id"],
            "aid": seed["application_id"],
            "name": name,
        },
    )
    manifest = {
        "schema_version": 1,
        "test_type": "ui",
        "case_count": 1,
        "cases": [{"case_key": "tests/test_login.py::test_ok", "node_id": "tests/test_login.py::test_ok"}],
        "code_copy": {"root_rel": "copies/v1", "files": [], "file_count": 0},
    }
    _exec_sync(
        """
        INSERT INTO suite_versions
            (id, project_id, application_id, suite_id, version, source_ref, source_commit, manifest)
        VALUES (CAST(:vid AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), CAST(:sid AS uuid),
                1, 'local', 'local', CAST(:manifest AS jsonb))
        """,
        {
            "vid": version_id,
            "pid": seed["project_id"],
            "aid": seed["application_id"],
            "sid": suite_id,
            "manifest": json.dumps(manifest),
        },
    )
    return version_id


def _task_count(seed, name: str) -> int:
    rows = _exec_sync(
        "SELECT count(*) AS n FROM test_tasks WHERE project_id = CAST(:pid AS uuid) AND name = :name",
        {"pid": seed["project_id"], "name": name},
    )
    return int(rows[0]["n"])


def _revision_count(seed) -> int:
    rows = _exec_sync(
        "SELECT count(*) AS n FROM task_revisions WHERE project_id = CAST(:pid AS uuid)",
        {"pid": seed["project_id"]},
    )
    return int(rows[0]["n"])


# --------------------------------------------------------------------------- #
# AC-CONTRACT-01：同名复用只发生在内容一致时
# --------------------------------------------------------------------------- #
def test_same_name_same_content_reuses_task(api_client, seed):
    first = _create(api_client, seed)
    second = _post(api_client, seed)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first["id"]
    assert second.json()["revision_count"] == 1
    assert _task_count(seed, "登录冒烟") == 1


def test_same_name_different_build_is_configuration_conflict(api_client, seed):
    build_a = _make_build(seed, "ci-a")
    build_b = _make_build(seed, "ci-b")
    first = _create(api_client, seed, build_id=build_a)

    resp = _post(api_client, seed, build_id=build_b)
    assert resp.status_code == 409, resp.text
    envelope = resp.json()
    assert envelope["code"] == "task_configuration_conflict"
    details = envelope["details"]
    assert details["existing_task_id"] == first["id"]
    assert "build_id" in details["fields"]
    # 不回显配置内容，只给字段名
    assert build_b not in resp.text

    # 不得新增任务或修订，原任务保持原样
    assert _task_count(seed, "登录冒烟") == 1
    assert _revision_count(seed) == 1
    latest = api_client.get(f"/api/v1/tasks/{first['id']}").json()
    assert latest["revision"]["build_id"] == build_a


def test_same_name_different_suite_is_configuration_conflict(api_client, seed):
    version_a = _make_ui_suite_version(seed, name=f"ui-a-{seed['suffix']}")
    version_b = _make_ui_suite_version(seed, name=f"ui-b-{seed['suffix']}")
    _create(api_client, seed, suite_version_id=version_a)

    resp = _post(api_client, seed, suite_version_id=version_b)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "task_configuration_conflict"
    assert "suite_version_id" in resp.json()["details"]["fields"]


def test_same_name_different_config_is_configuration_conflict(api_client, seed):
    _create(api_client, seed)
    resp = _post(api_client, seed, config={"package_name": "com.example.demo", "app_version": "2.0.0"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "task_configuration_conflict"
    assert "config" in resp.json()["details"]["fields"]


# --------------------------------------------------------------------------- #
# 幂等键：跨进程/重启复用，同键不同内容冲突
# --------------------------------------------------------------------------- #
def test_idempotency_key_is_persisted_and_reused(api_client, seed):
    key = f"idem-{seed['suffix']}"
    first = _post(api_client, seed, params={"request_key": key})
    assert first.status_code == 201, first.text
    task_id = first.json()["id"]

    rows = _exec_sync(
        "SELECT request_key, fingerprint, task_id FROM task_request_keys "
        " WHERE project_id = CAST(:pid AS uuid) AND request_key = :key",
        {"pid": seed["project_id"], "key": key},
    )
    assert len(rows) == 1, "幂等键必须落库，不能只存在进程内"
    assert str(rows[0]["task_id"]) == task_id
    assert rows[0]["fingerprint"]

    second = _post(api_client, seed, params={"request_key": key})
    assert second.status_code == 200, second.text
    assert second.json()["id"] == task_id
    assert _task_count(seed, "登录冒烟") == 1


def test_idempotency_key_survives_engine_restart(api_client, seed):
    """清掉进程内的引擎/会话缓存，模拟服务重启后仍能复用同一对象。"""
    from app import db as db_mod

    key = f"restart-{seed['suffix']}"
    first = _post(api_client, seed, params={"request_key": key})
    assert first.status_code == 201, first.text

    db_mod._engine = None  # type: ignore[attr-defined]
    db_mod._sessionmaker = None  # type: ignore[attr-defined]

    second = _post(api_client, seed, params={"request_key": key})
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["revision_count"] == 1


def test_idempotency_key_with_different_content_conflicts(api_client, seed):
    key = f"idem-conflict-{seed['suffix']}"
    first = _post(api_client, seed, params={"request_key": key})
    assert first.status_code == 201, first.text

    resp = _post(
        api_client,
        seed,
        params={"request_key": key},
        config={"package_name": "com.example.demo", "app_version": "9.9.9"},
    )
    assert resp.status_code == 409, resp.text
    envelope = resp.json()
    assert envelope["code"] == "idempotency_conflict"
    assert envelope["details"]["existing_task_id"] == first.json()["id"]
    assert _task_count(seed, "登录冒烟") == 1
    assert _revision_count(seed) == 1


def test_idempotency_header_is_honoured(api_client, seed):
    headers = {**CLIENT_HEADERS, "Idempotency-Key": f"hdr-{seed['suffix']}"}
    first = _post(api_client, seed, headers=headers)
    second = _post(api_client, seed, headers=headers)
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]


# --------------------------------------------------------------------------- #
# PATCH：新修订、整份替换、省略即不变
# --------------------------------------------------------------------------- #
def test_patch_replaces_config_without_deep_merge(api_client, seed):
    created = _create(api_client, seed, config={"a": {"b": 1, "c": 2}, "keep": "x"})
    resp = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "config": {"a": {"b": 9}}},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["revision"]["config"] == {"a": {"b": 9}}


def test_patch_omitted_binding_fields_are_unchanged(api_client, seed):
    build_id = _make_build(seed, "keep-build")
    version_id = _make_ui_suite_version(seed, name=f"keep-{seed['suffix']}")
    created = _create(api_client, seed, build_id=build_id, suite_version_id=version_id)

    resp = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "name": "只改名字"},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    revision = resp.json()["revision"]
    assert revision["revision"] == 2
    assert revision["build_id"] == build_id
    assert revision["suite_version_id"] == version_id
    assert revision["environment_id"] == created["revision"]["environment_id"]
    assert revision["config"] == created["revision"]["config"]
    assert revision["readiness"] == "draft"


def test_stale_patch_does_not_append_revision(api_client, seed):
    created = _create(api_client, seed)
    first = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "name": "第一次改"},
        headers=CLIENT_HEADERS,
    )
    assert first.status_code == 200, first.text

    stale = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "name": "第二次改"},
        headers=CLIENT_HEADERS,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_version"
    assert _revision_count(seed) == 2, "并发失败不得留下多余修订"


# --------------------------------------------------------------------------- #
# validate：追加 validated 修订，响应即最新引用
# --------------------------------------------------------------------------- #
def _ready_task(api_client, seed):
    build_id = _make_build(seed, f"ready-{seed['suffix']}")
    version_id = _make_ui_suite_version(seed, name=f"ready-{seed['suffix']}")
    return _create(api_client, seed, build_id=build_id, suite_version_id=version_id)


def test_validate_appends_validated_revision_and_adopts_it(api_client, seed):
    created = _ready_task(api_client, seed)
    draft_revision_id = created["revision"]["id"]

    resp = api_client.post(f"/api/v1/tasks/{created['id']}/validate", headers=CLIENT_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lifecycle"] == "ready"
    assert body["lock_version"] == 2
    assert body["revision"]["id"] != draft_revision_id
    assert body["revision"]["revision"] == 2
    assert body["revision"]["readiness"] == "validated"
    assert body["revision"]["config"] == created["revision"]["config"]

    # 页面后续必须用响应里的 revision.id：详情与修订历史都指向它
    latest = api_client.get(f"/api/v1/tasks/{created['id']}").json()
    assert latest["revision"]["id"] == body["revision"]["id"]
    revisions = api_client.get(f"/api/v1/tasks/{created['id']}/revisions").json()
    by_id = {item["id"]: item for item in revisions["items"]}
    assert by_id[draft_revision_id]["readiness"] == "draft", "原修订不得被回写成 validated"
    assert by_id[body["revision"]["id"]]["readiness"] == "validated"


def test_validate_concurrent_modification_returns_stale_version(api_client, seed, monkeypatch):
    """让读取到的 lock_version 比库里小 1，模拟"读后到写前被别人改了"。"""
    from app.services import tasks as task_service

    created = _ready_task(api_client, seed)
    real_fetch = task_service._fetch_task_bundle

    async def stale_fetch(session, task_id, *, for_update=False):
        bundle = await real_fetch(session, task_id, for_update=for_update)
        if bundle is not None:
            bundle = {**bundle, "lock_version": bundle["lock_version"] - 1}
        return bundle

    monkeypatch.setattr(task_service, "_fetch_task_bundle", stale_fetch)
    resp = api_client.post(f"/api/v1/tasks/{created['id']}/validate", headers=CLIENT_HEADERS)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "stale_version"

    monkeypatch.undo()
    assert _revision_count(seed) == 1, "CAS 失败不得追加 validated 修订"


# --------------------------------------------------------------------------- #
# 旧修订与旧运行引用不被回写
# --------------------------------------------------------------------------- #
def test_old_revision_and_run_reference_are_not_rewritten(api_client, seed):
    build_id = _make_build(seed, "history-build")
    created = _create(api_client, seed, build_id=build_id)
    old_revision_id = created["revision"]["id"]
    run_id = str(uuid.uuid4())
    _exec_sync(
        """
        INSERT INTO test_runs
            (id, project_id, application_id, platform, revision_id, request_key,
             state, ended_at, config_snapshot, created_by)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid), 'android',
                CAST(:rid AS uuid), :key, 'cancelled', now(), '{}'::jsonb, 'test')
        """,
        {
            "id": run_id,
            "pid": seed["project_id"],
            "aid": seed["application_id"],
            "rid": old_revision_id,
            "key": f"run-{seed['suffix']}",
        },
    )

    patched = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "config": {"package_name": "com.changed"}},
        headers=CLIENT_HEADERS,
    )
    assert patched.status_code == 200, patched.text

    run_rows = _exec_sync(
        "SELECT revision_id, state FROM test_runs WHERE id = CAST(:id AS uuid)",
        {"id": run_id},
    )
    assert str(run_rows[0]["revision_id"]) == old_revision_id, "旧运行必须仍指向旧修订"

    old_rows = _exec_sync(
        "SELECT readiness, config FROM task_revisions WHERE id = CAST(:id AS uuid)",
        {"id": old_revision_id},
    )
    assert old_rows[0]["readiness"] == "draft"
    assert old_rows[0]["config"]["package_name"] == "com.example.demo"
