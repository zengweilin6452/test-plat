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
    token = getattr(request.app.state, "control_token", None)
    if not token:
        # lifespan 没跑（例如直接构造 app 的测试）时回落到磁盘 token
        from ..config import settings

        token = control_mod.read_token(settings.control_token_path)
    return token or ""


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
    cancel = (
        await session.execute(
            text(
                "SELECT 1 FROM run_events"
                " WHERE run_id = :run_id AND event_type = :kind LIMIT 1"
            ),
            {"run_id": str(run_id), "kind": "cancel_requested"},
        )
    ).scalar_one_or_none() is not None
    if fence.get("ok"):
        await leases_mod.extend_lease(
            session,
            run_id=str(run_id),
            lease_seconds=leases_mod.DEFAULT_LEASE_SECONDS,
        )
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
        raise validation_error("events 必须是数组")
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
            {"type": "event", "kind": event.get("event_type"), "name": name, "at": None},
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
        },
        actor="runner",
    )
    hub_mod.publish(str(run_id), {"type": "finished", "state": result.state, "outcome": None})
    return {"ok": True, "state": result.state, "outcome": result.outcome}


__all__ = ["router", "require_control_token", "CONTROL_TOKEN_HEADER"]
