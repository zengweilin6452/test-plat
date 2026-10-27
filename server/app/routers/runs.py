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

import json
import re
import shutil
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..domain import artifacts as artifacts_mod
from ..domain import events as events_mod
from ..domain import runs as runs_mod
from ..errors import device_not_ready, not_found, readiness_incomplete, state_conflict, validation_error
from ..ws import hub as hub_mod

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

    # 0001_initial.py 的 run_components 列名是 kind（不是 component），
    # 且只有 created_at，没有 started_at/ended_at——查不存在的列会让
    # 详情接口直接 500。组件级时间线以 created_at 为准。
    comp = (
        await session.execute(
            text(
                "SELECT kind, state, outcome, created_at "
                "FROM run_components WHERE run_id = :run_id ORDER BY kind"
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
                "component": c["kind"],
                "kind": c["kind"],
                "state": c["state"],
                "outcome": c["outcome"],
                "created_at": c["created_at"],
            }
            for c in comp
        ],
    }


# ---------------------------------------------------------------------------
# P3：运行生命周期 / 证据 / 报告 / 导入（development-plan.md §7、§8.2、§10、§11）
#
# 纪律：
#   * 路由层**不直接写 state**，所有状态迁移只走 domain/runs.transition()。
#   * request_key 幂等由 UNIQUE(project_id, request_key) 兜底；并发插入冲突时
#     回滚并重查，返回既有 run（用户连点两次提交不能变成 500）。
#   * POST /runs/import 是刻意的降级通道：把已有 vendor 产物目录补录成 run，
#     走**同一套** finalize（扫描 + sha256 登记 + junit 推导 outcome），
#     只是报告里 mode=imported，避免导入数据与真跑数据两套可信度。
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_PLATFORMS = ("android", "ios", "web")


def _is_uuid(value: object) -> bool:
    return bool(_UUID_RE.match(str(value or "")))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def _project_of(session: AsyncSession, run_id: str) -> str:
    row = (
        await session.execute(text("SELECT project_id FROM test_runs WHERE id::text = :id"), {"id": str(run_id)})
    ).scalar_one_or_none()
    if row is None:
        raise not_found("run", str(run_id))
    return str(row)


async def _pick_application(
    session: AsyncSession, application_id: str | None, platform: str
) -> dict:
    """给了 application_id 就用它，否则取该平台最早创建且未归档的应用。"""
    if application_id:
        row = (
            await session.execute(
                text("SELECT id, project_id, platform, name FROM applications "
                     "WHERE id::text = :aid AND platform = :platform AND archived_at IS NULL"),
                {"aid": str(application_id), "platform": platform},
            )
        ).mappings().first()
        if row is None:
            raise not_found("application", str(application_id))
        return dict(row)
    row = (
        await session.execute(
            text(
                "SELECT id, project_id, platform, name FROM applications "
                "WHERE platform = :platform AND archived_at IS NULL "
                "ORDER BY created_at, id LIMIT 1"
            ),
            {"platform": platform},
        )
    ).mappings().first()
    if row is None:
        raise validation_error(["找不到可用应用，请显式提供 application_id"])
    return dict(row)


async def _resolve_revision(
    session: AsyncSession, *, task_id: str | None, revision_id: str | None,
    project_id: str, application_id: str
) -> str:
    """只引用所选应用下真实存在的修订，不合成悬空外键。"""
    if not revision_id and not task_id:
        raise readiness_incomplete(["task_id 或 revision_id"])
    got = (
        await session.execute(
            text(
                "SELECT tr.id FROM task_revisions tr "
                "JOIN test_tasks t ON t.id = tr.task_id "
                "WHERE t.project_id = :pid AND t.application_id = :aid "
                "AND (CAST(:rid AS text) IS NULL OR tr.id::text = :rid) "
                "AND (CAST(:tid AS text) IS NULL OR t.id::text = :tid) "
                "ORDER BY tr.revision DESC LIMIT 1"
            ),
            {"pid": project_id, "aid": application_id,
             "rid": str(revision_id) if revision_id else None,
             "tid": str(task_id) if task_id else None},
        )
    ).scalar_one_or_none()
    if got is None:
        raise not_found("revision" if revision_id else "task", str(revision_id or task_id))
    return str(got)


async def _insert_run(session: AsyncSession, body: Mapping) -> dict:
    """插入 queued run；request_key 重复则返回既有 run（created=False）。"""
    request_key = str(body.get("request_key") or "").strip()
    if not request_key:
        raise validation_error(["request_key 必填（幂等去重键）"])
    if len(request_key) > 200:
        raise validation_error(["request_key 过长（<=200）"])

    platform = str(body.get("platform") or "android")
    if platform not in _PLATFORMS:
        raise validation_error(["platform 只支持 android / ios / web"])

    application = await _pick_application(session, body.get("application_id"), platform)
    project_id = str(application["project_id"])
    application_id = str(application["id"])

    existing = (
        await session.execute(
            text("SELECT id FROM test_runs WHERE project_id = :pid AND request_key = :rk"),
            {"pid": project_id, "rk": request_key},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"id": str(existing), "created": False, "project_id": project_id}

    revision_id = await _resolve_revision(
        session,
        task_id=body.get("task_id"),
        revision_id=body.get("revision_id"),
        project_id=project_id,
        application_id=application_id,
    )

    revision = (
        await session.execute(
            text("SELECT config, test_type FROM task_revisions WHERE id = :id"),
            {"id": revision_id},
        )
    ).mappings().one()
    revision_config = dict(revision["config"] or {})
    overrides = body.get("overrides") or {}
    if not isinstance(overrides, Mapping):
        raise validation_error(["overrides 必须是对象"])
    device = body.get("device") if "device" in body else revision_config.get("device")
    device = device or {}
    if not isinstance(device, Mapping):
        raise validation_error(["device 必须是对象"])
    resource_id = device.get("resource_id")
    if resource_id is not None and not _is_uuid(resource_id):
        raise validation_error(["device.resource_id 必须是 uuid"])
    importing = str(body.get("source") or "") == "import"
    if importing and not resource_id:
        # completed 行受 ck_test_runs_state_executing_needs_resource 约束：没有资源
        # 就插不进去。导入通道不派发，但必须显式指明这批产物来自哪台设备。
        raise validation_error(["导入需要 device.resource_id（completed 运行必须绑定执行资源）"])
    resource_profile_id = None
    if resource_id:
        resource = (
            await session.execute(
                text("SELECT status, profile_id FROM execution_resources "
                     "WHERE id = :rid AND project_id = :pid AND platform = :platform"),
                {"rid": resource_id, "pid": project_id, "platform": platform},
            )
        ).mappings().first()
        if resource is None:
            raise not_found("resource", str(resource_id))
        # 导入通道不派发、不占租约，产物可能来自一台此刻已离线的设备，
        # 所以只要求资源真实存在且属于本项目；真跑仍要求 ready。
        if not importing and resource["status"] != "ready":
            raise device_not_ready(str(resource_id), resource["status"])
        resource_profile_id = resource["profile_id"]

    snapshot = {
        **revision_config,
        "request_key": request_key,
        "platform": platform,
        "application_id": application_id,
        "module": "perf" if revision["test_type"] == "performance" else revision["test_type"],
        "overrides": dict(overrides),
        "requested_resource_id": resource_id,
        "source": str(body.get("source") or "api"),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.get("source_dir"):
        snapshot["source_dir"] = str(body["source_dir"])
    paths = body.get("test_paths")
    if paths:
        snapshot["test_paths"] = [str(p) for p in paths]
    if body.get("fake_outcome"):
        snapshot["fake_outcome"] = str(body["fake_outcome"])

    row = (
        await session.execute(
            text(
                "INSERT INTO test_runs ("
                "  id, project_id, application_id, platform, revision_id, parent_run_id,"
                "  request_key, state, config_snapshot, created_by, resource_id, profile_id"
                ") VALUES ("
                "  :id, :project_id, :application_id, :platform, :revision_id, :parent_run_id,"
                "  :request_key, 'queued', CAST(:config AS jsonb), :created_by,"
                "  :resource_id, :profile_id"
                ") ON CONFLICT (project_id, request_key) DO NOTHING RETURNING id, state"
            ),
            {
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "application_id": application_id,
                "platform": platform,
                "revision_id": revision_id,
                "parent_run_id": body.get("parent_run_id"),
                "request_key": request_key,
                "config": _json(snapshot),
                "created_by": str(body.get("created_by") or "web"),
                # 导入通道没有调度器去绑定设备，必须在插入时就写死资源与档案；
                # 真跑仍留空，由 dispatcher 领取租约时绑定（resource/profile 成对）。
                "resource_id": resource_id if importing else None,
                "profile_id": resource_profile_id if importing else None,
            },
        )
    ).mappings().first()
    if row is None:
        existing = (
            await session.execute(
                text("SELECT id FROM test_runs WHERE project_id = :pid AND request_key = :rk"),
                {"pid": project_id, "rk": request_key},
            )
        ).scalar_one()
        return {"id": str(existing), "created": False, "project_id": project_id}

    run_id = str(row["id"])
    await events_mod.append_event(
        session,
        project_id=project_id,
        run_id=run_id,
        source_key=events_mod.SOURCE_API,
        source_event_id="created",
        event_type="queued",
        payload={"source": snapshot["source"], "request_key": request_key},
    )
    return {
        "id": run_id,
        "created": True,
        "project_id": project_id,
        "state": str(row["state"]),
    }


async def _display_id(session: AsyncSession, run_id: str) -> str:
    """全局序号：按 (created_at, id) 升序的排名，与列表页 RUN-0001 口径一致。"""
    seq = (
        await session.execute(
            text(
                "SELECT count(*) FROM test_runs r2 "
                "WHERE (r2.created_at, r2.id) <= "
                "      (SELECT r3.created_at, r3.id FROM test_runs r3 WHERE r3.id::text = :id)"
            ),
            {"id": str(run_id)},
        )
    ).scalar_one()
    return "RUN-%04d" % int(seq or 0)


async def _run_view(session: AsyncSession, run_id: str) -> dict:
    """run 单条视图：详情、WS 快照、报告都复用它，避免三处口径不一致。

    progress 由 run_events 的阶段权重推导（domain/events.compute_progress），
    stage 再按 api-design.md 的阈值换算，因此刷新页面不会丢进度。
    """
    row = (
        await session.execute(
            text(
                "SELECT r.id, r.project_id, r.application_id, r.platform, r.revision_id,"
                "       r.state, r.outcome, r.reason_code, r.not_tested_reason,"
                "       r.resource_id, r.parent_run_id, r.request_key,"
                "       r.started_at, r.ended_at, r.created_at, r.config_snapshot,"
                "       a.name AS application_name, tr.task_id, tr.test_type,"
                "       t.name AS task_name, er.resource_key AS resource_name"
                "  FROM test_runs r"
                "  JOIN applications a ON a.id = r.application_id"
                "  LEFT JOIN task_revisions tr ON tr.id = r.revision_id"
                "  LEFT JOIN test_tasks t ON t.id = tr.task_id"
                "  LEFT JOIN execution_resources er ON er.id = r.resource_id"
                " WHERE r.id::text = :id"
            ),
            {"id": str(run_id)},
        )
    ).mappings().first()
    if row is None:
        raise not_found("run", str(run_id))
    project_id = str(row["project_id"])
    events = await events_mod.list_events(
        session, project_id=project_id, run_id=str(run_id), limit=500
    )
    progress = events_mod.compute_progress(events)
    terminal = runs_mod.is_terminal(str(row["state"]))
    stage = events_mod.stage_number(progress, terminal=terminal)
    cancel_requested = any(e.get("event_type") == "cancel_requested" for e in events)
    duration_s = None
    if row["started_at"] and row["ended_at"]:
        duration_s = int((row["ended_at"] - row["started_at"]).total_seconds())
    snapshot = row["config_snapshot"] or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    return {
        "id": str(row["id"]),
        "display_id": await _display_id(session, str(run_id)),
        "name": row["task_name"] or row["application_name"],
        "task_id": str(row["task_id"]) if row["task_id"] else None,
        "application": {"id": str(row["application_id"]), "name": row["application_name"]},
        "application_id": str(row["application_id"]),
        "project_id": project_id,
        "platform": row["platform"],
        "test_type": row["test_type"],
        "module": snapshot.get("module") or row["test_type"] or "ui",
        "revision_id": str(row["revision_id"]) if row["revision_id"] else None,
        "state": row["state"],
        "outcome": row["outcome"],
        "reason_code": row["reason_code"],
        "not_tested_reason": row["not_tested_reason"],
        "resource_id": str(row["resource_id"]) if row["resource_id"] else None,
        "resource_name": row["resource_name"],
        "resource": row["resource_name"],
        "progress": progress,
        "stage": stage,
        "cancel_requested": cancel_requested,
        "parent_run_id": str(row["parent_run_id"]) if row["parent_run_id"] else None,
        "request_key": row["request_key"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "duration_s": duration_s,
        "config_snapshot": snapshot,
    }


@router.post("/runs", status_code=201)
async def create_run(
    body: dict = Body(default_factory=dict), session: AsyncSession = Depends(get_session)
):
    """创建 run（queued）。重复 request_key 返回 200 + 既有 run（api-design.md §1.3）。"""
    created = await _insert_run(session, body)
    run_id = str(created["id"])
    view = await _run_view(session, run_id)
    if not created["created"]:
        return JSONResponse(
            status_code=200,
            content={
                "id": run_id,
                "display_id": view["display_id"],
                "state": view["state"],
                "outcome": view["outcome"],
                "duplicate": True,
            },
        )
    hub_mod.publish(
        run_id,
        {"type": "state", "state": view["state"], "progress": 0, "stage": 1, "at": None},
    )
    return JSONResponse(
        status_code=201,
        content={"id": run_id, "display_id": view["display_id"], "state": view["state"]},
    )


@router.get("/runs/{run_id}/events")
async def list_run_events(
    run_id: str,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """run_events 增量拉取：WS 断线重连、刷新后补进度都靠它。"""
    project_id = await _project_of(session, run_id)
    items = await events_mod.list_events(
        session, project_id=project_id, run_id=str(run_id), after_sequence=after, limit=limit
    )
    return {"items": items, "total": len(items), "after": after}


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """取消 run。

    queued 直接 cancelled（还没占设备，迁移即可）。执行中的只登记 cancel_requested
    事件：真正落地必须由 runner 收到 heartbeat.cancel 后停设备、放 vendor 锁，API 再
    释放 DB 租约（§7.1 释放顺序）；reconciler 负责清理卡死的执行态。
    """
    project_id = await _project_of(session, run_id)
    state = str(
        (
            await session.execute(
                text("SELECT state FROM test_runs WHERE id::text = :id"), {"id": str(run_id)}
            )
        ).scalar_one()
    )
    if runs_mod.is_terminal(state):
        raise state_conflict(run_id, state, "non_terminal")
    await events_mod.append_event(
        session,
        project_id=project_id,
        run_id=str(run_id),
        source_key=events_mod.SOURCE_CONTROL,
        source_event_id="cancel",
        event_type="cancel_requested",
        payload={"requested_by": "web", "from_state": state},
    )
    if state == runs_mod.STATE_QUEUED:
        await runs_mod.transition(
            session,
            str(run_id),
            runs_mod.STATE_QUEUED,
            runs_mod.STATE_CANCELLED,
            reason="cancel_requested",
            actor="web",
        )
    current = str(
        (
            await session.execute(
                text("SELECT state FROM test_runs WHERE id::text = :id"), {"id": str(run_id)}
            )
        ).scalar_one()
    )
    if runs_mod.is_terminal(current):
        hub_mod.publish(str(run_id), {"type": "finished", "state": current, "outcome": None});
    else:
        hub_mod.publish(
            str(run_id),
            {"type": "event", "kind": "cancel_requested", "name": None, "at": None},
        )
    return {"id": str(run_id), "state": current, "cancel_requested": True}


@router.get("/runs/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    """证据清单。download_url 由平台拼，前端不自己拼路径。"""
    project_id = await _project_of(session, run_id)
    items = await artifacts_mod.list_artifacts(
        session, project_id=project_id, run_id=str(run_id)
    )
    for item in items:
        item["download_url"] = "/api/v1/runs/%s/artifacts/%s/download" % (
            run_id,
            item["id"],
        )
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}/artifacts/{artifact_id}/download")
async def download_run_artifact(
    run_id: str, artifact_id: str, session: AsyncSession = Depends(get_session)
):
    project_id = await _project_of(session, run_id)
    artifact = await artifacts_mod.get_artifact(
        session, project_id=project_id, run_id=str(run_id), artifact_id=str(artifact_id)
    )
    if artifact.get("availability") != "available":
        raise not_found("artifact", str(artifact_id))
    path = artifacts_mod.resolve_storage_path(str(artifact["storage_key"]))
    if not path.is_file():
        raise not_found("artifact", str(artifact_id))
    return FileResponse(
        str(path),
        media_type=str(artifact.get("mime_type") or "application/octet-stream"),
        filename=Path(str(artifact["logical_key"])).name,
    )


@router.get("/runs/{run_id}/report")
async def get_run_report(
    run_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    """平台计算的报告（不是 vendor 报告原样透传）。"""
    from .. import runtime as runtime_mod

    view = await _run_view(session, run_id)
    items = await artifacts_mod.list_artifacts(
        session, project_id=str(view["project_id"]), run_id=str(run_id)
    )
    vendor_reports = [
        {"kind": item["kind"], "artifact_id": item["id"]}
        for item in items
        if item["kind"] in ("report_json", "report_html", "log")
    ]
    source = await runtime_mod.read_report_source(str(run_id)) or {}
    snapshot = view["config_snapshot"] or {}
    mode = "imported" if snapshot.get("source") == "import" else "live"
    return {
        "runId": view["id"],
        "hostRunId": view["request_key"],
        "name": view["name"],
        "projectId": view["project_id"],
        "applicationId": view["application_id"],
        "platform": view["platform"],
        "environmentId": None,
        "resourceId": view["resource_id"],
        "module": view["module"],
        "status": view["state"],
        "verdict": view["outcome"],
        "target": view["application"],
        "deviceProfile": view["resource_name"],
        "durationS": view["duration_s"],
        "metricsSummary": source.get("metricsSummary") or {},
        "thresholdsAtRun": source.get("thresholdsAtRun") or {},
        "reason": view["reason_code"],
        "reasonText": view["not_tested_reason"] or view["reason_code"],
        "evaluatedAt": view["ended_at"],
        "mode": source.get("mode") or mode,
        "vendorReports": vendor_reports,
        "junit": source.get("junit") or {},
    }


def _import_artifacts_dir(run_id: str, source: Path) -> Path:
    """把外部 vendor 产物目录复制到受管产物目录，返回复制后的路径。

    为什么必须复制：artifacts.storage_key 是相对 settings.artifacts_dir 的路径，
    下载端点与 GET /report 都按这个根反查。直接登记外部绝对路径会让 storage_key
    退化成裸文件名（storage_key_for 的兜底），读回来永远是"文件不存在"。
    复制而不是移动：源目录是用户的既有证据，导入是只读补录，不能改它。
    """
    target = Path(settings.artifacts_dir) / str(run_id)
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
    return target


@router.post("/runs/import", status_code=201)
async def import_run(
    body: dict = Body(default_factory=dict), session: AsyncSession = Depends(get_session)
):
    """降级通道：导入已有 vendor 产物目录（report.json / junit.xml / evidence/**）。

    与真跑**共用** runtime.finalize_run：同样扫描目录、同样登记 sha256、同样由 junit
    推导 outcome。差别只在于没有 runner 与设备，所以不占租约，报告 mode=imported。
    """
    source_dir = str(body.get("source_dir") or "").strip()
    if not source_dir:
        raise validation_error(["source_dir 必填（已有 vendor 产物目录）"])
    path = Path(source_dir)
    if not path.is_dir():
        raise validation_error(["source_dir 不存在或不是目录: %s" % source_dir])

    payload = dict(body)
    payload["source"] = "import"
    created = await _insert_run(session, payload)
    await session.commit()
    run_id = str(created["id"])
    project_id = str(created["project_id"])

    from .. import runtime as runtime_mod

    # 产物必须搬进受管目录：下载端点与 GET /report 都只按 settings.artifacts_dir
    # 反查 storage_key，登记一个外部绝对路径等于登记了永远读不到的行。
    imported_dir = _import_artifacts_dir(run_id, path)
    result = await runtime_mod.finalize_run(
        run_id=run_id,
        state=runs_mod.STATE_COMPLETED,
        outcome=None,
        reason="imported",
        project_id=project_id,
        artifacts_dir=imported_dir,
        release_lease_reason="imported",
        actor="import",
    )
    # 上面 commit 之后请求级事务已经关闭（get_session 用 session.begin() 包住），
    # 不能在同一个 session 上再发查询；视图改用一个新会话读。
    from ..db import get_sessionmaker

    async with get_sessionmaker()() as view_session:
        view = await _run_view(view_session, run_id)
    return JSONResponse(
        status_code=200 if not created["created"] else 201,
        content={
            "id": run_id,
            "display_id": view["display_id"],
            "state": result.state,
            "outcome": result.outcome,
            "artifacts": result.artifact_count,
            "sha256": result.sha256s,
            "duplicate": not created["created"],
        },
    )


__all__ = ["router"]
