"""首期交付验收工单 02：可信来源 -> 固定副本 -> 不可变版本（真实 PostgreSQL）。

核验工单验收标准里既有测试没覆盖到的部分：
  - 来源为空时 GET /suite-sources 明确「未配置 + 需要宿主配置」，且不含宿主路径；
  - 浏览器只能传 source_id：宿主路径字段被拒绝，错误正文不回显宿主路径；
  - 发现失败（collect 报错/0 用例）时保留固定副本，但不发布版本。

来源与副本都放在 tmp_path 下，用 TESTDOCK_SUITE_SOURCES / TESTDOCK_CODE_COPIES_DIR
做受控夹具，不写真实配置、不碰共享库。
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
        "需要 TESTDOCK_TEST_DATABASE_URL 才能跑工单 02 集成测试",
        allow_module_level=True,
    )


@pytest.fixture()
def copies(tmp_path, monkeypatch):
    """一个干净的固定副本根目录；顺手把来源配置清空。"""
    root = tmp_path / "code-copies"
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(root))
    monkeypatch.setenv("TESTDOCK_TRUSTED_SUITE_ROOTS", str(tmp_path))
    monkeypatch.delenv("TESTDOCK_SUITE_SOURCES", raising=False)
    return root


def _published_copies(copies_root: Path) -> list[Path]:
    """副本根下已发布的副本目录（暂存目录以 '.' 开头，不算发布）。"""
    if not copies_root.is_dir():
        return []
    return [item for item in copies_root.iterdir() if item.is_dir() and not item.name.startswith(".")]


def test_empty_sources_are_explicit_and_path_free(api_client, copies):
    """来源为空时接口要说明「需要宿主配置」，而不是只给一个空数组。"""
    response = api_client.get("/api/v1/suite-sources")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["items"] == []
    assert body["total"] == 0
    hint = body.get("hint")
    assert isinstance(hint, str) and hint.strip(), "空来源必须给出明确提示"
    assert "宿主" in hint, hint
    # 提示里不能出现任何宿主绝对路径
    assert str(copies) not in response.text
    assert "code-copies" not in hint


def test_host_path_field_is_rejected_without_echo(api_client, seed, copies):
    """浏览器只能传 source_id：路径字段被拒绝，错误正文不回显该宿主路径。"""
    host_path = Path("D:/host-only-suite-issue02").as_posix()
    response = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": "any", "suite_root": host_path},
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"
    assert host_path not in response.text, response.text

    # 登记入口同样只认 source_id，且同样不回显路径
    created = api_client.post(
        "/api/v1/suites",
        json={
            "application_id": seed["other_application_id"],
            "name": "路径字段套件",
            "test_type": "ui",
            "source_path": host_path,
        },
        headers=CLIENT_HEADERS,
    )
    assert created.status_code == 422, created.text
    assert created.json()["code"] == "validation_error"
    assert host_path not in created.text, created.text


def test_failed_collect_keeps_copy_but_publishes_no_version(api_client, seed, ctx_source):
    """发现失败：固定副本保留（供诊断），但绝不发布半成品版本。"""
    before = api_client.get(f"/api/v1/suites/{seed['other_suite_id']}/versions").json()["total"]
    response = api_client.post(
        f"/api/v1/suites/{seed['other_suite_id']}/discover",
        json={"source_id": ctx_source["id"]},
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "discover_failed"
    assert response.json()["details"]["source_id"] == ctx_source["id"]

    # 失败不发布版本
    after = api_client.get(f"/api/v1/suites/{seed['other_suite_id']}/versions").json()
    assert after["total"] == before

    # 副本保留（已发布目录里至少有一个；暂存目录也一并接受）
    published = _published_copies(ctx_source["copies"])
    assert published, "发现失败后固定副本应保留，便于诊断"
    assert any((item / "pytest.ini").is_file() for item in published)


@pytest.fixture()
def ctx_source(tmp_path, monkeypatch, copies):
    """一个「收集不到用例」的受控来源：只有 pytest.ini，没有 test_*.py。"""
    root = tmp_path / "empty_src"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    monkeypatch.setenv(
        "TESTDOCK_SUITE_SOURCES",
        json.dumps([{"id": "empty_src", "name": "空来源", "path": str(root)}]),
    )
    return {"id": "empty_src", "root": root, "copies": copies}
