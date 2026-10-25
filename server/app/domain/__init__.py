"""领域层：状态转换的唯一入口（development-plan.md §6.3）。

规则：路由层只做参数解析与 HTTP 语义，不直接写 state 列。所有状态取值与
迁移判断都集中在 domain/ 里：
  - task.py   test_tasks.lifecycle / lock_version / task_revisions.readiness
  - suite.py  suite_versions 的版本推进与 manifest 归一化
这样"哪些迁移合法"只有一处定义，DB 的 CHECK 约束与领域判断不会各说一套。
"""

from __future__ import annotations

from . import suite, task

# P3 追加：运行生命周期 / 租约 / 产物 / 事件
from . import artifacts, events, leases, runs

__all__ = [
    "artifacts",
    "events",
    "leases",
    "runs",
    "suite",
    "task",
]
