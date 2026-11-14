"""Phase 1 直接操控：控制权代理、输入门控与手势 WS 透传。

约定（docs/plan/api-design.md §2.7）：
  - 控制权由平台代领，token 只在服务端；浏览器只看到 enabled；
  - 手势走 vendor /api/v1/input/gesture（单设备单手势、严格同源）；
  - 关闭会话释放控制权；他人持有 409，不抢占。
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid

import pytest
from app.routers import debug
from sqlalchemy import text
from starlette.responses import Response

from tests._p3_common import CLIENT_HEADERS, requires_db
from tests._p3_common import api_client as api_client  # noqa: F401 - 夹具复用
from tests._p3_common import p3_project as p3_project  # noqa: F401 - 夹具复用
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - 夹具复用

pytestmark = requires_db


@pytest.fixture(autouse=True)
def _clear_tokens():
    debug._CONTROL_TOKENS.clear()
    yield
    debug._CONTROL_TOKENS.clear()


def _insert_session(sync_engine, project: dict, *, state: str = "active") -> tuple[str, str]:
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
    return session_id, resource["serial"]


def _json_response(payload: dict, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False),
        status_code=status,
        media_type="application/json",
    )


def _install_forward(monkeypatch, handler):
    calls: list[dict] = []

    async def fake_forward(session_id, method, path, *, json_body=None, headers=None):
        calls.append(
            {
                "session_id": str(session_id),
                "method": method,
                "path": path,
                "json_body": json_body,
                "headers": dict(headers or {}),
            }
        )
        return handler(method, path, json_body, headers)

    # P2-03：vendor 代理分路由层（快照/控制端点）与服务层（关闭/释放）两条通道，
    # 替身两边都装，调用统一记进同一个列表。
    monkeypatch.setattr(debug, "_forward", fake_forward)
    from app.services import debug_session as debug_session_mod

    monkeypatch.setattr(debug_session_mod, "_forward", fake_forward)
    return calls


def test_claim_stores_token_and_strips_it(api_client, p3_project, sync_engine, monkeypatch):
    session_id, serial = _insert_session(sync_engine, p3_project)
    calls = _install_forward(
        monkeypatch,
        lambda method, path, body, headers: _json_response(
            {"ok": True, "token": "server-secret", "ttl_seconds": 5}
        ),
    )

    response = api_client.post(
        f"/api/v1/debug-sessions/{session_id}/control",
        json={"enabled": True},
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True and "server-secret" not in response.text
    assert debug._CONTROL_TOKENS[session_id] == "server-secret"
    assert "X-Viewer-Control" not in calls[0]["headers"]
    assert f"device={serial}" in calls[0]["path"]


def test_claim_busy_passthrough_does_not_store(api_client, p3_project, sync_engine, monkeypatch):
    session_id, _ = _insert_session(sync_engine, p3_project)
    _install_forward(
        monkeypatch,
        lambda method, path, body, headers: _json_response(
            {"code": "control-busy", "message": "其他操作者持有该设备的控制权"},
            status=409,
        ),
    )

    response = api_client.post(
        f"/api/v1/debug-sessions/{session_id}/control",
        json={"enabled": True},
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "control-busy"
    assert session_id not in debug._CONTROL_TOKENS


def test_claim_reuses_existing_token(api_client, p3_project, sync_engine, monkeypatch):
    session_id, _ = _insert_session(sync_engine, p3_project)
    debug._CONTROL_TOKENS[session_id] = "held"
    calls = _install_forward(
        monkeypatch,
        lambda method, path, body, headers: _json_response(
            {"ok": True, "token": "held", "ttl_seconds": 5, "note": "续期"}
        ),
    )

    response = api_client.post(
        f"/api/v1/debug-sessions/{session_id}/control",
        json={"enabled": True},
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 200
    assert calls[0]["headers"].get("X-Viewer-Control") == "held"
    assert debug._CONTROL_TOKENS[session_id] == "held"


def test_heartbeat_expired_drops_token(api_client, p3_project, sync_engine, monkeypatch):
    session_id, _ = _insert_session(sync_engine, p3_project)
    debug._CONTROL_TOKENS[session_id] = "stale"
    _install_forward(
        monkeypatch,
        lambda method, path, body, headers: _json_response(
            {"code": "forbidden", "message": "控制权已释放"}, status=403
        ),
    )

    response = api_client.post(
        f"/api/v1/debug-sessions/{session_id}/control/heartbeat",
        json={},
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "control_expired"
    assert session_id not in debug._CONTROL_TOKENS


def test_release_forwards_token_and_drops(api_client, p3_project, sync_engine, monkeypatch):
    session_id, _ = _insert_session(sync_engine, p3_project)
    debug._CONTROL_TOKENS[session_id] = "held"
    calls = _install_forward(
        monkeypatch,
        lambda method, path, body, headers: _json_response({"ok": True}),
    )

    response = api_client.post(
        f"/api/v1/debug-sessions/{session_id}/control",
        json={"enabled": False},
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert calls[0]["headers"].get("X-Viewer-Control") == "held"
    assert calls[0]["json_body"] == {"enabled": False}
    assert session_id not in debug._CONTROL_TOKENS


def test_input_key_requires_control_and_forwards(api_client, p3_project, sync_engine, monkeypatch):
    session_id, _ = _insert_session(sync_engine, p3_project)

    missing = api_client.post(
        f"/api/v1/debug-sessions/{session_id}/input/key",
        json={"name": "back"},
        headers=CLIENT_HEADERS,
    )
    assert missing.status_code == 409
    assert missing.json()["code"] == "control_not_enabled"

    debug._CONTROL_TOKENS[session_id] = "held"
    calls = _install_forward(
        monkeypatch,
        lambda method, path, body, headers: _json_response({"ok": True}),
    )
    response = api_client.post(
        f"/api/v1/debug-sessions/{session_id}/input/key",
        json={"name": "back"},
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 200
    assert calls[0]["headers"].get("X-Viewer-Control") == "held"
    assert calls[0]["json_body"] == {"name": "back"}


def test_input_key_control_disabled_maps_to_expired(
    api_client, p3_project, sync_engine, monkeypatch
):
    """vendor 在 TTL 后返回 400 control-disabled：平台要清 token 并给 control_expired。"""
    session_id, _ = _insert_session(sync_engine, p3_project)
    debug._CONTROL_TOKENS[session_id] = "stale"
    _install_forward(
        monkeypatch,
        lambda method, path, body, headers: _json_response(
            {"code": "control-disabled", "message": "该设备当前无操作者持有控制权"},
            status=400,
        ),
    )

    response = api_client.post(
        f"/api/v1/debug-sessions/{session_id}/input/key",
        json={"name": "back"},
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "control_expired"
    assert session_id not in debug._CONTROL_TOKENS


def test_close_session_releases_control(api_client, p3_project, sync_engine, monkeypatch):
    session_id, _ = _insert_session(sync_engine, p3_project)
    debug._CONTROL_TOKENS[session_id] = "held"
    calls = _install_forward(
        monkeypatch,
        lambda method, path, body, headers: _json_response({"ok": True}),
    )

    asyncio.run(debug._close_session(session_id, reason="pytest"))

    assert any(c["json_body"] == {"enabled": False} for c in calls)
    assert session_id not in debug._CONTROL_TOKENS


def test_gesture_ws_forwards_hello_and_frames(api_client, p3_project, sync_engine):
    """平台连 vendor 时必须带严格 Origin、先发 token hello，再透传手势帧。"""
    import websockets

    session_id, _ = _insert_session(sync_engine, p3_project)
    debug._CONTROL_TOKENS[session_id] = "held"

    recorded: dict = {}
    started = threading.Event()
    loop = asyncio.new_event_loop()

    async def handler(ws):
        recorded["origin"] = ws.request.headers.get("Origin")
        recorded["hello"] = json.loads(await ws.recv())
        recorded["frame"] = json.loads(await ws.recv())
        await ws.send(json.dumps({"kind": "ack", "echo": recorded["frame"]}))
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
    assert started.wait(10), "假 vendor WS 未启动"
    try:
        with api_client.websocket_connect(f"/api/v1/ws/debug/{session_id}/gesture") as ws:
            ws.send_text(json.dumps({"type": "start", "nx": 0.5, "ny": 0.5, "seq": 1}))
            message = json.loads(ws.receive_text())

        assert message["kind"] == "ack"
        assert recorded["hello"] == {"token": "held"}
        assert recorded["frame"] == {"type": "start", "nx": 0.5, "ny": 0.5, "seq": 1}
        assert recorded["origin"] == f"http://127.0.0.1:{recorded['port']}"
    finally:
        debug._READY_PORTS.pop(session_id, None)
        loop.call_soon_threadsafe(stop_event["event"].set)
        thread.join(timeout=10)
        loop.close()


def test_gesture_ws_requires_control(api_client, p3_project, sync_engine):
    session_id, _ = _insert_session(sync_engine, p3_project)
    from starlette.websockets import WebSocketDisconnect

    with api_client.websocket_connect(f"/api/v1/ws/debug/{session_id}/gesture") as ws:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == 4403
