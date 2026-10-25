"""运行记录：GET /runs（列表）与运行级汇总。

表结构真源（不做任何推测）：
  - test_runs 有 state / outcome / revision_id / resource_id / started_at / ended_at，
    没有 task_id，也没有 progress；任务归属必须经 revision_id -> task_revisions.task_id。
  - 模块（ui / perf / joint）来自 task_revisions.test_type，不在 test_tasks 上。
  - test_runs.outcome 只可能在 state='completed' 时非空（schema CHECK），
    因此 outcome=null 的语义是"还没结论"，不是失败。
  - 进度不落库，由 run_components 的真实完成比例推导：
    SUM(CASE WHEN rc.state='completed' THEN 1 ELSE 0 END) / COUNT(*)；
    没有 component 时返回 null（不伪造 0%）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["runs"])

# 原型用 run-0001 这种流水号；平台侧按 created_at 升序计算全局序号，
# 保证同一份数据稳定可预期（不依赖随机或前端拼接）。
_RUNS_SQL = """
    WITH numbered AS (
        SELECT r.*, row_number() OVER (ORDER BY r.created_at, r.id) AS seq
          FROM test_runs r
    )
    SELECT n.id, n.seq, n.state, n.outcome, n.reason_code, n.not_tested_reason,
           n.platform, n.started_at, n.ended_at, n.created_at,
           n.application_id, a.name AS application_name,
           n.revision_id, tr.task_id, tr.test_type,
           t.name AS task_name,
           n.resource_id, er.resource_key AS resource_name
      FROM numbered n
      JOIN applications a ON a.id = n.application_id
      LEFT JOIN task_revisions tr ON tr.id = n.revision_id
      LEFT JOIN test_tasks t ON t.id = tr.task_id
      LEFT JOIN execution_resources er ON er.id = n.resource_id
"""

_COMPONENT_SQL = """
    SELECT rc.run_id,
           count(*) AS component_total,
           count(*) FILTER (WHERE rc.state = 'completed') AS component_completed
      FROM run_components rc
     WHERE rc.run_id = ANY(:run_ids)
     GROUP BY rc.run_id
"""


@router.get("/runs")
async def list_runs(
    scope: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """运行列表。scope 只接受 android / ios / web，其他值 422（与 /resources 一致）。"""
    where: list[str] = []
    params: dict[str, object] = {"limit": limit}

    if scope:
        if scope not in {"android", "ios", "web"}:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=422,
                detail=f"scope 只支持 android / ios / web，收到 {scope!r}",
            )
        where.append("n.platform = :scope")
        params["scope"] = scope
    if state:
        where.append("n.state = :state")
        params["state"] = state

    sql = _RUNS_SQL
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY n.created_at DESC, n.id DESC LIMIT :limit"

    rows = (await session.execute(text(sql), params)).mappings().all()
    run_ids = [row["id"] for row in rows]
    progress: dict[object, float | None] = {}
    if run_ids:
        comp = (await session.execute(text(_COMPONENT_SQL), {"run_ids": run_ids})).mappings().all()
        for c in comp:
            total = c["component_total"] or 0
            progress[c["run_id"]] = (
                round(c["component_completed"] * 100 / total) if total else None
            )

    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "display_id": f"RUN-{row['seq']:04d}",
                "name": row["task_name"] or row["application_name"],
                "task_id": row["task_id"],
                "application": {"id": row["application_id"], "name": row["application_name"]},
                "platform": row["platform"],
                "test_type": row["test_type"],
                "state": row["state"],
                "outcome": row["outcome"],
                "reason_code": row["reason_code"],
                "not_tested_reason": row["not_tested_reason"],
                # 没有 component 记录时返回 null，前端显示"无进度数据"而不是 0%
                "progress": progress.get(row["id"]),
                "resource": row["resource_name"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "created_at": row["created_at"],
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """单次运行的详情骨架：只有主记录与组件进度，证据/门禁在后续阶段接入。"""
    from fastapi import HTTPException

    sql = _RUNS_SQL + " WHERE n.id::text = :run_id"
    row = (await session.execute(text(sql), {"run_id": run_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")

    comp = (
        await session.execute(
            text(
                "SELECT component, state, started_at, ended_at "
                "FROM run_components WHERE run_id = :run_id ORDER BY component"
            ),
            {"run_id": row["id"]},
        )
    ).mappings().all()

    return {
        "id": row["id"],
        "display_id": f"RUN-{row['seq']:04d}",
        "name": row["task_name"] or row["application_name"],
        "task_id": row["task_id"],
        "application": {"id": row["application_id"], "name": row["application_name"]},
        "platform": row["platform"],
        "test_type": row["test_type"],
        "state": row["state"],
        "outcome": row["outcome"],
        "reason_code": row["reason_code"],
        "not_tested_reason": row["not_tested_reason"],
        "resource": row["resource_name"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "components": [
            {
                "component": c["component"],
                "state": c["state"],
                "started_at": c["started_at"],
                "ended_at": c["ended_at"],
            }
            for c in comp
        ],
    }
