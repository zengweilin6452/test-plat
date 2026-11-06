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

import base64
import json
import re
import shutil
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..domain import artifacts as artifacts_mod
from ..domain import events as events_mod
from ..domain import identity as identity_mod
from ..domain import runs as runs_mod
from ..errors import device_not_ready, not_found, readiness_incomplete, state_conflict, validation_error
from ..schemas import RunsOut
from ..ws import hub as hub_mod

router = APIRouter(tags=["runs"])

# 原型用 run-0001 这种流水号；编号由 test_runs.display_no 持久分配（迁移 0007），
# 查询期不再用 row_number 现算 —— 现算会随历史数据增删而重编号（工单 09、INV-10）。
_RUNS_SQL = """
    SELECT n.id, n.display_no, n.state, n.outcome, n.reason_code, n.not_tested_reason,
           n.platform, n.started_at, n.ended_at, n.created_at,
           n.application_id, a.name AS application_name,
           n.revision_id, tr.task_id, tr.test_type,
           t.name AS task_name,
           n.resource_id, er.resource_key AS resource_name
      FROM test_runs n
      JOIN applications a ON a.id = n.application_id
      LEFT JOIN task_revisions tr ON tr.id = n.revision_id
      LEFT JOIN test_tasks t ON t.id = tr.task_id
      LEFT JOIN execution_resources er ON er.id = n.resource_id
"""

#: 列表 / 详情 / WS 共用同一条进度投影（spec §9.3）：由 run_events 推导，
#: 与 domain/events.compute_progress 同一口径（stage 权重在下面 CASE 里逐项复刻，
#: 改动权重必须同时改两处，test_issue08 有一条静态断言守住）。
#: 用 SQL 聚合而不是把事件全捞回来：事件可能上千条，详情页不该因此变慢。
_EVENT_PROGRESS_SQL = """
    SELECT run_id,
           max(GREATEST(
               CASE WHEN payload->>'progress' ~ '^[0-9]{1,3}$'
                    THEN (payload->>'progress')::int ELSE 0 END,
               CASE COALESCE(payload->>'stage', payload->>'name')
                    WHEN 'ack' THEN 5
                    WHEN 'lease' THEN 10
                    WHEN 'ready' THEN 20
                    WHEN 'pytest' THEN 80
                    WHEN 'archive' THEN 100
                    ELSE 0 END
           ))::int AS progress,
           max(sequence)::int AS last_sequence
      FROM run_events
     WHERE run_id = ANY(:run_ids)
     GROUP BY run_id
"""


@router.get("/runs", response_model=RunsOut)
async def list_runs(
    scope: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    application_id: Annotated[str | None, Query()] = None,
    test_type: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """运行列表（报告中心传 state=completed 只取完成报告）。

    过滤：scope（android/ios/web）、state（七态）、application_id、test_type，
    q 在**完整过滤集合**里按文字包含匹配 display_id / 任务名 / 应用名
    （position() 不解释 % 和 _，输入不会被当成 SQL 通配符）。

    游标分页：`display_no` 是创建时持久分配的全局序号，天然就是"创建水位"。
    cursor 里同时封了过滤条件签名，换一组过滤条件带旧游标 → 422，不会拼出
    两个过滤集合的混合页（spec §9.3、AC-FILTER-01）。
    """
    if scope and scope not in ("android", "ios", "web"):
        raise validation_error([f"scope 只支持 android / ios / web，收到 {scope!r}"])
    if state and state not in runs_mod.ALL_STATES:
        raise validation_error(
            [f"state 只支持 {' / '.join(runs_mod.ALL_STATES)}，收到 {state!r}"]
        )
    if test_type and test_type not in ("ui", "performance", "joint"):
        raise validation_error(["test_type 只支持 ui / performance / joint"])
    if application_id:
        try:
            uuid.UUID(str(application_id))
        except ValueError:
            raise validation_error(["application_id 必须是 uuid"])
    if project_id:
        try:
            uuid.UUID(str(project_id))
        except ValueError:
            raise validation_error(["project_id 必须是 uuid"])
        exists = (
            await session.execute(
                text("SELECT 1 FROM projects WHERE id::text = :pid"), {"pid": project_id}
            )
        ).first()
        if exists is None:
            raise not_found("project", project_id)

    filters = {
        "scope": scope,
        "state": state,
        "application_id": application_id,
        "test_type": test_type,
        "q": q,
        "project_id": project_id,
    }
    where: list[str] = []
    params: dict[str, object] = {"limit": limit}

    if scope:
        where.append("n.platform = :scope")
        params["scope"] = scope
    if state:
        where.append("n.state = :state")
        params["state"] = state
    if application_id:
        where.append("n.application_id = CAST(:aid AS uuid)")
        params["aid"] = str(application_id)
    if test_type:
        where.append("tr.test_type = :tt")
        params["tt"] = test_type
    if project_id:
        # 工单 05：运行列表跟随当前项目；缺省 = 全部项目汇总
        where.append("n.project_id::text = :pid")
        params["pid"] = project_id
    if q:
        q = str(q).strip()
        if q:
            params["q"] = q
            where.append(
                "(position(lower(:q) IN lower('RUN-' || lpad(n.display_no::text, 4, '0'))) > 0"
                " OR position(lower(:q) IN lower(COALESCE(t.name, ''))) > 0"
                " OR position(lower(:q) IN lower(a.name)) > 0)"
            )
        else:
            filters["q"] = None
    if cursor:
        where.append("n.display_no < :before_no")
        params["before_no"] = _parse_cursor(cursor, filters)

    sql = _RUNS_SQL
    if where:
        sql += " WHERE " + " AND ".join(where)
    # display_no 唯一且随创建递增：排序稳定，分页水位就是它自己
    sql += " ORDER BY n.display_no DESC LIMIT :limit"

    # 多取一条判断 has_more，客户端不用再空跑一页
    params["limit"] = limit + 1
    rows = (await session.execute(text(sql), params)).mappings().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    run_ids = [row["id"] for row in rows]
    progress: dict[object, int] = {}
    if run_ids:
        for item in (
            await session.execute(text(_EVENT_PROGRESS_SQL), {"run_ids": run_ids})
        ).mappings().all():
            progress[item["run_id"]] = int(item["progress"] or 0)

    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "display_id": runs_mod.format_display_id(row["display_no"]),
                "name": row["task_name"] or row["application_name"],
                "task_id": row["task_id"],
                "application": {"id": row["application_id"], "name": row["application_name"]},
                "platform": row["platform"],
                "test_type": row["test_type"],
                "state": row["state"],
                "outcome": row["outcome"],
                "reason_code": row["reason_code"],
                "not_tested_reason": row["not_tested_reason"],
                # 与详情/WS 同一投影；完全没有事件时返回 null（前端显示"无进度数据"）
                "progress": progress.get(row["id"]),
                "resource": row["resource_name"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "created_at": row["created_at"],
            }
        )
    return {
        "items": items,
        "total": len(items),
        # cursor 指向本页最后一条的水位；翻页原样传回即可，尽头/空页为 None
        "next_cursor": _cursor_token(filters, int(rows[-1]["display_no"]))
        if has_more and rows
        else None,
        "has_more": has_more,
    }


#: cursor = base64url(json{f: 过滤条件快照, n: 水位 display_no})。
#: 过滤条件封进 token：带旧游标换过滤条件必须 422，不能静默混页。
def _cursor_token(filters: dict[str, object], display_no: int) -> str:
    payload = json.dumps({"f": filters, "n": display_no}, ensure_ascii=False, sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _parse_cursor(cursor: str, filters: dict[str, object]) -> int:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        if (
            isinstance(data, dict)
            and isinstance(data.get("n"), int)
            and not isinstance(data.get("n"), bool)
            and data.get("f") == filters
        ):
            return int(data["n"])
    except Exception:  # noqa: BLE001 - 任何解析失败都按非法游标处理
        pass
    raise validation_error(["cursor 非法或不匹配当前过滤条件，请从头开始浏览"])


@router.get("/runs/{run_id}")
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """运行详情：与 WS snapshot、报告复用同一个 `_run_view` 投影。

    同一份投影是硬要求（spec §9.3）：列表、详情与 WS 的 progress / stage /
    cancel_requested 必须一致，否则刷新页面看到的进度会跳变。
    """
    return await _run_view(session, run_id)


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
    session: AsyncSession, application_id: str | None, platform: str, *, required: bool = True
) -> dict:
    """浏览器必须显式选择应用（spec §6.2）。

    不再"取该平台最早创建的应用"——那会把运行悄悄挂到另一个应用上。
    只有内部导入通道（required=False）保留兼容回退。
    """
    if application_id:
        row = (
            await session.execute(
                text(
                    "SELECT id, project_id, platform, name FROM applications "
                    "WHERE id::text = :aid AND archived_at IS NULL"
                ),
                {"aid": str(application_id)},
            )
        ).mappings().first()
        if row is None:
            raise not_found("application", str(application_id))
        if row["platform"] != platform:
            raise validation_error(
                [f"platform {platform!r} 与应用平台 {row['platform']!r} 不一致"]
            )
        return dict(row)
    if required:
        raise validation_error(["application_id 必填（浏览器必须显式选择应用）"])
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
    project_id: str, application_id: str, require_validated: bool = True
) -> str:
    """解析并固定本次执行使用的修订（spec §9.1）。

    - task_id 必填：运行必须明确属于哪个任务，不能靠"应用下最新修订"猜；
    - revision_id 可省略以兼容旧客户端，但一旦省略就在这里**解析一次并固定**，
      响应把实际 revision_id 返回，派发时绝不重新解析；
    - 修订必须属于该任务、该应用、该项目，且 readiness='validated'；
      跨归属与非 validated 一律拒绝，不合成悬空外键。
    """
    if not revision_id and not task_id:
        raise readiness_incomplete(["task_id 或 revision_id"])
    if not task_id:
        raise readiness_incomplete(["task_id"])

    got = (
        await session.execute(
            text(
                "SELECT tr.id, tr.readiness FROM task_revisions tr "
                "JOIN test_tasks t ON t.id = tr.task_id "
                "WHERE t.project_id = :pid AND t.application_id = :aid "
                "AND t.id::text = :tid "
                "AND (CAST(:rid AS text) IS NULL OR tr.id::text = :rid) "
                # 省略 revision_id 时只接受已验证修订：草稿不能直接发起运行
                "AND (CAST(:rid AS text) IS NOT NULL OR tr.readiness = 'validated'"
                "     OR NOT CAST(:require_validated AS boolean)) "
                "ORDER BY tr.revision DESC LIMIT 1"
            ),
            {"pid": project_id, "aid": application_id,
             "rid": str(revision_id) if revision_id else None,
             "tid": str(task_id),
             "require_validated": require_validated},
        )
    ).mappings().first()
    if got is None:
        if revision_id:
            raise not_found("revision", str(revision_id))
        raise readiness_incomplete([f"任务 {task_id} 没有已验证的修订，请先 validate"])
    if require_validated and got["readiness"] != "validated":
        raise readiness_incomplete(
            [f"revision {got['id']} 尚未验证（readiness={got['readiness']}），不能发起运行"]
        )
    return str(got["id"])


#: 浏览器不得用这些字段改写修订里固定的输入（spec §9.1）。导入通道在内部
#: `/runs/import` 里自己写 source=import，不接受浏览器传 source。
_FIXED_INPUT_FIELDS = ("overrides", "source_dir", "test_paths", "fake_outcome", "source")

#: 声明式性能场景适用的测试类型（工单 06）：UI 运行没有性能场景可合订。
_SCENARIO_TEST_TYPES = ("performance", "joint")


async def _resolve_execution_scenario(
    session: AsyncSession, *, revision: Mapping, revision_config: Mapping
) -> tuple[dict | None, str | None]:
    """把修订 config.perf 与套件版本场景合订成一份执行输入（工单 06）。

    「谁的场景算数」只在这里定义（domain.suite.resolve_scenario）：
      - 两份一致 -> 用套件版本快照，来源 suite_manifest；
      - 只有一份 -> 用它，来源写明是 suite_manifest 还是 revision；
      - 两份不一致 -> 400 拒绝（validation_error），绝不用其中一份静默覆盖另一份；
      - 都没有 -> 不合订任何值（performance 采集入口会因缺场景而拒绝）。

    合订结果与来源随 config_snapshot 冻结进运行，派发不再重新解析——执行
    依据在提交时就固定了。
    """
    from ..domain import suite as suite_domain

    test_type = str(revision.get("test_type") or "")
    if test_type not in _SCENARIO_TEST_TYPES:
        return None, None
    manifest: dict = {}
    suite_version_id = revision.get("suite_version_id")
    if suite_version_id:
        raw = (
            await session.execute(
                text("SELECT manifest FROM suite_versions WHERE id = :sid"),
                {"sid": str(suite_version_id)},
            )
        ).scalar_one_or_none()
        manifest = raw if isinstance(raw, dict) else {}
    try:
        scenario, source = suite_domain.resolve_scenario(
            test_type=test_type,
            manifest=manifest,
            revision_perf=revision_config.get("perf"),
        )
    except suite_domain.PerfScenarioConflict as exc:
        raise validation_error([f"perf: {exc}"]) from exc
    if scenario is not None:
        problems = suite_domain.scenario_problems(scenario)
        if problems:
            raise validation_error([f"perf: {problem}" for problem in problems])
    return scenario, source


async def _insert_run(session: AsyncSession, body: Mapping, *, internal: bool = False) -> dict:
    """插入 queued run；request_key 重复则返回既有 run（created=False）。

    internal=True 只给 `/runs/import` 用：它需要 source=import 与 source_dir，
    且允许省略 application_id（补录历史产物）。浏览器通道一律走严格校验。
    """
    request_key = str(body.get("request_key") or "").strip()
    if not request_key:
        raise validation_error(["request_key 必填（幂等去重键）"])
    if len(request_key) > 200:
        raise validation_error(["request_key 过长（<=200）"])

    if not internal:
        offending = [name for name in _FIXED_INPUT_FIELDS if name in body]
        if offending:
            # 固定输入只能来自修订：overrides / source_dir / test_paths / 伪造结论
            # 若被接受，就等于给了浏览器一条绕过验证与固定副本的通道。
            raise validation_error(
                [f"不允许在请求中改写固定输入：{', '.join(offending)}"]
            )

    platform = str(body.get("platform") or "android")
    if platform not in _PLATFORMS:
        raise validation_error(["platform 只支持 android / ios / web"])

    application = await _pick_application(
        session, body.get("application_id"), platform, required=not internal
    )
    project_id = str(application["project_id"])
    application_id = str(application["id"])

    # 归档守卫（工单 04）：锁身份行后确认项目 / 应用未归档，归档提交后不可能再插入新运行
    await identity_mod.assert_scope_active(session, project_id=project_id, application_id=application_id)

    existing = (
        await session.execute(
            text("SELECT id, revision_id FROM test_runs WHERE project_id = :pid AND request_key = :rk"),
            {"pid": project_id, "rk": request_key},
        )
    ).mappings().first()
    if existing is not None:
        return {
            "id": str(existing["id"]),
            "created": False,
            "project_id": project_id,
            "revision_id": str(existing["revision_id"]),
            "task_id": str(body.get("task_id") or "") or None,
        }

    revision_id = await _resolve_revision(
        session,
        task_id=body.get("task_id"),
        revision_id=body.get("revision_id"),
        project_id=project_id,
        application_id=application_id,
        # 导入通道补录的是历史产物，不要求修订当时已验证
        require_validated=not internal,
    )

    parent_run_id = body.get("parent_run_id")
    if parent_run_id:
        if not _is_uuid(parent_run_id):
            raise validation_error(["parent_run_id 必须是 uuid"])
        parent = (
            await session.execute(
                text(
                    "SELECT id FROM test_runs "
                    "WHERE id::text = :id AND project_id = :pid AND application_id = :aid"
                ),
                {"id": str(parent_run_id), "pid": project_id, "aid": application_id},
            )
        ).first()
        if parent is None:
            # 重跑只能引用同一应用下的运行；跨应用/跨项目一律按不存在处理
            raise not_found("run", str(parent_run_id))
        parent_run_id = str(parent_run_id)

    revision = (
        await session.execute(
            text("SELECT config, test_type, suite_version_id FROM task_revisions WHERE id = :id"),
            {"id": revision_id},
        )
    ).mappings().one()
    revision_config = dict(revision["config"] or {})
    # 声明式场景：修订配置与套件版本清单是两份声明，提交时合订成一份并写明
    # 来源（工单 06）。导入通道补录历史产物、不再执行，不做合订。
    scenario, scenario_source = (
        (None, None)
        if internal
        else await _resolve_execution_scenario(
            session, revision=revision, revision_config=revision_config
        )
    )
    # device 是显式选择（§6.2 允许），不属于"改写固定输入"；其余执行输入一律
    # 取自修订，请求体里出现就会被 _FIXED_INPUT_FIELDS 拒绝。
    device = body.get("device") if "device" in body else revision_config.get("device")
    device = device or {}
    if not isinstance(device, Mapping):
        raise validation_error(["device 必须是对象"])
    resource_id = device.get("resource_id")
    if resource_id is not None and not _is_uuid(resource_id):
        raise validation_error(["device.resource_id 必须是 uuid"])
    importing = internal
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

    # AC-GATE-01：排队即固定默认策略（id+版本+规则快照）。跑完前改策略版本
    # 不影响这次执行的判定依据；快照里的 rules 只是审计副本，判定按 id 读行。
    policy_snapshot = (
        await session.execute(
            text(
                "SELECT id, version, rules FROM gate_policies"
                " WHERE application_id = :aid"
                " ORDER BY version DESC, created_at DESC, id DESC LIMIT 1"
            ),
            {"aid": application_id},
        )
    ).mappings().first()

    snapshot = {
        **revision_config,
        "request_key": request_key,
        "gate_policy": {
            "id": str(policy_snapshot["id"]),
            "version": int(policy_snapshot["version"]),
            "rules": policy_snapshot["rules"],
        }
        if policy_snapshot
        else None,
        "platform": platform,
        "application_id": application_id,
        "module": "perf" if revision["test_type"] == "performance" else revision["test_type"],
        # 合订后的声明式场景与来源（仅 performance/joint；来源是审计事实，
        # 不是给前端猜的：suite_manifest / revision）。
        **(
            {"perf": scenario, "perf_source": scenario_source}
            if scenario is not None
            else {}
        ),
        "requested_resource_id": resource_id,
        "source": "import" if internal else "api",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }

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
                "parent_run_id": parent_run_id,
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
        # 并发插入撞唯一键：回读既有运行。它的 revision 才是真实固定输入，
        # 不能用本次请求解析出来的 revision 冒充。
        existing = (
            await session.execute(
                text(
                    "SELECT id, revision_id FROM test_runs "
                    "WHERE project_id = :pid AND request_key = :rk"
                ),
                {"pid": project_id, "rk": request_key},
            )
        ).mappings().one()
        return {
            "id": str(existing["id"]),
            "created": False,
            "project_id": project_id,
            "revision_id": str(existing["revision_id"]),
            "task_id": str(body.get("task_id") or "") or None,
        }

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
        # 固定下来的修订：省略 revision_id 的兼容请求也能从这里看到实际引用
        "revision_id": revision_id,
        "task_id": str(body.get("task_id") or "") or None,
    }


async def _run_view(session: AsyncSession, run_id: str) -> dict:
    """run 单条视图：详情、WS 快照、报告都复用它，避免三处口径不一致。

    progress 走 `_EVENT_PROGRESS_SQL`（与列表同一投影），stage 再按
    api-design.md 的阈值换算，因此刷新页面不会丢进度。
    cancel_requested 读**列**而不是事件：取消受理是持久化事实，不能被
    事件分页/清理截断（spec §9.3、AC-CONTRACT-03）。
    """
    row = (
        await session.execute(
            text(
                "SELECT r.id, r.display_no, r.project_id, r.application_id, r.platform,"
                "       r.revision_id,"
                "       r.state, r.outcome, r.reason_code, r.not_tested_reason,"
                "       r.resource_id, r.parent_run_id, r.request_key,"
                "       r.started_at, r.ended_at, r.created_at, r.config_snapshot,"
                "       r.cancel_requested_at, r.cancel_requested_by,"
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
    progress_row = (
        await session.execute(text(_EVENT_PROGRESS_SQL), {"run_ids": [row["id"]]})
    ).mappings().first()
    progress = int(progress_row["progress"] or 0) if progress_row else None
    last_sequence = int(progress_row["last_sequence"] or 0) if progress_row else 0
    terminal = runs_mod.is_terminal(str(row["state"]))
    stage = events_mod.stage_number(progress or 0, terminal=terminal)
    cancel_requested = row["cancel_requested_at"] is not None
    components = (
        await session.execute(
            text(
                "SELECT kind, state, outcome, created_at "
                "FROM run_components WHERE run_id = :run_id ORDER BY kind"
            ),
            {"run_id": row["id"]},
        )
    ).mappings().all()
    duration_s = None
    if row["started_at"] and row["ended_at"]:
        duration_s = int((row["ended_at"] - row["started_at"]).total_seconds())
    snapshot = row["config_snapshot"] or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    return {
        "id": str(row["id"]),
        "display_id": runs_mod.format_display_id(row["display_no"]),
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
        "last_sequence": last_sequence,
        "components": [
            {
                "component": c["kind"],
                "kind": c["kind"],
                "state": c["state"],
                "outcome": c["outcome"],
                "created_at": c["created_at"],
            }
            for c in components
        ],
        "cancel_requested": cancel_requested,
        "cancel_requested_at": row["cancel_requested_at"],
        "cancel_requested_by": row["cancel_requested_by"],
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
                "revision_id": created["revision_id"],
                "task_id": created["task_id"],
                "duplicate": True,
            },
        )
    hub_mod.publish(
        run_id,
        {"type": "state", "state": view["state"], "progress": 0, "stage": 1, "at": None},
    )
    return JSONResponse(
        status_code=201,
        content={
            "id": run_id,
            "display_id": view["display_id"],
            "state": view["state"],
            # 本次真正固定的修订（兼容请求省略 revision_id 时由服务端解析并返回）
            "revision_id": created["revision_id"],
            "task_id": created["task_id"],
        },
    )


@router.get("/runs/{run_id}/events")
async def list_run_events(
    run_id: str,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """run_events 增量拉取：WS 断线重连、刷新后补进度都靠它。

    分页语义（spec §9.3）：total 是**本页条数**；next_after 是下一页的起点
    （本页最后一条的 sequence，空页则沿用请求的 after）；has_more 表示后面还有。
    客户端循环补拉直到 has_more=false，按 (run_id, sequence) 去重。
    """
    project_id = await _project_of(session, run_id)
    # 多取一条判断 has_more，避免"最后一页刚好满页"时让客户端再空跑一次
    fetched = await events_mod.list_events(
        session,
        project_id=project_id,
        run_id=str(run_id),
        after_sequence=after,
        limit=limit + 1,
    )
    has_more = len(fetched) > limit
    items = fetched[:limit]
    next_after = int(items[-1]["sequence"]) if items else after
    return {
        "items": items,
        "total": len(items),
        "after": after,
        "next_after": next_after,
        "has_more": has_more,
    }


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """取消 run：受理取消事实，并让执行中的运行真的停下来（spec §6.2、§9.1）。

    - 取消事实写进 `test_runs.cancel_requested_at`（重复受理保留首次时间），
      不依赖事件流是否完整，也不因为重复点击多出一条事实；
    - queued 的运行直接迁移到 cancelled（还没占设备）；
    - dispatching / running / finalizing 的运行**主动终止 runner 进程树**
      （Windows `taskkill /T /F`，runner 拉起的 pytest/adb 一起收掉），再按
      cancelled 收敛：终态、事件、租约释放都在同一个 finalize 事务里可见。
      为什么不能只写事实等 heartbeat：runner 可能卡在 vendor 里不再心跳，
      设备就会一直被占到 reconciler 的 60s 陈旧判定 —— 取消按钮等于没生效。
      终止失败（进程表丢失且无 ack pid）仍按 cancelled 收敛，交给下次派发的
      本机兜底锁挡住残留进程（与 reconciler 的"尽力 kill + 释放"同一策略）。
    - runner 恰好已经上报完成的，finalize 看到终态就返回真实完成态，
      **不会**把真实结论改写成 cancelled；
    - 已终态的 run 不再受理取消（409 state_conflict，不是 500）。
    """
    project_id = await _project_of(session, run_id)
    terminal = sorted(runs_mod.TERMINAL_STATES)
    placeholders = ", ".join(f":t{i}" for i in range(len(terminal)))
    params: dict[str, object] = {"id": str(run_id), "actor": "web"}
    params.update({f"t{i}": state for i, state in enumerate(terminal)})

    # 事实与本请求的后续步骤分开事务：终止进程和 finalize 都要先让"取消已受理"
    # 落库（finalize 在另一个会话里对同一行加 FOR UPDATE，不能和本请求的长事务
    # 互相等锁）。条件 UPDATE 同时是终态闸门：并发的 completed 不会被伪造
    # 出一次 cancelled 事实。
    from ..db import get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as tx:
        async with tx.begin():
            row = (
                await tx.execute(
                    text(
                        "UPDATE test_runs"
                        "   SET cancel_requested_at = COALESCE(cancel_requested_at, now()),"
                        "       cancel_requested_by = COALESCE(cancel_requested_by, :actor)"
                        f" WHERE id::text = :id AND state NOT IN ({placeholders})"
                        " RETURNING state, cancel_requested_at"
                    ),
                    params,
                )
            ).mappings().first()
            if row is None:
                current = str(
                    (
                        await tx.execute(
                            text("SELECT state FROM test_runs WHERE id::text = :id"),
                            {"id": str(run_id)},
                        )
                    ).scalar_one()
                )
                raise state_conflict(run_id, current, "non_terminal")

            state = str(row["state"])
            await events_mod.append_event(
                tx,
                project_id=project_id,
                run_id=str(run_id),
                source_key=events_mod.SOURCE_CONTROL,
                source_event_id="cancel",
                event_type="cancel_requested",
                payload={"requested_by": "web", "from_state": state},
            )
            if state == runs_mod.STATE_QUEUED:
                # 行锁已在手：queued->cancelled 不会和 dispatcher 抢，直接收敛。
                await runs_mod.transition(
                    tx,
                    str(run_id),
                    runs_mod.STATE_QUEUED,
                    runs_mod.STATE_CANCELLED,
                    reason="cancel_requested",
                    actor="web",
                )

    killed = False
    if state in (runs_mod.STATE_DISPATCHING, runs_mod.STATE_RUNNING, runs_mod.STATE_FINALIZING):
        from .. import runtime as runtime_mod
        from ..runner import spawn as spawn_mod

        # 先切断进程树，再释放租约：顺序反了会出现"设备已可派发、旧 runner 还在
        # 操作设备"的窗口（reconciler 的注释里写过同一条纪律）。
        killed = await spawn_mod.terminate_run_process(str(run_id))
        await runtime_mod.finalize_run(
            run_id=str(run_id),
            state=runs_mod.STATE_CANCELLED,
            outcome=None,
            reason="cancel_requested",
            project_id=project_id,
            # 取消前 runner 可能已经写出 report.json / 采集窗口：不登记产物，
            # 报告页就会把"采集确实发生过"整块丢掉（与 spawn._finalize_after_exit
            # 同一口径：只有 errored 才不认这些产物）。
            artifacts_dir=spawn_mod.artifacts_dir_for(str(run_id)),
            release_lease_reason="cancel_requested",
            extra_event={"cancel_requested_by": "web", "runner_terminated": killed},
            actor="web",
        )

    final = (
        await session.execute(
            text("SELECT state, outcome FROM test_runs WHERE id::text = :id"),
            {"id": str(run_id)},
        )
    ).mappings().one()
    current = str(final["state"])
    if runs_mod.is_terminal(current):
        hub_mod.publish(
            str(run_id),
            {"type": "finished", "state": current, "outcome": final["outcome"]},
        )
    else:
        hub_mod.publish(
            str(run_id),
            {"type": "event", "kind": "cancel_requested", "name": None, "at": None},
        )
    return {
        "id": str(run_id),
        "state": current,
        "outcome": final["outcome"],
        "cancel_requested": True,
        "cancel_requested_at": row["cancel_requested_at"],
        "runner_terminated": killed,
    }


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
        # 复核后的三态：available 才给下载入口；missing/expired 给原因不给假链接
        item["download_url"] = (
            "/api/v1/runs/%s/artifacts/%s/download" % (run_id, item["id"])
            if item["availability"] == "available"
            else None
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
    if path is None or not path.is_file():
        raise not_found("artifact", str(artifact_id))
    return FileResponse(
        str(path),
        media_type=str(artifact.get("mime_type") or "application/octet-stream"),
        filename=Path(str(artifact["logical_key"])).name,
    )


def _code_copy_summary(manifest: Any) -> dict | None:
    """从 suite_versions.manifest 里挑固定代码副本摘要（只读，不现算来源目录）。

    manifest 或 code_copy 缺失 -> None（旧版本没有副本摘要时报告明说 null）。
    """
    if not isinstance(manifest, dict):
        return None
    code_copy = manifest.get("code_copy")
    if not isinstance(code_copy, dict):
        return None
    return {
        "tree_sha256": code_copy.get("tree_sha256"),
        "file_count": code_copy.get("file_count"),
        "root_rel": code_copy.get("root_rel"),
    }


async def _report_view(session: AsyncSession, run_id: str) -> dict:
    """报告快照（GET /report 与 /report/export 共用同一份，工单 11）。

    可追溯性纪律（spec §9.3、AC-REP-04）：
    - resource_profiles 是不可变档案（内容变化 = 新增行），报告引用运行时挂在
      test_runs.profile_id 上的档案就永远不会被"改档案"改写；缺失明确为 null，
      不用设备 serial 冒充档案。
    - gate_evaluations 行不可变，跑完后改策略不回溯历史报告。
    - evidence 只给 id/kind/可用性；storage_key（宿主存储路径）不出报告。
    """
    from .. import runtime as runtime_mod

    view = await _run_view(session, run_id)
    project_name = (
        await session.execute(
            text("SELECT name FROM projects WHERE id::text = :pid"),
            {"pid": str(view["project_id"])},
        )
    ).scalar()
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

    revision = None
    if view["revision_id"]:
        revision = dict(
            (
                await session.execute(
                    text(
                        "SELECT tr.id, tr.readiness, tr.test_type, tr.environment_id,"
                        "       tr.suite_version_id,"
                        "       ab.id AS build_id, ab.version AS build_version,"
                        "       ab.build_key AS build_key, ab.source_commit AS build_commit,"
                        "       ab.sha256 AS build_sha256,"
                        "       sv.id AS suite_version_row_id, sv.version AS suite_version,"
                        "       sv.source_ref AS suite_source_ref,"
                        "       sv.source_commit AS suite_source_commit,"
                        "       sv.manifest AS suite_manifest"
                        "  FROM task_revisions tr"
                        "  LEFT JOIN app_builds ab ON ab.id = tr.build_id"
                        "  LEFT JOIN suite_versions sv ON sv.id = tr.suite_version_id"
                        " WHERE tr.id = CAST(:rid AS uuid)"
                    ),
                    {"rid": str(view["revision_id"])},
                )
            ).mappings().one()
        )

    # 套件块只读不可变行：修订绑定的 suite_version 行 + 其 manifest.code_copy。
    # 缺失（旧修订没绑套件、或旧版本 manifest 没有副本摘要）一律 null，绝不拿
    # "当前版本"或来源目录现算的值冒充（工单 05 纪律）。
    suite = None
    if revision and revision["suite_version_row_id"]:
        code_copy = _code_copy_summary(revision["suite_manifest"])
        suite = {
            "id": str(revision["suite_version_row_id"]),
            "version": revision["suite_version"],
            "source_ref": revision["suite_source_ref"],
            "source_commit": revision["suite_source_commit"],
            "code_copy": code_copy,
        }

    profile = (
        await session.execute(
            text(
                "SELECT rp.id, rp.name, rp.fingerprint, rp.spec"
                "  FROM test_runs tr JOIN resource_profiles rp ON rp.id = tr.profile_id"
                " WHERE tr.id = CAST(:rid AS uuid)"
            ),
            {"rid": str(run_id)},
        )
    ).mappings().first()

    gates = (
        await session.execute(
            text(
                "SELECT ge.mode, ge.verdict, ge.reason_code, ge.created_at"
                "  FROM gate_evaluations ge"
                "  JOIN run_components rc"
                "    ON rc.project_id = ge.project_id AND rc.id = ge.component_id"
                " WHERE rc.run_id = CAST(:rid AS uuid)"
                " ORDER BY ge.created_at"
            ),
            {"rid": str(run_id)},
        )
    ).mappings().all()

    evidence = []
    for item in items:
        evidence.append(
            {
                "id": str(item["id"]),
                "kind": item["kind"],
                "logical_key": item["logical_key"],
                "mime_type": item.get("mime_type"),
                "byte_size": item.get("byte_size"),
                "sha256": item.get("sha256"),
                "availability": item["availability"],
                # 不可用原因（file_missing / retention_expired / storage_unresolvable），
                # 缺失或过期时报告与抽屉都能说明"为什么看不到"（AC-REP-03）
                "unavailable_reason": item.get("unavailable_reason"),
                "created_at": item.get("created_at"),
                # 只有 available 给下载入口；missing/expired 不提供假链接（AC-REP-03）
                "download_url": f"/api/v1/runs/{run_id}/artifacts/{item['id']}/download"
                if item["availability"] == "available"
                else None,
            }
        )

    return {
        # 报告里的编号与页面、导出、告警同源：都是持久分配的 display_id；
        # 精确身份仍由 id（UUID）承载（INV-10）。
        "runId": view["display_id"],
        "hostRunId": view["display_id"],
        "id": view["id"],
        "name": view["name"],
        "projectId": view["project_id"],
        "applicationId": view["application_id"],
        "platform": view["platform"],
        "environmentId": str(revision["environment_id"]) if revision else None,
        "resourceId": view["resource_id"],
        "resourceName": view["resource_name"],
        "module": view["module"],
        "status": view["state"],
        "verdict": view["outcome"],
        "target": view["application"],
        # 改名 / 归档前后读取同一历史运行：ID、修订快照、原始结论和证据不变；
        # 展示名明确标为「当前名称」，不伪装成运行当时的原始记录（工单 02/04，AC-09）。
        "currentNames": {
            "application": view["application"]["name"],
            "project": project_name,
        },
        "nameSource": "current_display_name",
        # 运行时档案（不可变行的内容）；没有就明说 null，不用设备 serial 冒充
        "resourceProfile": dict(profile) if profile else None,
        "deviceProfile": profile["name"] if profile else None,
        "revision": {
            "id": str(revision["id"]),
            "readiness": revision["readiness"],
            "test_type": revision["test_type"],
            "suite_version_id": str(revision["suite_version_id"])
            if revision["suite_version_id"]
            else None,
        }
        if revision
        else None,
        # 套件版本与其固定代码副本摘要（工单 05）：缺失为 null，不冒充
        "suite": suite,
        "build": {
            "id": str(revision["build_id"]),
            "version": revision["build_version"],
            "build_key": revision["build_key"],
            "source_commit": revision["build_commit"],
            "sha256": revision["build_sha256"],
        }
        if revision and revision["build_id"]
        else None,
        "components": view["components"],
        "gateEvaluations": [
            {
                "mode": g["mode"],
                "verdict": g["verdict"],
                "reason_code": g["reason_code"],
                "created_at": g["created_at"],
            }
            for g in gates
        ],
        "evidence": evidence,
        "durationS": view["duration_s"],
        "metricsSummary": source.get("metricsSummary") or {},
        "thresholdsAtRun": source.get("thresholdsAtRun") or {},
        # joint 的采集窗口（真实时间戳）：窗口必须覆盖 UI 执行窗，
        # 报告页据此说明"采集确实包围了这次 UI 执行"。
        "collectWindow": source.get("collectWindow"),
        "reason": view["reason_code"],
        "reasonText": view["not_tested_reason"] or view["reason_code"],
        "evaluatedAt": view["ended_at"],
        "mode": source.get("mode") or mode,
        "vendorReports": vendor_reports,
        "junit": source.get("junit") or {},
    }


@router.get("/runs/{run_id}/report")
async def get_run_report(
    run_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    """平台计算的报告（不是 vendor 报告原样透传）。"""
    return await _report_view(session, run_id)


@router.get("/runs/{run_id}/report/export")
async def export_run_report(
    run_id: str, session: AsyncSession = Depends(get_session)
) -> Response:
    """服务端导出：与报告快照同一份内容，稳定文件名，不含凭据或宿主路径。"""
    report = await _report_view(session, run_id)
    # 与 GET /report 走同一个 JSON 编码器：两边逐字段一致，导出才配叫"同一份快照"
    payload = json.dumps(jsonable_encoder(report), ensure_ascii=False)
    filename = "TestDock-%s.json" % report["runId"]
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    # 内部通道：允许 source=import 与 source_dir，且可省略 application_id（补录历史产物）
    created = await _insert_run(session, payload, internal=True)
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
