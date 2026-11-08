"""声明式性能场景的 runner 侧校验（与平台 domain 同一口径）。

runner 跑在独立子进程里，不能 import ``app.domain.suite``（分层：runner 只依赖
vendor 与标准库）。所以这条规则在两端各留一份镜像：

- 平台：``app/domain/suite.py::scenario_problems``（发布口 / 修订 readiness / 派发）；
- runner：本模块（采集入口 ``run_perf_job``）。

``tests/test_issue06_perf_scenario.py::test_runner_window_matches_platform_rule``
逐项对照两端的常量与边界行为，任何一端放宽都会立刻变红。

能力字段（2026-11 性能能力接入）：除 duration_s / items 外，场景还可声明
start_mode（启动编排）、capture_har（HAR 抓包）、net_profile/net_tier/net_port/
net_mitmdump/net_overrides（网络剖面与代理）、frame_poll（逐帧统计）、
page_marks（页面打标 -> page_load_ms）、ui_timeout_s（joint UI 上限）。
全部可选；未知字段一律拒绝（宁可发布失败也不让配置被静默忽略）。
"""

from __future__ import annotations

from typing import Any

#: 性能采集窗口的合法区间（秒，整数）——与 app/domain/suite.py 常量一致
PERF_DURATION_MIN_S = 10
PERF_DURATION_MAX_S = 3600

#: 与 vendor netprof.PROFILE_NAMES 对齐（custom 必须带 net_overrides）
NET_PROFILES = ("none", "4g", "3g", "weak", "custom")
NET_TIERS = ("passthrough", "decrypt")
STARTUP_MODES = ("cold", "warm")

#: 场景白名单：未知字段直接拒绝，不让配置被静默忽略
SCENARIO_KEYS = (
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


def _bool_problems(value: Any, label: str) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    return [f"{label} 必须是布尔值"]


def _net_problems(scenario: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    profile = scenario.get("net_profile")
    if profile is not None:
        if not isinstance(profile, str) or profile not in NET_PROFILES:
            problems.append(f"net_profile 只支持 {'/'.join(NET_PROFILES)} 或不填")
    tier = scenario.get("net_tier")
    if tier is not None and (not isinstance(tier, str) or tier not in NET_TIERS):
        problems.append(f"net_tier 只支持 {'/'.join(NET_TIERS)} 或不填")
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
        if profile == "custom" and isinstance(overrides, dict) and len(overrides) < 4:
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
            problems.append(f"page_marks[{index}] 必须是 {page_mark_shape()}")
            continue
        page = mark.get("page")
        at_s = mark.get("at_s")
        if not isinstance(page, str) or not page.strip():
            problems.append(f"page_marks[{index}].page 必须是非空字符串")
        if not isinstance(at_s, (int, float)) or isinstance(at_s, bool) or at_s < 0:
            problems.append(f"page_marks[{index}].at_s 必须是不小于 0 的数字（相对采集窗口起点秒）")
    return problems


def page_mark_shape() -> str:
    return '{"page": "页面名", "at_s": 秒}'


def collect_kwargs_from_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """场景 -> vendor kit.collect 的可选 kwargs（只透传已启用的能力）。

    返回值全部是 vendor kit.collect 的合法参数；未启用的能力不传，
    保持 vendor 默认（无编排、无代理、无 HAR、无逐帧轮询）。
    """
    kwargs: dict[str, Any] = {}
    start_mode = scenario.get("start_mode")
    if start_mode:
        kwargs["start_mode"] = str(start_mode)
    if scenario.get("capture_har"):
        kwargs["capture_har"] = True
    if scenario.get("net_profile"):
        kwargs["net_profile"] = str(scenario["net_profile"])
    if scenario.get("net_tier"):
        kwargs["net_tier"] = str(scenario["net_tier"])
    if scenario.get("net_port"):
        kwargs["net_port"] = int(scenario["net_port"])
    if scenario.get("net_mitmdump"):
        kwargs["net_mitmdump"] = str(scenario["net_mitmdump"])
    overrides = scenario.get("net_overrides")
    if isinstance(overrides, dict) and overrides:
        kwargs["net_overrides"] = {
            str(name): float(value)
            for name, value in overrides.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    if scenario.get("frame_poll"):
        kwargs["frame_poll"] = True
    return kwargs


def page_marks_from_scenario(scenario: dict[str, Any]) -> list[tuple[float, str]]:
    """场景 -> [(at_s, page), ...]（按时间升序），供采集窗口内调度 mark_page。"""
    marks = scenario.get("page_marks") or []
    scheduled: list[tuple[float, str]] = []
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        at_s = mark.get("at_s")
        page = mark.get("page")
        if isinstance(at_s, (int, float)) and not isinstance(at_s, bool) and isinstance(page, str) and page.strip():
            scheduled.append((float(at_s), page.strip()))
    return sorted(scheduled)


def scenario_problems(scenario: Any) -> list[str]:
    """返回场景问题列表（空表示通过）。

    规则：duration_s 必须是 10–3600 的整数秒（不接受 bool / 浮点 / 字符串），
    items 必须是非空字符串列表；可选能力字段按白名单与取值域校验；
    未知字段一律拒绝。越界一律拒绝，不夹紧、不改写。
    """
    if not isinstance(scenario, dict) or not scenario:
        return ["缺少声明式性能场景（duration_s 与采集项）"]
    problems: list[str] = []
    unknown = sorted(set(scenario) - set(SCENARIO_KEYS))
    if unknown:
        problems.append("场景包含未知字段：" + "、".join(unknown))
    duration = scenario.get("duration_s")
    if not isinstance(duration, int) or isinstance(duration, bool):
        problems.append("性能场景 duration_s 必须是整数秒")
    elif not (PERF_DURATION_MIN_S <= duration <= PERF_DURATION_MAX_S):
        problems.append(
            f"性能场景 duration_s 必须在 {PERF_DURATION_MIN_S}–{PERF_DURATION_MAX_S} 秒之间"
        )
    items = scenario.get("items")
    if not isinstance(items, list) or not items or not all(
        isinstance(item, str) and item.strip() for item in items
    ):
        problems.append("性能场景采集项 items 必须是非空字符串列表")
    start_mode = scenario.get("start_mode")
    if start_mode is not None and (not isinstance(start_mode, str) or start_mode not in STARTUP_MODES):
        problems.append(f"start_mode 只支持 {'/'.join(STARTUP_MODES)} 或不填")
    problems.extend(_bool_problems(scenario.get("capture_har"), "capture_har"))
    problems.extend(_bool_problems(scenario.get("frame_poll"), "frame_poll"))
    problems.extend(_net_problems(scenario))
    problems.extend(_page_mark_problems(scenario))
    ui_timeout = scenario.get("ui_timeout_s")
    if ui_timeout is not None and (
        not isinstance(ui_timeout, int) or isinstance(ui_timeout, bool) or ui_timeout <= 0
    ):
        problems.append("ui_timeout_s 必须是正整数")
    return problems


__all__ = [
    "NET_PROFILES",
    "NET_TIERS",
    "PERF_DURATION_MAX_S",
    "PERF_DURATION_MIN_S",
    "SCENARIO_KEYS",
    "STARTUP_MODES",
    "collect_kwargs_from_scenario",
    "page_mark_shape",
    "page_marks_from_scenario",
    "scenario_problems",
]
