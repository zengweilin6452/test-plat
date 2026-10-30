"""内部协议路由：runner -> API（development-plan.md §8.3）。

为什么需要这些端点
------------------
runner 是独立子进程，可能崩溃、被 kill 或在没有网络的情况下消失。因此协议设计成
"runner 主动上报 + API 全幂等"：
  * ack        拿到 revision 与任务配置（幂等的"我起来了"）
  * heartbeat  每 10s 一次，回传 cancel / fence_ok；超 60s 无心跳由 reconciler 回收
  * fence      写结果前确认 fencing_token 仍是当前租约的 token（防脑裂）
  * events     转发 stdout 的 JSON 事件（source_event_id 幂等去重）
  * complete   成功收敛（终态可重复调用，返回 already=true）
  * fail       失败收敛（同上）

鉴权：所有 /internal/* 必须带 X-Control-Token。token 在 API 启动时生成并写入
data/control.token（0600），重启即轮换 —— 旧 runner 重放旧 token 会被 401 拒绝。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..domain import control as control_mod
from ..domain import events as events_mod
from ..domain import leases as leases_mod
from ..domain import runs as runs_mod
from ..errors import control_token_invalid, fence_mismatch, not_found, validation_error
from ..ws import hub as hub_mod

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

CONTROL_TOKEN_HEADER = "X-Control-Token"


def _expected_token(request: Request) -> str:
    """校验侧令牌：与 spawn 侧共用 domain 层解析入口（进程内 > app.state > 文件）。

    两边都走 resolve_token 是硬要求 —— 各自回落会让 runner 拿到没人认的令牌。
    """
    from ..config import settings

    return control_mod.resolve_token(
        getattr(request.app.state, "control_token", None),
        settings.control_token_path,
    )


async def require_control_token(
    request: Request,
    token: str | None = Header(default=None, alias=CONTROL_TOKEN_HEADER),
) -> None:
    """恒定时间比较；缺失或不匹配一律 401（不泄露"是否存在 token"）。"""
    expected = _expected_token(request)
    if not expected or not control_mod.tokens_match(token, expected):
        raise control_token_invalid()


async def _run_row(session: AsyncSession, run_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT id, project_id, state, outcome, resource_id, revision_id,"
                "       application_id, platform, config_snapshot, started_at"
                "  FROM test_runs WHERE id::text = :id"
            ),
            {"id": str(run_id)},
        )
    ).mappings().first()
    if row is None:
        raise not_found("run", str(run_id))
    return dict(row)


@router.post("/runs/{run_id}/ack", dependencies=[Depends(require_control_token)])
async def ack_run(
    run_id: str,
    body: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """runner 报到：落 ack 事件并回传 revision 与任务配置。"""
    row = await _run_row(session, run_id)
    if runs_mod.is_terminal(str(row["state"])):
        # 已被取消或已收敛：告诉 runner 别跑了（它看到 already 会尽快退出）
        return {"ok": True, "already": True, "state": row["state"]}
    pid = body.get("pid")
    await events_mod.append_event(
        session,
        project_id=str(row["project_id"]),
        run_id=str(run_id),
        source_key=events_mod.SOURCE_CONTROL,
        source_event_id=events_mod.event_id_for("ack", run_id, pid),
        event_type="ack",
        payload={
            "pid": pid,
            "stage": "ack",
            "progress": 5,
            "revision_id": str(row["revision_id"]) if row["revision_id"] else None,
        },
    )
    await session.commit()
    return {
        "ok": True,
        "revision_id": str(row["revision_id"]) if row["revision_id"] else None,
        "application_id": str(row["application_id"]),
        "platform": row["platform"],
        "config": row["config_snapshot"] or {},
    }


@router.post("/runs/{run_id}/heartbeat", dependencies=[Depends(require_control_token)])
async def heartbeat_run(
    run_id: str,
    body: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """心跳：续租并回传 cancel / fence_ok。这是 runner 感知"该停了"的唯一通道。"""
    row = await _run_row(session, run_id)
    pid = body.get("pid")
    progress = body.get("progress")
    stage = body.get("stage")
    token = body.get("fencing_token")

    fence = await leases_mod.verify_fence(session, run_id=str(run_id), token=token)
    # 取消读列而不是事件：受理事实必须持久且不被事件分页/清理截断（spec §9.3）
    cancel = bool(
        (
            await session.execute(
                text("SELECT cancel_requested_at IS NOT NULL FROM test_runs WHERE id = :run_id"),
                {"run_id": str(run_id)},
            )
        ).scalar_one()
    )
    if fence.get("ok"):
        # extend_lease 内部用 DEFAULT_LEASE_SECONDS；带 token 时只续自己那条租约，
        # 免得旧 runner 的心跳把新租约续上（原调用多传 lease_seconds，心跳恒 500）
        await leases_mod.extend_lease(session, run_id=str(run_id), token=token)
    await events_mod.append_event(
        session,
        project_id=str(row["project_id"]),
        run_id=str(run_id),
        source_key=events_mod.SOURCE_CONTROL,
        source_event_id=events_mod.event_id_for("hb", run_id, pid, progress, stage),
        event_type="heartbeat",
        payload={"pid": pid, "progress": progress, "stage": stage},
    )
    await session.commit()
    return {"ok": True, "cancel": bool(cancel), "fence_ok": bool(fence.get("ok"))}


@router.get("/runs/{run_id}/fence", dependencies=[Depends(require_control_token)])
async def check_fence(
    run_id: str,
    token: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """写结果前确认 fencing_token 仍是当前租约的 token；不匹配 409 fence_mismatch。"""
    result = await leases_mod.verify_fence(session, run_id=str(run_id), token=token)
    if not result.get("ok"):
        raise fence_mismatch(str(run_id), result.get("expected"), result.get("provided"))
    return {
        "ok": True,
        "token": result.get("expected"),
        "resource_id": result.get("resource_id"),
    }


@router.post("/runs/{run_id}/events", dependencies=[Depends(require_control_token)])
async def post_events(
    run_id: str,
    body: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量转发 runner stdout 的 JSON 事件（source_event_id 幂等去重）。"""
    row = await _run_row(session, run_id)
    items = body.get("events") or []
    if not isinstance(items, list):
        raise validation_error(["events 必须是数组"])
    batch: list[events_mod.Event] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or item.get("event_type") or "runner")
        source_id = str(item.get("source_event_id") or "")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if not source_id:
            source_id = events_mod.event_id_for("runner", run_id, kind, payload)
        batch.append(
            events_mod.Event(
                str(item.get("source_key") or "runner"),
                source_id,
                kind,
                payload,
            )
        )
    inserted = await events_mod.append_events(
        session,
        project_id=str(row["project_id"]),
        run_id=str(run_id),
        events=batch,
    )
    await session.commit()
    for event in inserted:
        payload = event.get("payload") or {}
        name = payload.get("name") if isinstance(payload, dict) else None
        hub_mod.publish(
            str(run_id),
            {
                "type": "event",
                "kind": event.get("event_type"),
                "name": name,
                # 序号让客户端按 (run_id, sequence) 去重、断线后从 last_sequence 补拉
                "sequence": event.get("sequence"),
                "at": None,
            },
        )
    return {"accepted": len(inserted)}


@router.post("/runs/{run_id}/complete", dependencies=[Depends(require_control_token)])
async def complete_run(
    run_id: str,
    body: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """成功收敛。fence 校验 -> finalize（产物 / 事件 / 状态 / 租约顺序固定）。"""
    row = await _run_row(session, run_id)
    token = body.get("fencing_token")
    if runs_mod.is_terminal(str(row["state"])):
        return {
            "ok": True,
            "already": True,
            "state": row["state"],
            "outcome": row["outcome"],
        }
    fence = await leases_mod.verify_fence(session, run_id=str(run_id), token=token)
    if not fence.get("ok"):
        raise fence_mismatch(str(run_id), fence.get("expected"), fence.get("provided"))
    await session.commit()

    from pathlib import Path

    from .. import runtime as runtime_mod

    outcome = body.get("outcome")
    raw_dir = body.get("artifacts_dir")
    artifacts_path = Path(str(raw_dir)) if raw_dir else None
    result = await runtime_mod.finalize_run(
        run_id=str(run_id),
        state=runs_mod.STATE_COMPLETED,
        outcome=outcome if outcome in runs_mod.ALL_OUTCOMES else None,
        reason=str(body.get("reason") or "runner_completed"),
        project_id=str(row["project_id"]),
        artifacts_dir=artifacts_path,
        release_lease_reason="run_finished",
        extra_event={
            "components": body.get("components") or [],
            "cases": body.get("cases") or [],
        },
        actor="runner",
    )
    hub_mod.publish(
        str(run_id),
        {"type": "finished", "state": result.state, "outcome": result.outcome},
    )
    return {
        "ok": True,
        "state": result.state,
        "outcome": result.outcome,
        "artifacts": result.artifact_count,
    }


@router.post("/runs/{run_id}/fail", dependencies=[Depends(require_control_token)])
async def fail_run(
    run_id: str,
    body: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """失败收敛：state=errored / cancelled，outcome 必须为 NULL（DB CHECK 兜底）。"""
    row = await _run_row(session, run_id)
    token = body.get("fencing_token")
    if runs_mod.is_terminal(str(row["state"])):
        return {
            "ok": True,
            "already": True,
            "state": row["state"],
            "outcome": row["outcome"],
        }
    code = str(body.get("error_code") or "runner_failed")
    if code in ("cancelled", "cancelled_before_send", "cancelled_queued"):
        target = runs_mod.STATE_CANCELLED
    else:
        target = runs_mod.STATE_ERRORED
    if token is not None:
        fence = await leases_mod.verify_fence(session, run_id=str(run_id), token=token)
        if not fence.get("ok"):
            raise fence_mismatch(str(run_id), fence.get("expected"), fence.get("provided"))
    await session.commit()

    from .. import runtime as runtime_mod

    result = await runtime_mod.finalize_run(
        run_id=str(run_id),
        state=target,
        outcome=None,
        reason=code,
        project_id=str(row["project_id"]),
        release_lease_reason="run_failed",
        extra_event={
            "error_code": code,
            "message": str(body.get("message") or ""),
            "stage": str(body.get("stage") or ""),
            # joint 的失败也带组件事实（如 UI=cancelled"前置采集失败未执行"）
            "components": body.get("components") or [],
        },
        actor="runner",
    )
    hub_mod.publish(str(run_id), {"type": "finished", "state": result.state, "outcome": None})
    return {"ok": True, "state": result.state, "outcome": result.outcome}



# --------------------------------------------------------------------------- #
# P5：调试会话 runner 回报（viewer 端口就绪）
# --------------------------------------------------------------------------- #
async def _debug_fence(session: AsyncSession, session_id: str, token: Any) -> dict:
    row = (await session.execute(text(
        "SELECT id, state, expires_at > now() AS unexpired FROM debug_sessions "
        "WHERE id = CAST(:sid AS uuid)"
    ), {"sid": session_id})).mappings().first()
    if row is None:
        raise not_found("debug_session", session_id)
    lease = await leases_mod.live_lease_for_debug(session, session_id)
    valid = (row["state"] in ("opening", "active") and row["unexpired"] and lease is not None
             and str(lease["fencing_token"]) == str(token))
    return {"ok": bool(valid), "cancel": row["state"] not in ("opening", "active") or not row["unexpired"],
            "state": row["state"]}


@router.post("/debug-sessions/{session_id}/ack", dependencies=[Depends(require_control_token)])
@router.post("/debug-sessions/{session_id}/heartbeat", dependencies=[Depends(require_control_token)])
async def heartbeat_debug(session_id: str, body: dict = Body(default_factory=dict),
                          session: AsyncSession = Depends(get_session)) -> dict:
    result = await _debug_fence(session, session_id, body.get("fencing_token"))
    if result["ok"]:
        await session.execute(text(
            "UPDATE resource_leases SET expires_at = now() + make_interval(secs => :seconds) "
            "WHERE debug_session_id = CAST(:sid AS uuid) AND released_at IS NULL "
            "AND fencing_token = :token"
        ), {"sid": session_id, "token": body["fencing_token"], "seconds": leases_mod.DEFAULT_LEASE_SECONDS})
    return {**result, "fence_ok": result["ok"]}


@router.get("/debug-sessions/{session_id}/fence", dependencies=[Depends(require_control_token)])
async def fence_debug(session_id: str, token: str | None = None,
                      session: AsyncSession = Depends(get_session)) -> dict:
    result = await _debug_fence(session, session_id, token)
    if not result["ok"]:
        raise fence_mismatch(session_id, None, token)
    return result


@router.post("/debug-sessions/{session_id}/close", dependencies=[Depends(require_control_token)])
async def close_debug(session_id: str, body: dict = Body(default_factory=dict),
                      session: AsyncSession = Depends(get_session)) -> dict:
    result = await _debug_fence(session, session_id, body.get("fencing_token"))
    if result["state"] in ("closed", "lost"):
        return {"ok": True, "already": True}
    if not result["ok"]:
        raise fence_mismatch(session_id, None, body.get("fencing_token"))
    await session.rollback()
    from .debug import _close_session
    await _close_session(session_id, reason=str(body.get("reason") or "runner_exit"))
    return {"ok": True}


@router.post("/debug-sessions/{session_id}/ready", dependencies=[Depends(require_control_token)])
async def debug_session_ready(
    session_id: str,
    body: dict = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """runner 报告 vendor viewer 已在 127.0.0.1:<port> 监听。

    幂等：只有 state=opening 的会话会被转成 active（重复回报直接 already=true）。
    端口写进 debug_sessions.viewer_port —— 等等，0001 迁移没有这一列；端口由
    routers.debug 的进程内 _READY_PORTS 表持有（单进程部署下足够，与
    spawn._PROCESSES 同一信任级别）。
    """
    port = body.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise validation_error(["port 必须在 1–65535 之间"])
    fence = await _debug_fence(session, session_id, body.get("fencing_token"))
    if not fence["ok"]:
        raise fence_mismatch(session_id, None, body.get("fencing_token"))
    row = (
        await session.execute(
            text(
                "SELECT id, state FROM debug_sessions WHERE id = CAST(:sid AS uuid)"
            ),
            {"sid": str(session_id)},
        )
    ).mappings().first()
    if row is None:
        raise not_found("debug_session", str(session_id))
    if row["state"] == "active":
        return {"ok": True, "already": True, "state": "active"}
    if row["state"] != "opening":
        # 已关闭/丢失的会话不再接受回报
        return {"ok": False, "state": row["state"]}
    await session.execute(
        text(
            "UPDATE debug_sessions SET state = 'active'"
            " WHERE id = CAST(:sid AS uuid) AND state = 'opening'"
        ),
        {"sid": str(session_id)},
    )
    from .debug import register_viewer_port

    register_viewer_port(str(session_id), int(port))
    await session.commit()
    return {"ok": True, "state": "active"}


__all__ = ["router", "require_control_token", "CONTROL_TOKEN_HEADER"]
