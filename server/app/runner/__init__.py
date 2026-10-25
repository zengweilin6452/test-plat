"""runner 子进程管理：只负责"拉起 / 转发 / 杀掉"，不含设备逻辑。

设备逻辑全部在 `testdock_runner` 包里（唯一允许 import vendor 的地方），并通过
`python -m testdock_runner` 在**独立进程**中执行。这样 API 进程既不需要 vendor
依赖，也不会因为设备操作卡死自己的事件循环。
"""

from __future__ import annotations

from . import spawn

__all__ = ["spawn"]
