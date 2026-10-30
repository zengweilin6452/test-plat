"""工单 06：类型化清单与任务验证（AC-INPUT-03 / AC-CORE-02）。

覆盖：
  - performance 用声明式场景发布版本，manifest 不含伪造 cases
  - UI 套件版本只能由 discover 产生；performance 套件不走 discover
  - joint 必须同时有 UI 用例/固定副本与性能采集项、ui_timeout_s
  - 套件与修订测试类型不一致时 validate 失败（准确 invalid 文案）
  - 缺构建/缺套件/空清单显示准确 missing/invalid，不用占位数据通过
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

from _p2_common import CLIENT_HEADERS, TEST_DB  # noqa: E402

pytestmark = pytest.mark.integration

if not TEST_DB:
    pytest.skip(
        "需要 TESTDOCK_TEST_DATABASE_URL 才能跑工单 06 集成测试",
        allow_module_level=True,
    )


_SCENARIO = {"duration_s": 60, "items": ["CPU", "Memory"]}


@pytest.fixture()
def source(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(tmp_path / "code-copies"))
    root = tmp_path / "suite_src"
    root.mkdir()
    (root / "test_min.py").write_text(
        "def test_alpha():\n    assert True\n", encoding="utf-8"
    )
    (root / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    monkeypatch.setenv(
        "TESTDOCK_SUITE_SOURCES",
        json.dumps([{"id": "ui_src", "name": "UI 来源", "path": str(root)}]),
    )
    return "ui_src"


def _new_suite(api_client, seed, test_type: str, *, source_id=None, name=None):
    body = {
        "application_id": seed["application_id"],
        "name": name or f"{test_type}-{test_type}",
        "test_type": test_type,
    }
    if source_id:
        body["source_id"] = source_id
    return api_client.post("/api/v1/suites", json=body, headers=CLIENT_HEADERS)


def _publish(api_client, suite_id, **body):
    return api_client.post(
        f"/api/v1/suites/{suite_id}/versions", json=body, headers=CLIENT_HEADERS
    )


# --------------------------------------------------------------------------- #
# performance
# --------------------------------------------------------------------------- #
def test_performance_publishes_declarative_scenario_without_cases(api_client, seed):
    created = _new_suite(api_client, seed, "performance", name="声明式场景")
    assert created.status_code == 201, created.text
    suite = created.json()
    assert suite["created_version"] is None
    assert suite["version_count"] == 0

    resp = _publish(api_client, suite["id"], scenario=_SCENARIO)
    assert resp.status_code == 201, resp.text
    version = resp.json()
    assert version["version"] == 1
    assert version["case_count"] == 0
    assert version["case_keys"] == []
    manifest = version["manifest"]
    assert manifest["test_type"] == "performance"
    assert manifest["cases"] == []
    assert manifest["scenario"] == _SCENARIO


def test_performance_rejects_out_of_range_duration(api_client, seed):
    suite = _new_suite(api_client, seed, "performance", name="时长越界").json()
    resp = _publish(api_client, suite["id"], scenario={"duration_s": 5, "items": ["CPU"]})
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "validation_error"


def test_performance_rejects_empty_items(api_client, seed):
    suite = _new_suite(api_client, seed, "performance", name="空采集项").json()
    resp = _publish(api_client, suite["id"], scenario={"duration_s": 30, "items": []})
    assert resp.status_code == 422, resp.text


def test_performance_suite_cannot_use_discover(api_client, seed, source):
    suite = _new_suite(api_client, seed, "performance", name="不该发现").json()
    resp = api_client.post(
        f"/api/v1/suites/{suite['id']}/discover",
        json={"source_id": source},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# UI / joint
# --------------------------------------------------------------------------- #
def test_ui_suite_rejects_declarative_version(api_client, seed, source):
    suite = _new_suite(api_client, seed, "ui", source_id=source, name="UI 套件").json()
    assert suite["created_version"] is not None
    resp = _publish(api_client, suite["id"], scenario=_SCENARIO)
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "validation_error"


def test_ui_suite_registration_requires_source(api_client, seed):
    resp = _new_suite(api_client, seed, "ui", name="缺来源")
    assert resp.status_code == 400, resp.text
    assert "source_id" in resp.json()["message"]


def test_joint_requires_ui_source(api_client, seed):
    suite = _new_suite(api_client, seed, "joint", name="联动缺来源").json()
    resp = _publish(api_client, suite["id"], scenario=_SCENARIO, ui_timeout_s=120)
    assert resp.status_code == 400, resp.text
    assert "source_id" in resp.json()["message"]


def test_joint_requires_ui_timeout(api_client, seed, source):
    suite = _new_suite(api_client, seed, "joint", name="联动缺超时").json()
    resp = _publish(api_client, suite["id"], scenario=_SCENARIO, source_id=source)
    assert resp.status_code == 400, resp.text
    assert any("ui_timeout_s" in item for item in resp.json()["details"]["errors"])


def test_joint_publishes_ui_and_performance_parts(api_client, seed, source):
    suite = _new_suite(api_client, seed, "joint", name="联动完整").json()
    resp = _publish(
        api_client,
        suite["id"],
        scenario=_SCENARIO,
        ui_timeout_s=120,
        source_id=source,
    )
    assert resp.status_code == 201, resp.text
    version = resp.json()
    manifest = version["manifest"]
    assert version["case_count"] == 1
    assert manifest["test_type"] == "joint"
    assert manifest["performance"] == _SCENARIO
    assert manifest["ui_timeout_s"] == 120
    assert isinstance(manifest["code_copy"], dict)


# --------------------------------------------------------------------------- #
# readiness 的 missing / invalid 文案
# --------------------------------------------------------------------------- #
def test_readiness_reports_type_mismatch_and_missing_parts():
    from app.domain.task import check_readiness

    ui_manifest = {
        "schema_version": 1,
        "test_type": "ui",
        "cases": [{"case_key": "tests/test_a.py::test_one"}],
        "code_copy": {"root_rel": "x", "files": [], "file_count": 0},
    }
    base = {"suite_version_id": "sv", "build_id": "b", "test_type": "performance"}
    report = check_readiness(
        revision=base,
        platform="android",
        application_platform="android",
        suite_version={"manifest": ui_manifest},
        case_total=1,
        suite_test_type="ui",
    )
    assert not report.ok
    assert any("不一致" in item for item in report.invalid)

    empty_ui = {"schema_version": 1, "test_type": "ui", "cases": [], "code_copy": {}}
    report = check_readiness(
        revision={**base, "test_type": "ui"},
        platform="android",
        application_platform="android",
        suite_version={"manifest": empty_ui},
        case_total=0,
        suite_test_type="ui",
    )
    assert not report.ok
    assert any("UI 清单为空" in item for item in report.invalid)

    perf_with_fake_cases = {
        "schema_version": 1,
        "test_type": "performance",
        "cases": [{"case_key": "tests/test_a.py::test_one"}],
        "scenario": _SCENARIO,
    }
    report = check_readiness(
        revision=base,
        platform="android",
        application_platform="android",
        suite_version={"manifest": perf_with_fake_cases},
        case_total=1,
        suite_test_type="performance",
    )
    assert not report.ok
    assert any("不应包含 pytest 用例" in item for item in report.invalid)

    missing = check_readiness(
        revision={"test_type": "performance"},
        platform="android",
        application_platform="android",
        suite_version=None,
        case_total=0,
        suite_test_type=None,
    )
    assert missing.missing == ["suite_version_id", "build_id"]
    assert missing.invalid == []
