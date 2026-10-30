"""任务与修订的持久化操作。

约定
----
- 所有 SQL 都用 text() + 命名参数（与 P1 只读路由风格一致，表名以 0001 真源为准）。
- 事务边界在 server/app/db.py 的 get_session()（一个请求一个事务）；本模块只发 SQL，
  不 commit，所以"改任务 + 追加修订"天然原子。
- 状态值一律来自 app.domain.task，本模块**不硬编码** 'draft' / 'ready' / 'archived'。
- 修订不可变：全模块只有 INSERT INTO task_revisions，不存在 UPDATE task_revisions。

几个列为什么这样处理（都以 0001_initial.py 为准）
--------------------------------------------------
- task_revisions.environment_id NOT NULL：业务请求体里没有这个概念，缺省回落到
  项目下最早的 environment；项目下一个都没有时明确 400（伪造 UUID 会撞外键）。
- test_tasks.created_by / task_revisions.created_by NOT NULL：取请求头推导的 actor。
- 每条跨列外键都带 project_id/application_id，所以插入前必须校验归属，
  否则 PG 会抛 23503，前端看到的是 500。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from psycopg.types.json import Jsonb
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import suite as suite_domain
from ..domain import task as task_domain
from ..errors import conflict, not_found, stale_version, validation_error
from ..schemas import TaskRevisionListOut, TaskRevisionRecord

#: 任务详情/列表共用投影：任务 + 应用（拿平台）
_SELECT_TASK = """
    SELECT t.id, t.project_id, t.application_id, t.name, t.lifecycle, t.lock_version,
           t.created_by, t.created_at, t.updated_at,
           a.name AS application_name, a.platform AS application_platform
      FROM test_tasks t
      JOIN applications a ON a.id = t.application_id AND a.project_id = t.project_id
     WHERE t.id = :tid
"""

#: 最新修订（LATERAL 语义由 ORDER BY revision DESC LIMIT 1 表达）
_SELECT_LATEST_REVISION = """
    SELECT tr.id, tr.task_id, tr.revision, tr.test_type, tr.readiness,
           tr.build_id, tr.suite_version_id, tr.environment_id, tr.config,
           tr.created_by, tr.created_at
      FROM task_revisions tr
     WHERE tr.task_id = :tid
     ORDER BY tr.revision DESC
     LIMIT 1
"""

#: 最近一次运行：test_runs 没有 task_id，必须经 revision_id 回连到任务
_SELECT_LATEST_RUN = """
    SELECT r.id, r.state, r.outcome, r.reason_code, r.not_tested_reason,
           r.started_at, r.ended_at, r.created_at
      FROM test_runs r
      JOIN task_revisions tr2 ON tr2.id = r.revision_id
     WHERE tr2.task_id = :tid
     ORDER BY r.created_at DESC, r.id DESC
     LIMIT 1
"""


def as_uuid(value: Any) -> str | None:
    """规范成 UUID 文本；非法值返回 None（调用方报 400，而不是让 PG 抛 22P02）。"""
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _revision_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "task_id": str(row["task_id"]),
        "revision": row["revision"],
        "test_type": row["test_type"],
        "readiness": row["readiness"],
        "build_id": str(row["build_id"]) if row["build_id"] else None,
        "suite_version_id": str(row["suite_version_id"]) if row["suite_version_id"] else None,
        "environment_id": str(row["environment_id"]) if row["environment_id"] else None,
        "config": row["config"] or {},
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


def _run_dict(row: Any) -> dict[str, Any] | None:
    if row is None or row["id"] is None:
        return None
    return {
        "id": str(row["id"]),
        "state": row["state"],
        "outcome": row["outcome"],
        "reason_code": row["reason_code"],
        "not_tested_reason": row["not_tested_reason"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "created_at": row["created_at"],
    }


def _task_dict(
    task_row: Any,
    rev_row: Any,
    run_row: Any,
    revision_count: int,
    *,
    case_count: int | None = None,
) -> dict[str, Any]:
    """任务视图。

    case_count 只在 validate 后回填（详情态需要它显示"套件里有几条用例"），
    列表态不查（避免 N+1）。
    """
    return {
        "id": str(task_row["id"]),
        "display_id": f"TASK-{task_row['id']}",
        "project_id": str(task_row["project_id"]),
        "name": task_row["name"],
        "lifecycle": task_row["lifecycle"],
        "lock_version": task_row["lock_version"],
        "created_by": task_row["created_by"],
        "created_at": task_row["created_at"],
        "updated_at": task_row["updated_at"],
        "application": {
            "id": str(task_row["application_id"]),
            "name": task_row["application_name"],
            "platform": task_row["application_platform"],
        },
        "platform": task_row["application_platform"],
        "test_type": rev_row["test_type"] if rev_row is not None else None,
        "revision": _revision_dict(rev_row),
        "readiness": rev_row["readiness"] if rev_row is not None else None,
        "revision_count": revision_count,
        "case_count": case_count,
        "run": _run_dict(run_row),
    }


async def _load_application(session: AsyncSession, application_id: str) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT id, project_id, platform, name, identifier, archived_at "
                "FROM applications WHERE id = :aid"
            ),
            {"aid": application_id},
        )
    ).mappings().first()
    if row is None:
        raise not_found("application", application_id)
    return row


async def _resolve_environment(
    session: AsyncSession, project_id: str, environment_id: str | None
) -> str:
    """task_revisions.environment_id 是 NOT NULL，缺省回落到项目最早的 environment。"""
    if environment_id:
        eid = as_uuid(environment_id)
        if eid is None:
            raise validation_error([f"environment_id 不是合法 UUID：{environment_id!r}"])
        row = (
            await session.execute(
                text("SELECT id FROM environments WHERE project_id = :pid AND id = :eid"),
                {"pid": project_id, "eid": eid},
            )
        ).first()
        if row is None:
            raise validation_error([f"environment_id {environment_id} 不属于该项目"])
        return eid

    row = (
        await session.execute(
            text(
                "SELECT id FROM environments WHERE project_id = :pid AND archived_at IS NULL "
                "ORDER BY created_at, id LIMIT 1"
            ),
            {"pid": project_id},
        )
    ).first()
    if row is None:
        raise validation_error(
            ["项目下没有任何 environment，无法创建修订（task_revisions.environment_id 为 NOT NULL）"]
        )
    return str(row[0])


async def _check_build(
    session: AsyncSession, project_id: str, application_id: str, build_id: str | None
) -> str | None:
    if not build_id:
        return None
    bid = as_uuid(build_id)
    if bid is None:
        raise validation_error([f"build_id 不是合法 UUID：{build_id!r}"])
    row = (
        await session.execute(
            text(
                "SELECT id FROM app_builds "
                "WHERE project_id = :pid AND application_id = :aid AND id = :bid"
            ),
            {"pid": project_id, "aid": application_id, "bid": bid},
        )
    ).first()
    if row is None:
        raise validation_error([f"build_id {build_id} 不属于该应用"])
    return bid


async def _check_suite_version(
    session: AsyncSession, project_id: str, application_id: str, sv_id: str | None
) -> Any:
    """返回 suite_versions 行（含 manifest）；None 表示未绑定。"""
    if not sv_id:
        return None
    sid = as_uuid(sv_id)
    if sid is None:
        raise validation_error([f"suite_version_id 不是合法 UUID：{sv_id!r}"])
    return (
        await session.execute(
            text(
                "SELECT sv.id, sv.suite_id, sv.version, sv.source_ref, sv.source_commit, "
                "       sv.manifest, sv.created_at, s.test_type AS suite_test_type "
                "  FROM suite_versions sv "
                "  JOIN test_suites s ON s.id = sv.suite_id "
                " WHERE sv.project_id = :pid AND sv.application_id = :aid AND sv.id = :sid"
            ),
            {"pid": project_id, "aid": application_id, "sid": sid},
        )
    ).mappings().first()


async def _next_revision_no(session: AsyncSession, project_id: str, task_id: str) -> int:
    row = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(revision), 0) FROM task_revisions "
                "WHERE project_id = :pid AND task_id = :tid"
            ),
            {"pid": project_id, "tid": task_id},
        )
    ).first()
    return int(row[0] or 0) + 1


async def _insert_revision(
    session: AsyncSession,
    *,
    project_id: str,
    application_id: str,
    task_id: str,
    environment_id: str,
    build_id: str | None,
    suite_version_id: str | None,
    test_type: str,
    readiness: str,
    config: dict[str, Any],
    created_by: str,
) -> str:
    """追加一条修订（唯一写修订的入口）。revision 序号由 MAX+1 在事务内计算。"""
    revision_no = await _next_revision_no(session, project_id, task_id)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO task_revisions
                    (id, project_id, application_id, task_id, revision, environment_id,
                     build_id, suite_version_id, test_type, readiness, config, created_by)
                VALUES
                    (:id, :pid, :aid, :tid, :rev, :eid, :bid, :svid, :tt, :rd, :cfg, :by)
                RETURNING id
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": project_id,
                "aid": application_id,
                "tid": task_id,
                "rev": revision_no,
                "eid": environment_id,
                "bid": build_id,
                "svid": suite_version_id,
                "tt": test_type,
                "rd": readiness,
                # text() 不走 SQLAlchemy 的 JSONB 类型绑定，必须用 psycopg 的 Jsonb 显式适配，
                # 否则 dict 会被当成行构造器而报 "cannot adapt type 'dict'"。
                "cfg": Jsonb(config),
                "by": created_by,
            },
        )
    ).first()
    if row is None:  # pragma: no cover - RETURNING 必然有行
        raise RuntimeError("插入 task_revisions 未返回 id")
    return str(row[0])


async def _fetch_task_bundle(
    session: AsyncSession, task_id: str, *, for_update: bool = False
) -> dict[str, Any] | None:
    """一次取回 任务 + 最新修订 + 最近 run + 修订总数（不存在返回 None）。"""
    sql = _SELECT_TASK + (" FOR UPDATE OF t" if for_update else "")
    row = (await session.execute(text(sql), {"tid": task_id})).mappings().first()
    if row is None:
        return None
    rev = (await session.execute(text(_SELECT_LATEST_REVISION), {"tid": task_id})).mappings().first()
    run = (await session.execute(text(_SELECT_LATEST_RUN), {"tid": task_id})).mappings().first()
    count = (
        await session.execute(text("SELECT count(*) FROM task_revisions WHERE task_id = :tid"), {"tid": task_id})
    ).scalar_one()
    return _task_dict(row, rev, run, int(count))


def _task_id_or_404(task_id: str) -> str:
    tid = as_uuid(task_id)
    if tid is None:
        raise not_found("task", str(task_id))
    return tid


async def get_task(session: AsyncSession, task_id: str) -> dict[str, Any]:
    tid = _task_id_or_404(task_id)
    bundle = await _fetch_task_bundle(session, tid)
    if bundle is None:
        raise not_found("task", str(task_id))
    return bundle


async def find_task_by_name(
    session: AsyncSession, *, application_id: str, name: str
) -> str | None:
    """按 (application_id, name) 查既有任务 id。

    同一应用下同名任务视为同一个业务对象：前端双击、浏览器重试、用户从列表
    再次提交，都不应该多出一条任务（每次创建都会连带一条修订，重复会污染时间线）。
    不加全局唯一约束是刻意的：0001 已冻结，且"曾经归档过的同名任务"允许再建 —
    所以查询只看**未归档**的任务，归档后重新建同名任务仍然成功。
    """
    aid = as_uuid(application_id)
    if aid is None:
        return None
    row = (
        await session.execute(
            text(
                "SELECT id FROM test_tasks "
                " WHERE application_id = :aid AND name = :name AND lifecycle <> :archived "
                " ORDER BY created_at, id LIMIT 1"
            ),
            {"aid": aid, "name": name, "archived": task_domain.lifecycle_after_archive()},
        )
    ).first()
    return str(row[0]) if row is not None else None


# --------------------------------------------------------------------------- #
# 创建
# --------------------------------------------------------------------------- #
async def _lock_request_key(session: AsyncSession, project_id: str, request_key: str) -> None:
    """事务级 advisory lock：同一个键的并发请求串行化到本事务提交为止。

    没有它，两个并发请求会同时读到"键不存在"，然后一个撞唯一约束、另一个成功；
    有了它，第二个请求在锁上等待，醒来后读到的就是已提交的键行。锁随事务
    commit/rollback 自动释放，不需要显式解锁。
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": f"task_request_key:{project_id}:{request_key}"},
    )


async def _lookup_request_key(
    session: AsyncSession, project_id: str, request_key: str
) -> Any | None:
    return (
        await session.execute(
            text(
                "SELECT request_key, fingerprint, task_id FROM task_request_keys "
                " WHERE project_id = :pid AND request_key = :key"
            ),
            {"pid": project_id, "key": request_key},
        )
    ).mappings().first()


async def _record_request_key(
    session: AsyncSession,
    *,
    project_id: str,
    request_key: str,
    fingerprint: str,
    task_id: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO task_request_keys
                (id, project_id, request_key, fingerprint, task_id)
            VALUES (:id, :pid, :key, :fp, :tid)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "pid": project_id,
            "key": request_key,
            "fp": fingerprint,
            "tid": task_id,
        },
    )


def _create_content(
    *,
    application_id: str,
    name: str,
    platform: str,
    test_type: str,
    build_id: str | None,
    suite_version_id: str | None,
    environment_id: str | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """创建请求的规范化业务内容（spec §9.1：应用、名称、类型、平台、构建、套件、环境、config）。"""
    return {
        "application_id": application_id,
        "name": name,
        "platform": platform,
        "test_type": test_type,
        "build_id": build_id,
        "suite_version_id": suite_version_id,
        "environment_id": environment_id,
        "config": config,
    }


def _existing_content(task: dict[str, Any]) -> dict[str, Any]:
    """既有任务的最新修订折算成同一形状，供同名/同键的内容比较。"""
    revision = task.get("revision") or {}
    return {
        "application_id": task["application"]["id"],
        "name": task["name"],
        "platform": task.get("platform"),
        "test_type": task.get("test_type"),
        "build_id": revision.get("build_id"),
        "suite_version_id": revision.get("suite_version_id"),
        "environment_id": revision.get("environment_id"),
        "config": revision.get("config") or {},
    }


async def create_task(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    created_by: str,
    request_key: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """创建任务 + 第一条 draft 修订（同一事务）。

    返回 (task, duplicate)。duplicate=True 表示没有新建，复用了既有任务
    （路由据此回 200 而不是 201）。

    两层去重都在本函数内、与建任务同一事务，保证"判定 + 落库"原子：

    1. **请求级幂等**：request_key / Idempotency-Key 是"同一个请求"。键绑定
       规范化创建内容（应用、名称、类型、平台、构建、套件、环境、config）：
       同键同内容复用首次的任务，同键不同内容 409 idempotency_conflict 且不产生
       任何副作用。键落在 task_request_keys 表，跨进程、跨重启有效。
    2. **业务级判重**：同一应用下同名且未归档的任务，内容完全一致才复用；
       换构建/套件/类型/config 的同名请求 409 task_configuration_conflict，
       附 existing_task_id 与差异字段名，绝不悄悄返回旧配置（spec §9.1）。
    """
    application_id = as_uuid(payload.get("application_id"))
    if application_id is None:
        raise validation_error([f"application_id 不是合法 UUID：{payload.get('application_id')!r}"])
    application = await _load_application(session, application_id)
    project_id = str(application["project_id"])
    if payload.get("project_id") and as_uuid(payload["project_id"]) != project_id:
        raise validation_error(["project_id 与 application_id 不属于同一个项目"])
    if application["archived_at"] is not None:
        raise validation_error(["应用已归档，不能新建任务"])

    test_type = payload["test_type"]
    if test_type not in task_domain.TEST_TYPES:  # pragma: no cover - pydantic Literal 已挡
        raise validation_error([f"test_type 只支持 {', '.join(task_domain.TEST_TYPES)}"])

    environment_id = await _resolve_environment(session, project_id, payload.get("environment_id"))
    build_id = await _check_build(session, project_id, application_id, payload.get("build_id"))
    suite_version = await _check_suite_version(
        session, project_id, application_id, payload.get("suite_version_id")
    )
    if payload.get("suite_version_id") and suite_version is None:
        raise validation_error([f"suite_version_id {payload['suite_version_id']} 不属于该应用"])
    suite_version_id = str(suite_version["id"]) if suite_version is not None else None

    config = dict(payload.get("config") or {})
    # 建任务时把应用平台写进 config 快照：任务平台与应用平台不一致是允许的（文档允许
    # 非 android 端建任务），但 validate 会因此失败，留痕便于前端解释原因。
    config.setdefault("application_platform", application["platform"])

    content = _create_content(
        application_id=application_id,
        name=payload["name"],
        platform=payload["platform"],
        test_type=test_type,
        build_id=build_id,
        suite_version_id=suite_version_id,
        environment_id=environment_id,
        config=config,
    )
    fingerprint = task_domain.create_content_fingerprint(content)

    key = (request_key or "").strip()
    if key:
        # 先拿锁再读键：读到的键行一定是已提交的，不需要处理"唯一约束竞争"。
        await _lock_request_key(session, project_id, key)
        hit = await _lookup_request_key(session, project_id, key)
        if hit is not None:
            if hit["fingerprint"] != fingerprint:
                raise conflict(
                    "idempotency_conflict",
                    "同一幂等键提交了不同内容；原请求已生效，本次未执行",
                    {"request_key": key, "existing_task_id": str(hit["task_id"])},
                )
            return await get_task(session, str(hit["task_id"])), True

    existing_id = await find_task_by_name(
        session, application_id=application_id, name=payload["name"]
    )
    if existing_id is not None:
        existing = await get_task(session, existing_id)
        differing = task_domain.create_content_diff(_existing_content(existing), content)
        if differing:
            raise conflict(
                "task_configuration_conflict",
                "同一应用下已有同名任务但配置不同；请选择原任务或另起名称",
                {
                    "existing_task_id": existing_id,
                    "existing_name": existing["name"],
                    "fields": differing,
                },
            )
        if key:
            await _record_request_key(
                session,
                project_id=project_id,
                request_key=key,
                fingerprint=fingerprint,
                task_id=existing_id,
            )
        return existing, True

    task_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO test_tasks
                (id, project_id, application_id, name, lifecycle, lock_version, created_by)
            VALUES (:id, :pid, :aid, :name, :lc, :lv, :by)
            """
        ),
        {
            "id": task_id,
            "pid": project_id,
            "aid": application_id,
            "name": payload["name"],
            # 新建即 draft：domain.LIFECYCLES[0] 就是 'draft'，不写字面量
            "lc": task_domain.LIFECYCLES[0],
            "lv": 1,
            "by": created_by,
        },
    )

    await _insert_revision(
        session,
        project_id=project_id,
        application_id=application_id,
        task_id=task_id,
        environment_id=environment_id,
        build_id=build_id,
        suite_version_id=suite_version_id,
        test_type=test_type,
        readiness=task_domain.readiness_after_patch(),
        config=config,
        created_by=created_by,
    )

    if key:
        # 键行与任务同一事务：任务建失败时键行一起回滚，不会留下指向半成品的键。
        await _record_request_key(
            session,
            project_id=project_id,
            request_key=key,
            fingerprint=fingerprint,
            task_id=task_id,
        )

    bundle = await _fetch_task_bundle(session, task_id)
    assert bundle is not None  # 刚插入，必然存在
    return bundle, False


# --------------------------------------------------------------------------- #
# 更新（CAS + 追加修订）
# --------------------------------------------------------------------------- #
async def patch_task(
    session: AsyncSession,
    *,
    task_id: str,
    payload: dict[str, Any],
    created_by: str,
) -> dict[str, Any]:
    """乐观锁更新。

    CAS 必须是"带条件的 UPDATE"，不能先 SELECT 再 UPDATE：两个并发请求会在
    SELECT 与 UPDATE 之间同时读到旧版本号，双双通过检查（lost update）。
    这里把 lock_version = :expected 写进 WHERE，受影响行数为 0 即冲突。

    冲突时的 details 必须带**最新对象**，前端据此直接刷新而不是再发一次 GET
    （api-design.md §1.3）。
    """
    tid = _task_id_or_404(task_id)
    expected = int(payload["lock_version"])

    current = await _fetch_task_bundle(session, tid)
    if current is None:
        raise not_found("task", str(task_id))

    # 领域规则：归档后不可改
    if not task_domain.can_patch(current["lifecycle"]):
        from ..errors import illegal_transition

        raise illegal_transition(
            current["lifecycle"],
            "draft",
            f"任务已归档（{task_domain.ARCHIVED_PATCH_DENIED}），不能修改",
        )

    next_lock = task_domain.next_lock_version(current["lock_version"])
    updated = (
        await session.execute(
            text(
                """
                UPDATE test_tasks
                   SET name = COALESCE(:name, name),
                       lifecycle = :lc,
                       lock_version = :next_lock,
                       updated_at = now()
                 WHERE id = :tid AND lock_version = :expected
                """
            ),
            {
                "name": payload.get("name"),
                "lc": task_domain.lifecycle_after_patch(current["lifecycle"]),
                "next_lock": next_lock,
                "tid": tid,
                "expected": expected,
            },
        )
    ).rowcount
    if not updated:
        # 读后到现在的这段时间里被别人改了：重新取最新态返回给前端
        latest = await _fetch_task_bundle(session, tid)
        if latest is None:  # pragma: no cover - 任务被删
            raise not_found("task", str(task_id))
        raise stale_version(latest)

    application = await _load_application(session, current["application"]["id"])
    project_id = str(application["project_id"])
    application_id = str(application["id"])
    old_rev = current["revision"] or {}

    environment_id = await _resolve_environment(
        session, project_id, payload.get("environment_id") or old_rev.get("environment_id")
    )
    build_id = await _check_build(
        session,
        project_id,
        application_id,
        payload.get("build_id") if payload.get("build_id") is not None else old_rev.get("build_id"),
    )
    requested_sv = (
        payload["suite_version_id"] if payload.get("suite_version_id") is not None
        else old_rev.get("suite_version_id")
    )
    suite_version = await _check_suite_version(session, project_id, application_id, requested_sv)
    if requested_sv and suite_version is None:
        raise validation_error([f"suite_version_id {requested_sv} 不属于该应用"])

    config = task_domain.config_merged(old_rev.get("config"), payload.get("config"))

    await _insert_revision(
        session,
        project_id=project_id,
        application_id=application_id,
        task_id=tid,
        environment_id=environment_id,
        build_id=build_id,
        suite_version_id=str(suite_version["id"]) if suite_version is not None else None,
        test_type=payload.get("test_type") or old_rev.get("test_type") or task_domain.TEST_TYPES[0],
        # PATCH 产生的新修订永远回到 draft：配置变了，之前的 validate 结论失效
        readiness=task_domain.readiness_after_patch(),
        config=config,
        created_by=created_by,
    )

    latest = await _fetch_task_bundle(session, tid)
    assert latest is not None
    return latest


# --------------------------------------------------------------------------- #
# 校验（readiness gate）
# --------------------------------------------------------------------------- #
async def validate_task(session: AsyncSession, *, task_id: str, created_by: str) -> dict[str, Any]:
    """校验 readiness，通过则同事务追加一条 readiness='validated' 的修订。

    注意"通过则写新修订"而不是把旧修订改成 validated：修订不可变是硬规则，
    而且一条修订的 readiness 变化本身就是一次可审计的状态变化。
    """
    tid = _task_id_or_404(task_id)
    current = await _fetch_task_bundle(session, tid)
    if current is None:
        raise not_found("task", str(task_id))

    if not task_domain.can_validate(current["lifecycle"]):
        from ..errors import illegal_transition

        raise illegal_transition(current["lifecycle"], "ready", "任务已归档，不能重新校验")

    rev = current["revision"] or {}
    application = await _load_application(session, current["application"]["id"])
    project_id = str(application["project_id"])
    application_id = str(application["id"])

    suite_version = await _check_suite_version(
        session, project_id, application_id, rev.get("suite_version_id")
    )
    case_total = suite_domain.case_total(suite_version["manifest"]) if suite_version is not None else 0

    report = task_domain.check_readiness(
        revision=rev,
        platform=current["platform"],
        application_platform=application["platform"],
        suite_version=dict(suite_version) if suite_version is not None else None,
        case_total=case_total,
        suite_test_type=(
            str(suite_version["suite_test_type"]) if suite_version is not None else None
        ),
    )
    if not report.ok:
        from ..errors import task_not_ready

        raise task_not_ready(missing=report.missing, invalid=report.invalid)

    next_lock = task_domain.next_lock_version(current["lock_version"])
    updated = (
        await session.execute(
            text(
                "UPDATE test_tasks SET lifecycle = :lc, lock_version = :lv, updated_at = now() "
                "WHERE id = :tid AND lock_version = :expected"
            ),
            {
                "lc": task_domain.lifecycle_after_validate(current["lifecycle"]),
                "lv": next_lock,
                "tid": tid,
                "expected": current["lock_version"],
            },
        )
    ).rowcount
    if not updated:  # pragma: no cover - 并发校验同一任务时的极端情况
        latest = await _fetch_task_bundle(session, tid)
        raise stale_version(latest)

    await _insert_revision(
        session,
        project_id=project_id,
        application_id=application_id,
        task_id=tid,
        environment_id=rev.get("environment_id") or await _resolve_environment(session, project_id, None),
        build_id=rev.get("build_id"),
        suite_version_id=rev.get("suite_version_id"),
        test_type=rev.get("test_type") or task_domain.TEST_TYPES[0],
        readiness=task_domain.readiness_after_validate(),
        config=dict(rev.get("config") or {}),
        created_by=created_by,
    )

    latest = await _fetch_task_bundle(session, tid)
    assert latest is not None
    latest["case_count"] = case_total
    return latest


# --------------------------------------------------------------------------- #
# 归档
# --------------------------------------------------------------------------- #
async def archive_task(session: AsyncSession, *, task_id: str) -> dict[str, Any]:
    """归档任务。幂等：已经是 archived 时不再改 lock_version，直接返回当前态。"""
    tid = _task_id_or_404(task_id)
    current = await _fetch_task_bundle(session, tid)
    if current is None:
        raise not_found("task", str(task_id))

    target = task_domain.lifecycle_after_archive()
    if current["lifecycle"] == target:
        return current

    await session.execute(
        text(
            "UPDATE test_tasks SET lifecycle = :lc, lock_version = :lv, updated_at = now() "
            "WHERE id = :tid AND lock_version = :expected"
        ),
        {
            "lc": target,
            "lv": task_domain.next_lock_version(current["lock_version"]),
            "tid": tid,
            "expected": current["lock_version"],
        },
    )
    latest = await _fetch_task_bundle(session, tid)
    assert latest is not None
    return latest


# --------------------------------------------------------------------------- #
# 修订历史
# --------------------------------------------------------------------------- #
async def list_revisions(session: AsyncSession, task_id: str) -> dict[str, Any]:
    """修订列表，revision 倒序（最新在前）。

    返回前用 schemas.TaskRevisionRecord 自检：契约冻结在前端时间线上，
    服务端一旦多加/少给/改名一个字段，这里直接抛 ValidationError 而不是
    让前端静默渲染成破折号。自检通过后再 dump 成普通 dict 交给路由。
    """
    tid = _task_id_or_404(task_id)
    exists = (await session.execute(text("SELECT 1 FROM test_tasks WHERE id = :tid"), {"tid": tid})).first()
    if exists is None:
        raise not_found("task", str(task_id))
    rows = (
        await session.execute(
            text(
                "SELECT id, task_id, revision, test_type, readiness, build_id, suite_version_id, "
                "       environment_id, config, created_by, created_at "
                "  FROM task_revisions WHERE task_id = :tid ORDER BY revision DESC"
            ),
            {"tid": tid},
        )
    ).mappings().all()

    records = [TaskRevisionRecord.model_validate(_revision_dict(r)) for r in rows]
    payload = TaskRevisionListOut(items=records, total=len(records))
    # round_trip 让 datetime 渲染成 ISO8601 字符串（与 FastAPI 的 JSON 编码一致），
    # 这样响应体形状与模型声明逐字节对得上，前端拿到的就是契约里的东西。
    return payload.model_dump(mode="json")
