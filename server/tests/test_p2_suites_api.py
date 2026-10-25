"""P2 套件 API 集成测试（需要真实 PostgreSQL）。

覆盖：
  - GET  /suites                列表 + ?test_type= 精确过滤 + 非法枚举 400
  - GET  /suites/{id}/versions  未知 id -> 404 信封
  - POST /suites/{id}/discover  宿主子进程 pytest --collect-only
        * 成功 201：新增 version=1、case_count、manifest.cases、suite_root 留痕
        * 再次 discover 追加 version=2（版本不可变，旧版本保留）
        * 缺 X-TestDock-Client -> 428
        * suite_root 不存在 -> 422 discover_failed（带 stderr 尾巴字段）
        * suite_root 收集不到用例 -> 422 discover_failed

discover 的子进程会跑真正的 pytest；为了快且可重复，这里用一个 tmp_path 下的
最小套件目录（3 条用例），不依赖仓库里的 tests/。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

pytest_plugins = ("_p2_common",)

from _p2_common import CLIENT_HEADERS, TEST_DB  # noqa: E402

pytestmark = pytest.mark.integration

if not TEST_DB:
    pytest.skip(
        "需要 TESTDOCK_TEST_DATABASE_URL 才能跑 P2 集成测试",
        allow_module_level=True,
    )


_MINIMAL_SUITE = '''def test_alpha():
    assert True


def test_beta():
    assert True


class TestGroup:
    def test_gamma(self):
        assert True
'''


@pytest.fixture()
def suite_root(tmp_path):
    root = tmp_path / "suite_min"
    root.mkdir()
    (root / "test_min.py").write_text(_MINIMAL_SUITE, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# 列表
# --------------------------------------------------------------------------- #
def test_list_suites_returns_seeded_suites(api_client, seed):
    body = api_client.get("/api/v1/suites").json()
    assert "items" in body
    assert body["total"] == len(body["items"])

    by_id = {item["id"]: item for item in body["items"]}
    assert seed["suite_id"] in by_id
    assert seed["other_suite_id"] in by_id

    perf = by_id[seed["suite_id"]]
    assert perf["test_type"] == "performance"
    assert perf["application"]["id"] == seed["application_id"]
    assert perf["application"]["platform"] == "android"
    assert perf["version_count"] == 0
    assert perf["latest_version"] is None

    ui = by_id[seed["other_suite_id"]]
    assert ui["test_type"] == "ui"
    assert ui["application"]["platform"] == "ios"


def test_list_suites_filters_by_test_type(api_client, seed):
    body = api_client.get("/api/v1/suites", params={"test_type": "performance"}).json()
    ids = {item["id"] for item in body["items"]}
    assert seed["suite_id"] in ids
    assert seed["other_suite_id"] not in ids
    assert all(item["test_type"] == "performance" for item in body["items"])

    ui_body = api_client.get("/api/v1/suites", params={"test_type": "ui"}).json()
    ui_ids = {item["id"] for item in ui_body["items"]}
    assert seed["other_suite_id"] in ui_ids
    assert seed["suite_id"] not in ui_ids


def test_list_suites_rejects_unknown_test_type(api_client):
    resp = api_client.get("/api/v1/suites", params={"test_type": "smoke"})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# 版本
# --------------------------------------------------------------------------- #
def test_list_versions_of_unknown_suite_is_404(api_client):
    resp = api_client.get("/api/v1/suites/00000000-0000-0000-0000-000000000000/versions")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "not_found"


def test_versions_start_empty(api_client, seed):
    body = api_client.get(f"/api/v1/suites/{seed['suite_id']}/versions").json()
    assert body == {"items": [], "total": 0}


# --------------------------------------------------------------------------- #
# discover
# --------------------------------------------------------------------------- #
def test_discover_creates_first_version(api_client, seed, suite_root):
    resp = api_client.post(
        f"/api/v1/suites/{seed['suite_id']}/discover",
        json={"suite_root": str(suite_root)},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["version"] == 1
    assert body["suite_id"] == seed["suite_id"]
    assert body["case_count"] == 3
    assert body["source_ref"] == f"suite:{seed['suite_id']}"
    assert body["source_commit"] == "local"
    assert body["manifest"]["schema_version"] == 1
    assert body["manifest"]["suite_root"] == str(suite_root.resolve())

    keys = body["case_keys"]
    assert len(keys) == 3
    assert any(k.endswith("::test_alpha") for k in keys)
    assert any(k.endswith("::TestGroup::test_gamma") for k in keys)

    # 列表里能看到最新版本
    listing = api_client.get("/api/v1/suites", params={"test_type": "performance"}).json()
    listed = {item["id"]: item for item in listing["items"]}[seed["suite_id"]]
    assert listed["version_count"] == 1
    assert listed["latest_version"]["version"] == 1
    assert listed["latest_version"]["case_count"] == 3


def test_discover_appends_new_version_and_keeps_old(api_client, seed, suite_root):
    first = api_client.post(
        f"/api/v1/suites/{seed['suite_id']}/discover",
        json={"suite_root": str(suite_root)},
        headers=CLIENT_HEADERS,
    )
    assert first.status_code == 201, first.text

    # 目录里加一条用例后重新 discover
    (suite_root / "test_more.py").write_text("def test_delta():\n    assert True\n", encoding="utf-8")
    second = api_client.post(
        f"/api/v1/suites/{seed['suite_id']}/discover",
        json={"suite_root": str(suite_root), "source_ref": "e2e-suite", "source_commit": "abc1234"},
        headers=CLIENT_HEADERS,
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    assert second.json()["case_count"] == 4
    assert second.json()["source_ref"] == "e2e-suite"
    assert second.json()["source_commit"] == "abc1234"

    versions = api_client.get(f"/api/v1/suites/{seed['suite_id']}/versions").json()
    assert versions["total"] == 2
    assert [v["version"] for v in versions["items"]] == [2, 1]
    # 旧版本不可变：仍然只有 3 条
    old = versions["items"][1]
    assert old["case_count"] == 3
    assert old["id"] == first.json()["id"]


def test_discover_requires_client_header(api_client, seed, suite_root):
    resp = api_client.post(
        f"/api/v1/suites/{seed['suite_id']}/discover",
        json={"suite_root": str(suite_root)},
    )
    assert resp.status_code == 428, resp.text
    assert resp.json()["code"] == "client_header_required"


def test_discover_unknown_suite_is_404(api_client, suite_root):
    resp = api_client.post(
        "/api/v1/suites/00000000-0000-0000-0000-000000000000/discover",
        json={"suite_root": str(suite_root)},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "not_found"


def test_discover_missing_root_is_422(api_client, seed, tmp_path):
    resp = api_client.post(
        f"/api/v1/suites/{seed['suite_id']}/discover",
        json={"suite_root": str(tmp_path / "no-such-dir")},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    envelope = resp.json()
    assert envelope["code"] == "discover_failed"
    assert envelope["request_id"]
    assert "details" in envelope


def test_discover_root_without_tests_is_422(api_client, seed, tmp_path):
    empty = tmp_path / "empty_suite"
    empty.mkdir()
    (empty / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")

    resp = api_client.post(
        f"/api/v1/suites/{seed['suite_id']}/discover",
        json={"suite_root": str(empty)},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "discover_failed"


def test_discover_failure_does_not_create_version(api_client, seed, tmp_path):
    api_client.post(
        f"/api/v1/suites/{seed['suite_id']}/discover",
        json={"suite_root": str(tmp_path / "nope")},
        headers=CLIENT_HEADERS,
    )
    versions = api_client.get(f"/api/v1/suites/{seed['suite_id']}/versions").json()
    assert versions["total"] == 0
