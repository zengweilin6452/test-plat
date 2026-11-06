"""run_events 写入：进度、阶段、审计都走这里（development-plan.md §7.2/§8.3）。

为什么单独一个模块
------------------
run_events 上有三个唯一索引，写错任何一个都会让整条事件流断掉：
  UNIQUE(project_id, run_id, sequence)
  UNIQUE(project_id, run_id, source_key, source_event_id)
  UNIQUE(project_id, id)

* sequence 必须**由 DB 分配**：并发 runner 各自算 max+1 会撞。这里用
  SELECT COALESCE(MAX(sequence),0) ... FOR UPDATE 锁住该 run 的事件行，把
  "算号 + 插入"放进同一事务（配合调用方 BEGIN）。代价是同一 run 的事件串行，
  但这正是我们想要的 —— 事件流本来就有序。
* source_event_id 是**幂等键**：runner 网络重试同一条事件时走 ON CONFLICT DO
  NOTHING，不产生重复。stdout 的 JSON 行天然没有 id，就用行内容哈希。

表结构真源（0001_initial.py:run_events）：
  id, project_id, run_id, sequence, source_key, source_event_id, event_type,
  payload jsonb NOT NULL DEFAULT '{}', occurred_at, created_at
  payload 有 CHECK jsonb_typeof(payload) = 'object' —— 因此**不能存数组/标量**，
  失败原因这类信息放进 payload["reason"]，而不是另开列（表里没有 reason 列）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: 公共事件源的 source_key 前缀（内部端点写的事件）
SOURCE_CONTROL = "control"
SOURCE_DISPATCHER = "dispatcher"
SOURCE_RECONCILER = "reconciler"
SOURCE_API = "api"

#: 阶段权重 -> progress 百分比（development-plan.md §8.3 / api-design.md）
STAGE_WEIGHTS: Mapping[str, int] = {
    "ack": 5,
    "lease": 10,
    "ready": 20,
    "pytest": 80,
    "archive": 100,
}


@dataclass(frozen=True)
class Event:
    """待写入的一条事件。"""

    source_key: str
    source_event_id: str
    event_type: str
    payload: dict[str, Any]


def event_id_for(*parts: Any) -> str:
    """由内容派生稳定的 source_event_id（重试同一条事件不会重复落库）。"""
    raw = "\u0000".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _json_object(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """payload 必须是 JSON object（DB CHECK jsonb_typeof = 'object'）。

    非 object 的输入被包一层 {"value": ...}，而不是被静默丢弃 —— 事件不能丢，
    否则回放时看不出来少了什么。
    """
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        return {"value": payload}
    return {str(k): _jsonable(v) for k, v in payload.items()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


_NEXT_SEQ_SQL = text(
    """
    SELECT COALESCE(MAX(sequence), 0) AS max_seq
      FROM run_events
     WHERE project_id = :project_id
       AND run_id = :run_id
    """
)

_INSERT_SQL = text(
    """
    INSERT INTO run_events (
        id, project_id, run_id, sequence, source_key, source_event_id, event_type,
        payload, occurred_at
    ) VALUES (
        :id, :project_id, :run_id, :sequence, :source_key, :source_event_id, :event_type,
        CAST(:payload AS jsonb), now()
    )
    ON CONFLICT (project_id, run_id, source_key, source_event_id) DO NOTHING
    RETURNING id, sequence, event_type, source_key, source_event_id, payload, occurred_at
    """
)


async def append_events(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    run_id: str | uuid.UUID,
    events: Iterable[Event],
) -> list[dict[str, Any]]:
    """批量追加事件；返回真正新插入的行（重复事件被吞掉）。

    必须在调用方事务内执行：finalize 的 "产物 + 事件 + 状态" 要一起可见。
    """
    items = list(events)
    if not items:
        return []
    # 锁父运行，串行分配序号；PostgreSQL 不允许对聚合结果 FOR UPDATE。
    await session.execute(
        text("SELECT id FROM test_runs WHERE project_id = :pid AND id = :rid FOR UPDATE"),
        {"pid": str(project_id), "rid": str(run_id)},
    )
    seq = int(
        (
            await session.execute(
                _NEXT_SEQ_SQL,
                {"project_id": str(project_id), "run_id": str(run_id)},
            )
        ).scalar_one()
    )
    inserted: list[dict[str, Any]] = []
    for item in items:
        seq += 1
        row = (
            await session.execute(
                _INSERT_SQL,
                {
                    "id": str(uuid.uuid4()),
                    "project_id": str(project_id),
                    "run_id": str(run_id),
                    "sequence": seq,
                    "source_key": item.source_key,
                    "source_event_id": item.source_event_id,
                    "event_type": item.event_type,
                    "payload": json.dumps(_json_object(item.payload), ensure_ascii=False),
                },
            )
        ).mappings().first()
        if row is not None:
            data = dict(row)
            data["payload"] = row["payload"]
            inserted.append(data)
        else:
            # 幂等命中：不推进 sequence，避免制造空洞
            seq -= 1
    return inserted


async def append_event(
    session: AsyncSession,
    *,
    project_id: str | uuid.UUID,
    run_id: str | uuid.UUID,
    source_key: str,
    source_event_id: str,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return await append_events(
        session,
        project_id=project_id,
        run_id=run_id,
        events=[Event(source_key, source_event_id, event_type, _json_object(payload))],
    )


async def list_events(
    session: AsyncSession,
    run_id: str | uuid.UUID,
    *,
    project_id: str | uuid.UUID | None = None,
    after_sequence: int = 0,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """GET /runs/{id}/events 的数据源（按 sequence 升序，支持增量拉取）。"""
    rows = (
        await session.execute(
            text(
                """
                SELECT id, sequence, source_key, source_event_id, event_type, payload,
                       occurred_at
                  FROM run_events
                 WHERE run_id = :run_id
                   AND (CAST(:project_id AS uuid) IS NULL OR project_id = CAST(:project_id AS uuid))
                   AND sequence > :after_sequence
                 ORDER BY sequence
                 LIMIT :limit
                """
            ),
            {
                "run_id": str(run_id),
                "project_id": str(project_id) if project_id else None,
                "after_sequence": int(after_sequence),
                "limit": int(limit),
            },
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def compute_progress(events: Iterable[Mapping[str, Any]]) -> int:
    """由事件流推导 progress（0..100）。

    为什么从事件算而不是存列：test_runs 没有 progress 列，进度是**派生值**。
    只认 stage 事件里登记过的阶段名，取最大权重 —— 乱序到达也不会让进度倒退。
    """
    best = 0
    for event in events:
        payload = event.get("payload") or {}
        if not isinstance(payload, Mapping):
            continue
        stage = payload.get("stage") or payload.get("name")
        explicit = payload.get("progress")
        if isinstance(explicit, (int, float)):
            best = max(best, int(explicit))
        if isinstance(stage, str) and stage in STAGE_WEIGHTS:
            best = max(best, STAGE_WEIGHTS[stage])
    return max(0, min(100, best))


def stage_number(progress: int, *, terminal: bool) -> int:
    """progress -> 前端 4 段阶段（api-design.md：<40=1, <85=2, 100=3, 终态=4）。"""
    if terminal:
        return 4
    if progress >= 100:
        return 3
    if progress >= 40:
        return 2
    return 1


__all__ = [
    "Event",
    "SOURCE_API",
    "SOURCE_CONTROL",
    "SOURCE_DISPATCHER",
    "SOURCE_RECONCILER",
    "STAGE_WEIGHTS",
    "append_event",
    "append_events",
    "compute_progress",
    "event_id_for",
    "list_events",
    "stage_number",
]
