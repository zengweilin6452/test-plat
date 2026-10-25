"""调度层：dispatcher 领任务、reconciler 收尸（development-plan.md §7.1）。

两者都是**幂等且可重入**的后台循环：进程被 kill、重启、同一时刻多个 worker
同时跑，都只会让它们"多试一次"，不会破坏不变量。
"""

from __future__ import annotations

from . import dispatcher, reconciler

__all__ = ["dispatcher", "reconciler"]
