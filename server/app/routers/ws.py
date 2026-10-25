"""WebSocket 实时通道：/ws/runs/{id}（api-design.md §5 / development-plan.md §8.2）。

为什么用 WS 而不是纯前端轮询：跑一次 UI 套件要几分钟，前端要看到 state / progress /
stage 的连续变化。WS 只是推的通道，真相仍然在库里：连接建立先推 snapshot，之后每 2s
对库做一次轮询（不依赖 runner 事件一定到达 —— runner 可能崩），因此刷新页面或断线重连
都能立刻回到正确进度；app/ws/hub 让 runner 事件也能即时插入推送。

帧格式（服务端 -> 客户端，文本帧 JSON）：
  {"type":"snapshot","run":{...}}
  {"type":"state","state":"running","progress":40,"stage":2,"at":null}
  {"type":"event","kind":"stage","name":"pytest","at":null}
  {"type":"finished","state":"completed","outcome":"passed"}
客户端只允许发 {"type":"ping"}。关闭码：4404 run 不存在；4409 已终态（推完再关）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ws import hub as hub_mod

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])

# 库轮询间隔（秒），与开发计划里 2s 轮询推 state/progress/stage 一致
POLL_INTERVAL = 2.0
TERMINAL = ("completed", "errored", "cancelled")


@router.websocket("/ws/runs/{run_id}")
async def run_socket(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    run_id = str(run_id)
    hub_mod.bind_loop(asyncio.get_running_loop())
    queue = hub_mod.subscribe(run_id)
    stop = asyncio.Event()

    async def snapshot() -> dict[str, Any] | None:
        from ..db import get_sessionmaker
        from ..routers.runs import _run_view

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            try:
                return await _run_view(session, run_id)
            except Exception:  # noqa: BLE001 - run 不存在 / DB 抖动都当"没有"
                return None
            finally:
                await session.rollback()

    try:
        view = await snapshot()
        if view is None:
            await websocket.close(code=4404)
            return
        await websocket.send_text(json.dumps({"type": "snapshot", "run": _plain(view)}, ensure_ascii=False))
        if view["state"] in TERMINAL:
            await websocket.send_text(
                json.dumps({"type": "finished", "state": view["state"], "outcome": view["outcome"]})
            )
            await websocket.close(code=4409)
            return

        last = {"state": view["state"], "progress": view.get("progress")}

        async def poll_loop() -> None:
            while not stop.is_set():
                await asyncio.sleep(POLL_INTERVAL)
                if stop.is_set():
                    return
                current = await snapshot()
                if current is None:
                    return
                changed = (current["state"] != last["state"]) or (
                    current.get("progress") != last["progress"]
                )
                last["state"] = current["state"]
                last["progress"] = current.get("progress")
                if changed:
                    frame = {
                        "type": "state",
                        "state": current["state"],
                        "progress": current.get("progress"),
                        "stage": current.get("stage"),
                        "at": None,
                    }
                    await websocket.send_text(json.dumps(frame, ensure_ascii=False))
                if current["state"] in TERMINAL:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "finished",
                                "state": current["state"],
                                "outcome": current["outcome"],
                            }
                        )
                    )
                    with contextlib.suppress(Exception):
                        await websocket.close(code=4409)
                    stop.set()
                    return

        async def hub_loop() -> None:
            while not stop.is_set():
                frame = await queue.get()
                if frame is None:
                    return
                await websocket.send_text(json.dumps(_plain(frame), ensure_ascii=False))

        poller = asyncio.create_task(poll_loop())
        publisher = asyncio.create_task(hub_loop())
        try:
            while not stop.is_set():
                message = await websocket.receive_text()
                with contextlib.suppress(ValueError):
                    payload = json.loads(message)
                    if isinstance(payload, dict) and payload.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                if poller.done() or publisher.done():
                    break
        finally:
            stop.set()
            for task in (poller, publisher):
                task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("ws failed: run=%s", run_id)
    finally:
        with contextlib.suppress(Exception):
            hub_mod.unsubscribe(run_id, queue)


def _plain(value: Any) -> Any:
    """把不可 JSON 序列化的对象（UUID / datetime 等）转成字符串。"""
    import datetime as _dt
    import uuid as _uuid

    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, _uuid.UUID):
        return str(value)
    return str(value)


__all__ = ["router"]
