"""声明式性能场景的 runner 侧校验（与平台 domain 同一口径）。

runner 跑在独立子进程里，不能 import ``app.domain.suite``（分层：runner 只依赖
vendor 与标准库）。所以这条规则在两端各留一份镜像：

- 平台：``app/domain/suite.py::scenario_problems``（发布口 / 修订 readiness / 派发）；
- runner：本模块（采集入口 ``run_perf_job``）。

``tests/test_issue06_perf_scenario.py::test_runner_window_matches_platform_rule``
逐项对照两端的常量与边界行为，任何一端放宽都会立刻变红。
"""

from __future__ import annotations

from typing import Any

#: 性能采集窗口的合法区间（秒，整数）——与 app/domain/suite.py 常量一致
PERF_DURATION_MIN_S = 10
PERF_DURATION_MAX_S = 3600


def scenario_problems(scenario: Any) -> list[str]:
    """返回场景问题列表（空表示通过）。

    规则：duration_s 必须是 10–3600 的整数秒（不接受 bool / 浮点 / 字符串），
    items 必须是非空字符串列表。越界一律拒绝，不夹紧、不改写。
    """
    if not isinstance(scenario, dict) or not scenario:
        return ["缺少声明式性能场景（duration_s 与采集项）"]
    problems: list[str] = []
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
    return problems


__all__ = ["PERF_DURATION_MAX_S", "PERF_DURATION_MIN_S", "scenario_problems"]
