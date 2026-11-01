"""Phase 2：调试页 H.264 视频 WS 代理。

平台把浏览器 <-> vendor /api/v1/preview/video 连起来：
  - 上游必须带严格 Origin 并发 {"proto":1} hello（vendor 拒绝缺失 Origin）；
  - 只下行转发 ready/error JSON 与 27 字节头二进制帧；
  - 会话非 active/未知 -> 4403/4404；每会话最多一条视频流。
"""

from __future__ import annotations

import asyncio
import json
import struct
import threading
import uuid

import pytest
from sqlalchemy import text

from app.routers import debug
from tests._p3_common import requires_db
from tests._p3_common import api_client as api_client  # noqa: F401 - 夹具复用
from tests._p3_common import p3_project as p3_project  # noqa: F401 - 夹具复用
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - 夹具复用

pytestmark = requires_db

_HEADER = struct.Struct(">BBIIQBHHI")


def _insert_session(sync_engine, project: dict, *, state: str = "active") -> str:
    session_id = str(uuid.uuid4())
    resource = project["resources"][0]
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO debug_sessions"
                " (id, project_id, resource_id, actor_ref, state, expires_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         'pytest', :state, now() + interval '10 minutes')"
            ),
            {
                "id": session_id,
                "pid": project["project_id"],
                "rid": resource["id"],
                "state": state,
            },
        )
    return session_id


def _session_packet(width: int = 1080, height: int = 2400) -> bytes:
    return _HEADER.pack(1, 2, 7, 1, 0, 0, width, height, 0)


def test_video_ws_forwards_origin_hello_ready_and_frames(api_client, p3_project, sync_engine):
    import websockets

    session_id = _insert_session(sync_engine, p3_project)
    recorded: dict = {}
    started = threading.Event()
    loop = asyncio.new_event_loop()

    async def handler(ws):
        recorded["origin"] = ws.request.headers.get("Origin")
        recorded["hello"] = json.loads(await ws.recv())
        await ws.send(json.dumps({"kind": "ready", "generation": 7}))
        await ws.send(_session_packet())
        await ws.close()

    async def serve(stop: asyncio.Event):
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            recorded["port"] = server.sockets[0].getsockname()[1]
            debug._READY_PORTS[session_id] = recorded["port"]
            started.set()
            await stop.wait()

    stop_event: dict = {}

    def run():
        asyncio.set_event_loop(loop)
        stop = asyncio.Event()
        stop_event["event"] = stop
        loop.run_until_complete(serve(stop))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(10), "假 vendor 视频 WS 未启动"
    try:
        with api_client.websocket_connect(f"/api/v1/ws/debug/{session_id}/video") as ws:
            ready = json.loads(ws.receive_text())
            payload = ws.receive_bytes()
            ws.send_text(json.dumps({"ignored": True}))
        assert ready == {"kind": "ready", "generation": 7}
        version, kind, generation, sequence, pts, flags, width, height, length = (
            _HEADER.unpack(payload)
        )
        assert (version, kind, generation, width, height, length) == (1, 2, 7, 1080, 2400, 0)
        assert recorded["hello"] == {"proto": 1}
        assert recorded["origin"] == f"http://127.0.0.1:{recorded['port']}"
    finally:
        debug._READY_PORTS.pop(session_id, None)
        loop.call_soon_threadsafe(stop_event["event"].set)
        thread.join(timeout=10)
        loop.close()


def test_video_ws_unknown_session_4404(api_client, p3_project):
    from starlette.websockets import WebSocketDisconnect

    with api_client.websocket_connect(f"/api/v1/ws/debug/{uuid.uuid4()}/video") as ws:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4404


def test_video_ws_inactive_session_4403(api_client, p3_project, sync_engine):
    from starlette.websockets import WebSocketDisconnect

    session_id = _insert_session(sync_engine, p3_project, state="opening")
    with api_client.websocket_connect(f"/api/v1/ws/debug/{session_id}/video") as ws:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4403
