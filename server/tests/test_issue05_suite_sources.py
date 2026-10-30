"""工单 05：受控来源与固定代码副本（AC-INPUT-02）。

覆盖：
  - GET /suite-sources 只给 source_id / 显示名 / 适用类型，不含宿主目录
  - POST /suites 从预配置来源登记并发布 V1（固定副本 + 摘要）
  - 来源未配置、不适用、链接逃逸一律拒绝，错误不回显宿主路径
  - AC-INPUT-02：形成 V1 后修改来源目录，旧版本与执行副本仍是 V1
  - 副本损坏/缺失阻断执行，不回退到可变来源目录
  - 磁盘不足返回明确错误，且不发布版本、不淘汰旧副本
  - 旧版本无副本标“未保留固定代码”，validate 被阻断

发现会真的跑 pytest --collect-only；来源与副本都放在 tmp_path 下，不碰仓库。
"""

from __future__ import annotations

import json
import subprocess
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
        "需要 TESTDOCK_TEST_DATABASE_URL 才能跑工单 05 集成测试",
        allow_module_level=True,
    )


_ONE_CASE = "def test_alpha():\n    assert True\n"
_TWO_CASES = "def test_alpha():\n    assert True\n\n\ndef test_beta():\n    assert True\n"


def _write_suite(root: Path, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "test_min.py").write_text(body, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")


@pytest.fixture()
def source(tmp_path, monkeypatch):
    """一个预配置来源 + 固定副本目录，返回 {"id", "root", "copies"}。"""
    monkeypatch.setenv("TESTDOCK_TRUSTED_SUITE_ROOTS", str(tmp_path))
    copies = tmp_path / "code-copies"
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(copies))
    root = tmp_path / "suite_src"
    _write_suite(root, _ONE_CASE)
    monkeypatch.setenv(
        "TESTDOCK_SUITE_SOURCES",
        json.dumps(
            [
                {
                    "id": "ui_src",
                    "name": "UI 来源",
                    "path": str(root),
                    "test_types": ["ui", "joint"],
                }
            ]
        ),
    )
    return {"id": "ui_src", "root": root, "copies": copies}


def _create_suite(api_client, seed, source, *, name="来源套件", test_type="ui"):
    return api_client.post(
        "/api/v1/suites",
        json={
            "application_id": seed["application_id"],
            "name": name,
            "test_type": test_type,
            "source_id": source["id"],
        },
        headers=CLIENT_HEADERS,
    )


def test_suite_sources_hides_host_paths(api_client, source):
    body = api_client.get("/api/v1/suite-sources").json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item == {"id": "ui_src", "name": "UI 来源", "test_types": ["ui", "joint"]}
    assert str(source["root"]) not in json.dumps(body)


def test_create_suite_publishes_v1_with_code_copy(api_client, seed, source):
    resp = _create_suite(api_client, seed, source)
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["name"] == "来源套件"
    assert body["test_type"] == "ui"
    assert body["version_count"] == 1
    assert body["latest_version"]["version"] == 1
    assert body["latest_version"]["case_count"] == 1

    created = body["created_version"]
    assert created["has_code_copy"] is True
    assert created["source_ref"] == "ui_src"
    code_copy = created["manifest"]["code_copy"]
    assert code_copy["file_count"] == 2
    assert len(code_copy["tree_sha256"]) == 64
    # 副本落在平台管理的目录里，manifest 不出现宿主来源路径
    assert (source["copies"] / code_copy["root_rel"]).is_dir()
    assert str(source["root"]) not in json.dumps(created["manifest"])


def test_create_suite_unknown_source_is_400(api_client, seed, source):
    resp = api_client.post(
        "/api/v1/suites",
        json={
            "application_id": seed["application_id"],
            "name": "未知来源",
            "test_type": "ui",
            "source_id": "nope",
        },
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["details"]["reason"] == "source_not_configured"


def test_create_suite_rejects_source_for_other_test_type(api_client, seed, source):
    resp = _create_suite(api_client, seed, source, name="性能套件", test_type="performance")
    assert resp.status_code == 400, resp.text
    assert resp.json()["details"]["reason"] == "source_type_mismatch"


def test_create_suite_rejects_link_source(api_client, seed, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    _write_suite(outside, _ONE_CASE)
    link = tmp_path / "link_src"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows 未开开发者模式时建不了符号链接；junction 同样是 reparse point，
        # 走同一条链接/交接点拒绝路径。
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            pytest.skip("当前环境不允许创建符号链接或 junction")

    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(tmp_path / "code-copies"))
    monkeypatch.setenv(
        "TESTDOCK_SUITE_SOURCES",
        json.dumps([{"id": "linked", "name": "链接来源", "path": str(link)}]),
    )
    resp = api_client.post(
        "/api/v1/suites",
        json={
            "application_id": seed["application_id"],
            "name": "链接套件",
            "test_type": "ui",
            "source_id": "linked",
        },
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "discover_failed"
    assert resp.json()["details"]["reason"] == "source_symlink"


def test_old_version_keeps_v1_after_source_changes(api_client, seed, source):
    """AC-INPUT-02：V1 形成后修改来源目录，旧版本与执行副本仍是 V1。"""
    from app.integrations.discover import verify_code_copy

    created = _create_suite(api_client, seed, source)
    assert created.status_code == 201, created.text
    suite = created.json()
    v1 = suite["created_version"]
    copy_dir = source["copies"] / v1["manifest"]["code_copy"]["root_rel"]

    # 来源目录发生变化（新增用例）
    (source["root"] / "test_min.py").write_text(_TWO_CASES, encoding="utf-8")
    (source["root"] / "test_extra.py").write_text(
        "def test_gamma():\n    assert True\n", encoding="utf-8"
    )

    versions = api_client.get(f"/api/v1/suites/{suite['id']}/versions").json()
    assert versions["total"] == 1
    assert versions["items"][0]["case_count"] == 1

    # 执行侧读的仍是 V1 副本：摘要校验通过，内容还是 1 条用例
    assert verify_code_copy(v1["manifest"]["code_copy"], copies_root=source["copies"]) == copy_dir
    assert "test_extra.py" not in (copy_dir / "test_min.py").read_text(encoding="utf-8")
    assert not (copy_dir / "test_extra.py").exists()

    # 显式发现才产生 V2，V1 保留
    second = api_client.post(
        f"/api/v1/suites/{suite['id']}/discover",
        json={"source_id": source["id"]},
        headers=CLIENT_HEADERS,
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    assert second.json()["case_count"] == 3

    versions = api_client.get(f"/api/v1/suites/{suite['id']}/versions").json()
    assert [v["version"] for v in versions["items"]] == [2, 1]
    assert versions["items"][1]["case_count"] == 1


def test_corrupted_copy_blocks_execution(api_client, seed, source):
    from app.integrations.discover import CodeCopyError, verify_code_copy

    created = _create_suite(api_client, seed, source)
    code_copy = created.json()["created_version"]["manifest"]["code_copy"]
    copy_dir = source["copies"] / code_copy["root_rel"]

    (copy_dir / "test_min.py").unlink()
    with pytest.raises(CodeCopyError) as excinfo:
        verify_code_copy(code_copy, copies_root=source["copies"])
    assert excinfo.value.code in {"code_copy_corrupt", "code_copy_missing"}

    # 不因原件损坏回退到可变来源目录：来源仍在，但执行侧不会读它
    assert (source["root"] / "test_min.py").is_file()


def test_disk_full_is_explicit_and_publishes_nothing(api_client, seed, source, monkeypatch):
    from app.integrations import discover as discover_integration

    class _Usage:
        free = 1

    monkeypatch.setattr(discover_integration.shutil, "disk_usage", lambda _p: _Usage())

    before = api_client.get("/api/v1/suites").json()["total"]
    resp = _create_suite(api_client, seed, source, name="磁盘不足")
    assert resp.status_code == 422, resp.text
    envelope = resp.json()
    assert envelope["code"] == "discover_failed"
    assert envelope["details"]["reason"] == "disk_full"
    assert envelope["details"]["required_bytes"] > envelope["details"]["free_bytes"]

    # 不自动淘汰旧副本、不发布半成品版本
    after = api_client.get("/api/v1/suites").json()["total"]
    assert after == before


def test_legacy_version_without_copy_is_marked_and_blocked(api_client, seed, source):
    from app.domain.task import check_readiness

    created = _create_suite(api_client, seed, source)
    suite = created.json()
    version_id = suite["created_version"]["id"]

    # 模拟旧版本：只有 local 标记，没有固定代码副本
    _exec_sync(
        "UPDATE suite_versions SET manifest = manifest - 'code_copy' WHERE id = CAST(:id AS uuid)",
        {"id": version_id},
    )
    versions = api_client.get(f"/api/v1/suites/{suite['id']}/versions").json()
    assert versions["items"][0]["has_code_copy"] is False

    legacy_manifest = versions["items"][0]["manifest"]
    revision = {
        "suite_version_id": version_id,
        "build_id": "00000000-0000-0000-0000-000000000001",
        "test_type": "ui",
    }
    blocked = check_readiness(
        revision=revision,
        platform="android",
        application_platform="android",
        suite_version={"manifest": legacy_manifest},
        case_total=1,
    )
    assert not blocked.ok
    assert any("未保留固定代码副本" in item for item in blocked.invalid)

    # performance 声明式场景不需要代码副本
    allowed = check_readiness(
        revision={**revision, "test_type": "performance"},
        platform="android",
        application_platform="android",
        suite_version={"manifest": legacy_manifest},
        case_total=1,
    )
    assert allowed.ok, allowed.invalid
