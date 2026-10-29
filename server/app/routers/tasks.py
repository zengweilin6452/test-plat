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

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import CLIENT_HEADER, CLIENT_HEADER_VALUE, client_header_required
from ..schemas import TaskCreateIn, TaskPatchIn, TaskRevisionListOut, TasksOut
from ..services import tasks as task_service

router = APIRouter(tags=["tasks"])

#: 缺省 actor（created_by 两列都是 NOT NULL）。真实身份接入 P3 的鉴权后再替换。
DEFAULT_ACTOR = "web-client"
#: 幂等键请求头：同一 key + 同一路径的重复提交返回首次结果
IDEMPOTENCY_HEADER = "Idempotency-Key"
#: 进程内的幂等缓存：{key: (task_id, status_code)}。
#: 之所以不用 DB 表：0001 已经冻结（不能新增表），而 P2 只需覆盖"前端双击提交"这个窗口。
#: 单进程 uvicorn 下足够；横向扩容前必须迁到 DB 或 Redis（已在 docstring 里标注）。
_IDEMPOTENT_TASKS: dict[str, str] = {}


def require_client_header(
    x_testdock_client: Annotated[str | None, Header(alias=CLIENT_HEADER)] = None,
) -> str:
    """写操作必须带 X-TestDock-Client: web（development-plan.md §8.1 防跨站表单）。

    缺失时 428 Precondition Required 而不是 403：这是"缺少前置条件"，
    不是"认证失败"，语义上更准确，也避免前端把它当成登录问题去跳登录页。
    """
    if x_testdock_client is None:
        raise client_header_required()
    if x_testdock_client.strip().lower() != CLIENT_HEADER_VALUE:
        raise client_header_required()
    return x_testdock_client.strip()


@router.get("/tasks", response_model=TasksOut)
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
        SELECT t.id, t.name, t.lifecycle, t.lock_version, t.application_id,
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
                "lock_version": row["lock_version"],
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

    两级去重，都在返回 200（而不是 201）+ 既有任务：

    1. **请求级幂等**：客户端用 `?request_key=` 或 `Idempotency-Key` 头声明
       "这是同一个请求的重发"。DB 里没有可写的幂等表（0001 已冻结），
       所以用一个进程内表记首次创建的 task_id；单进程 uvicorn 足够，
       横向扩容前必须迁到 DB 或 Redis。
    2. **业务级判重**：同一 `application_id` 下同名且未归档的任务直接返回既有的那条。
       前端双击、浏览器重试、用户从列表再提交一次，都不该多出一条任务
       （每建一次任务就多一条修订，重复会污染时间线）。归档过的同名任务另算：
       允许再建，所以查询只认未归档的那些。
    """
    key = (request_key or request.headers.get(IDEMPOTENCY_HEADER) or "").strip()
    if key:
        existing_id = _IDEMPOTENT_TASKS.get(key)
        if existing_id:
            task = await task_service.get_task(session, existing_id)
            return _reused(task)

    if body.application_id and body.name:
        existing_id = await task_service.find_task_by_name(
            session, application_id=body.application_id, name=body.name
        )
        if existing_id:
            task = await task_service.get_task(session, existing_id)
            if key:
                _IDEMPOTENT_TASKS[key] = task["id"]
            return _reused(task)

    task = await task_service.create_task(
        session,
        payload=body.model_dump(),
        created_by=DEFAULT_ACTOR,
    )
    if key:
        _IDEMPOTENT_TASKS[key] = task["id"]
    return task


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
