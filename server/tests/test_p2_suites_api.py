"""P2 套件 API 集成测试（需要真实 PostgreSQL）。

覆盖：
  - GET  /suites                列表 + ?test_type= 精确过滤 + 非法枚举 400
  - GET  /suites/{id}/versions  未知 id -> 404 信封
  - POST /suites/{id}/discover  固定副本上跑 pytest --collect-only
        * 成功 201：新增 version=1、case_count、manifest.cases、code_copy 摘要
        * 再次 discover 追加 version=2（版本不可变，旧版本保留）
        * 缺 X-TestDock-Client -> 428
        * source_id 未配置 -> 400 validation_error
        * 来源不存在 -> 422 discover_failed（带 stderr 尾巴字段）
        * 来源收集不到用例 -> 422 discover_failed
        * 传任意 suite_root -> 400 validation_error（只认预配置 source_id）

discover 的子进程会跑真正的 pytest；为了快且可重复，这里用一个 tmp_path 下的
最小套件目录（3 条用例），不依赖仓库里的 tests/。
"""

from __future__ import annotations

import json
import sys
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
def suite_source(tmp_path, monkeypatch):
    # 工单 05 起浏览器只传 source_id：来源由服务端预配置，发现读固定副本。
    monkeypatch.setenv("TESTDOCK_TRUSTED_SUITE_ROOTS", str(tmp_path))
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(tmp_path / "code-copies"))
    root = tmp_path / "suite_min"
    root.mkdir()
    (root / "test_min.py").write_text(_MINIMAL_SUITE, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    monkeypatch.setenv(
        "TESTDOCK_SUITE_SOURCES",
        json.dumps(
            [
                {
                    "id": "suite_min",
                    "name": "最小套件",
                    "path": str(root),
                    "test_types": ["ui", "performance", "joint"],
                }
            ]
        ),
    )
    return {"id": "suite_min", "root": root}


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


def test_list_suites_excludes_archived_by_default(api_client, seed):
    _exec_sync(
        "UPDATE test_suites SET archived_at = now() WHERE id = CAST(:id AS uuid)",
        {"id": seed["other_suite_id"]},
    )
    body = api_client.get("/api/v1/suites").json()
    ids = {item["id"] for item in body["items"]}
    assert seed["other_suite_id"] not in ids
    assert seed["suite_id"] in ids

    archived = api_client.get("/api/v1/suites", params={"include_archived": "true"}).json()
    assert seed["other_suite_id"] in {item["id"] for item in archived["items"]}


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
    body = api_client.get(f"/api/v1/suites/{seed['other_suite_id']}/versions").json()
    assert body == {"items": [], "total": 0}


# --------------------------------------------------------------------------- #
# discover
# --------------------------------------------------------------------------- #
def test_discover_creates_first_version(api_client, seed, suite_source):
    resp = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": suite_source["id"]},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["version"] == 1
    assert body["suite_id"] == seed["other_suite_id"]
    assert body["case_count"] == 3
    assert body["source_ref"] == suite_source["id"]
    assert body["source_commit"] == "local"
    assert body["manifest"]["schema_version"] == 1
    # 不向浏览器回显宿主绝对路径；manifest 只保留相对文件清单与摘要。
    assert "suite_root" not in body["manifest"]
    code_copy = body["manifest"]["code_copy"]
    assert code_copy["file_count"] == 2
    assert len(code_copy["tree_sha256"]) == 64
    assert str(suite_source["root"].resolve()) not in json.dumps(body["manifest"])

    keys = body["case_keys"]
    assert len(keys) == 3
    assert any(k.endswith("::test_alpha") for k in keys)
    assert any(k.endswith("::TestGroup::test_gamma") for k in keys)

    # 列表里能看到最新版本
    listing = api_client.get("/api/v1/suites", params={"test_type": "ui"}).json()
    listed = {item["id"]: item for item in listing["items"]}[seed["other_suite_id"]]
    assert listed["version_count"] == 1
    assert listed["latest_version"]["version"] == 1
    assert listed["latest_version"]["case_count"] == 3


def test_discover_appends_new_version_and_keeps_old(api_client, seed, suite_source):
    first = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": suite_source["id"]},
        headers=CLIENT_HEADERS,
    )
    assert first.status_code == 201, first.text

    # 目录里加一条用例后重新 discover
    (suite_source["root"] / "test_more.py").write_text("def test_delta():\n    assert True\n", encoding="utf-8")
    second = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": suite_source["id"], "source_ref": "e2e-suite", "source_commit": "abc1234"},
        headers=CLIENT_HEADERS,
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    assert second.json()["case_count"] == 4
    assert second.json()["source_ref"] == "e2e-suite"
    assert second.json()["source_commit"] == "abc1234"

    versions = api_client.get(f"/api/v1/suites/{seed['other_suite_id']}/versions").json()
    assert versions["total"] == 2
    assert [v["version"] for v in versions["items"]] == [2, 1]
    # 旧版本不可变：仍然只有 3 条
    old = versions["items"][1]
    assert old["case_count"] == 3
    assert old["id"] == first.json()["id"]


def test_discover_requires_client_header(api_client, seed, suite_source):
    resp = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": suite_source["id"]},
    )
    assert resp.status_code == 428, resp.text
    assert resp.json()["code"] == "client_header_required"


def test_discover_unknown_suite_is_404(api_client, suite_source):
    resp = api_client.post(
        "/api/v1/suites/00000000-0000-0000-0000-000000000000/discover",
        json={"source_id": suite_source["id"]},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "not_found"


def test_discover_missing_source_is_422(api_client, seed, tmp_path, monkeypatch):
    monkeypatch.setenv("TESTDOCK_TRUSTED_SUITE_ROOTS", str(tmp_path))
    monkeypatch.setenv(
        "TESTDOCK_SUITE_SOURCES",
        json.dumps([{"id": "gone", "name": "已删除来源", "path": str(tmp_path / "no-such-dir")}]),
    )
    resp = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": "gone"},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    envelope = resp.json()
    assert envelope["code"] == "discover_failed"
    assert envelope["request_id"]
    assert "details" in envelope
    # 不回显宿主绝对目录
    assert str(tmp_path) not in resp.text


def test_discover_source_without_tests_is_422(api_client, seed, tmp_path, monkeypatch):
    monkeypatch.setenv("TESTDOCK_TRUSTED_SUITE_ROOTS", str(tmp_path))
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(tmp_path / "code-copies"))
    empty = tmp_path / "empty_suite"
    empty.mkdir()
    (empty / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    monkeypatch.setenv(
        "TESTDOCK_SUITE_SOURCES",
        json.dumps([{"id": "empty", "name": "空来源", "path": str(empty)}]),
    )

    resp = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": "empty"},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "discover_failed"


def test_discover_rejects_arbitrary_host_path(api_client, seed, suite_source):
    """浏览器不能把任意宿主路径当来源；只能传预配置 source_id。"""
    resp = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"suite_root": str(suite_source["root"])},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "validation_error"


def test_discover_unconfigured_source_is_400(api_client, seed):
    resp = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": "not-configured"},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "validation_error"
    assert resp.json()["details"]["reason"] == "source_not_configured"


def test_discover_failure_does_not_create_version(api_client, seed, tmp_path, monkeypatch):
    monkeypatch.setenv("TESTDOCK_TRUSTED_SUITE_ROOTS", str(tmp_path))
    monkeypatch.setenv(
        "TESTDOCK_SUITE_SOURCES",
        json.dumps([{"id": "gone", "name": "已删除来源", "path": str(tmp_path / "nope")}]),
    )
    api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": "gone"},
        headers=CLIENT_HEADERS,
    )
    versions = api_client.get(f"/api/v1/suites/{seed['other_suite_id']}/versions").json()
    assert versions["total"] == 0
