"""调试会话的业务服务（自 routers/debug.py 迁入，P2-03 分层）。

职责边界
--------
只放「没有 HTTP 语义的会话业务与进程内状态」：

- viewer 端口登记表（internal ready 上报的落点，代理/WS 读它）；
- runner 进程管理（进程表 + 命令行兜底扫描 + 跨 loop 拉起）；
- 会话关闭编排（幂等）：控制权归还 -> state=closed -> 释放租约 -> 审计；
- 框选验证凭证的进程内凭证库（发放 / 校验消费 / 按会话作废）。

HTTP 层（端点、vendor 代理 _forward、WS 透传、视图投影）留在
routers/debug.py。进程内 dict 由本模块持有，路由层经别名导入共享**同一
对象**（单进程 uvicorn 口径，多 worker 部署要换共享存储）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid as uuid_mod
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError, conflict

#: 进程内 viewer 端口表：{session_id: port}，ready 上报时写入，关闭时删除。
READY_PORTS: dict[str, int] = {}

#: 框选验证凭证有效期（秒）。验证只证明「发凭证那一刻画面上唯一命中」，
#: 窗口内必须完成登记，否则重新验证（阈值/框选/画面都可能已经变了）。
CROP_VERIFICATION_TTL_SECONDS = 120.0
#: 进程内验证凭证：token -> {session_id, snapshot_id, region, threshold, expires_at}。
#: 单进程 uvicorn 下与 READY_PORTS 同口径：多 worker 部署要换成共享存储。
CROP_VERIFICATIONS: dict[str, dict[str, Any]] = {}

#: 直接操控：平台代浏览器持有 vendor 控制权 token；浏览器永远拿不到 token。
#: 与 READY_PORTS/CROP_VERIFICATIONS 同口径，多 worker 部署需换共享存储。
CONTROL_TOKENS: dict[str, str] = {}
#: 每会话最多一条手势 WS（vendor 侧每设备同时只允许一个手势）。
GESTURE_CLIENTS: dict[str, int] = {}


# --------------------------------------------------------------------------- #
# viewer 端口登记
# --------------------------------------------------------------------------- #
def register_viewer_port(session_id: str, port: int) -> None:
    """internal ready 端点回报的 viewer 端口登记（进程内表，见模块 docstring）。"""
    READY_PORTS[str(session_id)] = int(port)


# --------------------------------------------------------------------------- #
# runner 进程管理
# --------------------------------------------------------------------------- #
def find_runner_pid_by_run_id(run_id: str) -> int | None:
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


def terminate_runner_blocking(run_id: str) -> None:
    """杀 runner 进程树（同步 subprocess，避开 Selector loop 不支持子进程的限制）。

    spawn._PROCESSES 是进程内表，API 重启后为空——只查它的话，重启前 spawn 的
    runner 会漏杀，成为持有本地设备锁的孤儿（新会话 runner 全部 DeviceBusy，
    reason=local_lease_busy）。所以进程表没有时按命令行兜底扫描。
    """
    from ..runner import spawn as spawn_mod

    proc = spawn_mod._PROCESSES.get(str(run_id))
    pid = proc.pid if proc is not None else None
    if pid is None:
        pid = find_runner_pid_by_run_id(str(run_id))
    if pid:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)]
            if os.name == "nt"
            else ["kill", "-9", str(pid)],
            capture_output=True,
        )
    spawn_mod._PROCESSES.pop(str(run_id), None)


def spawn_runner_threadsafe(**kwargs) -> int:
    """在独立线程 + Proactor loop 里 spawn runner。

    请求处理器跑在 Selector loop（psycopg 异步需要），而 Windows 的
    asyncio.create_subprocess_exec 只有 Proactor loop 支持；跨 loop 子进程
    归属也不对，所以在专用线程里起一个短命 Proactor loop 完成拉起。
    """
    import threading

    from ..runner import spawn as spawn_mod

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
# 审计 / 占用者 / 会话关闭
# --------------------------------------------------------------------------- #
async def audit(
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


async def busy_holder(session: AsyncSession, resource_id: str) -> dict[str, Any] | None:
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


async def _forward(
    session_id: str,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """vendor 请求通道（与路由层 _forward 同形，端口查 READY_PORTS）。

    服务层的关闭/控制权释放需要对 vendor 发请求；与路由层分开存在是为了
    不让 services 反向 import routers。上游不可达 -> 503 viewer_unavailable。
    """
    port = READY_PORTS.get(str(session_id))
    if port is None:
        raise ApiError(
            503,
            "viewer_unavailable",
            "viewer 上游不可达：会话未激活或端口未回报",
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
    return upstream


async def release_control(session_id: str) -> None:
    """尽力释放 vendor 控制权并清掉本地 token；会话关闭/清理共用。

    调用处在 suppress 里，vendor 不可达时静默放弃（与迁移前行为一致）。
    """
    sid = str(session_id)
    token = CONTROL_TOKENS.pop(sid, None)
    GESTURE_CLIENTS.pop(sid, None)
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


async def close_session(session_id: str, *, reason: str) -> dict[str, Any] | None:
    """关闭会话（幂等）：控制权归还 -> state=closed + closed_at -> 释放租约 -> 审计。

    所有关闭路径（DELETE、spawn 失败、runner 退出兜底）都汇到这里，所以验证凭证
    的按会话清理也放在这里：会话没了，旧凭证就不该还能解锁模板登记。
    """
    from ..db import get_sessionmaker
    from ..domain import leases as leases_mod

    drop_crop_verifications(str(session_id))
    # 控制权先尽力还给 vendor：token 在本地也一并清掉，token 不随会话残留。
    await release_control(str(session_id))
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
                await audit(
                    session,
                    project_id=str(row["project_id"]),
                    action="debug_session_closed",
                    entity_id=str(session_id),
                    changes={"reason": reason},
                )
    READY_PORTS.pop(str(session_id), None)
    return {"id": str(session_id), "state": "closed"}


async def last_close_reason(session: AsyncSession, session_id: str) -> str | None:
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


# --------------------------------------------------------------------------- #
# 框选验证凭证库
# --------------------------------------------------------------------------- #
def prune_crop_verifications() -> None:
    now = time.monotonic()
    for token in [t for t, rec in CROP_VERIFICATIONS.items() if rec["expires_at"] <= now]:
        CROP_VERIFICATIONS.pop(token, None)


def drop_crop_verifications(session_id: str) -> None:
    """会话关闭即作废该会话的全部验证凭证（按 session 清，不动别的会话）。

    TTL 只是兜底：会话已经关了，凭证再"没过期"也不能证明当前画面仍然成立。
    """
    target = str(session_id)
    for token in [
        t for t, rec in CROP_VERIFICATIONS.items() if rec["session_id"] == target
    ]:
        CROP_VERIFICATIONS.pop(token, None)


def issue_crop_verification(
    *, session_id: str, snapshot_id: str, region: list[int], threshold: float
) -> str:
    """发放一次性登记凭证：绑定验证时的会话、新快照、命中框与阈值。"""
    prune_crop_verifications()
    token = secrets.token_urlsafe(24)
    CROP_VERIFICATIONS[token] = {
        "session_id": str(session_id),
        "snapshot_id": str(snapshot_id),
        "region": [int(value) for value in region],
        "threshold": float(threshold),
        "expires_at": time.monotonic() + CROP_VERIFICATION_TTL_SECONDS,
    }
    return token


def reject_unverified(reason: str, **extra: Any) -> ApiError:
    return conflict(
        "crop_not_verified",
        "框选尚未验证通过，不能登记模板：" + reason + "。请用当前画面重新验证框选。",
        extra,
    )


def consume_crop_verification(
    *, token: Any, session_id: str, snapshot_id: str, region: list[int], threshold: float
) -> None:
    """校验并消费凭证：只有「刚刚用新画面唯一命中」的那次验证能解锁登记。

    任何一项不一致（会话 / 快照 / 框选 / 阈值）都按未验证处理，且**不消费**
    凭证，让客户端带着正确参数重试；命中后立即作废（一次性）。
    """
    prune_crop_verifications()
    if not isinstance(token, str) or not token:
        raise reject_unverified("缺少验证凭证")
    record = CROP_VERIFICATIONS.get(token)
    if record is None:
        raise reject_unverified("验证凭证已失效（已使用或已过期）")
    if record["session_id"] != str(session_id):
        raise reject_unverified("验证凭证属于另一个调试会话")
    if record["snapshot_id"] != str(snapshot_id):
        raise reject_unverified("快照与验证时不同（验证基于最新捕获的画面）")
    if record["region"] != [int(value) for value in region]:
        raise reject_unverified("框选区域与验证时不同")
    if abs(record["threshold"] - float(threshold)) > 1e-9:
        raise reject_unverified("阈值与验证时不同")
    CROP_VERIFICATIONS.pop(token, None)


__all__ = [
    "CONTROL_TOKENS",
    "CROP_VERIFICATION_TTL_SECONDS",
    "CROP_VERIFICATIONS",
    "GESTURE_CLIENTS",
    "READY_PORTS",
    "busy_holder",
    "close_session",
    "consume_crop_verification",
    "drop_crop_verifications",
    "find_runner_pid_by_run_id",
    "issue_crop_verification",
    "last_close_reason",
    "prune_crop_verifications",
    "register_viewer_port",
    "reject_unverified",
    "release_control",
    "spawn_runner_threadsafe",
    "terminate_runner_blocking",
]
