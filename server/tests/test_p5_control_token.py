"""控制令牌一致性回归（P5 内部协议 / 调试会话）。

背景（真机验收 2026-10-28 实测）：`python -m app.main` 启动时服务跑在 `__main__`
模块里，而 `debug_runtime._current_app_state()` 里的 `from ..main import app` 会把
`app.main` **再导入一次**，拿到一个没跑过 lifespan 的 app（state 为空），于是 spawn
侧回落去读磁盘文件。`ensure_token` 每次启动都重新生成并落盘，所以只要本机还有
第二个 API 进程（或文件被手工改过），runner 拿到的令牌就和 /internal/* 校验用的
不一致 —— 调试会话建起来就 401 退出（state=closed, reason=runner_exit）。

三条口径：
1. 进程内登记过令牌时，解析结果永远是它，不受磁盘文件影响；
2. app.state 不可达（双导入）时，spawn 侧与校验侧解析出同一个值；
3. 端点级：POST /debug-sessions 交给 spawn 的令牌必须能通过 /internal/* 校验。
"""

from __future__ import annotations

import types
import uuid

import pytest
from starlette.requests import Request

from tests._p3_common import CLIENT_HEADERS, requires_db
from tests._p3_common import api_client as api_client  # noqa: F401 - 夹具复用
from tests._p3_common import p3_project as p3_project  # noqa: F401 - 夹具复用
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - 夹具复用


@pytest.fixture
def token_env(tmp_path, monkeypatch):
    """内存令牌与磁盘令牌刻意不同：实现只要回落到文件，断言就会失败。"""
    from app.config import settings
    from app.domain import control as control_mod

    path = tmp_path / "control.token"
    control_mod.write_token(path, "disk-" + uuid.uuid4().hex)
    memory = "memory-" + uuid.uuid4().hex
    previous = control_mod.current_token()
    control_mod.set_current_token(memory)
    monkeypatch.setattr(type(settings), "control_token_path", property(lambda self: path))
    try:
        yield {"memory": memory, "path": path}
    finally:
        control_mod.set_current_token(previous)


def test_resolve_token_prefers_in_process_value(token_env):
    from app.domain import control as control_mod

    # 进程内值 > app.state > 文件：两侧都走这一个函数才不会各说各话
    assert control_mod.resolve_token(None, token_env["path"]) == token_env["memory"]
    assert control_mod.resolve_token("state-" + uuid.uuid4().hex, token_env["path"]) == token_env["memory"]

    # 没登记过令牌（CLI / 没跑 lifespan 的纯单测）才回落到文件
    control_mod.set_current_token(None)
    assert control_mod.resolve_token(None, token_env["path"]) == control_mod.read_token(token_env["path"])


def test_runner_token_ignores_rotated_file(token_env, monkeypatch):
    """spawn 侧：`from ..main import app` 拿到空 state 时，也不能去读文件。"""
    from app.routers import debug_runtime

    monkeypatch.setattr(debug_runtime, "_current_app_state", lambda: types.SimpleNamespace())
    _, token = debug_runtime.get_control_url_and_token()
    assert token == token_env["memory"]


def test_guard_resolves_same_token(token_env):
    """校验侧：与 spawn 侧同一条件下解析出同一个值。"""
    from app.routers.internal import _expected_token

    request = Request({"type": "http", "app": types.SimpleNamespace(state=types.SimpleNamespace())})
    assert _expected_token(request) == token_env["memory"]


@requires_db
def test_spawn_token_passes_internal_guard(api_client, p3_project, monkeypatch, token_env):
    """端点级：双导入 + 文件被轮换时，交给 runner 的令牌仍能通过 /internal/* 校验。"""
    from app.routers import debug_runtime
    from app.runner import spawn as spawn_mod

    captured: dict = {}

    async def _fake_spawn(**kwargs):
        captured.update(kwargs)
        return 4242

    monkeypatch.setattr(spawn_mod, "spawn_runner", _fake_spawn)
    monkeypatch.setattr(debug_runtime, "_current_app_state", lambda: types.SimpleNamespace())

    serial = p3_project["resources"][0]["serial"]
    resp = api_client.post(
        "/api/v1/debug-sessions",
        json={"serial": serial, "purpose": "token regression"},
        headers=CLIENT_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["id"]
    try:
        assert captured["control_token"] == token_env["memory"]
        # runner 的 ack/ready 走同一个校验：令牌错了这里就是 401
        fence = api_client.get(
            f"/internal/debug-sessions/{session_id}/fence",
            params={"token": 1},
            headers={"X-Control-Token": captured["control_token"]},
        )
        assert fence.status_code == 200, fence.text
    finally:
        api_client.delete(f"/api/v1/debug-sessions/{session_id}", headers=CLIENT_HEADERS)
