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


# --------------------------------------------------------------------------- #
# 类型化清单（工单 06 / spec §6.6、§9.2）
# --------------------------------------------------------------------------- #
#: 性能采集窗口的合法区间（秒，整数）
DURATION_MIN_S = 10
DURATION_MAX_S = 3600


def build_typed_manifest(
    test_type: str,
    *,
    node_ids: list[str] | None = None,
    scenario: dict[str, Any] | None = None,
    ui_timeout_s: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按类型构造 manifest。

    - ui：只有用例清单（由 discover 产生），必须带固定代码副本（由调用方放进 extra）；
    - performance：只有声明式场景，**不伪造 cases**（case_count 恒为 0）；
    - joint：UI 用例清单 + 固定代码副本 + 性能采集项 + ui_timeout_s。
    """
    manifest = build_manifest(node_ids or [], extra=extra)
    manifest["test_type"] = test_type
    if test_type == "performance":
        # 声明式场景不是 pytest 用例：显式清零，避免下游把场景当成 case 统计。
        manifest["case_count"] = 0
        manifest["cases"] = []
        manifest["scenario"] = dict(scenario or {})
    elif test_type == "joint":
        manifest["performance"] = dict(scenario or {})
        if ui_timeout_s is not None:
            manifest["ui_timeout_s"] = int(ui_timeout_s)
    return manifest


def validate_manifest(manifest: Any, *, test_type: str) -> list[str]:
    """按类型校验 manifest，返回可读的问题列表（空表示通过）。

    规则来自 spec §6.6：
      - ui：必须有用例清单；空清单失败（不允许用占位数据通过验证）；
      - performance：必须是声明式场景，duration_s 为 10–3600 的整数、采集项非空，
        且不得出现伪造的 cases；
      - joint：UI 与性能任一部分缺失都失败。
    """
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest 缺失或格式不正确"]

    declared = manifest.get("test_type")
    if declared is not None and declared != test_type:
        problems.append(f"清单类型 {declared!r} 与套件类型 {test_type!r} 不一致")

    cases = case_total(manifest)
    if test_type == "ui":
        if cases <= 0:
            problems.append("UI 清单为空：没有收集到任何用例")
    elif test_type == "performance":
        if cases > 0 or manifest.get("cases"):
            problems.append("性能场景不应包含 pytest 用例（不能用占位用例冒充执行）")
        problems.extend(_scenario_problems(manifest.get("scenario")))
    elif test_type == "joint":
        if cases <= 0:
            problems.append("joint 清单缺少 UI 用例")
        problems.extend(
            [f"joint {item}" for item in _scenario_problems(manifest.get("performance"))]
        )
        ui_timeout = manifest.get("ui_timeout_s")
        if not isinstance(ui_timeout, int) or ui_timeout <= 0:
            problems.append("joint 清单缺少 ui_timeout_s（正整数秒）")
    else:
        problems.append(f"未知测试类型：{test_type!r}")
    return problems


def _scenario_problems(scenario: Any) -> list[str]:
    """声明式场景的必需字段：duration_s（10–3600 整数）与 items（非空字符串列表）。"""
    if not isinstance(scenario, dict) or not scenario:
        return ["缺少声明式性能场景（duration_s 与采集项）"]
    problems: list[str] = []
    duration = scenario.get("duration_s")
    if not isinstance(duration, int) or isinstance(duration, bool):
        problems.append("性能场景 duration_s 必须是整数秒")
    elif not (DURATION_MIN_S <= duration <= DURATION_MAX_S):
        problems.append(
            f"性能场景 duration_s 必须在 {DURATION_MIN_S}–{DURATION_MAX_S} 秒之间"
        )
    items = scenario.get("items")
    if not isinstance(items, list) or not items or not all(
        isinstance(item, str) and item.strip() for item in items
    ):
        problems.append("性能场景采集项 items 必须是非空字符串列表")
    return problems
