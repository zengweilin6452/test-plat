"""工单 03：套件发现使用固定副本，执行前复验同一副本（真实 PostgreSQL）。

覆盖 AC-INPUT-02：
- 浏览器只给可信根内的 source_id/路径；越界与链接逃逸 422 discover_failed；
- 发现版本 manifest 只保留相对文件清单与摘要，不回显宿主绝对路径；
- 形成 V1 后修改来源目录，V1 的发现/执行仍用 V1 副本；
- 副本损坏/缺失时执行前阻断，不回退到来源目录。
"""

from __future__ import annotations

import asyncio
import os
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
        "需要 TESTDOCK_TEST_DATABASE_URL 才能跑套件副本集成测试",
        allow_module_level=True,
    )


_MINIMAL_SUITE = '''def test_alpha():
    assert True


def test_beta():
    assert True


def test_gamma():
    assert True
'''


@pytest.fixture()
def suite_root(tmp_path, monkeypatch):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    copies = tmp_path / "copies"
    copies.mkdir()
    monkeypatch.setenv("TESTDOCK_TRUSTED_SUITE_ROOTS", str(trusted))
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(copies))
    root = trusted / "suite_min"
    root.mkdir()
    (root / "test_min.py").write_text(_MINIMAL_SUITE, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    return root


def _discover(api_client, suite_id: str, body: dict):
    return api_client.post(
        f"/api/v1/suites/{suite_id}/discover", json=body, headers=CLIENT_HEADERS
    )


def _prepare(version_id: str) -> Path:
    from app.services.suites import prepare_execution_copy

    from tests._p3_common import async_session

    async def _inner() -> Path:
        async with async_session() as session:
            return await prepare_execution_copy(session, version_id)

    return asyncio.run(_inner())


def test_discover_publishes_code_copy_without_host_paths(
    api_client, seed, suite_root, tmp_path
):
    response = _discover(api_client, seed["suite_id"], {"suite_root": "suite_min"})
    assert response.status_code == 201, response.text
    body = response.json()
    manifest = body["manifest"]

    assert "suite_root" not in manifest
    code_copy = manifest["code_copy"]
    assert code_copy["file_count"] == 2
    assert len(code_copy["tree_sha256"]) == 64
    assert {item["path"] for item in code_copy["files"]} == {"pytest.ini", "test_min.py"}
    dumped = response.text
    assert str(tmp_path) not in dumped
    assert "trusted" not in dumped


def test_version_copy_is_stable_after_source_changes(
    api_client, seed, suite_root
):
    first = _discover(api_client, seed["suite_id"], {"suite_root": "suite_min"})
    assert first.status_code == 201, first.text
    v1 = first.json()
    v1_copy = v1["manifest"]["code_copy"]

    # 形成 V1 后修改来源：新增一条用例
    (suite_root / "test_more.py").write_text(
        "def test_delta():\n    assert True\n", encoding="utf-8"
    )
    second = _discover(api_client, seed["suite_id"], {"suite_root": "suite_min"})
    assert second.status_code == 201, second.text
    v2 = second.json()
    assert v2["version"] == 2
    assert v2["manifest"]["code_copy"]["tree_sha256"] != v1_copy["tree_sha256"]

    # V1 行不可变
    versions = api_client.get(f"/api/v1/suites/{seed['suite_id']}/versions").json()
    old = next(item for item in versions["items"] if item["id"] == v1["id"])
    assert old["manifest"]["code_copy"] == v1_copy

    # 执行前解析到 V1 副本：来源新增文件不进入副本
    root = _prepare(v1["id"])
    assert (root / "test_min.py").is_file()
    assert not (root / "test_more.py").exists()

    from app.integrations import discover as discover_integration

    result = discover_integration.collect_suite(root)
    assert result.ok, result.stderr_tail
    assert len(result.node_ids) == 3
    assert not any("test_delta" in node for node in result.node_ids)


def test_corrupted_copy_blocks_execution(api_client, seed, suite_root):
    response = _discover(api_client, seed["suite_id"], {"suite_root": "suite_min"})
    assert response.status_code == 201, response.text
    version = response.json()
    root = _prepare(version["id"])
    (root / "test_min.py").write_text("def test_alpha():\n    assert False\n", encoding="utf-8")

    with pytest.raises(Exception) as exc:
        _prepare(version["id"])
    error = exc.value
    assert getattr(error, "code", None) == "discover_failed"
    assert error.extra_details["reason"] == "code_copy_corrupt"


def test_source_outside_trusted_root_is_rejected(api_client, seed, tmp_path, suite_root):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_leak.py").write_text("def test_leak():\n    pass\n", encoding="utf-8")

    response = _discover(api_client, seed["suite_id"], {"suite_root": str(outside)})
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "discover_failed"
    assert body["details"]["reason"] == "source_outside_trusted_root"
    assert str(outside) not in response.text


def test_symlink_source_is_rejected(api_client, seed, suite_root, tmp_path):
    outside = tmp_path / "outside_link_target"
    outside.mkdir()
    (outside / "test_leak.py").write_text("def test_leak():\n    pass\n", encoding="utf-8")
    link = suite_root.parent / "linked_suite"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name == "nt":
            import subprocess

            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                pytest.skip("当前环境不能创建符号链接/junction")
        else:
            pytest.skip("当前环境不能创建符号链接")

    response = _discover(api_client, seed["suite_id"], {"suite_root": str(link)})
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "discover_failed"
    assert body["details"]["reason"] == "source_symlink"
