"""迁移只追加守卫（无需数据库）。

工单 01 要求：新增迁移只追加，0001 保持原件。
这里用两层证据：

1. `docs/contracts/migration-baseline.json` 固定 0001 的 sha256；
   任何对 0001 的字节级修改都会让测试失败。
2. 解析 versions/*.py 的 revision/down_revision，断言链是线性、无分支、
   无重复，且 0003 是空骨架（不含任何 op.* DDL）。

真正的 DDL 可执行性仍由 test_migration_structure.py 与 CI 的 alembic upgrade 负责。
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parent
VERSIONS_DIR = SERVER_DIR / "alembic" / "versions"
BASELINE = REPO_ROOT / "docs" / "contracts" / "migration-baseline.json"
BASE_REVISION = "0001"


def _module_literals(path: Path) -> dict[str, object]:
    """只读取模块顶层的字面量赋值（不 import 迁移模块）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return values


def _revision_files() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in sorted(VERSIONS_DIR.glob("[0-9]*.py")):
        revision = _module_literals(path).get("revision")
        assert isinstance(revision, str), f"{path.name} 缺少字符串 revision"
        # dict 覆盖会让重复 revision 静默消失，必须显式拦截。
        assert revision not in out, (
            f"revision 重复: {revision} 同时出现在 {out[revision].name} 与 {path.name}"
        )
        out[revision] = path
    return out


def test_0001_byte_for_byte_unchanged() -> None:
    assert BASELINE.is_file(), (
        f"缺少迁移基线 {BASELINE}；先运行 scripts/freeze_migration_baseline.py"
    )
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))
    target = VERSIONS_DIR / "0001_initial.py"
    # 按规范化换行计算：Windows 与 Linux 的检出策略不应改变“内容未变”的结论。
    normalized = target.read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(normalized).hexdigest()
    assert digest == expected["0001_initial.py"]["sha256"], (
        "0001_initial.py 被修改了。已冻结的 0001 不允许改动；"
        "新结构请追加 0002+ 迁移。"
    )


def test_revision_chain_is_linear_and_unique() -> None:
    files = _revision_files()
    assert len(files) == len(set(files)), "revision 重复"
    assert BASE_REVISION in files, "缺少 0001 基迁移"

    parents: dict[str, str | None] = {}
    for revision, path in files.items():
        values = _module_literals(path)
        parent = values.get("down_revision")
        assert parent is None or isinstance(parent, str), (
            f"{path.name} 的 down_revision 必须是字符串或 None（当前只支持线性链）"
        )
        parents[revision] = parent

    bases = [r for r, p in parents.items() if p is None]
    assert bases == [BASE_REVISION], f"唯一基迁移必须是 0001，实际 {bases}"

    # 每个父 revision 只能有一个子节点（禁止分支）
    children: dict[str, list[str]] = {}
    for revision, parent in parents.items():
        if parent is not None:
            children.setdefault(parent, []).append(revision)
    branched = {p: c for p, c in children.items() if len(c) > 1}
    assert not branched, f"迁移出现分支: {branched}"

    # 从 0001 出发必须能走完整条链
    reachable = {BASE_REVISION}
    current = BASE_REVISION
    while children.get(current):
        current = children[current][0]
        assert current not in reachable, f"迁移链出现环: {current}"
        reachable.add(current)
    assert reachable == set(files), (
        f"存在从 0001 不可达的迁移: {sorted(set(files) - reachable)}"
    )


def test_0003_is_empty_append_only_skeleton() -> None:
    """0003 只作为后续工单的追加锚点，不得包含任何 DDL。"""
    path = VERSIONS_DIR / "0003_contract_baseline.py"
    assert path.is_file(), "缺少 0003 迁移骨架"

    values = _module_literals(path)
    assert values.get("revision") == "0003"
    assert values.get("down_revision") == "0002"

    tree = ast.parse(path.read_text(encoding="utf-8"))
    op_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id == "op":
                    op_calls.append(func.attr)
    assert not op_calls, f"0003 是空骨架，不应包含 DDL 调用: {sorted(set(op_calls))}"

    # upgrade / downgrade 必须是 pass（或仅 docstring），保证无副作用。
    funcs = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"upgrade", "downgrade"}
    }
    assert set(funcs) == {"upgrade", "downgrade"}
    for name, func in funcs.items():
        body = [stmt for stmt in func.body if not isinstance(stmt, ast.Expr)]
        assert len(body) == 1 and isinstance(body[0], ast.Pass), (
            f"0003.{name} 必须只有 pass"
        )
