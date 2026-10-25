"""任务中心：GET /tasks（列表）。任务 CRUD 在 P2。

注意表结构真源：
  - test_tasks 没有 module 列；试模块归属在 task_revisions.test_type
    （ui / perf / joint 由 revision 上的适配器与配置表达）
  - test_runs 没有 progress 列；进度由 run_components + case_results 聚合推导
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session

router = APIRouter(tags=["tasks"])


@router.get("/tasks")
async def list_tasks(
    test_type: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """列表带每个任务最近一次运行与最新 revision 的测试类型。

    state 与 outcome 分开返回：原型把两者挤进一个 status 字段，
    真实系统必须区分（completed 才可能有 outcome，见 schema CHECK）。
    """
    sql = """
        SELECT t.id, t.name, t.lifecycle, t.application_id,
               a.name AS application_name, a.platform,
               rev.test_type AS test_type, rev.id AS revision_id, rev.readiness,
               r.id AS run_id, r.state AS run_state, r.outcome AS run_outcome,
               r.created_at AS run_created_at, r.ended_at AS run_ended_at,
               (SELECT count(*) FROM task_revisions tr2 WHERE tr2.task_id = t.id) AS revision_count,
               (SELECT count(*) FROM run_components rc WHERE rc.run_id = r.id) AS component_total
          FROM test_tasks t
          JOIN applications a ON a.id = t.application_id
          LEFT JOIN LATERAL (
               SELECT tr.id, tr.test_type, tr.readiness
                 FROM task_revisions tr
                WHERE tr.task_id = t.id
                ORDER BY tr.revision DESC
                LIMIT 1
          ) rev ON TRUE
          LEFT JOIN LATERAL (
               SELECT r2.id, r2.state, r2.outcome, r2.created_at, r2.ended_at
                 FROM test_runs r2
                 JOIN task_revisions tr3 ON tr3.id = r2.revision_id
                WHERE tr3.task_id = t.id
                ORDER BY r2.created_at DESC
                LIMIT 1
          ) r ON TRUE
    """
    where: list[str] = []
    params: dict[str, object] = {}
    if test_type:
        where.append("rev.test_type = :test_type")
        params["test_type"] = test_type
    if q:
        where.append("(t.name ILIKE :q OR t.id::text = :qid)")
        params["q"] = f"%{q}%"
        params["qid"] = q
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(r.created_at, t.updated_at) DESC"

    rows = (await session.execute(text(sql), params)).mappings().all()
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "display_id": f"RUN-{row['run_id']}" if row["run_id"] else f"TASK-{row['id']}",
                "name": row["name"],
                "test_type": row["test_type"],
                "lifecycle": row["lifecycle"],
                "application": {"id": row["application_id"], "name": row["application_name"]},
                "platform": row["platform"],
                "revision_id": row["revision_id"],
                "readiness": row["readiness"],
                "run": {
                    "id": row["run_id"],
                    "state": row["run_state"],
                    "outcome": row["run_outcome"],
                    "created_at": row["run_created_at"],
                    "ended_at": row["run_ended_at"],
                    "component_total": row["component_total"],
                }
                if row["run_id"]
                else None,
                "revision_count": row["revision_count"],
            }
        )
    return {"items": items, "total": len(items)}
