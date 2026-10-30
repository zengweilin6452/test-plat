"""工单 03：来源边界、固定代码副本与阶段预算（离线，不需要 PostgreSQL）。

守住的可运行事实：
1. 越界路径、`..` 穿越、符号链接/交接点逃逸、来源替换都被拒绝；
2. 复制期间来源内容/文件集合/目录身份变化可检测，失败不发布副本；
3. 副本逐文件摘要 + 树摘要可复验，损坏/缺失阻断，不回退来源目录；
4. 发现只在固定副本上跑，来源目录后续变化不影响已发布副本；
5. 3600s 合法执行窗不被同为 3600s 的宿主总预算截断。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.integrations import discover as d


@pytest.fixture()
def trusted(tmp_path: Path) -> Path:
    root = tmp_path / "trusted"
    root.mkdir()
    return root


@pytest.fixture()
def copies_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "copies"
    root.mkdir()
    monkeypatch.setenv("TESTDOCK_CODE_COPIES_DIR", str(root))
    return root


@pytest.fixture()
def suite_source(trusted: Path) -> Path:
    src = trusted / "suite_a"
    src.mkdir()
    (src / "test_a.py").write_text(
        "def test_alpha():\n    assert True\n", encoding="utf-8"
    )
    (src / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    return src


# --------------------------------------------------------------------------- #
# 来源边界
# --------------------------------------------------------------------------- #
def test_rejects_absolute_path_outside_trusted_root(tmp_path: Path, trusted: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(d.SourceBoundaryError) as exc:
        d.resolve_source(str(outside), trusted_roots=[trusted])
    assert exc.value.code == "source_outside_trusted_root"


def test_rejects_parent_traversal(trusted: Path):
    with pytest.raises(d.SourceBoundaryError) as exc:
        d.resolve_source("../outside", trusted_roots=[trusted])
    assert exc.value.code == "source_outside_trusted_root"


def test_accepts_source_id_and_absolute_path_inside_root(suite_source: Path, trusted: Path):
    by_id = d.resolve_source("suite_a", trusted_roots=[trusted])
    by_path = d.resolve_source(str(suite_source), trusted_roots=[trusted])
    assert by_id.path == by_path.path
    assert by_id.source_id == "suite_a"
    assert by_id.path == suite_source.resolve()


def test_missing_source_is_reported_without_host_path(trusted: Path):
    with pytest.raises(d.SourceBoundaryError) as exc:
        d.resolve_source("nope", trusted_roots=[trusted])
    assert exc.value.code == "source_missing"
    assert str(trusted) not in exc.value.message


def _make_link(link: Path, target: Path) -> None:
    """建目录链接；Windows 无权限时用 junction 兜底，失败则 skip。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        import subprocess

        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return
    pytest.skip("当前环境不能创建符号链接/junction")


def test_rejects_symlink_escape(tmp_path: Path, trusted: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_leak.py").write_text("def test_leak():\n    pass\n", encoding="utf-8")
    link = trusted / "link"
    _make_link(link, outside)

    with pytest.raises(d.SourceBoundaryError) as exc:
        d.resolve_source(str(link), trusted_roots=[trusted])
    assert exc.value.code == "source_symlink"


def test_rejects_symlink_inside_source(tmp_path: Path, trusted: Path, suite_source: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = suite_source / "leak.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不能创建文件符号链接")

    with pytest.raises(d.SourceBoundaryError) as exc:
        d.resolve_source(str(suite_source), trusted_roots=[trusted])
    assert exc.value.code == "source_symlink"


def test_router_facing_error_is_discover_failed(
    tmp_path: Path, trusted: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("TESTDOCK_TRUSTED_SUITE_ROOTS", str(trusted))
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(Exception) as exc:
        d.resolve_suite_root(str(outside))
    error = exc.value
    assert getattr(error, "code", None) == "discover_failed"
    assert error.extra_details["reason"] == "source_outside_trusted_root"
    assert str(trusted) not in error.message


# --------------------------------------------------------------------------- #
# 复制期间来源变化
# --------------------------------------------------------------------------- #
def test_detects_source_content_change_during_copy(copies_root: Path, suite_source: Path, trusted: Path):
    source = d.resolve_source(str(suite_source), trusted_roots=[trusted])

    def mutate(rel: str) -> None:
        (suite_source / "test_a.py").write_text(
            "def test_alpha():\n    assert False\n", encoding="utf-8"
        )

    with pytest.raises(d.CodeCopyError) as exc:
        d.copy_source(source, on_file_copied=mutate)
    assert exc.value.code == "source_changed"
    # 不发布副本：只有 staging 目录，没有旁车摘要
    assert not list(copies_root.glob("*.code-copy.json"))
    published = [p for p in copies_root.iterdir() if not p.name.startswith(".staging-")]
    assert published == []


def test_detects_source_replacement_during_copy(copies_root: Path, suite_source: Path, trusted: Path):
    source = d.resolve_source(str(suite_source), trusted_roots=[trusted])

    def replace(rel: str) -> None:
        # 复制按路径排序：pytest.ini -> test_a.py。最后一个文件复制完后替换来源，
        # 避免复制循环中途读不到后续文件。
        if rel != "test_a.py":
            return
        moved = suite_source.with_name("suite_a_old")
        try:
            os.rename(suite_source, moved)
        except PermissionError:
            # Windows 上杀毒/索引器可能短暂占用目录句柄；内容变化用例已覆盖，
            # 这里跳过而不是把环境噪声当成实现失败。
            pytest.skip("Windows 目录句柄被占用，无法模拟来源替换")
        suite_source.mkdir()
        (suite_source / "test_a.py").write_text(
            "def test_replaced():\n    assert True\n", encoding="utf-8"
        )

    with pytest.raises(d.CodeCopyError) as exc:
        d.copy_source(source, on_file_copied=replace)
    assert exc.value.code == "source_changed"


def test_detects_added_source_file_during_copy(copies_root: Path, suite_source: Path, trusted: Path):
    source = d.resolve_source(str(suite_source), trusted_roots=[trusted])

    def add(rel: str) -> None:
        (suite_source / "test_new.py").write_text(
            "def test_new():\n    assert True\n", encoding="utf-8"
        )

    with pytest.raises(d.CodeCopyError) as exc:
        d.copy_source(source, on_file_copied=add)
    assert exc.value.code == "source_changed"


# --------------------------------------------------------------------------- #
# 摘要校验
# --------------------------------------------------------------------------- #
def test_copy_manifest_has_no_host_paths_and_verifies(copies_root: Path, suite_source: Path, trusted: Path):
    source = d.resolve_source(str(suite_source), trusted_roots=[trusted])
    copy_root, code_copy = d.copy_source(source)

    assert copy_root.parent == copies_root.resolve()
    assert code_copy["root_rel"] == copy_root.name
    assert code_copy["file_count"] == 2
    assert code_copy["tree_sha256"] and len(code_copy["tree_sha256"]) == 64
    assert {item["path"] for item in code_copy["files"]} == {"pytest.ini", "test_a.py"}
    dumped = json.dumps(code_copy)
    assert str(trusted) not in dumped
    assert str(copies_root) not in dumped
    assert d.verify_code_copy(code_copy) == copy_root


def test_verify_blocks_corrupted_copy(copies_root: Path, suite_source: Path, trusted: Path):
    source = d.resolve_source(str(suite_source), trusted_roots=[trusted])
    copy_root, code_copy = d.copy_source(source)

    (copy_root / "test_a.py").write_text(
        "def test_alpha():\n    assert False\n", encoding="utf-8"
    )
    with pytest.raises(d.CodeCopyError) as exc:
        d.verify_code_copy(code_copy)
    assert exc.value.code == "code_copy_corrupt"


def test_verify_blocks_missing_file_and_directory(copies_root: Path, suite_source: Path, trusted: Path):
    source = d.resolve_source(str(suite_source), trusted_roots=[trusted])
    copy_root, code_copy = d.copy_source(source)

    (copy_root / "test_a.py").unlink()
    with pytest.raises(d.CodeCopyError) as exc:
        d.verify_code_copy(code_copy)
    assert exc.value.code == "code_copy_corrupt"

    import shutil

    shutil.rmtree(copy_root)
    with pytest.raises(d.CodeCopyError) as exc:
        d.verify_code_copy(code_copy)
    assert exc.value.code == "code_copy_missing"


def test_verify_blocks_extra_file(copies_root: Path, suite_source: Path, trusted: Path):
    source = d.resolve_source(str(suite_source), trusted_roots=[trusted])
    copy_root, code_copy = d.copy_source(source)
    (copy_root / "test_extra.py").write_text("def test_extra():\n    pass\n", encoding="utf-8")
    with pytest.raises(d.CodeCopyError) as exc:
        d.verify_code_copy(code_copy)
    assert exc.value.code == "code_copy_corrupt"


# --------------------------------------------------------------------------- #
# 发现读取固定副本，而不是来源目录
# --------------------------------------------------------------------------- #
def test_discovery_reads_copy_not_live_source(copies_root: Path, suite_source: Path, trusted: Path):
    source = d.resolve_source(str(suite_source), trusted_roots=[trusted])
    copy_root, code_copy = d.copy_source(source)
    assert d.verify_code_copy(code_copy) == copy_root

    # 来源目录在复制后新增/删除用例：已固定副本不受影响
    (suite_source / "test_beta.py").write_text(
        "def test_beta():\n    assert True\n", encoding="utf-8"
    )
    result = d.collect_suite(copy_root)
    assert result.ok, result.stderr_tail
    assert result.node_ids and all("test_alpha" in node for node in result.node_ids)
    assert not any("test_beta" in node for node in result.node_ids)

    (suite_source / "test_a.py").unlink()
    still = d.collect_suite(copy_root)
    assert still.ok, still.stderr_tail
    assert any("test_alpha" in node for node in still.node_ids)


# --------------------------------------------------------------------------- #
# 阶段预算
# --------------------------------------------------------------------------- #
def test_stage_budget_does_not_truncate_3600s_window():
    from app.services.suites import StageBudget, plan_execution_budget

    budget = StageBudget.default()
    planned = plan_execution_budget(duration_s=3600, host_timeout_s=7200)
    assert planned["execution_window_s"] == 3600
    assert planned["host_deadline_s"] == 3600 + budget.host_stage_total_s
    assert planned["host_deadline_s"] > 3600


def test_stage_budget_rejects_insufficient_host_timeout():
    from app.services.suites import plan_execution_budget

    with pytest.raises(Exception) as exc:
        plan_execution_budget(duration_s=3600, host_timeout_s=3600)
    assert getattr(exc.value, "code", None) == "validation_error"


def test_stage_budget_uses_larger_of_ui_and_duration_window():
    from app.services.suites import plan_execution_budget

    planned = plan_execution_budget(
        duration_s=120, ui_timeout_s=600, host_timeout_s=7200
    )
    assert planned["execution_window_s"] == 600
