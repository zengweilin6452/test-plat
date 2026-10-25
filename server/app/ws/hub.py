"""进程内 WS 广播中心。

为什么不用 Redis / 消息队列
-------------------------
API 是**单进程** uvicorn（main() 用显式 Selector 事件循环跑一个 Server），
所有 WS 连接、dispatcher、reconciler、runner tail 都在同一个循环里。所以一个
asyncio.Queue 就是完整的广播总线，没有跨进程投递问题。

两个需要注意的点：
  1. 从线程里推（runner 的 stdout 读线程、taskkill 回调）不能直接 await，
     用 publish_threadsafe() -> loop.call_soon_threadsafe。
  2. 慢客户端不能拖垮广播：队列满就丢最老的一帧（帧本身是可丢的增量视图，
     下一帧 snapshot 会补齐真相）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: 每个订阅者队列的上限（约 2s 轮询 * 若干事件，够用；超了丢最老）
QUEUE_LIMIT = 256

_SUBSCRIBERS: dict[str, set[asyncio.Queue]] = {}
_LOOP: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """应用启动时绑定事件循环（publish_threadsafe 需要它）。"""
    global _LOOP
    _LOOP = loop or asyncio.get_event_loop()


def subscribe(run_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
    _SUBSCRIBERS.setdefault(str(run_id), set()).add(queue)
    return queue


def unsubscribe(run_id: str, queue: asyncio.Queue) -> None:
    bucket = _SUBSCRIBERS.get(str(run_id))
    if not bucket:
        return
    bucket.discard(queue)
    if not bucket:
        _SUBSCRIBERS.pop(str(run_id), None)


def subscriber_count(run_id: str) -> int:
    return len(_SUBSCRIBERS.get(str(run_id), ()))


def publish(run_id: str, frame: dict[str, Any]) -> None:
    """在事件循环线程里广播一帧。"""
    for queue in list(_SUBSCRIBERS.get(str(run_id), ())):
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(frame)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                logger.debug("WS 队列满，丢弃一帧 run=%s", run_id)


def publish_threadsafe(run_id: str, frame: dict[str, Any]) -> None:
    """从非事件循环线程广播（runner stdout 线程等）。"""
    loop = _LOOP
    if loop is None:
        return
    try:
        loop.call_soon_threadsafe(publish, str(run_id), frame)
    except RuntimeError:  # 循环已关闭（测试收尾）
        pass


def reset() -> None:
    """测试用：清空所有订阅者。"""
    _SUBSCRIBERS.clear()


__all__ = [
    "QUEUE_LIMIT",
    "bind_loop",
    "publish",
    "publish_threadsafe",
    "reset",
    "subscribe",
    "subscriber_count",
    "unsubscribe",
]
