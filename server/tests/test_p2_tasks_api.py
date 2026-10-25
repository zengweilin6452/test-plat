"""P2 任务与修订 API 集成测试（需要真实 PostgreSQL）。

覆盖任务书要求的全部关键路径：
  - POST /tasks              一次事务里建 test_tasks + 第一条 draft 修订，201
  - 幂等创建                 同 key 重复提交不产生第二条任务
  - GET   /tasks/{id}        任务 + 最新修订 + 最近 run
  - PATCH /tasks/{id}        lock_version CAS，冲突 409 + details 带最新对象
  - POST  /tasks/{id}/validate  缺件 422 task_not_ready（details 列 missing）
  - POST  /tasks/{id}/archive   幂等；归档后不可 PATCH（409 illegal_transition）
  - GET   /tasks/{id}/revisions 倒序
  - 缺 X-TestDock-Client     428 client_header_required

没有 TESTDOCK_TEST_DATABASE_URL 时整体 skip（与 P1 只读测试口径一致）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/ 不是包、也不在 sys.path（pytest 的 rootdir 是 server/），
# 这里显式把本目录塞进去，才能 import 同目录的 _p2_common。
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# fixture 定义在 _p2_common 里，通过 pytest_plugins 注册到本模块。
pytest_plugins = ("_p2_common",)

from _p2_common import CLIENT_HEADERS, TEST_DB  # noqa: E402

pytestmark = pytest.mark.integration

if not TEST_DB:
    pytest.skip(
        "需要 TESTDOCK_TEST_DATABASE_URL 才能跑 P2 集成测试",
        allow_module_level=True,
    )


def _payload(seed, **overrides):
    body = {
        "name": "核心链路冒烟",
        "test_type": "ui",
        "platform": "android",
        "application_id": seed["application_id"],
        "config": {"package_name": "com.example.demo", "app_version": "1.0.0"},
    }
    body.update(overrides)
    return body


def _create(api_client, seed, **overrides):
    resp = api_client.post("/api/v1/tasks", json=_payload(seed, **overrides), headers=CLIENT_HEADERS)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# 创建
# --------------------------------------------------------------------------- #
def test_create_task_writes_task_and_first_draft_revision(api_client, seed):
    body = _create(api_client, seed)

    assert body["id"]
    assert body["display_id"] == f"TASK-{body['id']}"
    assert body["name"] == "核心链路冒烟"
    assert body["lifecycle"] == "draft"
    assert body["lock_version"] == 1
    assert body["platform"] == "android"
    assert body["application"]["id"] == seed["application_id"]

    revision = body["revision"]
    assert revision["revision"] == 1
    assert revision["readiness"] == "draft"
    assert revision["test_type"] == "ui"
    assert revision["build_id"] is None
    assert revision["suite_version_id"] is None
    # environment_id 是 NOT NULL，缺省回落到项目下的 environment
    assert revision["environment_id"] == seed["environment_id"]
    assert body["readiness"] == "draft"
    assert body["revision_count"] == 1
    assert body["run"] is None


def test_create_task_is_idempotent_with_request_key(api_client, seed):
    key = f"req-{seed['suffix']}"
    first = api_client.post(
        "/api/v1/tasks",
        json=_payload(seed),
        headers=CLIENT_HEADERS,
        params={"request_key": key},
    )
    assert first.status_code == 201, first.text
    second = api_client.post(
        "/api/v1/tasks",
        json=_payload(seed),
        headers=CLIENT_HEADERS,
        params={"request_key": key},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["revision_count"] == 1

    listing = api_client.get("/api/v1/tasks", params={"q": "核心链路冒烟"}).json()
    matching = [i for i in listing["items"] if i["id"] == first.json()["id"]]
    assert len(matching) == 1


def test_create_task_without_client_header_is_428(api_client, seed):
    resp = api_client.post("/api/v1/tasks", json=_payload(seed))
    assert resp.status_code == 428, resp.text
    envelope = resp.json()
    assert envelope["code"] == "client_header_required"
    assert envelope["request_id"]
    assert "details" in envelope


def test_create_task_validates_body(api_client, seed):
    resp = api_client.post(
        "/api/v1/tasks",
        json=_payload(seed, name=""),
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# 详情
# --------------------------------------------------------------------------- #
def test_get_task_returns_latest_revision_and_run_slot(api_client, seed):
    created = _create(api_client, seed)
    resp = api_client.get(f"/api/v1/tasks/{created['id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == created["id"]
    assert body["revision"]["id"] == created["revision"]["id"]
    assert body["run"] is None
    assert body["revision_count"] == 1


def test_get_task_unknown_id_is_404_envelope(api_client):
    resp = api_client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


# --------------------------------------------------------------------------- #
# PATCH：CAS
# --------------------------------------------------------------------------- #
def test_patch_appends_revision_and_bumps_lock_version(api_client, seed):
    created = _create(api_client, seed)
    first_rev_id = created["revision"]["id"]

    resp = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "name": "改名后的任务", "config": {"package_name": "com.x.y"}},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "改名后的任务"
    assert body["lock_version"] == 2
    assert body["revision_count"] == 2
    assert body["revision"]["id"] != first_rev_id
    assert body["revision"]["revision"] == 2
    assert body["revision"]["config"] == {"package_name": "com.x.y"}
    assert body["revision"]["readiness"] == "draft"
    assert body["lifecycle"] == "draft"

    # 修订不可变：旧修订仍在，且内容没被覆盖
    revisions = api_client.get(f"/api/v1/tasks/{created['id']}/revisions").json()
    by_id = {r["id"]: r for r in revisions["items"]}
    assert by_id[first_rev_id]["revision"] == 1
    assert by_id[first_rev_id]["config"]["package_name"] == "com.example.demo"


def test_patch_with_stale_lock_version_is_409_with_latest_object(api_client, seed):
    created = _create(api_client, seed)
    first = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "name": "第一次改"},
        headers=CLIENT_HEADERS,
    )
    assert first.status_code == 200, first.text
    assert first.json()["lock_version"] == 2

    # 拿着已经过期的 1 再改一次
    stale = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "name": "第二次改"},
        headers=CLIENT_HEADERS,
    )
    assert stale.status_code == 409, stale.text
    envelope = stale.json()
    assert envelope["code"] == "stale_version"
    latest = envelope["details"]["latest"]
    assert latest["lock_version"] == 2
    assert latest["name"] == "第一次改"
    assert latest["revision"]["revision"] == 2


def test_patch_requires_client_header(api_client, seed):
    created = _create(api_client, seed)
    resp = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": 1, "name": "无头改"},
    )
    assert resp.status_code == 428
    assert resp.json()["code"] == "client_header_required"


def test_patch_requires_lock_version(api_client, seed):
    created = _create(api_client, seed)
    resp = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"name": "没带版本号"},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# validate：readiness
# --------------------------------------------------------------------------- #
def test_validate_without_suite_version_reports_missing(api_client, seed):
    created = _create(api_client, seed)
    resp = api_client.post(f"/api/v1/tasks/{created['id']}/validate", headers=CLIENT_HEADERS)
    assert resp.status_code == 422, resp.text
    envelope = resp.json()
    assert envelope["code"] == "task_not_ready"
    missing = envelope["details"]["missing"]
    assert "suite_version_id" in missing
    assert "build_id" in missing

    # 失败的 validate 不产生新修订
    revisions = api_client.get(f"/api/v1/tasks/{created['id']}/revisions").json()
    assert revisions["total"] == 1
    assert revisions["items"][0]["readiness"] == "draft"


def test_validate_without_client_header_is_428(api_client, seed):
    created = _create(api_client, seed)
    resp = api_client.post(f"/api/v1/tasks/{created['id']}/validate")
    assert resp.status_code == 428
    assert resp.json()["code"] == "client_header_required"


def test_validate_reports_invalid_for_unknown_suite_version(api_client, seed):
    """invalid 只收"填了但不对"的项：套件版本不存在 -> invalid，未填的 -> missing。"""
    missing_uuid = "00000000-0000-0000-0000-000000000000"
    resp = api_client.post(
        "/api/v1/tasks",
        json=_payload(seed, suite_version_id=missing_uuid),
        headers=CLIENT_HEADERS,
    )
    # 创建阶段就把不属于该应用的套件版本挡掉（请求校验 400，不是 readiness 422）
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "validation_error"


def test_validate_platform_mismatch_is_invalid(api_client, seed):
    """直接调 domain.check_readiness 验证平台不一致落在 invalid 桶里。

    走 API 没法造出这个不一致：test_tasks 没有 platform 列，任务的 platform
    永远回读自 applications.platform，PATCH 也不接受 platform 字段。
    """
    from app.domain import task as task_domain

    report = task_domain.check_readiness(
        revision={"suite_version_id": "s", "build_id": "b"},
        platform="android",
        application_platform="ios",
        suite_version={"id": "s"},
        case_total=3,
    )
    assert report.ok is False
    assert any("platform" in item for item in report.invalid)
    assert report.missing == []


# --------------------------------------------------------------------------- #
# archive
# --------------------------------------------------------------------------- #
def test_archive_is_idempotent(api_client, seed):
    created = _create(api_client, seed)
    first = api_client.post(f"/api/v1/tasks/{created['id']}/archive", headers=CLIENT_HEADERS)
    assert first.status_code == 200, first.text
    assert first.json()["lifecycle"] == "archived"
    lock_after_first = first.json()["lock_version"]

    second = api_client.post(f"/api/v1/tasks/{created['id']}/archive", headers=CLIENT_HEADERS)
    assert second.status_code == 200, second.text
    assert second.json()["lifecycle"] == "archived"
    assert second.json()["lock_version"] == lock_after_first


def test_patch_after_archive_is_409_illegal_transition(api_client, seed):
    created = _create(api_client, seed)
    archived = api_client.post(f"/api/v1/tasks/{created['id']}/archive", headers=CLIENT_HEADERS)
    assert archived.status_code == 200, archived.text
    lock = archived.json()["lock_version"]

    resp = api_client.patch(
        f"/api/v1/tasks/{created['id']}",
        json={"lock_version": lock, "name": "改不了"},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "illegal_transition"


def test_validate_after_archive_is_409(api_client, seed):
    created = _create(api_client, seed)
    api_client.post(f"/api/v1/tasks/{created['id']}/archive", headers=CLIENT_HEADERS)
    resp = api_client.post(f"/api/v1/tasks/{created['id']}/validate", headers=CLIENT_HEADERS)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "illegal_transition"


# --------------------------------------------------------------------------- #
# revisions
# --------------------------------------------------------------------------- #
def test_revisions_are_returned_newest_first(api_client, seed):
    created = _create(api_client, seed)
    for no in (1, 2):
        resp = api_client.patch(
            f"/api/v1/tasks/{created['id']}",
            json={"lock_version": no, "name": f"第 {no} 次改"},
            headers=CLIENT_HEADERS,
        )
        assert resp.status_code == 200, resp.text

    body = api_client.get(f"/api/v1/tasks/{created['id']}/revisions").json()
    assert body["total"] == 3
    assert [r["revision"] for r in body["items"]] == [3, 2, 1]
    assert all(r["task_id"] == created["id"] for r in body["items"])
