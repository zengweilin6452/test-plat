"""DB 权威租约 + fencing token（development-plan.md §7.1）。

为什么不信任 vendor 本地锁
--------------------------
vendor 的 DeviceLease 只是**单机**互斥（Windows 上是每进程字节区锁，同一进程
重入甚至不会失败），它挡不住多 worker、多节点、容器重启后残留的 holder 文件。
所以"谁能用这台设备"的权威判定必须落在 Postgres 行锁上：

    BEGIN;
      SELECT id FROM execution_resources
       WHERE status = 'ready'
         AND id NOT IN (SELECT resource_id FROM resource_leases WHERE released_at IS NULL)
       ORDER BY id
         FOR UPDATE SKIP LOCKED
       LIMIT 1;
      UPDATE execution_resources SET fence_counter = fence_counter + 1
       RETURNING fence_counter;
      INSERT INTO resource_leases (..., fencing_token) VALUES (...);
    COMMIT;

SKIP LOCKED 让并发领取者不会互相排队：抢不到的一方拿到 0 行，立刻返回
"没有可用设备"，而不是串行等待后再超时。

fencing token 的用途
--------------------
每次领取都让 fence_counter +1，租约记下当次值。runner 在每个关键边界
（开始跑、每次上报、finalize、写产物）都要带上 token；对不上说明租约已被
回收或转手，必须立刻停手并丢弃结果 —— 否则会出现"过期 runner 把操作写进
新 run"的静默错误。

表结构真源（0001_initial.py）：
  execution_resources(id, project_id, node_id, profile_id, platform, resource_key,
                      kind, status, fence_counter, created_at)   ← 没有 last_seen_at
  resource_leases(id, project_id, resource_id, run_id, debug_session_id,
                  fencing_token, holder_id, expires_at, released_at, release_reason,
                  created_at)   ← expires_at > created_at 有 CHECK
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 租约时长：比 heartbeat 间隔（10s）宽松得多；掉线判定交给 reconciler 的
# stale_run_seconds=60，租约本身给 120s，避免"刚领到就过期"。
DEFAULT_LEASE_SECONDS = 120

_PICK_SQL = text(
    """
    SELECT er.id, er.project_id, er.node_id, er.profile_id, er.platform,
           er.resource_key, er.kind
      FROM execution_resources er
     WHERE er.project_id = :project_id
       AND er.status = 'ready'
       AND (CAST(:platform AS text) IS NULL OR er.platform = :platform)
       AND er.id NOT IN (
             SELECT rl.resource_id FROM resource_leases rl WHERE rl.released_at IS NULL
           )
       AND (CAST(:resource_id AS uuid) IS NULL OR er.id = CAST(:resource_id AS uuid))
     ORDER BY er.id
       FOR UPDATE SKIP LOCKED
     LIMIT 1
    """
)

_BUMP_FENCE_SQL = text(
    """
    UPDATE execution_resources
       SET fence_counter = fence_counter + 1
     WHERE id = :resource_id
    RETURNING fence_counter
    """
)

_INSERT_LEASE_SQL = text(
    """
    INSERT INTO resource_leases (
        id, project_id, resource_id, run_id, fencing_token, holder_id, expires_at
    ) VALUES (
        :id, :project_id, :resource_id, :run_id, :fencing_token, :holder_id,
        now() + make_interval(secs => :lease_seconds)
    )
    RETURNING id, project_id, resource_id, run_id, fencing_token, holder_id,
              expires_at, released_at, release_reason, created_at
    """
)


@dataclass(frozen=True)
class Lease:
    """一条活动租约（领取成功后的返回值）。"""

    id: str
    project_id: str
    resource_id: str
    run_id: str | None
    fencing_token: int
    holder_id: str
    expires_at: Any
    serial: str | None = None
    platform: str | None = None

    def as_details(self) -> dict[str, Any]:
        return {
            "lease_id": self.id,
            "resource_id": self.resource_id,
            "run_id": self.run_id,
            "fencing_token": self.fencing_token,
            "holder_id": self.holder_id,
            "expires_at": self.expires_at,
            "serial": self.serial,
        }


async def acquire_lease(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    run_id: str | uuid.UUID,
    holder_id: str,
    resource_id: str | uuid.UUID | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    platform: str | None = None,
) -> Lease | None:
    """在**调用方的事务里**领取一台设备；没有可用设备返回 None。

    调用方负责 commit —— dispatcher 把"领取 + state=dispatching"放进同一个
    事务，避免出现"租约已建但 run 还是 queued"的中间态被 reconciler 误回收。
    """
    picked = (
        await session.execute(
            _PICK_SQL,
            {
                "project_id": str(project_id),
                "resource_id": str(resource_id) if resource_id else None,
                "platform": platform,
            },
        )
    ).mappings().first()
    if picked is None:
        return None

    rid = str(picked["id"])
    # 租约的复合外键要求运行已绑定同一资源，必须先绑定再插租约。
    await session.execute(
        text("UPDATE test_runs SET resource_id = :resource_id, profile_id = :profile_id, "
             "lock_version = lock_version + 1 WHERE id = :run_id AND project_id = :pid"),
        {"resource_id": rid, "profile_id": str(picked["profile_id"]),
         "run_id": str(run_id), "pid": str(project_id)},
    )
    fence = (await session.execute(_BUMP_FENCE_SQL, {"resource_id": rid})).scalar_one()

    row = (
        await session.execute(
            _INSERT_LEASE_SQL,
            {
                "id": str(uuid.uuid4()),
                "project_id": str(project_id),
                "resource_id": rid,
                "run_id": str(run_id),
                "fencing_token": int(fence),
                "holder_id": holder_id,
                "lease_seconds": int(lease_seconds),
            },
        )
    ).mappings().first()

    return Lease(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        resource_id=str(row["resource_id"]),
        run_id=str(row["run_id"]) if row["run_id"] else None,
        fencing_token=int(row["fencing_token"]),
        holder_id=row["holder_id"],
        expires_at=row["expires_at"],
        serial=picked["resource_key"],
        platform=picked["platform"],
    )


async def live_lease_for_run(
    session: AsyncSession, run_id: str | uuid.UUID
) -> dict[str, Any] | None:
    """当前 run 的活动租约（未释放）。"""
    row = (
        await session.execute(
            text(
                """
                SELECT rl.id, rl.project_id, rl.resource_id, rl.run_id, rl.fencing_token,
                       rl.holder_id, rl.expires_at, rl.released_at, er.resource_key
                  FROM resource_leases rl
                  JOIN execution_resources er ON er.id = rl.resource_id
                 WHERE rl.run_id = :run_id
                   AND rl.released_at IS NULL
                 ORDER BY rl.created_at DESC
                 LIMIT 1
                """
            ),
            {"run_id": str(run_id)},
        )
    ).mappings().first()
    return dict(row) if row else None


async def verify_fence(
    session: AsyncSession,
    *,
    run_id: str | uuid.UUID,
    token: int | None,
) -> dict[str, Any]:
    """校验 runner 带来的 fencing token 是否仍是当前活动租约的 token。

    返回 {ok, checked, expected, provided, lease, resource_id}。token 为 None
    （旧 runner / import 通道）时按"不校验"处理：ok=True 但 checked=False。
    """
    lease = await live_lease_for_run(session, run_id)
    expected = int(lease["fencing_token"]) if lease else None
    if token is None:
        return {
            "ok": True,
            "checked": False,
            "expected": expected,
            "provided": None,
            "lease": lease,
            "resource_id": lease["resource_id"] if lease else None,
        }
    ok = expected is not None and int(token) == expected
    return {
        "ok": ok,
        "checked": True,
        "expected": expected,
        "provided": int(token),
        "lease": lease,
        "resource_id": lease["resource_id"] if lease else None,
    }


async def extend_lease(
    session: AsyncSession, *, run_id: str | uuid.UUID, token: int | None = None
) -> bool:
    """心跳续租：把 expires_at 推后。token 给了就只续自己那条租约。"""
    result = await session.execute(
        text(
            """
            UPDATE resource_leases
               SET expires_at = now() + make_interval(secs => :lease_seconds)
             WHERE run_id = :run_id
               AND released_at IS NULL
               AND (CAST(:token AS bigint) IS NULL OR fencing_token = CAST(:token AS bigint))
            """
        ),
        {
            "run_id": str(run_id),
            "token": int(token) if token is not None else None,
            "lease_seconds": DEFAULT_LEASE_SECONDS,
        },
    )
    return (result.rowcount or 0) > 0


async def release_lease(
    session: AsyncSession,
    *,
    run_id: str | uuid.UUID,
    reason: str,
    token: int | None = None,
) -> dict[str, Any] | None:
    """标记 DB 租约为已释放（幂等）。

    **顺序纪律**（development-plan.md §7.1）：调用本方法之前，runner 必须已经
    停掉设备上的会话、并且已经释放 vendor 本地锁。到此设备才算真的空闲。
    """
    row = (
        await session.execute(
            text(
                """
                UPDATE resource_leases
                   SET released_at = now(),
                       release_reason = :reason
                 WHERE run_id = :run_id
                   AND released_at IS NULL
                   AND (CAST(:token AS bigint) IS NULL OR fencing_token = CAST(:token AS bigint))
                RETURNING id, resource_id, run_id, fencing_token, released_at,
                          release_reason
                """
            ),
            {
                "run_id": str(run_id),
                "reason": reason,
                "token": int(token) if token is not None else None,
            },
        )
    ).mappings().first()
    if row is not None:
        return dict(row)
    # 幂等：可能已被 reconciler 回收；返回最近一条历史行供调用方判断
    existing = (
        await session.execute(
            text(
                """
                SELECT id, resource_id, run_id, fencing_token, released_at, release_reason
                  FROM resource_leases
                 WHERE run_id = :run_id
                 ORDER BY created_at DESC
                 LIMIT 1
                """
            ),
            {"run_id": str(run_id)},
        )
    ).mappings().first()
    return dict(existing) if existing else None




# --------------------------------------------------------------------------- #
# P5：调试会话租约（resource_leases.debug_session_id 通道）
# --------------------------------------------------------------------------- #
# 复用 run 租约的"DB 行锁是唯一真源"纪律：debug 会话同样必须持有 resource_leases
# 行（run_id XOR debug_session_id 的 CHECK 决定了它走另一列），部分唯一索引
# leases_one_live_resource 保证了"一台设备同时只有一个活动租约"——无论 run 还是
# debug。领取仍然走 _PICK_SQL（FOR UPDATE SKIP LOCKED + status='ready'），
# 只是锁定目标是指定 resource_id；被占用（包括被 run 占用）返回 None。

_ACQUIRE_DEBUG_LEASE_SQL = text(
    """
    INSERT INTO resource_leases (
        id, project_id, resource_id, debug_session_id, fencing_token, holder_id,
        expires_at
    ) VALUES (
        :id, :project_id, :resource_id, :debug_session_id, :fencing_token, :holder_id,
        now() + make_interval(secs => :lease_seconds)
    )
    RETURNING id, project_id, resource_id, run_id, debug_session_id, fencing_token,
              holder_id, expires_at, released_at, release_reason, created_at
    """
)


async def live_lease_for_debug(
    session: AsyncSession, debug_session_id: str | uuid.UUID
) -> dict[str, Any] | None:
    """当前调试会话的活动租约（未释放）。"""
    row = (
        await session.execute(
            text(
                """
                SELECT rl.id, rl.project_id, rl.resource_id, rl.debug_session_id,
                       rl.fencing_token, rl.holder_id, rl.expires_at, rl.released_at,
                       er.resource_key
                  FROM resource_leases rl
                  JOIN execution_resources er ON er.id = rl.resource_id
                 WHERE rl.debug_session_id = :sid
                   AND rl.released_at IS NULL
                 ORDER BY rl.created_at DESC
                 LIMIT 1
                """
            ),
            {"sid": str(debug_session_id)},
        )
    ).mappings().first()
    return dict(row) if row else None


async def acquire_lease_for_debug(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    debug_session_id: str | uuid.UUID,
    resource_id: str | uuid.UUID,
    holder_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Lease | None:
    """在调用方事务里为调试会话领取**指定**设备的租约。

    返回 None 表示设备当前不可领（不存在 / 非 ready / 已有活动租约）。
    """
    picked = (
        await session.execute(
            _PICK_SQL,
            {"project_id": str(project_id), "resource_id": str(resource_id), "platform": None},
        )
    ).mappings().first()
    if picked is None:
        return None

    rid = str(picked["id"])
    fence = (await session.execute(_BUMP_FENCE_SQL, {"resource_id": rid})).scalar_one()

    row = (
        await session.execute(
            _ACQUIRE_DEBUG_LEASE_SQL,
            {
                "id": str(uuid.uuid4()),
                "project_id": str(project_id),
                "resource_id": rid,
                "debug_session_id": str(debug_session_id),
                "fencing_token": int(fence),
                "holder_id": holder_id,
                "lease_seconds": int(lease_seconds),
            },
        )
    ).mappings().first()

    return Lease(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        resource_id=str(row["resource_id"]),
        run_id=None,
        fencing_token=int(row["fencing_token"]),
        holder_id=row["holder_id"],
        expires_at=row["expires_at"],
        serial=picked["resource_key"],
        platform=picked["platform"],
    )


async def release_lease_for_debug(
    session: AsyncSession,
    *,
    debug_session_id: str | uuid.UUID,
    reason: str,
    token: int | None = None,
) -> dict[str, Any] | None:
    """标记调试会话的 DB 租约为已释放（幂等，语义同 release_lease）。"""
    row = (
        await session.execute(
            text(
                """
                UPDATE resource_leases
                   SET released_at = now(),
                       release_reason = :reason
                 WHERE debug_session_id = :sid
                   AND released_at IS NULL
                   AND (CAST(:token AS bigint) IS NULL OR fencing_token = CAST(:token AS bigint))
                RETURNING id, resource_id, debug_session_id, fencing_token, released_at,
                          release_reason
                """
            ),
            {
                "sid": str(debug_session_id),
                "reason": reason,
                "token": int(token) if token is not None else None,
            },
        )
    ).mappings().first()
    if row is not None:
        return dict(row)
    existing = (
        await session.execute(
            text(
                """
                SELECT id, resource_id, debug_session_id, fencing_token, released_at,
                       release_reason
                  FROM resource_leases
                 WHERE debug_session_id = :sid
                 ORDER BY created_at DESC
                 LIMIT 1
                """
            ),
            {"sid": str(debug_session_id)},
        )
    ).mappings().first()
    return dict(existing) if existing else None


async def release_stale_leases(
    session: AsyncSession, *, stale_seconds: int
) -> list[dict[str, Any]]:
    """回收 expires_at 已过期的活动租约（reconciler 用），返回被回收的行。"""
    rows = (
        await session.execute(
            text(
                """
                UPDATE resource_leases
                   SET released_at = now(),
                       release_reason = :reason
                 WHERE released_at IS NULL
                   AND expires_at < now() - make_interval(secs => :stale_seconds)
                RETURNING id, project_id, resource_id, run_id, fencing_token, holder_id
                """
            ),
            {"stale_seconds": int(stale_seconds), "reason": "lease_expired"},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "Lease",
    "acquire_lease",
    "acquire_lease_for_debug",
    "extend_lease",
    "live_lease_for_debug",
    "live_lease_for_run",
    "release_lease",
    "release_lease_for_debug",
    "release_stale_leases",
    "verify_fence",
]
