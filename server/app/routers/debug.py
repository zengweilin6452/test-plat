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

4. **模板端点不伪造**：模板按调试会话隔离（vendor TemplateStore 绑定
   session.assets_dir），必须显式传 session_id（缺失 400 validation_error、
   非活动 409、上游不可达 503），绝不在 API 进程里伪造一份模板数据。

5. **WS 双向透传**：/ws/debug/{id} 仅在会话 active 时接受（否则 close 4403/4404），
   与 vendor /api/v1/preview 之间做字节级双向转发（json 帧与 binary 帧都不改），
   每会话最多 4 个客户端，会话关闭即 close(1000)。
"""

from __future__ import annotations

import asyncio
import base64
import subprocess
import contextlib
import json
import sys
import logging
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..domain import leases as leases_mod
from .tasks import require_client_header
from ..errors import (
    ApiError,
    bad_request,
    client_header_required,
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
            upstream = await client.request(method, url, json=json_body)
    except (httpx.HTTPError, OSError) as exc:
        raise ApiError(
            503,
            "viewer_unavailable",
            f"viewer 上游不可达：{exc.__class__.__name__}",
            {"session_id": str(session_id)},
        ) from exc
    headers: dict[str, str] = {}
    ctype = upstream.headers.get("content-type")
    if ctype:
        headers["content-type"] = ctype
    return Response(content=upstream.content, status_code=upstream.status_code, headers=headers)


def register_viewer_port(session_id: str, port: int) -> None:
    """internal ready 端点回报的 viewer 端口登记（进程内表，见模块 docstring）。"""
    _READY_PORTS[str(session_id)] = int(port)


def _terminate_runner_blocking(run_id: str) -> None:
    """杀 runner 进程树（同步 subprocess，避开 Selector loop 不支持子进程的限制）。"""
    import subprocess as subprocess_mod

    proc = spawn_mod._PROCESSES.get(str(run_id))
    pid = proc.pid if proc is not None else None
    if pid:
        subprocess_mod.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
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
                 ORDER BY er.created_at
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

    # 先插会话行（opening；FK 要求它先存在），再在同一事务里领租约
    session_id = str(uuid_mod.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_SESSION_SECONDS)
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
    """关闭会话（幂等）：runner 终止 -> state=closed + closed_at -> 释放租约 -> 审计。"""
    from ..db import get_sessionmaker

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


@router.get("/debug-sessions/{session_id}")
async def get_debug_session(session_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    row = await _session_row(session, session_id)
    viewer_port = _READY_PORTS.get(str(row["id"])) if row["state"] == "active" else None
    return _view(row, viewer_port=viewer_port)


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
    return await _forward(str(row["id"]), "GET", f"/api/v1/snapshots/{snapshot_id}/image")


@router.get("/debug-sessions/{session_id}/snapshots/{snapshot_id}/tree")
async def proxy_snapshot_tree(
    session_id: str, snapshot_id: str, session: AsyncSession = Depends(get_session)
) -> Response:
    row = await _active_row(session, session_id)
    return await _forward(str(row["id"]), "GET", f"/api/v1/snapshots/{snapshot_id}/tree")


@router.post("/debug-sessions/{session_id}/locators/validate")
async def proxy_locators_validate(
    session_id: str,
    request: Request,
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
# 模板端点（session_id 必填：模板按调试会话隔离，无兜底）
# --------------------------------------------------------------------------- #
async def _template_session(session: AsyncSession, session_id: str | None) -> str:
    """模板代理的目标会话。vendor 的 TemplateStore 绑定 session.assets_dir——
    模板数据本身就是按调试会话隔离的，所以会话 id 必须显式给出。

    曾经的"无 session_id 时挑最新活动会话"兜底是跨项目泄漏点（A 项目的请求
    会落到 B 项目的 viewer 上），已删除；缺失 session_id 走项目统一的
    validation_error（400），非活动会话 409，上游不可达 503。
    """
    if not session_id:
        raise validation_error(
            ["session_id 必填：模板按调试会话隔离，请传入调试会话 id"
             "（POST /api/v1/debug-sessions 创建后取得）"]
        )
    row = await _active_row(session, session_id)
    return str(row["id"])


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
                          session: AsyncSession = Depends(get_session)) -> Response:
    sid = await _template_session(session, session_id)
    return await _forward(sid, "POST", "/api/v1/templates", json_body=await request.json())


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
        raise ApiError(503, "service_unavailable", "图像验证超时")
    except OSError:
        raise ApiError(503, "service_unavailable", "图像匹配进程不可用")
    if completed.returncode:
        raise ApiError(503, "service_unavailable", "图像匹配进程不可用")
    result = json.loads(completed.stdout)
    if "error" in result:
        raise validation_error([result["error"]])
    return result


@router.post("/templates/validate-crop")
async def validate_crop(request: Request, session_id: str | None = None,
                        session: AsyncSession = Depends(get_session)) -> Response:
    sid = await _template_session(session, session_id)
    body = await request.json()
    region = body.get("region")
    threshold = body.get("threshold")
    snapshot_id = body.get("snapshot_id")
    if (not isinstance(region, list) or len(region) != 4
            or any(type(v) is not int for v in region)
            or not isinstance(snapshot_id, str) or not snapshot_id
            or type(threshold) not in (int, float) or not 0.1 <= threshold <= 1):
        raise validation_error(["需要有效 snapshot_id、四整数 region 和 0.10-1.00 threshold"])
    source = await _forward(sid, "GET", f"/api/v1/snapshots/{snapshot_id}/image")
    if source.status_code >= 300:
        return source
    capture = await _forward(sid, "POST", "/api/v1/snapshots", json_body={})
    if capture.status_code >= 300:
        return capture
    new_id = json.loads(capture.body)["snapshot_id"]
    current = await _forward(sid, "GET", f"/api/v1/snapshots/{new_id}/image")
    if current.status_code >= 300:
        return current
    result = await _match_crop(source.body, current.body, region, threshold)
    return Response(json.dumps({**result, "snapshot_id": new_id,
                               "source_snapshot_id": snapshot_id}),
                    media_type="application/json")


@router.post("/templates/validate")
async def validate_template(request: Request, session_id: str | None = None,
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

            raise validation_error(["threshold 必须是数值"])
        if not (0.10 <= value <= 1.00):
            from ..errors import validation_error

            raise validation_error(["threshold 必须在 0.10-1.00 之间"])
    sid = await _template_session(session, session_id)
    return await _forward(sid, "POST", "/api/v1/templates/validate", json_body=body)



@router.put("/templates/{logical:path}")
async def update_template(logical: str, request: Request, session_id: str | None = None,
                          session: AsyncSession = Depends(get_session)) -> Response:
    from urllib.parse import quote
    sid = await _template_session(session, session_id)
    return await _forward(sid, "PUT", "/api/v1/templates/" + quote(logical, safe="/"), json_body=await request.json())


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


__all__ = ["router", "MAX_WS_CLIENTS_PER_SESSION", "_READY_PORTS", "_close_session", "register_viewer_port"]
