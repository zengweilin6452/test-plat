"""P5 设备调试会话 API 集成测试（testdock 共享库，TESTDOCK_FAKE_RUNNER=1 通道）。

覆盖（任务书 §5）：
  * busy 设备 409 且 details 带占用者 display_id
  * offline（非 ready）设备 409
  * 未知 serial 404
  * fake runner（TESTDOCK_FAKE_RUNNER=1 -> runner 子进程回报固定端口）-> active、
    base_url/ws_path 出现、代理端点上游不可达 -> 503
  * DELETE 幂等 + 租约释放后设备回 ready、可再建会话
  * WS：会话不存在 close(4404)、非 active close(4403)
  * 模板端点无活动会话 -> 501
  * 静态：routers.debug 不得在模块顶层 import vendor
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from tests._p3_common import CLIENT_HEADERS, TEST_DB, reset_db_engine, requires_db
from tests._p3_common import control_token as control_token  # noqa: PLW0127 - 夹具复用
from tests._p3_common import sync_engine as sync_engine  # noqa: PLW0127 - 夹具复用
from tests._p3_common import api_client as api_client  # noqa: PLW0127 - 夹具复用
from tests._p3_common import p3_project as p3_project  # noqa: PLW0127 - 夹具复用
from tests._p3_common import make_run as make_run  # noqa: PLW0127 - 夹具复用
from tests._p3_common import sync_engine as sync_engine  # noqa: PLW0127 - 夹具复用

pytestmark = [requires_db, pytest.mark.skipif(not TEST_DB, reason="需要测试库")]


@pytest.fixture(scope="module")
def control_stub(api_client):
    """假控制面：runner 子进程把 ready 上报到这个本地 HTTP stub，
    stub 再转发给 TestClient 的 /internal/debug-sessions/{id}/ready ——
    TestClient 不监听 TCP 端口，fake runner 没法直接打到它。"""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    captured: dict = {"port": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            token = self.headers.get("X-Control-Token", "")
            # 转发给真正的 internal 端点（走 TestClient，与生产同一代码路径）
            response = api_client.post(
                self.path,
                content=body,
                headers={"X-Control-Token": token, "Content-Type": "application/json"},
            )
            captured["status"] = response.status_code
            captured["body"] = response.text
            payload = response.content
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # noqa: N802 - 静音
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    captured["port"] = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = getattr(api_client.app.state, "control_token", None)
    assert token, "lifespan 应该生成 control token"
    yield f"http://127.0.0.1:{captured['port']}", token
    server.shutdown()


@pytest.fixture(scope="module")
def fake_runner_env():
    """fake runner：spawn 出去的是 testdock_runner debug --fake，回报固定端口。"""
    old = os.environ.get("TESTDOCK_FAKE_RUNNER")
    os.environ["TESTDOCK_FAKE_RUNNER"] = "1"
    yield
    if old is None:
        os.environ.pop("TESTDOCK_FAKE_RUNNER", None)
    else:
        os.environ["TESTDOCK_FAKE_RUNNER"] = old


def _create_session(client: TestClient, serial: str) -> tuple[int, dict]:
    response = client.post(
        "/api/v1/debug-sessions",
        json={"serial": serial, "purpose": "pytest"},
        headers=CLIENT_HEADERS,
    )
    return response.status_code, _json(response)


def _json(response) -> dict:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return {}


def _set_resource_status(sync_engine, resource_id: str, status: str) -> None:
    from sqlalchemy import text

    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE execution_resources SET status = :s"
                " WHERE id = CAST(:i AS uuid)"
            ),
            {"s": status, "i": resource_id},
        )


def _active_lease(sync_engine, resource_id: str) -> dict | None:
    from sqlalchemy import text

    with sync_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, holder_id, run_id, debug_session_id FROM resource_leases"
                " WHERE resource_id = CAST(:i AS uuid) AND released_at IS NULL"
            ),
            {"i": resource_id},
        ).mappings().first()
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
# 校验 / 冲突
# --------------------------------------------------------------------------- #
@requires_db
def test_create_unknown_serial_404(api_client, p3_project):
    status, body = _create_session(api_client, "NO-SUCH-SERIAL-0000")
    assert status == 404
    assert body["code"] == "not_found"


@requires_db
def test_create_offline_device_conflict(api_client, p3_project, sync_engine):
    resource = p3_project["resources"][0]
    _set_resource_status(sync_engine, resource["id"], "offline")
    try:
        status, body = _create_session(api_client, resource["serial"])
        assert status == 409
        assert body["code"] == "device_not_ready"
    finally:
        _set_resource_status(sync_engine, resource["id"], "ready")


@requires_db
def test_create_busy_device_conflict_carries_holder(api_client, p3_project, fake_runner_env, make_run, sync_engine):
    """设备被 run 租约占用时新建调试会话 -> 409，details 带占用者 display_id。"""
    resource = p3_project["resources"][0]
    # 直接给该设备插一条活动 run 租约（模拟被一个 run 占用）
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    lease_id = str(uuid.uuid4())
    run_id = make_run(
        state="running",
        request_key="p5-busy-" + uuid.uuid4().hex[:8],
        project=p3_project,
    )
    # 取 run 实际绑定的 resource_id（FK (project,run,resource) 必须逐一对上）
    with sync_engine.connect() as conn:
        bound_resource = conn.execute(
            text("SELECT resource_id FROM test_runs WHERE id = CAST(:r AS uuid)"),
            {"r": run_id},
        ).scalar()
    assert bound_resource is not None
    resource["id"] = str(bound_resource)

    async def _insert() -> None:
        engine = create_async_engine(TEST_DB)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO resource_leases (id, project_id, resource_id, run_id,"
                        "                        fencing_token, holder_id, expires_at)"
                        " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                        "         CAST(:run AS uuid), 9001, 'pytest-run-holder',"
                        "         now() + interval '10 minutes')"
                    ),
                    {
                        "id": lease_id,
                        "pid": p3_project["project_id"],
                        "rid": resource["id"],
                        "run": run_id,
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(_insert())
    try:
        status, body = _create_session(api_client, resource["serial"])
        assert status == 409, body
        assert body["code"] == "device_busy"
        holder = body["details"].get("holder") or {}
        assert holder.get("display_id") == resource["serial"]
        assert holder.get("run_id") == run_id
    finally:
        async def _cleanup() -> None:
            engine = create_async_engine(TEST_DB)
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE resource_leases SET released_at = now(),"
                            " release_reason = 'test-cleanup'"
                            " WHERE id = CAST(:i AS uuid)"
                        ),
                        {"i": lease_id},
                    )
            finally:
                await engine.dispose()

        asyncio.run(_cleanup())


# --------------------------------------------------------------------------- #
# fake runner 全链路
# --------------------------------------------------------------------------- #
@requires_db
def test_fake_runner_lifecycle(api_client, p3_project, fake_runner_env, control_stub, monkeypatch, sync_engine):
    """fake runner 回报固定端口 -> active；代理上游不可达 -> 503；DELETE 幂等。"""
    url, _token = control_stub
    monkeypatch.setenv("TESTDOCK_CONTROL_URL", url)
    resource = p3_project["resources"][0]
    status, body = _create_session(api_client, resource["serial"])
    assert status == 201, body
    session_id = body["id"]
    try:
        # 轮询等待 fake runner 上报 ready（最多 ~20s）
        state = body["state"]
        detail = body
        for _ in range(40):
            detail = _json(api_client.get(f"/api/v1/debug-sessions/{session_id}"))
            state = detail.get("state")
            if state == "active":
                break
            import time

            time.sleep(0.5)
        assert state == "active", detail
        assert detail["base_url"].startswith("http://127.0.0.1:")
        assert detail["ws_path"] == f"/api/v1/ws/debug/{session_id}"

        # 代理端点：fake 端口上没有真 viewer -> 503 viewer_unavailable
        response = api_client.post(
            f"/api/v1/debug-sessions/{session_id}/snapshots", json={}, headers=CLIENT_HEADERS
        )
        assert response.status_code == 503
        assert _json(response)["code"] == "viewer_unavailable"

        # 模板代理必须显式携带会话：带 session_id 指向活动会话；fake 端口没有
        # 真 viewer -> 503，不伪造清单
        response = api_client.get(
            f"/api/v1/templates?session_id={session_id}", headers=CLIENT_HEADERS
        )
        assert response.status_code == 503
        assert _json(response)["code"] == "viewer_unavailable"

        # 活动会话下 WS 不再是 4403（连不连得上 vendor 由透传决定；这里只验状态门）
    finally:
        # DELETE：设备租约释放 + 状态回 ready
        response = api_client.delete(f"/api/v1/debug-sessions/{session_id}", headers=CLIENT_HEADERS)
        assert response.status_code == 200
        assert _json(response)["state"] == "closed"

    from sqlalchemy import text

    row = None
    with sync_engine.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM execution_resources WHERE id = CAST(:i AS uuid)"),
            {"i": resource["id"]},
        ).scalar()
        lease = conn.execute(
            text(
                "SELECT released_at FROM resource_leases"
                " WHERE debug_session_id = CAST(:s AS uuid)"
            ),
            {"s": session_id},
        ).scalar()
    assert row == "ready"
    assert lease is not None

    # 幂等：再 DELETE 一次仍 200
    response = api_client.delete(f"/api/v1/debug-sessions/{session_id}", headers=CLIENT_HEADERS)
    assert response.status_code == 200


@requires_db
def test_create_after_close_reacquires(api_client, p3_project, fake_runner_env, control_stub, monkeypatch):
    """关闭后设备可再次被会话占用（租约互斥确实被释放）。"""
    url, _token = control_stub
    monkeypatch.setenv("TESTDOCK_CONTROL_URL", url)
    resource = p3_project["resources"][1]
    status, body = _create_session(api_client, resource["serial"])
    assert status == 201
    session_id = body["id"]
    api_client.delete(f"/api/v1/debug-sessions/{session_id}", headers=CLIENT_HEADERS)
    status2, body2 = _create_session(api_client, resource["serial"])
    assert status2 == 201, body2
    api_client.delete(f"/api/v1/debug-sessions/{body2['id']}", headers=CLIENT_HEADERS)


# --------------------------------------------------------------------------- #
# WS 状态门
# --------------------------------------------------------------------------- #
@requires_db
def test_ws_unknown_session_4404(api_client, p3_project):
    _expect_close(
        api_client,
        "/api/v1/ws/debug/" + str(uuid.uuid4()),
        4404,
    )


@requires_db
def test_ws_opening_session_4403(api_client, p3_project, fake_runner_env, control_stub, monkeypatch, sync_engine):
    """非 active 会话 -> close 4403；直接 SQL 把会话压回 opening 再连。"""
    url, _token = control_stub
    monkeypatch.setenv("TESTDOCK_CONTROL_URL", url)
    from sqlalchemy import text

    resource = p3_project["resources"][0]
    status, body = _create_session(api_client, resource["serial"])
    assert status == 201
    session_id = body["id"]
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE debug_sessions SET state = 'opening'"
                    " WHERE id = CAST(:s AS uuid)"
                ),
                {"s": session_id},
            )
        _expect_close(api_client, f"/api/v1/ws/debug/{session_id}", 4403)
    finally:
        api_client.delete(f"/api/v1/debug-sessions/{session_id}", headers=CLIENT_HEADERS)


def _expect_close(client: TestClient, url: str, code: int) -> None:
    from starlette.websockets import WebSocketDisconnect

    with client.websocket_connect(url) as ws:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
    assert excinfo.value.code == code


# --------------------------------------------------------------------------- #
# 模板 400（session_id 必填：按调试会话隔离，删除了全局兜底）
# --------------------------------------------------------------------------- #
@requires_db
def test_templates_400_without_session(api_client, p3_project):
    """无 session_id 的模板请求曾兜底挑"最新活动会话"，是跨项目泄漏点；现在必须校验失败。"""
    for method, url, kwargs in [
        ("get", "/api/v1/templates", {}),
        ("post", "/api/v1/templates", {"json": {"name": "t"}}),
        ("put", "/api/v1/templates/some/path", {"json": {"name": "t"}}),
        ("post", "/api/v1/templates/validate", {"json": {"target": {"by": "image", "value": "a.png"}}}),
    ]:
        response = getattr(api_client, method)(url, headers=CLIENT_HEADERS, **kwargs)
        assert response.status_code == 400, (method, response.status_code)
        body = _json(response)
        assert body["code"] == "validation_error"
        assert "session_id" in body["message"]
        assert "debug-sessions" in body["message"]


@requires_db
def test_templates_with_unknown_session_404(api_client, p3_project):
    response = api_client.get(
        f"/api/v1/templates?session_id={uuid.uuid4()}", headers=CLIENT_HEADERS
    )
    assert response.status_code == 404
    assert _json(response)["code"] == "not_found"


# --------------------------------------------------------------------------- #
# 图像定位验证：必须转发到 vendor 的 /templates/validate
# --------------------------------------------------------------------------- #
@requires_db
def test_image_validate_forwards_to_vendor_template_endpoint(api_client, monkeypatch):
    """真机实测（2026-10-28）：POST /locators/validate 传 by='image' 必 500 ——
    vendor 的 `_query_payload` 对图像目标返回 4 元组（带 scores），
    `capture_and_query_sync` 在 with_scores=False 时按 3 元组解包。vendor/ 是只读
    源仓库，所以平台侧改走 vendor 自己的 /templates/validate；这条测试钉住转发路径，
    防止有人"顺手"改回通用定位端点。
    """
    from fastapi.responses import JSONResponse

    from app.routers import debug as debug_mod

    captured: dict = {}

    async def _fake_forward(session_id, method, path, *, json_body=None):
        captured.update({"session_id": session_id, "method": method, "path": path, "body": json_body})
        return JSONResponse({"count": 0, "matches": [], "scores": [], "note": "零匹配"})

    async def _fake_template_session(session, session_id):
        return "00000000-0000-0000-0000-000000000001"

    monkeypatch.setattr(debug_mod, "_template_session", _fake_template_session)
    monkeypatch.setattr(debug_mod, "_forward", _fake_forward)

    response = api_client.post(
        f"/api/v1/templates/validate?session_id={uuid.uuid4()}",
        json={"target": {"by": "image", "value": "buttons/ok.png"}},
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/templates/validate"
    assert captured["body"]["target"]["value"] == "buttons/ok.png"


# --------------------------------------------------------------------------- #
# 静态：debug 路由模块顶层不得 import vendor
# --------------------------------------------------------------------------- #
def test_debug_router_no_vendor_import_at_module_level():
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "app" / "routers" / "debug.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = {"mobile_auto", "mobile_perf", "uvicorn"}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [
                node.module or ""
            ]
            for name in names:
                assert not any(name == b or name.startswith(b + ".") for b in banned), name
