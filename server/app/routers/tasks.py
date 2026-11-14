"""任务中心：列表（P1）+ 任务与修订 CRUD（P2）。

表结构真源（勿改）：
  - test_tasks 没有 module 列；测试类型在 task_revisions.test_type（ui/performance/joint）
  - test_runs 没有 progress 列；进度由 run_components + case_results 聚合推导
  - test_tasks 有 lock_version：所有写操作都是 CAS，冲突返回 409 stale_version

分层约定（domain 层之外的纪律）：
  路由层只做 HTTP 语义 —— 解析请求、检查客户端标识头、把 domain 判定翻成错误码；
  SQL 在 app/services/，状态取值在 app/domain/。这里不出现状态字面量。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..dependencies import require_client_header
from ..domain import identity as identity_mod
from ..domain import runs as runs_mod
from ..errors import validation_error
from ..schemas import TaskCreateIn, TaskPatchIn, TaskRevisionListOut, TasksOut
from ..services import tasks as task_service

router = APIRouter(tags=["tasks"])

#: 缺省 actor（created_by 两列都是 NOT NULL）。真实身份接入 P3 的鉴权后再替换。
DEFAULT_ACTOR = "web-client"
#: 幂等键请求头：同一 key + 同一路径的重复提交返回首次结果。
#: 键的持久化在 services/tasks.py（task_request_keys 表，0005 迁移），
#: 不再依赖进程内字典 —— 重启与多进程下都必须复用同一对象（spec §9.1）。
IDEMPOTENCY_HEADER = "Idempotency-Key"


async def _task_scope(session: AsyncSession, task_id: str) -> tuple[str, str]:
    """读取任务所属的 (project_id, application_id)，供归档守卫锁定身份行。"""
    row = (
        await session.execute(
            _text(
                "SELECT t.application_id::text AS aid, a.project_id::text AS pid"
                "  FROM test_tasks t JOIN applications a ON a.id = t.application_id"
                " WHERE t.id::text = :id"
            ),
            {"id": task_id},
        )
    ).mappings().first()
    if row is None:
        from ..errors import not_found

        raise not_found("task", task_id)
    return row["pid"], row["aid"]


# require_client_header 已上移到 app/dependencies.py（P1-04：写操作守卫是
# 全 API 横切约束，不该住在第一个用到它的业务路由里）。本模块经顶部导入
# 继续使用；历史用法 `from .tasks import require_client_header` 仍然可用。


@router.get("/tasks", response_model=TasksOut)
async def list_tasks(
    test_type: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    run_state: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """列表带每个任务最近一次运行与最新 revision 的测试类型。

    state 与 outcome 分开返回：原型把两者挤进一个 status 字段，
    真实系统必须区分（completed 才可能有 outcome，见 schema CHECK）。
    """
    sql = """
        SELECT t.id, t.name, t.lifecycle, t.lock_version, t.application_id,
               a.name AS application_name, a.platform,
               rev.test_type AS test_type, rev.id AS revision_id, rev.readiness,
               r.id AS run_id, r.display_no AS run_display_no,
               r.state AS run_state, r.outcome AS run_outcome,
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
               SELECT r2.id, r2.display_no, r2.state, r2.outcome, r2.created_at, r2.ended_at
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
    if run_state:
        # 工单 20：按**关联运行的 state** 过滤任务（最近一次运行），
        # 不与任务 lifecycle（draft/ready/archived）或修订 readiness 混用。
        if run_state not in runs_mod.ALL_STATES:
            raise validation_error([f"run_state 只支持 {' / '.join(runs_mod.ALL_STATES)}，收到 {run_state!r}"])
        where.append("r.state = :run_state")
        params["run_state"] = run_state
    if q:
        where.append("(t.name ILIKE :q OR t.id::text = :qid)")
        params["q"] = f"%{q}%"
        params["qid"] = q
    if project_id:
        # 工单 05：任务列表跟随当前项目；test_tasks 自带 project_id 列
        where.append("t.project_id::text = :project_id")
        params["project_id"] = project_id
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(r.created_at, t.updated_at) DESC"

    rows = (await session.execute(text(sql), params)).mappings().all()
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                # 有运行的显示运行的持久编号（与运行页、报告同一字符串），
                # 没有运行的显示任务自身编号；两者都不随列表顺序变化。
                "display_id": runs_mod.format_display_id(row["run_display_no"])
                or f"TASK-{row['id']}",
                "name": row["name"],
                "test_type": row["test_type"],
                "lifecycle": row["lifecycle"],
                "lock_version": row["lock_version"],
                "application": {"id": row["application_id"], "name": row["application_name"]},
                "platform": row["platform"],
                "revision_id": row["revision_id"],
                "readiness": row["readiness"],
                "run": {
                    "id": row["run_id"],
                    "display_id": runs_mod.format_display_id(row["run_display_no"]),
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


# --------------------------------------------------------------------------- #
# P2：任务的写操作与详情
# --------------------------------------------------------------------------- #
@router.post("/tasks", status_code=201)
async def create_task(
    body: TaskCreateIn,
    request: Request,
    request_key: Annotated[str | None, Query(description="幂等键；也可用 Idempotency-Key 头")] = None,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """创建任务与第一条 draft 修订。

    两级去重都在 service 内、与建任务同一事务（见 task_service.create_task）：

    1. **请求级幂等**：`?request_key=` 或 `Idempotency-Key` 头声明"这是同一个请求"，
       键绑定规范化创建内容并持久化；同键同内容返回 200 + 原任务，
       同键不同内容 409 idempotency_conflict。
    2. **业务级判重**：同应用同名同内容复用原任务（200）；同名不同配置
       409 task_configuration_conflict，附 existing_task_id 与差异字段名。

    新建返回 201；复用既有对象返回 200。
    """
    key = (request_key or request.headers.get(IDEMPOTENCY_HEADER) or "").strip()
    # 归档守卫（工单 04）：归档范围禁止登记新任务
    await identity_mod.assert_scope_active(
        session, project_id=body.project_id, application_id=body.application_id
    )
    task, duplicate = await task_service.create_task(
        session,
        payload=body.model_dump(),
        created_by=DEFAULT_ACTOR,
        request_key=key or None,
    )
    return _reused(task) if duplicate else task


def _reused(task: dict[str, Any]) -> JSONResponse:
    """去重命中：返回既有任务，用 200 与"真的新建了"的 201 区分开。"""
    return JSONResponse(status_code=200, content=_jsonable(task))


def _jsonable(obj: Any) -> Any:
    """把 datetime / UUID 转成 JSON 可序列化的值（给 JSONResponse 用）。"""
    import datetime as _dt
    import json

    def default(value: Any) -> Any:
        if isinstance(value, (_dt.datetime, _dt.date)):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        raise TypeError(f"无法序列化 {type(value)!r}")

    return json.loads(json.dumps(obj, default=default, ensure_ascii=False))


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """任务详情：任务 + 最新修订 + 最近一次运行。"""
    return await task_service.get_task(session, task_id)


@router.patch("/tasks/{task_id}")
async def patch_task(
    task_id: str,
    body: TaskPatchIn,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """乐观锁更新：lock_version 必须匹配，否则 409 stale_version 且 details 带最新对象。

    成功时不是原地修改，而是**追加一条新修订**（修订不可变），并把 lifecycle 归位到 draft。
    """
    pid, aid = await _task_scope(session, task_id)
    await identity_mod.assert_scope_active(session, project_id=pid, application_id=aid)
    return await task_service.patch_task(
        session,
        task_id=task_id,
        payload=body.model_dump(exclude_unset=False),
        created_by=DEFAULT_ACTOR,
    )


@router.post("/tasks/{task_id}/validate")
async def validate_task(
    task_id: str,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """就绪校验：不满足 422 task_not_ready（details 列出 missing / invalid），满足则写 validated 修订。"""
    pid, aid = await _task_scope(session, task_id)
    await identity_mod.assert_scope_active(session, project_id=pid, application_id=aid)
    return await task_service.validate_task(session, task_id=task_id, created_by=DEFAULT_ACTOR)


@router.post("/tasks/{task_id}/archive")
async def archive_task(
    task_id: str,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """归档（终态）。幂等：重复调用返回同样结果，不报错、不再推进 lock_version。"""
    return await task_service.archive_task(session, task_id=task_id)


@router.get("/tasks/{task_id}/revisions", response_model=TaskRevisionListOut)
async def list_task_revisions(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """修订历史，revision 倒序。"""
    return await task_service.list_revisions(session, task_id)
