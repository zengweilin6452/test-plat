"""套件版本与用例清单的领域规则（唯一入口）。

schema 里没有独立的 cases 表：用例清单存在 suite_versions.manifest 这个 jsonb 里
（0001 中该列注释写的是"用例 key、入口、场景及 schemaVersion"）。本模块定义
manifest 的规范形状，discover 与 validate 都读同一套解析逻辑，避免两边各认一种键名。

规范形状：
    {
      "schema_version": 1,
      "case_count": 3,
      "cases": [
        {"case_key": "tests/test_a.py::test_one", "node_id": "...",
         "file": "tests/test_a.py", "entry": "...", "tags": []}
      ]
    }
向后兼容：只认 cases 列表长度来判断"是否已绑定用例"，case_count 缺失时用 len(cases)。
"""

from __future__ import annotations

from typing import Any

# test_suites.test_type 与 task_revisions.test_type 是同一套枚举，
# 复用 task.py 的常量，避免两个模块各写一份后漂移。
from .task import TEST_TYPES

#: manifest 的形状版本（未来改结构时用它做迁移判断）
MANIFEST_SCHEMA_VERSION = 1


def normalize_case(node_id: str) -> dict[str, Any]:
    """把 pytest 的 nodeid 归一成 manifest 里的一条 case。

    nodeid 形如 "tests/test_a.py::test_one" 或 "tests/test_a.py::TestK::test_m"。
    case_key 直接用 nodeid：它在同一次 collect 内唯一，且与 --collect-only 输出一一对应，
    便于以后用同样的命令复现。
    """
    node_id = node_id.strip()
    file_part, _, rest = node_id.partition("::")
    entry = rest or file_part
    return {
        "case_key": node_id,
        "node_id": node_id,
        "file": file_part or None,
        "entry": entry,
        "tags": [],
    }


def build_manifest(node_ids: list[str], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """由 collect 出的 nodeid 列表构造 manifest（去重但保持首次出现顺序）。"""
    seen: set[str] = set()
    cases: list[dict[str, Any]] = []
    for node_id in node_ids:
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        cases.append(normalize_case(node_id))
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "case_count": len(cases),
        "cases": cases,
    }
    if extra:
        manifest.update(extra)
    return manifest


def case_keys(manifest: Any) -> list[str]:
    """从 manifest 取出用例 key 列表；结构不认识时返回空列表（等价于未绑定用例）。"""
    if not isinstance(manifest, dict):
        return []
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        return []
    keys: list[str] = []
    for item in cases:
        if isinstance(item, dict):
            key = item.get("case_key") or item.get("node_id")
            if isinstance(key, str) and key:
                keys.append(key)
        elif isinstance(item, str) and item:
            keys.append(item)
    return keys


def case_total(manifest: Any) -> int:
    """已绑定用例条数。空 manifest / 无 cases 一律 0，用于 readiness 判定。"""
    return len(case_keys(manifest))


def next_version(current_max: int | None) -> int:
    """suite_versions.version 单调递增（UNIQUE(project_id,suite_id,version)）。"""
    return int(current_max or 0) + 1
