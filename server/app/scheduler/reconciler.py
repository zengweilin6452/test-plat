"""reconciler：每 15s 扫心跳超时 -> 释放租约 + run=errored（§7.1）。

为什么必须有一个"收尸者"
------------------------
runner 是独立子进程，可能因为蓝屏、OOM、用户 kill、断电而没有机会上报 fail。
如果没人管，这个 run 会永远停在 running，那台设备也会被一条永不释放的租约
占死 —— 这是真实事故里最常见的一类"平台慢死"。

判定依据是**心跳**而不是进程存活：容器/跨节点部署下平台看不到对方进程表，
只能信"最后一次心跳的时间"。阈值 60s 来自 development-plan.md §7.1，心跳间隔
10s，所以连续丢 6 次心跳才判死，抗抖。

顺序纪律（§7.1）
----------------
"停止设备 -> 释放 vendor 锁 -> 标 DB 租约"这个顺序是 runner 正常退出时的
义务。reconciler 是**异常路径**：runner 已经不可信（可能还活着在动设备），
所以这里额外做两件事：
  1. 尽力 kill 掉 runner 进程树（taskkill /T /F），先切断它的设备操作；
  2. 清掉本机兜底锁（holder 进程已死就是 stale，直接删）。
然后再释放租约并把 run 打成 errored(outcome IS NULL)。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import text

from ..config import settings
from ..db import get_sessionmaker
from ..domain import events as events_mod
from ..domain import leases as leases_mod
from ..domain import runs as runs_mod
from ..integrations import leases as local_leases

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 15.0


@dataclass
class ReconcileReport:
    """一轮回收的结果（测试断言它，而不是去猜日志）。"""

    expired_runs: list[str]
    released_leases: int
    cancelled_runs: list[str]


#: 仍处于执行态、且最后一次心跳早于阈值的 run。
#: 心跳记录在 run_events 的 heartbeat 事件里（test_runs 没有 last_heartbeat 列），
#: 所以这里用"最近一条 heartbeat 事件的 occurred_at"作为心跳时间；从未心跳过的
#: 用 started_at（若为空）退回 created_at，保证"卡在 dispatching 永远不动"也能被收。
_STALE_SQL = text(
    """
    SELECT tr.id, tr.project_id, tr.state,
           er.resource_key,
           rl.id AS lease_id,
           rl.fencing_token,
           COALESCE(hb.last_beat, tr.started_at, tr.created_at) AS last_beat
      FROM test_runs tr
      LEFT JOIN execution_resources er ON er.id = tr.resource_id
      LEFT JOIN resource_leases rl
             ON rl.run_id = tr.id AND rl.released_at IS NULL
      LEFT JOIN LATERAL (
            SELECT MAX(re.occurred_at) AS last_beat
              FROM run_events re
             WHERE re.run_id = tr.id
               AND re.event_type = 'heartbeat'
           ) hb ON TRUE
     WHERE tr.state IN ('dispatching', 'running', 'finalizing')
       AND COALESCE(hb.last_beat, tr.started_at, tr.created_at)
           < now() - make_interval(secs => :stale_seconds)
     ORDER BY tr.created_at
    """
)

_CANCELLABLE_SQL = text(
    """
    SELECT tr.id, tr.project_id, tr.state, er.resource_key
      FROM test_runs tr
      LEFT JOIN execution_resources er ON er.id = tr.resource_id
     WHERE tr.state IN ('queued', 'dispatching')
       -- 取消受理事实在列上（0006）；事件只用于时间线展示，不作判定依据
       AND tr.cancel_requested_at IS NOT NULL
    """
)


async def reconcile_once(*, stale_seconds: int | None = None) -> ReconcileReport:
    """执行一轮回收。返回 ReconcileReport（可重复调用，幂等）。"""
    threshold = int(stale_seconds if stale_seconds is not None else settings.stale_run_seconds)
    sessionmaker = get_sessionmaker()
    expired: list[str] = []
    released = 0
    cancelled: list[str] = []

    async with sessionmaker() as session:
        rows = (
            await session.execute(_STALE_SQL, {"stale_seconds": threshold})
        ).mappings().all()

    for row in rows:
        rid = str(row["id"])
        project_id = str(row["project_id"])
        try:
            # 1) 先切断 runner（进程树），否则它可能一边被标 errored 一边继续操作设备
            await dispatcher_terminate(rid)
            # 2) 清理本机兜底锁（holder 已死即 stale）
            if row["resource_key"]:
                local_leases.release(str(row["resource_key"]), settings.runtime_dir)
            # 3) 最后才标 DB 租约 + errored
            async with sessionmaker() as session:
                async with session.begin():
                    await leases_mod.release_lease(session, run_id=rid, reason="lease_expired")
                    released += 1
                    await runs_mod.transition(
                        session,
                        rid,
                        (
                            runs_mod.STATE_DISPATCHING,
                            runs_mod.STATE_RUNNING,
                            runs_mod.STATE_FINALIZING,
                        ),
                        runs_mod.STATE_ERRORED,
                        reason="lease_expired",
                        actor="reconciler",
                    )
                    await events_mod.append_event(
                        session,
                        project_id=project_id,
                        run_id=rid,
                        source_key=events_mod.SOURCE_RECONCILER,
                        source_event_id=events_mod.event_id_for(
                            "lease_expired", rid, row["last_beat"]
                        ),
                        event_type="error",
                        payload={
                            "stage": "heartbeat",
                            "reason": "lease_expired",
                            "message": "心跳超时 %ss，运行已回收（outcome 保持 NULL）" % threshold,
                            "last_heartbeat_at": str(row["last_beat"]),
                            "resource_id": row["resource_key"],
                            "fencing_token": row["fencing_token"],
                        },
                    )
            expired.append(rid)
            logger.warning("run %s 心跳超时 %ss -> errored(lease_expired)", rid, threshold)
        except Exception:  # noqa: BLE001 - 单条失败不能中断整轮
            logger.exception("回收 run %s 失败", rid)

    # 排队中被取消的 run：没人会去派发它们，直接落 cancelled
    async with sessionmaker() as session:
        pending_cancel = (
            await session.execute(_CANCELLABLE_SQL)
        ).mappings().all()
    for row in pending_cancel:
        rid = str(row["id"])
        try:
            async with sessionmaker() as session:
                async with session.begin():
                    await leases_mod.release_lease(
                        session, run_id=rid, reason="cancelled_before_start"
                    )
                    await runs_mod.transition(
                        session,
                        rid,
                        (runs_mod.STATE_QUEUED, runs_mod.STATE_DISPATCHING),
                        runs_mod.STATE_CANCELLED,
                        reason="cancelled_before_start",
                        actor="reconciler",
                    )
            cancelled.append(rid)
        except Exception:  # noqa: BLE001
            logger.exception("取消排队中的 run %s 失败", rid)

    return ReconcileReport(
        expired_runs=expired, released_leases=released, cancelled_runs=cancelled
    )


async def dispatcher_terminate(run_id: str) -> None:
    """尽力 kill 该 run 的 runner 进程树（Windows: taskkill /T /F）。"""
    from ..runner import spawn as spawn_mod

    await spawn_mod.terminate_run_process(run_id, force=True)


async def run_forever(
    *,
    interval: float = RECONCILE_INTERVAL_SECONDS,
    stop: asyncio.Event | None = None,
) -> None:
    """每 15s 一轮。stop 事件用于 API 关闭时优雅退出。"""
    while True:
        if stop is not None and stop.is_set():
            return
        try:
            await reconcile_once()
        except Exception:  # noqa: BLE001
            logger.exception("reconciler 轮次失败")
        try:
            await asyncio.wait_for(stop.wait() if stop else asyncio.sleep(interval), interval)
        except TimeoutError:
            pass


__all__ = [
    "RECONCILE_INTERVAL_SECONDS",
    "ReconcileReport",
    "reconcile_once",
    "run_forever",
]
