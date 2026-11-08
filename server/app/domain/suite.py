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
# 显式别名：routers/suites.py 通过 suite_domain.TEST_TYPES 读取这份再导出。
from .task import TEST_TYPES as TEST_TYPES

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
        problems.extend(scenario_problems(manifest.get("scenario")))
    elif test_type == "joint":
        if cases <= 0:
            problems.append("joint 清单缺少 UI 用例")
        problems.extend(
            [f"joint {item}" for item in scenario_problems(manifest.get("performance"))]
        )
        ui_timeout = manifest.get("ui_timeout_s")
        if not isinstance(ui_timeout, int) or ui_timeout <= 0:
            problems.append("joint 清单缺少 ui_timeout_s（正整数秒）")
    else:
        problems.append(f"未知测试类型：{test_type!r}")
    return problems


def scenario_problems(scenario: Any) -> list[str]:
    """声明式场景的必需与可选字段校验。

    必需：duration_s（10–3600 整数）、items（非空字符串列表）。
    可选能力字段（与 runner 侧 testdock_runner.perf_config 同一口径镜像，
    由 tests/test_issue06_perf_scenario.py 锁死不漂移）：start_mode、
    capture_har、net_profile/net_tier/net_port/net_mitmdump/net_overrides、
    frame_poll、page_marks、ui_timeout_s（joint 兼容位）。未知字段一律拒绝。
    """
    if not isinstance(scenario, dict) or not scenario:
        return ["缺少声明式性能场景（duration_s 与采集项）"]
    problems: list[str] = []
    unknown = sorted(set(scenario) - set(_SCENARIO_KEYS))
    if unknown:
        problems.append("场景包含未知字段：" + "、".join(unknown))
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
    start_mode = scenario.get("start_mode")
    if start_mode is not None and (not isinstance(start_mode, str) or start_mode not in _STARTUP_MODES):
        problems.append(f"start_mode 只支持 {'/'.join(_STARTUP_MODES)} 或不填")
    for flag, label in (("capture_har", "capture_har"), ("frame_poll", "frame_poll")):
        value = scenario.get(flag)
        if value is not None and not isinstance(value, bool):
            problems.append(f"{label} 必须是布尔值")
    problems.extend(_net_problems(scenario))
    problems.extend(_page_mark_problems(scenario))
    ui_timeout = scenario.get("ui_timeout_s")
    if ui_timeout is not None and (
        not isinstance(ui_timeout, int) or isinstance(ui_timeout, bool) or ui_timeout <= 0
    ):
        problems.append("ui_timeout_s 必须是正整数")
    return problems


#: 与 vendor netprof.PROFILE_NAMES / startup.STARTUP_MODES 对齐
_NET_PROFILES = ("none", "4g", "3g", "weak", "custom")
_NET_TIERS = ("passthrough", "decrypt")
_STARTUP_MODES = ("cold", "warm")
_SCENARIO_KEYS = (
    "duration_s",
    "items",
    "start_mode",
    "capture_har",
    "net_profile",
    "net_tier",
    "net_port",
    "net_mitmdump",
    "net_overrides",
    "frame_poll",
    "page_marks",
    "ui_timeout_s",
)


def _net_problems(scenario: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    profile = scenario.get("net_profile")
    if profile is not None:
        if not isinstance(profile, str) or profile not in _NET_PROFILES:
            problems.append(f"net_profile 只支持 {'/'.join(_NET_PROFILES)} 或不填")
    tier = scenario.get("net_tier")
    if tier is not None and (not isinstance(tier, str) or tier not in _NET_TIERS):
        problems.append(f"net_tier 只支持 {'/'.join(_NET_TIERS)} 或不填")
    port = scenario.get("net_port")
    if port is not None and (
        not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535)
    ):
        problems.append("net_port 必须是 1–65535 的整数")
    mitmdump = scenario.get("net_mitmdump")
    if mitmdump is not None and (not isinstance(mitmdump, str) or not mitmdump.strip()):
        problems.append("net_mitmdump 必须是 mitmdump 可执行文件路径")
    overrides = scenario.get("net_overrides")
    if overrides is not None:
        if not isinstance(overrides, dict):
            problems.append("net_overrides 必须是对象（latency_ms/down_kbps/up_kbps/loss_pct）")
        else:
            for name in ("latency_ms", "down_kbps", "up_kbps", "loss_pct"):
                value = overrides.get(name)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    problems.append(f"net_overrides.{name} 必须是非负数字")
                elif name == "loss_pct" and value > 100:
                    problems.append("net_overrides.loss_pct 不能超过 100")
        if profile == "custom" and len(overrides) < 4:
            problems.append("net_profile=custom 必须提供全部四个 net_overrides 参数")
    if profile == "custom" and overrides is None:
        problems.append("net_profile=custom 必须提供 net_overrides")
    return problems


def _page_mark_problems(scenario: dict[str, Any]) -> list[str]:
    marks = scenario.get("page_marks")
    if marks is None:
        return []
    if not isinstance(marks, list) or not marks:
        return ["page_marks 必须是非空的 {page, at_s} 列表"]
    problems: list[str] = []
    for index, mark in enumerate(marks):
        if not isinstance(mark, dict):
            problems.append(f"page_marks[{index}] 必须是 {{\"page\": \"页面名\", \"at_s\": 秒}}")
            continue
        page = mark.get("page")
        at_s = mark.get("at_s")
        if not isinstance(page, str) or not page.strip():
            problems.append(f"page_marks[{index}].page 必须是非空字符串")
        if not isinstance(at_s, (int, float)) or isinstance(at_s, bool) or at_s < 0:
            problems.append(f"page_marks[{index}].at_s 必须是不小于 0 的数字（相对采集窗口起点秒）")
    return problems


class PerfScenarioConflict(ValueError):
    """套件版本场景与修订 config.perf 两份声明不一致。"""


def _scenario_signature(scenario: dict[str, Any]) -> tuple[Any, tuple[str, ...]]:
    items = scenario.get("items")
    item_tuple = tuple(items) if isinstance(items, list) else ()
    return (scenario.get("duration_s"), item_tuple)


def resolve_scenario(
    *,
    test_type: str,
    manifest: Any,
    revision_perf: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """合订「套件版本场景」与「修订 config.perf」，返回 (场景, 来源)。

    优先级是显式规则，不是"后写覆盖先写"：
      1. 两份都有且一致 -> 用套件版本的值（版本快照是固定定义），来源 suite_manifest；
      2. 只有一份 -> 用它，来源写明是 suite_manifest 还是 revision；
      3. 两份都有但不一致 -> 抛 PerfScenarioConflict，交由调用方拒绝派发/提交，
         绝不静默用其中一份冒充另一份；
      4. 都没有 -> (None, None)，由调用方决定怎么处理：修订 readiness 与
         runner 采集入口都会拒绝，不会静默套用默认时长。

    performance 读 ``manifest.scenario``，joint 读 ``manifest.performance``。
    """
    declared: Any = None
    if isinstance(manifest, dict):
        declared = manifest.get("scenario" if test_type == "performance" else "performance")
    declared_perf = declared if isinstance(declared, dict) and declared else None
    revision_scenario = (
        revision_perf if isinstance(revision_perf, dict) and revision_perf else None
    )
    if declared_perf and revision_scenario:
        if _scenario_signature(declared_perf) != _scenario_signature(revision_scenario):
            raise PerfScenarioConflict(
                "修订 config.perf 与套件版本场景不一致："
                f"版本 duration_s={declared_perf.get('duration_s')!r}"
                f"/items={declared_perf.get('items')!r}，"
                f"修订 duration_s={revision_scenario.get('duration_s')!r}"
                f"/items={revision_scenario.get('items')!r}"
            )
        return dict(declared_perf), "suite_manifest"
    if declared_perf:
        return dict(declared_perf), "suite_manifest"
    if revision_scenario:
        return dict(revision_scenario), "revision"
    return None, None
