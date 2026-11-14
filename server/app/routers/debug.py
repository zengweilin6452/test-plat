"""设备调试会话 + 模板代理（P5，api-design.md §2.7 / §3.2）。

设计要点
--------
1. **租约互斥不靠约定**：创建会话 = 领取 DB 租约（resource_leases.debug_session_id
   通道，复用 run 租约的 FOR UPDATE SKIP LOCKED 判定）。设备已被 run 或其他调试
   会话占用时，部分唯一索引 leases_one_live_resource 让并发领取必然失败，
   这里把它翻译成 409 并带占用者 display_id（即 execution_resources.resource_key）。

2. **runner 回报 viewer 端口**：spawn 出去的是 `python -m testdock_runner debug`，
   它在子进程里启动 vendor viewer（uvicorn，127.0.0.1 随机空闲口），然后调
   POST /internal/debug-sessions/{id}/ready {port} 把端口告诉 API —— state 才从
   opening 转 active。API 自身完全不 import vendor（静态测试把关），只转发 HTTP。

3. **代理端点不解析业务**：/debug-sessions/{id}/snapshots 等只做"会话必须 active
   + 拼上游 URL + 原样转发"，json 与二进制都不改写。上游不可达返回 503。

4. **模板端点不伪造、存储是共享根**：必须显式传 session_id（缺失 400
   validation_error、非活动 409、上游不可达 503）——但那只是用来选「转发到哪个
   viewer」，不是存储隔离：debug runner 的 cwd 固定为 server/，vendor MobileConfig
   不覆盖 assets_dir 且其默认值是不带配置文件的相对路径 "assets"，所以每个调试会话
   的 TemplateStore 都落在**同一个** server/assets（= domain.templates.
   template_assets_root()）。模板因此跨会话可见、不随会话关闭消失（见
   GLOSSARY「模板库」）。API 进程里不伪造模板数据。

5. **登记必须先有验证凭证**：`POST /templates` 与 `PUT /templates/{logical}` 只
   接受 `validate-crop` 刚发放的一次性凭证（绑定 session + 新快照 + 命中框 +
   阈值，TTL 见 CROP_VERIFICATION_TTL_SECONDS）。凭证缺失/复用/过期/任何一项
   变化都 409 crop_not_verified 且不触达 vendor —— 前端的按钮 disabled 只是体验，
   服务端自己能独立拒绝未验证登记。会话关闭时按 session 清理（TTL 只是兜底）。

6. **WS 双向透传**：/ws/debug/{id} 仅在会话 active 时接受（否则 close 4403/4404），
   与 vendor /api/v1/preview 之间做字节级双向转发（json 帧与 binary 帧都不改），
   每会话最多 4 个客户端，会话关闭即 close(1000)。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..dependencies import require_client_header
from ..domain import leases as leases_mod
from ..errors import (
    ApiError,
    bad_request,
    conflict,
    not_found,
    runner_spawn_failed,
    validation_error,
)
from ..runner import spawn as spawn_mod

logger = logging.getLogger(__name__)

router = APIRouter(tags=["debug"])

API_PREFIX = "/api/v1"
#: 调试会话缺省时长（DB CHECK 要求 expires_at > created_at）
DEFAULT_SESSION_SECONDS = 3600
#: 每个调试会话的 WS 客户端上限（§3.2）
MAX_WS_CLIENTS_PER_SESSION = 4

#: 进程内会话 WS 客户端计数：{session_id: int}。单进程 uvicorn 下是权威计数。
_WS_CLIENTS: dict[str, int] = {}
#: 进程内 viewer 端口表：{session_id: port}，ready 上报时写入，关闭时删除。
_READY_PORTS: dict[str, int] = {}

#: 框选验证凭证有效期（秒）。验证只证明「发凭证那一刻画面上唯一命中」，
#: 窗口内必须完成登记，否则重新验证（阈值/框选/画面都可能已经变了）。
CROP_VERIFICATION_TTL_SECONDS = 120.0
#: 进程内验证凭证：token -> {session_id, snapshot_id, region, threshold, expires_at}。
#: 单进程 uvicorn 下与 _READY_PORTS 同口径：多 worker 部署要换成共享存储。
_CROP_VERIFICATIONS: dict[str, dict[str, Any]] = {}

#: 直接操控：平台代浏览器持有 vendor 控制权 token；浏览器永远拿不到 token。
#: 与 _READY_PORTS/_CROP_VERIFICATIONS 同口径，多 worker 部署需换共享存储。
_CONTROL_TOKENS: dict[str, str] = {}
#: 每会话最多一条手势 WS（vendor 侧每设备同时只允许一个手势）。
_GESTURE_CLIENTS: dict[str, int] = {}
#: 每会话最多一条 H.264 视频 WS（vendor 每设备预览客户端上限 4，平台只占一条）。
_VIDEO_CLIENTS: dict[str, int] = {}
#: vendor /input/key 允许的按键；与 mobile_auto 有限键表一致。
_CONTROL_KEYS = frozenset({"back", "home", "enter", "search", "delete", "recent"})

#: vendor viewer 的快照 id 是 `uuid4().hex[:16]`
#: （vendor/mobile_auto/src/mobile_auto/viewer/store.py:43），不是带连字符的 UUID。
#: 客户端传来的 snapshot_id 会被原样拼进上游 path，所以只放行这个 id 空间内的
#: 字符串：`../`、`/`、`?`、任意文本都挡在到达 vendor 之前。用严格 RFC UUID
#: 校验反而会拒绝真实快照（平台会把正常调试请求全部打成 400）。
_SNAPSHOT_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def _require_snapshot_id(value: Any) -> str:
    """上游 path 里只允许 vendor 真实形态的快照 id（16 位小写十六进制）。"""
    text = value if isinstance(value, str) else ""
    if _SNAPSHOT_ID_RE.fullmatch(text) is None:
        raise validation_error(
            ["snapshot_id 必须是 vendor 返回的快照 id（16 位十六进制），不能含路径或查询字符"]
        )
    return text


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
async def _session_row(session: AsyncSession, session_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT ds.id, ds.project_id, ds.resource_id, ds.actor_ref, ds.state,
                       ds.expires_at, ds.closed_at, ds.created_at,
                       er.resource_key, er.status AS resource_status
                  FROM debug_sessions ds
                  JOIN execution_resources er
                    ON er.project_id = ds.project_id AND er.id = ds.resource_id
                 WHERE ds.id = CAST(:sid AS uuid)
                """
            ),
            {"sid": str(session_id)},
        )
    ).mappings().first()
    if row is None:
        raise not_found("debug_session", str(session_id))
    return dict(row)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _view(row: dict[str, Any], *, viewer_port: int | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]),
        "resource_id": str(row["resource_id"]),
        "serial": row["resource_key"],
        "actor_ref": row["actor_ref"],
        "state": row["state"],
        "expires_at": _iso(row["expires_at"]),
        "closed_at": _iso(row["closed_at"]),
        "created_at": _iso(row["created_at"]),
    }
    if viewer_port is not None:
        data["base_url"] = f"http://127.0.0.1:{viewer_port}"
        data["ws_path"] = f"{API_PREFIX}/ws/debug/{row['id']}"
    return data


async def _audit(
    session: AsyncSession,
    *,
    project_id: str,
    action: str,
    entity_id: str,
    changes: dict[str, Any],
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO audit_events (
                id, project_id, actor_ref, action, entity_type, entity_id,
                request_id, changes
            ) VALUES (
                CAST(:id AS uuid), CAST(:pid AS uuid), :actor, :action, 'debug_session',
                CAST(:eid AS uuid), :rid, CAST(:changes AS jsonb)
            )
            """
        ),
        {
            "id": str(uuid_mod.uuid4()),
            "pid": str(project_id),
            "actor": str(changes.get("actor_ref") or "web-client"),
            "action": action,
            "eid": str(entity_id),
            "rid": uuid_mod.uuid4().hex,
            "changes": json.dumps(changes, ensure_ascii=False, default=str),
        },
    )


async def _busy_holder(session: AsyncSession, resource_id: str) -> dict[str, Any] | None:
    """设备当前活动租约的占用者（display_id 用 resource_key 代替）。"""
    row = (
        await session.execute(
            text(
                """
                SELECT rl.run_id, rl.debug_session_id, rl.check_id, rl.holder_id,
                       COALESCE(er.resource_key, '') AS display_id
                  FROM resource_leases rl
                  LEFT JOIN execution_resources er ON er.id = rl.resource_id
                 WHERE rl.resource_id = CAST(:rid AS uuid)
                   AND rl.released_at IS NULL
                 ORDER BY rl.created_at DESC
                 LIMIT 1
                """
            ),
            {"rid": str(resource_id)},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _viewer_port(session: AsyncSession, session_id: str) -> int:
    """active 会话的 viewer 端口；未回报/非 active 都视为不可代理。"""
    row = (
        await session.execute(
            text(
                """
                SELECT viewer_port FROM debug_sessions
                 WHERE id = CAST(:sid AS uuid)
                   AND state = 'active'
                   AND viewer_port IS NOT NULL
                """
            ),
            {"sid": str(session_id)},
        )
    ).mappings().first()
    if row is None:
        raise conflict(
            "debug_session_not_active",
            "调试会话尚未激活或 viewer 端口未回报，无法代理",
            {"session_id": str(session_id)},
        )
    return int(row["viewer_port"])


async def _forward(
    session_id: str,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """把请求原样转发到 127.0.0.1:<viewer_port>。上游不可达 -> 503。"""
    port = _READY_PORTS.get(str(session_id))
    if port is None:
        raise conflict(
            "debug_session_not_active",
            "调试会话尚未激活或 viewer 端口未回报，无法代理",
            {"session_id": str(session_id)},
        )
    url = f"http://127.0.0.1:{port}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            upstream = await client.request(method, url, json=json_body, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        raise ApiError(
            503,
            "viewer_unavailable",
            f"viewer 上游不可达：{exc.__class__.__name__}",
            {"session_id": str(session_id)},
        ) from exc
    out_headers: dict[str, str] = {}
    ctype = upstream.headers.get("content-type")
    if ctype:
        out_headers["content-type"] = ctype
    return Response(content=upstream.content, status_code=upstream.status_code, headers=out_headers)


# --------------------------------------------------------------------------- #
# 直接操控：平台代持 vendor 控制权（token 不出服务端）+ 手势 WS 透传
# --------------------------------------------------------------------------- #
def _viewer_device_path(path: str, serial: str) -> str:
    from urllib.parse import quote

    return f"{path}?device={quote(serial, safe='')}"


def _json_body(payload: dict[str, Any]) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False),
        media_type="application/json",
    )


def _control_view(response: Response) -> dict[str, Any]:
    try:
        data = json.loads(response.body)
    except (TypeError, ValueError):
        data = {}
    ttl = data.get("ttl_seconds") if isinstance(data, dict) else None
    return {
        "enabled": True,
        "ttl_seconds": int(ttl) if isinstance(ttl, (int, float)) else 5,
        "note": data.get("note") if isinstance(data, dict) else None,
    }


async def _release_control(session_id: str) -> None:
    """尽力释放 vendor 控制权并清掉本地 token；会话关闭/清理共用。"""
    sid = str(session_id)
    token = _CONTROL_TOKENS.pop(sid, None)
    _GESTURE_CLIENTS.pop(sid, None)
    if not token:
        return
    with contextlib.suppress(Exception):
        await _forward(
            sid,
            "POST",
            "/api/v1/control",
            headers={"X-Viewer-Control": token},
            json_body={"enabled": False},
        )


def _control_token_or_409(session_id: str) -> str:
    token = _CONTROL_TOKENS.get(str(session_id))
    if not token:
        raise conflict(
            "control_not_enabled",
            "尚未启用直接操控：先 POST /debug-sessions/{id}/control 领取控制权",
            {"session_id": str(session_id)},
        )
    return token


@router.post("/debug-sessions/{session_id}/control")
async def control_debug_session(
    session_id: str,
    request: Request,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """领取/释放真机控制权；token 只存服务端，响应里永不返回。"""
    row = await _active_row(session, session_id)
    sid = str(session_id)
    body = await request.json() if await request.body() else {}
    enabled = bool(body.get("enabled"))
    serial = str(row["resource_key"])
    path = _viewer_device_path("/api/v1/control", serial)

    if not enabled:
        await _release_control(sid)
        return _json_body({"enabled": False})

    token = _CONTROL_TOKENS.get(sid)
    if token:
        refreshed = await _forward(
            sid,
            "POST",
            path,
            headers={"X-Viewer-Control": token},
            json_body={"enabled": True},
        )
        if refreshed.status_code < 300:
            return _json_body(_control_view(refreshed))
        if refreshed.status_code not in (400, 403):
            return refreshed
        # token 已被 vendor 撤掉（TTL/重启）：丢掉本地凭据，按首次领取处理。
        _CONTROL_TOKENS.pop(sid, None)

    claimed = await _forward(sid, "POST", path, json_body={"enabled": True})
    if claimed.status_code >= 300:
        return claimed
    data = json.loads(claimed.body) if claimed.body else {}
    new_token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(new_token, str) or not new_token:
        raise ApiError(
            502,
            "viewer_bad_response",
            "vendor viewer 未返回控制权凭据",
            {"session_id": sid},
        )
    _CONTROL_TOKENS[sid] = new_token
    return _json_body(_control_view(claimed))


@router.post("/debug-sessions/{session_id}/control/heartbeat")
async def heartbeat_debug_control(
    session_id: str,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """续期控制权；vendor 说失效就丢 token 并明确返回 control_expired。"""
    row = await _active_row(session, session_id)
    sid = str(session_id)
    token = _control_token_or_409(sid)
    response = await _forward(
        sid,
        "POST",
        _viewer_device_path("/api/v1/control/heartbeat", str(row["resource_key"])),
        headers={"X-Viewer-Control": token},
        json_body={},
    )
    if response.status_code in (400, 403):
        _CONTROL_TOKENS.pop(sid, None)
        raise conflict(
            "control_expired",
            "直接操控控制权已失效，请重新启用",
            {"session_id": sid},
        )
    if response.status_code >= 300:
        return response
    return _json_body(_control_view(response))


@router.post("/debug-sessions/{session_id}/input/key")
async def debug_input_key(
    session_id: str,
    request: Request,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """直接操控的按键（back/home 等）；必须持有控制权。"""
    row = await _active_row(session, session_id)
    sid = str(session_id)
    token = _control_token_or_409(sid)
    body = await request.json() if await request.body() else {}
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or name not in _CONTROL_KEYS:
        raise validation_error([f"name 只支持 {', '.join(sorted(_CONTROL_KEYS))}"])
    response = await _forward(
        sid,
        "POST",
        _viewer_device_path("/api/v1/input/key", str(row["resource_key"])),
        headers={"X-Viewer-Control": token},
        json_body={"name": name},
    )
    expired = response.status_code == 403
    if response.status_code == 400:
        try:
            detail = json.loads(response.body)
        except (TypeError, ValueError):
            detail = {}
        expired = isinstance(detail, dict) and detail.get("code") == "control-disabled"
    if expired:
        _CONTROL_TOKENS.pop(sid, None)
        raise conflict(
            "control_expired",
            "直接操控控制权已失效，请重新启用",
            {"session_id": sid},
        )
    return response


def register_viewer_port(session_id: str, port: int) -> None:
    """internal ready 端点回报的 viewer 端口登记（进程内表，见模块 docstring）。"""
    _READY_PORTS[str(session_id)] = int(port)


def _find_runner_pid_by_run_id(run_id: str) -> int | None:
    """进程表丢失（API 重启过）时按命令行找该 run_id 的 runner 进程。

    spawn 的命令行固定是 `python -m testdock_runner ... --run-id <run_id>`，
    所以限定 python 进程名——否则扫描进程（powershell）自己的命令行也含
    脚本文本，会把扫描器本身当成 runner。
    """
    marker = f"--run-id {run_id}"
    if os.name == "nt":
        script = (
            "Get-CimInstance Win32_Process | Where-Object { "
            "$_.Name -like 'python*' "
            "-and $_.CommandLine "
            "-and $_.CommandLine.Contains('testdock_runner') "
            f"-and $_.CommandLine.Contains('{marker}') }} "
            "| ForEach-Object { $_.ProcessId }"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        for token in (completed.stdout or "").split():
            try:
                pid = int(token)
            except ValueError:
                continue
            if pid != os.getpid():
                return pid
        return None
    try:
        completed = subprocess.run(
            ["pgrep", "-f", f"testdock_runner.*{run_id}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for token in (completed.stdout or "").split():
        try:
            pid = int(token)
        except ValueError:
            continue
        if pid != os.getpid():
            return pid
    return None


def _terminate_runner_blocking(run_id: str) -> None:
    """杀 runner 进程树（同步 subprocess，避开 Selector loop 不支持子进程的限制）。

    `_PROCESSES` 是进程内表，API 重启后为空——只查它的话，重启前 spawn 的
    runner 会漏杀，成为持有本地设备锁的孤儿（新会话 runner 全部 DeviceBusy，
    reason=local_lease_busy）。所以进程表没有时按命令行兜底扫描。
    """
    proc = spawn_mod._PROCESSES.get(str(run_id))
    pid = proc.pid if proc is not None else None
    if pid is None:
        pid = _find_runner_pid_by_run_id(str(run_id))
    if pid:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)]
            if os.name == "nt"
            else ["kill", "-9", str(pid)],
            capture_output=True,
        )
    spawn_mod._PROCESSES.pop(str(run_id), None)


def _spawn_runner_threadsafe(**kwargs) -> int:
    """在独立线程 + Proactor loop 里 spawn runner。

    请求处理器跑在 Selector loop（psycopg 异步需要），而 Windows 的
    asyncio.create_subprocess_exec 只有 Proactor loop 支持；跨 loop 子进程
    归属也不对，所以在专用线程里起一个短命 Proactor loop 完成拉起。
    """
    import threading

    result: dict[str, Any] = {}

    def _run() -> None:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        async def _inner() -> None:
            result["pid"] = await spawn_mod.spawn_runner(**kwargs)

        try:
            asyncio.run(_inner())
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=_run, name="debug-spawn", daemon=True)
    thread.start()
    thread.join(timeout=30.0)
    if "error" in result:
        raise result["error"]
    if "pid" not in result:
        raise RuntimeError("runner 拉起超时（30s）")
    return int(result["pid"])


# --------------------------------------------------------------------------- #
# 会话生命周期
# --------------------------------------------------------------------------- #
@router.post("/debug-sessions", status_code=201)
async def create_debug_session(
    body: dict = Body(default_factory=dict),
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """创建调试会话：校验设备 -> 领租约 -> 建会话行 -> spawn runner（viewer）。"""
    serial = str(body.get("serial") or "").strip()
    purpose = str(body.get("purpose") or "").strip()
    if not serial:
        raise bad_request("serial 不能为空")
    actor = str(body.get("actor_ref") or "web-client")

    # 设备必须存在（serial 即 execution_resources.resource_key）
    resource = (
        await session.execute(
            text(
                """
                SELECT er.id, er.project_id, er.status, er.resource_key
                  FROM execution_resources er
                 WHERE er.resource_key = :serial
                 -- 同一台真机可能登记在多个项目：优先绑定在线的那条，其次取最新
                 ORDER BY (er.status = 'ready') DESC, er.created_at DESC
                 LIMIT 1
                """
            ),
            {"serial": serial},
        )
    ).mappings().first()
    if resource is None:
        raise not_found("device", serial)
    resource = dict(resource)
    if resource["status"] != "ready":
        raise conflict(
            "device_not_ready",
            f"设备 {serial} 当前状态为 {resource['status']!r}，不可调试",
            {"serial": serial, "status": resource["status"]},
        )
    from ..domain import identity as identity_mod

    # 归档守卫（工单 04）：归档范围禁止启动新调试会话
    await identity_mod.assert_scope_active(session, project_id=str(resource["project_id"]))

    # 先插会话行（opening；FK 要求它先存在），再在同一事务里领租约
    session_id = str(uuid_mod.uuid4())
    expires_at = datetime.now(UTC) + timedelta(seconds=DEFAULT_SESSION_SECONDS)
    await session.execute(
        text(
            """
            INSERT INTO debug_sessions (
                id, project_id, resource_id, actor_ref, state, expires_at
            ) VALUES (
                CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid), :actor,
                'opening', :expires_at
            )
            """
        ),
        {
            "id": session_id,
            "pid": str(resource["project_id"]),
            "rid": str(resource["id"]),
            "actor": actor,
            "expires_at": expires_at,
        },
    )
    lease = await leases_mod.acquire_lease_for_debug(
        session,
        project_id=str(resource["project_id"]),
        debug_session_id=session_id,
        resource_id=str(resource["id"]),
        holder_id=actor,
    )
    if lease is None:
        holder = await _busy_holder(session, str(resource["id"]))
        raise conflict(
            "device_busy",
            f"设备 {serial} 已被占用",
            {
                "serial": serial,
                "holder": holder or {},
                "holder_display_id": (holder or {}).get("display_id") or serial,
            },
        )

    await _audit(
        session,
        project_id=str(resource["project_id"]),
        action="debug_session_created",
        entity_id=session_id,
        changes={"serial": serial, "purpose": purpose, "lease_id": lease.id, "actor_ref": actor},
    )
    await session.commit()

    # spawn runner（viewer 模式）。控制面走 internal 协议（ready 上报端口）。
    from ..routers.debug_runtime import get_control_url_and_token

    control_url, control_token = get_control_url_and_token()
    try:
        await spawn_mod.spawn_runner(
            run_id=session_id,
            config={"module": "debug", "serial": serial, "purpose": purpose},
            lease={
                "fencing_token": lease.fencing_token,
                "serial": serial,
                "resource_id": lease.resource_id,
            },
            control_url=control_url,
            control_token=control_token,
        )
    except Exception as exc:  # noqa: BLE001 - spawn 失败必须回收会话与租约
        with contextlib.suppress(Exception):
            await _close_session(session_id, reason="spawn_failed")
        raise runner_spawn_failed(f"runner 启动失败：{exc!r}") from exc

    view_row = {
        "id": session_id,
        "project_id": resource["project_id"],
        "resource_id": resource["id"],
        "resource_key": resource["resource_key"],
        "actor_ref": actor,
        "state": "opening",
        "expires_at": expires_at,
        "closed_at": None,
        "created_at": expires_at,
    }
    return _view(view_row)


async def _close_session(session_id: str, *, reason: str) -> dict[str, Any] | None:
    """关闭会话（幂等）：runner 终止 -> state=closed + closed_at -> 释放租约 -> 审计。

    所有关闭路径（DELETE、spawn 失败、runner 退出兜底）都汇到这里，所以验证凭证
    的按会话清理也放在这里：会话没了，旧凭证就不该还能解锁模板登记。
    """
    from ..db import get_sessionmaker

    _drop_crop_verifications(str(session_id))
    # 控制权先尽力还给 vendor：token 在本地也一并清掉，token 不随会话残留。
    await _release_control(str(session_id))
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text(
                        """
                        SELECT id, project_id, state
                          FROM debug_sessions WHERE id = CAST(:sid AS uuid)
                        """
                    ),
                    {"sid": str(session_id)},
                )
            ).mappings().first()
            if row is None:
                return None
            if row["state"] not in ("closed", "lost"):
                await session.execute(
                    text(
                        """
                        UPDATE debug_sessions
                           SET state = 'closed', closed_at = now()
                         WHERE id = CAST(:sid AS uuid)
                        """
                    ),
                    {"sid": str(session_id)},
                )
                await leases_mod.release_lease_for_debug(
                    session, debug_session_id=str(session_id), reason=reason
                )
                await _audit(
                    session,
                    project_id=str(row["project_id"]),
                    action="debug_session_closed",
                    entity_id=str(session_id),
                    changes={"reason": reason},
                )
    _READY_PORTS.pop(str(session_id), None)
    return {"id": str(session_id), "state": "closed"}


async def _last_close_reason(session: AsyncSession, session_id: str) -> str | None:
    """会话关闭原因（审计里的最新一条 debug_session_closed）。

    会话行没有 reason 列；关闭路径（client_closed / runner_exit / spawn_failed /
    local_lease_busy…）都写审计，detail 据此给前端一个可行动的失败原因。
    """
    row = (
        await session.execute(
            text(
                """
                SELECT changes FROM audit_events
                 WHERE entity_type = 'debug_session'
                   AND entity_id = CAST(:sid AS uuid)
                   AND action = 'debug_session_closed'
                 ORDER BY created_at DESC
                 LIMIT 1
                """
            ),
            {"sid": str(session_id)},
        )
    ).mappings().first()
    if row is None or row["changes"] is None:
        return None
    changes = row["changes"]
    if isinstance(changes, str):
        try:
            changes = json.loads(changes)
        except ValueError:
            return None
    reason = changes.get("reason") if isinstance(changes, dict) else None
    return str(reason) if reason else None


@router.get("/debug-sessions/{session_id}")
async def get_debug_session(session_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    row = await _session_row(session, session_id)
    viewer_port = _READY_PORTS.get(str(row["id"])) if row["state"] == "active" else None
    view = _view(row, viewer_port=viewer_port)
    if row["state"] in ("closed", "lost"):
        view["close_reason"] = await _last_close_reason(session, str(row["id"]))
    return view


@router.delete("/debug-sessions/{session_id}")
async def delete_debug_session(
    session_id: str,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """关闭调试会话（幂等）。runner 还活着就先杀掉它。"""
    row = await _session_row(session, session_id)
    if row["state"] not in ("closed", "lost"):
        with contextlib.suppress(Exception):
            await asyncio.to_thread(_terminate_runner_blocking, str(row["id"]))
    await session.rollback()
    result = await _close_session(str(row["id"]), reason="client_closed")
    if result is None:
        raise not_found("debug_session", str(session_id))
    return result


# --------------------------------------------------------------------------- #
# 代理端点（viewer 上游：json+binary 都原样转发）
# --------------------------------------------------------------------------- #
async def _active_row(session: AsyncSession, session_id: str) -> dict[str, Any]:
    row = await _session_row(session, session_id)
    if row["state"] != "active":
        raise conflict(
            "debug_session_not_active",
            f"调试会话当前状态为 {row['state']!r}，不可代理",
            {"session_id": str(row["id"]), "state": row["state"]},
        )
    return row


@router.post("/debug-sessions/{session_id}/snapshots")
async def proxy_snapshot(
    session_id: str,
    request: Request,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> Response:
    row = await _active_row(session, session_id)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _forward(str(row["id"]), "POST", "/api/v1/snapshots", json_body=body)


@router.get("/debug-sessions/{session_id}/snapshots/{snapshot_id}/image")
async def proxy_snapshot_image(
    session_id: str, snapshot_id: str, session: AsyncSession = Depends(get_session)
) -> Response:
    row = await _active_row(session, session_id)
    target = _require_snapshot_id(snapshot_id)
    return await _forward(str(row["id"]), "GET", f"/api/v1/snapshots/{target}/image")


@router.get("/debug-sessions/{session_id}/snapshots/{snapshot_id}/tree")
async def proxy_snapshot_tree(
    session_id: str, snapshot_id: str, session: AsyncSession = Depends(get_session)
) -> Response:
    row = await _active_row(session, session_id)
    target = _require_snapshot_id(snapshot_id)
    return await _forward(str(row["id"]), "GET", f"/api/v1/snapshots/{target}/tree")


@router.post("/debug-sessions/{session_id}/locators/validate")
async def proxy_locators_validate(
    session_id: str,
    request: Request,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> Response:
    row = await _active_row(session, session_id)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _forward(
        str(row["id"]), "POST", "/api/v1/locators/validate", json_body=body
    )


# --------------------------------------------------------------------------- #
# 模板端点（session_id 必填：用来选转发目标 viewer；存储是共享根）
# --------------------------------------------------------------------------- #
async def _template_session(session: AsyncSession, session_id: str | None) -> str:
    """模板代理的目标会话（仅用于转发，不是存储范围）。

    vendor 的 TemplateStore 挂在 `session.config.assets_dir` 上，而 debug runner 的
    cwd 固定为 server/、assets_dir 用默认相对路径 "assets" —— 所有调试会话的
    TemplateStore 都指向同一个 `server/assets`（= domain.templates.
    template_assets_root()）。所以「跨会话可查」由共享根保证，会话 id 只是告诉
    平台把请求转到哪个活动 viewer。

    曾经的"无 session_id 时挑最新活动会话"兜底是跨项目泄漏点（A 项目的请求
    会落到 B 项目的 viewer 上），已删除；缺失 session_id 走项目统一的
    validation_error（400），非活动会话 409，上游不可达 503。
    """
    if not session_id:
        raise validation_error(
            ["session_id 必填：请传入活动调试会话 id 以选择转发目标"
             "（POST /api/v1/debug-sessions 创建后取得）"]
        )
    row = await _active_row(session, session_id)
    return str(row["id"])


def _prune_crop_verifications() -> None:
    now = time.monotonic()
    for token in [t for t, rec in _CROP_VERIFICATIONS.items() if rec["expires_at"] <= now]:
        _CROP_VERIFICATIONS.pop(token, None)


def _drop_crop_verifications(session_id: str) -> None:
    """会话关闭即作废该会话的全部验证凭证（按 session 清，不动别的会话）。

    TTL 只是兜底：会话已经关了，凭证再"没过期"也不能证明当前画面仍然成立。
    """
    target = str(session_id)
    for token in [
        t for t, rec in _CROP_VERIFICATIONS.items() if rec["session_id"] == target
    ]:
        _CROP_VERIFICATIONS.pop(token, None)


def _issue_crop_verification(
    *, session_id: str, snapshot_id: str, region: list[int], threshold: float
) -> str:
    """发放一次性登记凭证：绑定验证时的会话、新快照、命中框与阈值。"""
    _prune_crop_verifications()
    token = secrets.token_urlsafe(24)
    _CROP_VERIFICATIONS[token] = {
        "session_id": str(session_id),
        "snapshot_id": str(snapshot_id),
        "region": [int(value) for value in region],
        "threshold": float(threshold),
        "expires_at": time.monotonic() + CROP_VERIFICATION_TTL_SECONDS,
    }
    return token


def _reject_unverified(reason: str, **extra: Any) -> ApiError:
    return conflict(
        "crop_not_verified",
        "框选尚未验证通过，不能登记模板：" + reason + "。请用当前画面重新验证框选。",
        extra,
    )


def _consume_crop_verification(
    *, token: Any, session_id: str, snapshot_id: str, region: list[int], threshold: float
) -> None:
    """校验并消费凭证：只有「刚刚用新画面唯一命中」的那次验证能解锁登记。

    任何一项不一致（会话 / 快照 / 框选 / 阈值）都按未验证处理，且**不消费**
    凭证，让客户端带着正确参数重试；命中后立即作废（一次性）。
    """
    _prune_crop_verifications()
    if not isinstance(token, str) or not token:
        raise _reject_unverified("缺少验证凭证")
    record = _CROP_VERIFICATIONS.get(token)
    if record is None:
        raise _reject_unverified("验证凭证已失效（已使用或已过期）")
    if record["session_id"] != str(session_id):
        raise _reject_unverified("验证凭证属于另一个调试会话")
    if record["snapshot_id"] != str(snapshot_id):
        raise _reject_unverified("快照与验证时不同（验证基于最新捕获的画面）")
    if record["region"] != [int(value) for value in region]:
        raise _reject_unverified("框选区域与验证时不同")
    if abs(record["threshold"] - float(threshold)) > 1e-9:
        raise _reject_unverified("阈值与验证时不同")
    _CROP_VERIFICATIONS.pop(token, None)


def _registration_payload(body: Any) -> dict[str, Any]:
    """登记请求的形状校验：快照 / 四整数框 / 逻辑名 / 阈值齐全才算合法。

    阈值必填：验证凭证正是按阈值发放的，缺了它就无法判断「阈值改变后旧验证失效」。
    """
    if not isinstance(body, dict):
        raise validation_error(["登记请求必须是 JSON 对象"])
    problems: list[str] = []
    snapshot_id = body.get("snapshot_id")
    region = body.get("region")
    logical = body.get("logical")
    threshold = body.get("threshold")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        problems.append("需要有效的 snapshot_id（验证返回的新快照）")
    if (not isinstance(region, list) or len(region) != 4
            or any(type(value) is not int for value in region)):
        problems.append("region 必须是四个整数")
    if not isinstance(logical, str) or not logical.strip():
        problems.append("模板逻辑名不能为空")
    if type(threshold) not in (int, float) or not 0.10 <= threshold <= 1.00:
        problems.append("threshold 必须在 0.10-1.00 之间")
    if problems:
        raise validation_error(problems)
    payload: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "region": region,
        "logical": logical.strip(),
        "threshold": float(threshold),
    }
    if isinstance(body.get("note"), str) and body["note"].strip():
        payload["note"] = body["note"].strip()
    return payload


@router.get("/template-library")
def template_library() -> dict[str, Any]:
    """Single-workspace, read-only metadata; device operations still require a session."""
    from ..domain.templates import list_template_library

    try:
        return {"templates": list_template_library()}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ApiError(503, "service_unavailable", "模板库不可读，请检查资产清单和版本文件") from exc


@router.get("/templates")
async def list_templates(session_id: str | None = None, session: AsyncSession = Depends(get_session)) -> Response:
    sid = await _template_session(session, session_id)
    return await _forward(sid, "GET", "/api/v1/templates")


@router.post("/templates")
async def create_template(request: Request, session_id: str | None = None,
                          _client: str = Depends(require_client_header),
                          session: AsyncSession = Depends(get_session)) -> Response:
    """从验证通过的新快照登记模板版本（服务端强制，不依赖前端 disabled）。"""
    sid = await _template_session(session, session_id)
    body = await request.json()
    payload = _registration_payload(body)
    _consume_crop_verification(
        token=body.get("verification"),
        session_id=sid,
        snapshot_id=payload["snapshot_id"],
        region=payload["region"],
        threshold=payload["threshold"],
    )
    return await _forward(
        sid,
        "POST",
        "/api/v1/templates",
        json_body={
            key: payload[key] for key in ("snapshot_id", "region", "logical", "note") if key in payload
        },
    )


async def _match_crop(source: bytes, current: bytes, region: list[int], threshold: float) -> dict:
    payload = json.dumps({"source": base64.b64encode(source).decode(),
                          "current": base64.b64encode(current).decode(),
                          "region": region, "threshold": threshold}).encode()
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            [settings.runner_python, "-m", "testdock_runner.crop_match"],
            input=payload, capture_output=True, timeout=60,
            env=spawn_mod.build_env(run_id="crop-validation"), cwd=str(settings.repo_root),
        )
    except subprocess.TimeoutExpired:
        raise ApiError(503, "service_unavailable", "图像验证超时") from None
    except OSError:
        raise ApiError(503, "service_unavailable", "图像匹配进程不可用") from None
    if completed.returncode:
        raise ApiError(503, "service_unavailable", "图像匹配进程不可用")
    result = json.loads(completed.stdout)
    if "error" in result:
        raise validation_error([result["error"]])
    return result


@router.post("/templates/validate-crop")
async def validate_crop(request: Request, session_id: str | None = None,
                        _client: str = Depends(require_client_header),
                        session: AsyncSession = Depends(get_session)) -> Response:
    """用**新捕获的画面**验证框选：唯一命中才发放一次性登记凭证。

    响应在匹配结果之外带 `snapshot_id`（这次真实匹配用的新快照）与
    `source_snapshot_id`（框选来源的冻结快照），`region` 是新画面里的命中框，
    `verification` 是登记要带的凭证。新快照/命中框就是登记依据，客户端不应
    再拿旧快照去登记。
    """
    sid = await _template_session(session, session_id)
    body = await request.json()
    region = body.get("region")
    threshold = body.get("threshold")
    snapshot_id = _require_snapshot_id(body.get("snapshot_id"))
    if (not isinstance(region, list) or len(region) != 4
            or any(type(v) is not int for v in region)
            or type(threshold) not in (int, float) or not 0.1 <= threshold <= 1):
        raise validation_error(["需要有效 snapshot_id、四整数 region 和 0.10-1.00 threshold"])
    source = await _forward(sid, "GET", f"/api/v1/snapshots/{snapshot_id}/image")
    if source.status_code >= 300:
        return source
    capture = await _forward(sid, "POST", "/api/v1/snapshots", json_body={})
    if capture.status_code >= 300:
        return capture
    captured = json.loads(capture.body)
    new_id = captured["snapshot_id"]
    current = await _forward(sid, "GET", f"/api/v1/snapshots/{new_id}/image")
    if current.status_code >= 300:
        return current
    result = await _match_crop(source.body, current.body, region, threshold)
    payload: dict[str, Any] = {
        **result,
        "snapshot_id": new_id,
        "source_snapshot_id": snapshot_id,
        # 命中框/凭证只在唯一命中时给出：零匹配或多匹配都不能登记
        "region": None,
        "verification": None,
    }
    for key in ("width", "height", "captured_at"):
        if key in captured:
            payload[key] = captured[key]
    if result.get("count") == 1:
        match = (result.get("matches") or [{}])[0]
        matched = [match.get(k) for k in ("x", "y", "width", "height")]
        if all(type(value) is int and value >= 0 for value in matched) and matched[2] > 0 and matched[3] > 0:
            payload["region"] = matched
            payload["verification"] = _issue_crop_verification(
                session_id=sid, snapshot_id=new_id, region=matched, threshold=float(threshold)
            )
    return Response(json.dumps(payload), media_type="application/json")


@router.post("/templates/validate")
async def validate_template(request: Request, session_id: str | None = None,
                            _client: str = Depends(require_client_header),
                            session: AsyncSession = Depends(get_session)) -> Response:
    """IMAGE 定位验证：走 vendor 的专用端点 `/templates/validate`。

    为什么不用 `/locators/validate`：vendor 那条路径在 image 目标上必 500 ——
    `_query_payload` 对图像目标返回 4 元组（带 scores），而 `capture_and_query_sync`
    在 with_scores=False 时按 3 元组解包（viewer/app.py `ValueError: too many values
    to unpack`）。vendor/ 是只读源仓库，不在本地改；改用 vendor 自己的
    `/templates/validate`（with_scores=True，响应多一个 `scores` 数组）。

    阈值契约（AC-DBG-05）：0.10-1.00 之外直接 422，不把越界值透传给 vendor；
    匹配失败如实返回无匹配，不伪造命中。
    """
    body = await request.json()
    threshold = body.get("threshold") if isinstance(body, dict) else None
    if threshold is not None:
        try:
            value = float(threshold)
        except (TypeError, ValueError):
            from ..errors import validation_error

            raise validation_error(["threshold 必须是数值"]) from None
        if not (0.10 <= value <= 1.00):
            from ..errors import validation_error

            raise validation_error(["threshold 必须在 0.10-1.00 之间"])
    sid = await _template_session(session, session_id)
    return await _forward(sid, "POST", "/api/v1/templates/validate", json_body=body)



@router.put("/templates/{logical:path}")
async def update_template(logical: str, request: Request, session_id: str | None = None,
                          _client: str = Depends(require_client_header),
                          session: AsyncSession = Depends(get_session)) -> Response:
    """确认更新同名模板：同样必须先拿到框选验证凭证（更新也会生成新版本）。"""
    from urllib.parse import quote
    sid = await _template_session(session, session_id)
    body = await request.json()
    payload = _registration_payload({**body, "logical": logical} if isinstance(body, dict) else body)
    _consume_crop_verification(
        token=body.get("verification"),
        session_id=sid,
        snapshot_id=payload["snapshot_id"],
        region=payload["region"],
        threshold=payload["threshold"],
    )
    forwarded = {
        key: value for key, value in body.items() if key != "verification"
    }
    forwarded["logical"] = logical
    return await _forward(sid, "PUT", "/api/v1/templates/" + quote(logical, safe="/"), json_body=forwarded)


# --------------------------------------------------------------------------- #
# WS 透传（vendor /api/v1/preview）
# --------------------------------------------------------------------------- #
@router.websocket("/ws/debug/{session_id}")
async def debug_socket(websocket: WebSocket, session_id: str) -> None:
    """双向透传：客户端 <-> vendor viewer /api/v1/preview（json+binary 都不改）。"""
    from ..db import get_sessionmaker

    # 先 accept 再关门：close(code) 的自定义码只有在握手完成后才会透传给客户端。
    with contextlib.suppress(Exception):
        await websocket.accept()
    sessionmaker = get_sessionmaker()
    session_id = str(session_id)
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT ds.id, ds.state, er.resource_key
                      FROM debug_sessions ds
                      JOIN execution_resources er
                        ON er.project_id = ds.project_id AND er.id = ds.resource_id
                     WHERE ds.id = CAST(:sid AS uuid)
                    """
                ),
                {"sid": session_id},
            )
        ).mappings().first()
        await session.rollback()
    if row is None:
        with contextlib.suppress(Exception):
            await websocket.close(code=4404)
        return
    if row["state"] != "active" or _READY_PORTS.get(session_id) is None:
        with contextlib.suppress(Exception):
            await websocket.close(code=4403)
        return
    current = _WS_CLIENTS.get(session_id, 0)
    if current >= MAX_WS_CLIENTS_PER_SESSION:
        with contextlib.suppress(Exception):
            await websocket.close(code=4429)
        return
    _WS_CLIENTS[session_id] = current + 1

    upstream_url = (
        "ws://127.0.0.1:"
        + str(_READY_PORTS[session_id])
        + "/api/v1/preview?device="
        + str(row["resource_key"])
    )
    import websockets  # 延迟导入：app 模块顶层不引 vendor 依赖链

    upstream_ws = None
    try:
        upstream_ws = await websockets.connect(upstream_url, max_size=None)

        async def pump_to_client() -> None:
            while True:
                frame = await upstream_ws.recv()
                if isinstance(frame, (bytes, bytearray)):
                    await websocket.send_bytes(bytes(frame))
                else:
                    await websocket.send_text(str(frame))

        async def pump_to_upstream() -> None:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code") or 1000)
                data = message.get("bytes")
                if data is None:
                    text_val = message.get("text")
                    if text_val is not None:
                        await upstream_ws.send(text_val)
                else:
                    await upstream_ws.send(data)

        done, pending = await asyncio.wait(
            [
                asyncio.create_task(pump_to_client()),
                asyncio.create_task(pump_to_upstream()),
            ],
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(
                exc, (WebSocketDisconnect, websockets.ConnectionClosed)
            ):
                logger.debug("ws pump error: %s", exc)
    except Exception:  # noqa: BLE001
        logger.exception("ws/debug 透传失败: session=%s", session_id)
    finally:
        _WS_CLIENTS[session_id] = max(0, _WS_CLIENTS.get(session_id, 1) - 1)
        if _WS_CLIENTS.get(session_id, 0) == 0:
            _WS_CLIENTS.pop(session_id, None)
        if upstream_ws is not None:
            with contextlib.suppress(Exception):
                await upstream_ws.close()
        with contextlib.suppress(Exception):
            await websocket.close(code=1000)


@router.websocket("/ws/debug/{session_id}/video")
async def debug_video_socket(websocket: WebSocket, session_id: str) -> None:
    """H.264 下行透传：浏览器 <-> vendor /api/v1/preview/video。

    vendor 对视频信道同样要求严格 Origin 与 {"proto":1} hello；浏览器消息
    一律忽略（信道只下行）。失败由前端回退 JPEG，不在平台重连。
    """
    import websockets

    from ..db import get_sessionmaker

    with contextlib.suppress(Exception):
        await websocket.accept()
    sid = str(session_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT ds.state, er.resource_key
                      FROM debug_sessions ds
                      JOIN execution_resources er
                        ON er.project_id = ds.project_id AND er.id = ds.resource_id
                     WHERE ds.id = CAST(:sid AS uuid)
                    """
                ),
                {"sid": sid},
            )
        ).mappings().first()
        await session.rollback()
    if row is None:
        with contextlib.suppress(Exception):
            await websocket.close(code=4404)
        return
    port = _READY_PORTS.get(sid)
    if row["state"] != "active" or port is None:
        with contextlib.suppress(Exception):
            await websocket.close(code=4403)
        return
    if _VIDEO_CLIENTS.get(sid, 0) >= 1:
        with contextlib.suppress(Exception):
            await websocket.close(code=4429)
        return
    _VIDEO_CLIENTS[sid] = _VIDEO_CLIENTS.get(sid, 0) + 1

    upstream = None
    upstream_failed = False
    try:
        try:
            upstream = await websockets.connect(
                f"ws://127.0.0.1:{port}{_viewer_device_path('/api/v1/preview/video', str(row['resource_key']))}",
                max_size=None,
                origin=f"http://127.0.0.1:{port}",
            )
            await upstream.send(json.dumps({"proto": 1}))
        except Exception:
            # viewer 通道没起来（runner 被杀 / scrcpy 启动失败等）：用专门的
            # 关闭码告诉前端「重连救不了，需要关闭会话重进」，而不是 1000
            # 让前端误判成正常结束。
            upstream_failed = True
            raise

        async def to_client() -> None:
            while True:
                frame = await upstream.recv()
                if isinstance(frame, (bytes, bytearray)):
                    await websocket.send_bytes(bytes(frame))
                else:
                    await websocket.send_text(str(frame))

        async def watch_client() -> None:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code") or 1000)
                # 视频信道只下行：忽略浏览器发来的任何消息

        done, pending = await asyncio.wait(
            [asyncio.create_task(to_client()), asyncio.create_task(watch_client())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(
                exc, (WebSocketDisconnect, websockets.ConnectionClosed)
            ):
                logger.debug("video ws pump error: %s", exc)
    except Exception:  # noqa: BLE001 - 上游/浏览器断开都按会话结束收口
        logger.debug("video ws 透传失败: session=%s", sid)
    finally:
        remaining = _VIDEO_CLIENTS.get(sid, 1) - 1
        if remaining > 0:
            _VIDEO_CLIENTS[sid] = remaining
        else:
            _VIDEO_CLIENTS.pop(sid, None)
        if upstream is not None:
            with contextlib.suppress(Exception):
                await upstream.close()
        with contextlib.suppress(Exception):
            await websocket.close(code=4450 if upstream_failed else 1000)


@router.websocket("/ws/debug/{session_id}/gesture")
async def debug_gesture_socket(websocket: WebSocket, session_id: str) -> None:
    """直接操控手势透传：浏览器 <-> vendor /api/v1/input/gesture。

    平台先替浏览器把 token hello 发给 vendor（vendor 要求严格 Origin），
    之后双向透传 start/move/end；每会话最多一条手势连接。
    """
    import websockets

    from ..db import get_sessionmaker

    with contextlib.suppress(Exception):
        await websocket.accept()
    sid = str(session_id)
    token = _CONTROL_TOKENS.get(sid)
    if not token:
        with contextlib.suppress(Exception):
            await websocket.close(code=4403)
        return

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT ds.state, er.resource_key
                      FROM debug_sessions ds
                      JOIN execution_resources er
                        ON er.project_id = ds.project_id AND er.id = ds.resource_id
                     WHERE ds.id = CAST(:sid AS uuid)
                    """
                ),
                {"sid": sid},
            )
        ).mappings().first()
        await session.rollback()
    if row is None:
        with contextlib.suppress(Exception):
            await websocket.close(code=4404)
        return
    port = _READY_PORTS.get(sid)
    if row["state"] != "active" or port is None:
        with contextlib.suppress(Exception):
            await websocket.close(code=4403)
        return
    if _GESTURE_CLIENTS.get(sid, 0) >= 1:
        with contextlib.suppress(Exception):
            await websocket.close(code=4429)
        return
    _GESTURE_CLIENTS[sid] = _GESTURE_CLIENTS.get(sid, 0) + 1

    upstream = None
    try:
        upstream = await websockets.connect(
            f"ws://127.0.0.1:{port}{_viewer_device_path('/api/v1/input/gesture', str(row['resource_key']))}",
            max_size=None,
            origin=f"http://127.0.0.1:{port}",
        )
        await upstream.send(json.dumps({"token": token}))

        async def to_client() -> None:
            while True:
                frame = await upstream.recv()
                if isinstance(frame, (bytes, bytearray)):
                    await websocket.send_bytes(bytes(frame))
                else:
                    await websocket.send_text(str(frame))

        async def to_upstream() -> None:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code") or 1000)
                text_val = message.get("text")
                if text_val is not None:
                    await upstream.send(text_val)

        done, pending = await asyncio.wait(
            [asyncio.create_task(to_client()), asyncio.create_task(to_upstream())],
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(
                exc, (WebSocketDisconnect, websockets.ConnectionClosed)
            ):
                logger.debug("gesture ws pump error: %s", exc)
    except Exception:  # noqa: BLE001 - 上游/浏览器断开都按会话结束收口
        logger.debug("gesture ws 透传失败: session=%s", sid)
    finally:
        remaining = _GESTURE_CLIENTS.get(sid, 1) - 1
        if remaining > 0:
            _GESTURE_CLIENTS[sid] = remaining
        else:
            _GESTURE_CLIENTS.pop(sid, None)
        if upstream is not None:
            with contextlib.suppress(Exception):
                await upstream.close()
        with contextlib.suppress(Exception):
            await websocket.close(code=1000)


__all__ = ["router", "MAX_WS_CLIENTS_PER_SESSION", "_READY_PORTS", "_close_session", "register_viewer_port"]
