"""dispatcher：每 2s 领 queued 并 spawn runner（development-plan.md §7.1）。

一次派发的事务边界
------------------
领取设备（行锁 + fence_counter+1 + 插租约）和 state=dispatching 必须在**同一个
事务**里。分开写的话会存在一个窗口：租约已建、run 还是 queued —— 此时
reconciler 看到 queued 却没人领，或者反过来看到租约有主而 run 没动，两种误判
都会把好好的任务打成 errored。

为什么"领取失败 = errored"而不是"留在 queued"
------------------------------------------------
api-design.md §1.2 把"设备不可用"定为 424 device_not_ready（提交时同步校验）。
走到 dispatcher 说明提交时设备是 ready 的，之后掉线/被占 —— 这是执行期故障，
重试也只会一直排队，让用户看不到反馈。所以直接 errored(device_unavailable)，
用户重跑时会拿到新的 run（parent_run_id 保留谱系）。

为什么 spawn 失败要回滚成 errored 且必须释放租约
------------------------------------------------
runner 起不来（python 路径错、vendor 缺依赖）是**平台故障**，不是设备故障。
此时必须先把租约释放掉，否则这台设备会被一个从未启动的 run 永久占住 ——
这是 P3 最容易踩的坑。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ..config import settings
from ..db import get_sessionmaker
from ..domain import events as events_mod
from ..domain import leases as leases_mod
from ..domain import runs as runs_mod
from ..integrations import leases as local_leases
from ..runner import dispatch_runner

logger = logging.getLogger(__name__)

DISPATCH_INTERVAL_SECONDS = 2.0
DISPATCH_BATCH = 8
HOLDER_PREFIX = "dispatcher"


@dataclass
class DispatchOutcome:
    """一次派发的可观测结果（测试与日志都用它，不依赖返回值字符串）。"""

    run_id: str
    ok: bool
    reason: str = ""
    lease: dict[str, Any] | None = None


_QUEUED_SQL = text(
    """
    SELECT tr.id, tr.project_id, tr.platform, tr.application_id, tr.revision_id,
           tr.config_snapshot
      FROM test_runs tr
     WHERE tr.state = 'queued'
     ORDER BY tr.created_at, tr.id
     LIMIT :limit
    """
)


async def _resolve_config(session, run: dict[str, Any]) -> dict[str, Any]:
    """合并 config_snapshot 与运行所需的最小上下文（应用标识、串口等）。"""
    snapshot = run.get("config_snapshot") or {}
    if isinstance(snapshot, str):
        import json

        try:
            snapshot = json.loads(snapshot)
        except ValueError:
            snapshot = {}
    app_row = (
        await session.execute(
            text("SELECT name, identifier FROM applications WHERE id = :id"),
            {"id": str(run["application_id"])},
        )
    ).mappings().first()
    merged: dict[str, Any] = dict(snapshot)
    merged.setdefault("platform", run.get("platform"))
    if app_row:
        merged.setdefault("application_name", app_row["name"])
        merged.setdefault("app_package", app_row["identifier"])
    return merged


async def dispatch_one(run_id: str | uuid.UUID | None = None) -> DispatchOutcome:
    """派发一个 run（run_id 为空时挑最早的 queued）。

    返回 DispatchOutcome；任何失败都已经把 run 收敛到 errored，不会留在 queued。
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            if run_id is None:
                candidates = (
                    await session.execute(_QUEUED_SQL, {"limit": DISPATCH_BATCH})
                ).mappings().all()
                if not candidates:
                    return DispatchOutcome(run_id="", ok=False, reason="no_queued_run")
                run = dict(candidates[0])
            else:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT id, project_id, platform, application_id, revision_id,
                                   config_snapshot, state
                              FROM test_runs WHERE id = :id
                            """
                        ),
                        {"id": str(run_id)},
                    )
                ).mappings().first()
                if row is None:
                    return DispatchOutcome(run_id=str(run_id), ok=False, reason="run_not_found")
                if row["state"] != runs_mod.STATE_QUEUED:
                    return DispatchOutcome(
                        run_id=str(run_id), ok=False, reason="not_queued:%s" % row["state"]
                    )
                run = dict(row)

            rid = str(run["id"])
            project_id = str(run["project_id"])
            holder = "%s:%d" % (HOLDER_PREFIX, os_pid())

            lease = await leases_mod.acquire_lease(
                session,
                project_id=project_id,
                run_id=rid,
                holder_id=holder,
            )
            if lease is None:
                await _fail_run_in_tx(
                    session,
                    run=run,
                    reason="device_unavailable",
                    message="没有可用设备（全部离线、未授权或被占用）",
                    source=events_mod.SOURCE_DISPATCHER,
                )
                logger.warning("run %s 领取设备失败 -> errored(device_unavailable)", rid)
                return DispatchOutcome(run_id=rid, ok=False, reason="device_unavailable")

            # 本地兜底锁：DB 给了这台设备，但宿主上仍有进程占着（vendor 锁残留）
            local = local_leases.probe(str(lease.serial or ""), settings.runtime_dir)
            if local.held:
                await leases_mod.release_lease(session, run_id=rid, reason="local_lease_busy")
                await _fail_run_in_tx(
                    session,
                    run=run,
                    reason="local_lease_busy",
                    message="设备 %s 被本机另一进程持有（pid=%s）"
                    % (lease.serial, local.holder_pid),
                    source=events_mod.SOURCE_DISPATCHER,
                )
                return DispatchOutcome(run_id=rid, ok=False, reason="local_lease_busy")

            # queued -> dispatching，同时写入资源与开始时间（满足
            # ck_test_runs_state_executing_needs_resource 的兄弟约束：dispatching
            # 不强制 resource_id，但提前写入让前端能立刻看到"已分配设备"）
            await session.execute(
                text(
                    """
                    UPDATE test_runs
                       SET resource_id = :resource_id,
                           profile_id = :profile_id,
                           lock_version = lock_version + 1
                     WHERE id = :run_id AND state = 'queued'
                    """
                ),
                {
                    "run_id": rid,
                    "resource_id": lease.resource_id,
                    "profile_id": (
                        await session.execute(
                            text("SELECT profile_id FROM execution_resources WHERE id = :id"),
                            {"id": lease.resource_id},
                        )
                    ).scalar_one(),
                },
            )
            await runs_mod.transition(
                session,
                rid,
                runs_mod.STATE_QUEUED,
                runs_mod.STATE_DISPATCHING,
                reason="lease_acquired",
                actor=holder,
            )
            await events_mod.append_event(
                session,
                project_id=project_id,
                run_id=rid,
                source_key=events_mod.SOURCE_DISPATCHER,
                source_event_id=events_mod.event_id_for("lease", rid, lease.fencing_token),
                event_type="lease_acquired",
                payload={
                    "stage": "lease",
                    "resource_id": lease.resource_id,
                    "serial": lease.serial,
                    "fencing_token": lease.fencing_token,
                },
            )
            config = await _resolve_config(session, run)
            lease_details = lease.as_details()

    # 事务已提交：此时镜像里一定有"租约 + dispatching"。spawn 放在事务外，
    # 因为拉起子进程是不可回滚的副作用，绝不能让它发生在一个还会回滚的事务里。
    try:
        pid = await dispatch_runner.spawn(
            run_id=rid,
            config={**config, "revision_id": run.get("revision_id")},
            lease=lease_details,
        )
    except Exception as exc:  # noqa: BLE001 - spawn 失败必须收敛成 errored
        logger.exception("run %s spawn 失败", rid)
        await mark_spawn_failed(rid, error=str(exc), lease=lease_details)
        return DispatchOutcome(run_id=rid, ok=False, reason="runner_spawn_failed")

    logger.info("run %s 已派发 pid=%s serial=%s", rid, pid, lease_details.get("serial"))
    return DispatchOutcome(
        run_id=rid, ok=True, reason="spawned", lease=lease_details
    )


async def mark_spawn_failed(
    run_id: str | uuid.UUID, *, error: str, lease: dict[str, Any] | None
) -> None:
    """spawn 失败：释放租约 + run=errored。必须两步都做，否则设备被永久占用。"""
    sessionmaker = get_sessionmaker()
    rid = str(run_id)
    async with sessionmaker() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text("SELECT project_id, state FROM test_runs WHERE id = :id"),
                    {"id": rid},
                )
            ).mappings().first()
            if row is None:
                return
            await leases_mod.release_lease(session, run_id=rid, reason="runner_spawn_failed")
            if row["state"] in (runs_mod.STATE_DISPATCHING, runs_mod.STATE_QUEUED):
                await runs_mod.transition(
                    session,
                    rid,
                    (runs_mod.STATE_DISPATCHING, runs_mod.STATE_QUEUED),
                    runs_mod.STATE_ERRORED,
                    reason="runner_spawn_failed",
                    actor="dispatcher",
                )
                await events_mod.append_event(
                    session,
                    project_id=str(row["project_id"]),
                    run_id=rid,
                    source_key=events_mod.SOURCE_DISPATCHER,
                    source_event_id=events_mod.event_id_for("spawn_failed", rid),
                    event_type="error",
                    payload={
                        "stage": "spawn",
                        "reason": "runner_spawn_failed",
                        "message": error[:2000],
                        "lease": lease,
                    },
                )


async def _fail_run_in_tx(
    session,
    *,
    run: dict[str, Any],
    reason: str,
    message: str,
    source: str,
) -> None:
    rid = str(run["id"])
    await runs_mod.transition(
        session,
        rid,
        runs_mod.STATE_QUEUED,
        runs_mod.STATE_ERRORED,
        reason=reason,
        actor="dispatcher",
    )
    await events_mod.append_event(
        session,
        project_id=str(run["project_id"]),
        run_id=rid,
        source_key=source,
        source_event_id=events_mod.event_id_for(reason, rid),
        event_type="error",
        payload={"stage": "dispatch", "reason": reason, "message": message},
    )


def os_pid() -> int:
    import os

    return os.getpid()


async def dispatch_pending(limit: int = DISPATCH_BATCH) -> list[DispatchOutcome]:
    """一轮派发：最多 limit 个 queued。逐个处理，任一失败不影响后续。"""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = (
            await session.execute(_QUEUED_SQL, {"limit": int(limit)})
        ).mappings().all()
    outcomes: list[DispatchOutcome] = []
    for row in rows:
        try:
            outcomes.append(await dispatch_one(str(row["id"])))
        except Exception as exc:  # noqa: BLE001 - 单个 run 失败不能拖垮整轮
            logger.exception("派发 run %s 异常", row["id"])
            outcomes.append(
                DispatchOutcome(run_id=str(row["id"]), ok=False, reason="exception:%s" % exc)
            )
    return outcomes


async def run_forever(
    *,
    interval: float = DISPATCH_INTERVAL_SECONDS,
    stop: asyncio.Event | None = None,
) -> None:
    """每 2s 领一次。stop 事件用于 API 关闭时优雅退出。"""
    while True:
        if stop is not None and stop.is_set():
            return
        try:
            await dispatch_pending()
        except Exception:  # noqa: BLE001 - 循环必须活下去
            logger.exception("dispatcher 轮次失败")
        try:
            await asyncio.wait_for(stop.wait() if stop else asyncio.sleep(interval), interval)
        except asyncio.TimeoutError:
            pass


__all__ = [
    "DISPATCH_BATCH",
    "DISPATCH_INTERVAL_SECONDS",
    "DispatchOutcome",
    "dispatch_one",
    "dispatch_pending",
    "mark_spawn_failed",
    "run_forever",
]
