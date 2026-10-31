"""架构守卫：`server/app/**` 禁止 import vendor（README「领域规则」第 5 条）。

规则与边界（与 app/integrations/mobile_perf.py 模块 docstring 口径一致）：

1. 模块顶层（函数体外）不允许出现对 vendor 顶层包
   （``mobile_auto`` / ``mobile_perf``）的绝对 import——任何模块都不行，
   包括 mobile_perf.py 集成模块自身。
2. 函数内部的 vendor import 是「只读例外」，且只允许出现在唯一文件
   ``app/integrations/mobile_perf.py``。它只在显式提供 ``vendor_src``
   或 ``TESTDOCK_MOBILE_PERF_SRC`` 时才注入 sys.path。
   其他任何 app 模块（哪怕函数内）出现 vendor import 一律 FAIL。
3. app 内相对 import（``from .mobile_perf import ...``，level>0）指向的是
   app 自己的集成模块，不算 vendor，不拦截。

vendor 能力的主通道是 ``server/runner_pkg/testdock_runner`` 子进程；
本测试保证「例外」有明确边界，不会被悄悄扩大。
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

VENDOR_ROOTS = frozenset({"mobile_auto", "mobile_perf"})

# 唯一允许在函数内部 import vendor 的文件（相对 app/）
FUNCTION_LEVEL_WHITELIST = {Path("integrations") / "mobile_perf.py"}


def _imported_roots(node: ast.Import | ast.ImportFrom) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name.split(".", 1)[0] for alias in node.names}
    if node.level or node.module is None:
        return set()  # 相对 import 指向 app 自身，不是 vendor
    return {node.module.split(".", 1)[0]}


def _vendor_hits(node: ast.Import | ast.ImportFrom) -> set[str]:
    return _imported_roots(node) & VENDOR_ROOTS


def _collect_top_level(tree: ast.Module) -> list[ast.stmt]:
    """函数体之外的全部语句（含模块级 try/if/with 内部的 import）。"""

    def walk(body: list[ast.stmt]) -> list[ast.stmt]:
        found: list[ast.stmt] = []
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            found.append(stmt)
            if isinstance(stmt, ast.If):
                found.extend(walk(stmt.body))
                found.extend(walk(stmt.orelse))
            elif isinstance(stmt, ast.Try):
                found.extend(walk(stmt.body))
                for handler in stmt.handlers:
                    found.extend(walk(handler.body))
                found.extend(walk(stmt.orelse))
                found.extend(walk(stmt.finalbody))
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                found.extend(walk(stmt.body))
        return found

    return walk(tree.body)


def _in_function(tree: ast.Module) -> set[int]:
    """函数/方法体内部（含嵌套）的 import 节点 id 集合。"""
    inside: set[int] = set()

    def walk(body: list[ast.stmt]) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(stmt):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)):
                        inside.add(id(sub))
                walk(stmt.body)
            elif isinstance(stmt, ast.ClassDef):
                walk(stmt.body)

    walk(tree.body)
    return inside


def test_no_vendor_import():
    violations: list[str] = []
    py_files = sorted(APP_ROOT.rglob("*.py"))
    assert py_files, f"app/ 下没有找到任何 Python 文件：{APP_ROOT}"

    for path in py_files:
        rel = path.relative_to(APP_ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        top = _collect_top_level(tree)
        func_ids = _in_function(tree)

        for stmt in top:
            hits = _vendor_hits(stmt) if isinstance(stmt, (ast.Import, ast.ImportFrom)) else set()
            if hits:
                violations.append(f"{rel}:{stmt.lineno} 顶层 import vendor: {sorted(hits)}")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) not in func_ids:
                continue  # 顶层违规已在上面记录
            hits = _vendor_hits(node)
            if hits and rel not in FUNCTION_LEVEL_WHITELIST:
                violations.append(
                    f"{rel}:{node.lineno} 函数内 import vendor（白名单仅 "
                    f"{FUNCTION_LEVEL_WHITELIST}）: {sorted(hits)}"
                )

    assert not violations, "app/ 禁止 import vendor（README 领域规则第 5 条）：\n" + "\n".join(violations)
