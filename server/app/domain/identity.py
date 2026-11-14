"""项目与应用管理域逻辑（正式化改造工单 02/04）。

身份规则（ADR-0001）：
- 项目编码创建时去空白并统一小写，1–60 位 [a-z0-9-]，首位字母或数字，创建后不可修改；
- 显示名称去空白后 1–60 字符，可修改；
- 应用：所属项目、目标端、标识创建后不可修改；新建仅开放 android（沿用
  services/builds.PACKAGE_NAME_RE 的包名形状校验）；历史 iOS/Web 数据保持可读。
- 归档不是删除：唯一键被归档记录继续占用；重复归档/恢复幂等返回稳定结果。

归档守卫（规格 §5.2）：
- 非终态运行、未关闭调试会话、未释放租约任一存在即拒绝归档，blockers 给出具体对象；
- 项目归档检查整个项目；应用归档检查其运行；调试会话无法归属应用，
  会话占用项目设备时保守阻止应用归档并说明会话；
- 归档与运行提交共用行级锁：assert_scope_active 以 FOR UPDATE 锁身份行再校验
  archived_at，普通并发下归档提交后不可能再插入该范围的新运行。
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import (
    archive_blocked,
    bad_request,
    conflict,
    identity_conflict,
    not_found,
    object_archived,
)
from ..services.builds import PACKAGE_NAME_RE

#: 显示名称长度边界（规格 §4，前后端一致）
NAME_MIN_LEN = 1
NAME_MAX_LEN = 60

#: 项目编码：1–60 位小写字母/数字/短横线，首位字母或数字（创建时已去空白、转小写）
PROJECT_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")

#: 本轮新建应用仅开放的目标端；iOS/Web 历史数据保持可读
CREATABLE_PLATFORMS: frozenset[str] = frozenset({"android"})

#: 归档检查中的「进行中」运行状态（终态之外全部算占用）
ACTIVE_RUN_STATES: tuple[str, ...] = ("queued", "dispatching", "running", "finalizing")

#: 未关闭的调试会话状态
OPEN_SESSION_STATES: tuple[str, ...] = ("opening", "active", "closing")


def normalize_name(value: Any) -> str:
    """去首尾空白；空值 / 超长由调用方拒绝。"""
    return str(value or "").strip()


def validate_name(value: Any, *, entity: str) -> str:
    name = normalize_name(value)
    if not (NAME_MIN_LEN <= len(name) <= NAME_MAX_LEN):
        raise bad_request(
            f"{entity}名称需为 1-60 个字符（去首尾空白）",
            {"field": "name", "length": len(name)},
        )
    return name


def normalize_code(value: Any) -> str:
    return normalize_name(value).lower()


def validate_project_code(value: Any) -> str:
    code = normalize_code(value)
    if not PROJECT_CODE_RE.match(code):
        raise bad_request(
            "项目编码需为 1-60 位小写字母、数字或短横线，且以字母或数字开头",
            {"field": "code"},
        )
    return code


def validate_package_identifier(value: Any) -> str:
    """Android 应用标识沿用既有包名白名单（services/builds.PACKAGE_NAME_RE）。"""
    identifier = normalize_name(value)
    if PACKAGE_NAME_RE.match(identifier) is None:
        raise bad_request(
            f"Android 应用标识 {identifier!r} 不是合法包名（如 com.example.app）",
            {"field": "identifier"},
        )
    return identifier


# --------------------------------------------------------------------------- #
# 项目
# --------------------------------------------------------------------------- #
async def create_project(session: AsyncSession, *, code: Any, name: Any) -> dict[str, Any]:
    project_code = validate_project_code(code)
    display_name = validate_name(name, entity="项目")
    existing = (
        await session.execute(
            text("SELECT id, name, archived_at FROM projects WHERE code = :code"),
            {"code": project_code},
        )
    ).mappings().first()
    if existing is not None:
        raise identity_conflict(
            "project",
            str(existing["id"]),
            f"项目编码 {project_code!r} 已被「{existing['name']}」占用（归档记录同样占用编码）；"
            "请查看原对象或改用其他编码",
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO projects (id, code, name) VALUES (:id, :code, :name) "
                "RETURNING id, code, name, archived_at, created_at"
            ),
            {"id": str(uuid.uuid4()), "code": project_code, "name": display_name},
        )
    ).mappings().one()
    await session.execute(
        text("INSERT INTO environments (id, project_id, name) VALUES (:id, :project_id, 'default')"),
        {"id": str(uuid.uuid4()), "project_id": str(row["id"])},
    )
    return dict(row)


async def rename_project(session: AsyncSession, project_id: str, *, name: Any) -> dict[str, Any]:
    display_name = validate_name(name, entity="项目")
    row = (
        await session.execute(
            text(
                "UPDATE projects SET name = :name WHERE id::text = :id "
                "RETURNING id, code, name, archived_at, created_at"
            ),
            {"name": display_name, "id": project_id},
        )
    ).mappings().first()
    if row is None:
        raise not_found("project", project_id)
    return dict(row)


# --------------------------------------------------------------------------- #
# 应用
# --------------------------------------------------------------------------- #
async def create_application(
    session: AsyncSession, *, project_id: Any, platform: Any, name: Any, identifier: Any
) -> dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        raise bad_request("application 必须属于一个项目", {"field": "project_id"})
    if platform not in CREATABLE_PLATFORMS:
        raise bad_request(
            "当前仅支持登记 Android 应用；iOS / Web 尚未支持执行能力",
            {"field": "platform", "allowed": sorted(CREATABLE_PLATFORMS)},
        )
    display_name = validate_name(name, entity="应用")
    package = validate_package_identifier(identifier)

    project = (
        await session.execute(
            text("SELECT id, name, archived_at FROM projects WHERE id::text = :id"),
            {"id": pid},
        )
    ).mappings().first()
    if project is None:
        raise not_found("project", pid)
    if project["archived_at"] is not None:
        raise object_archived("project", pid, project["name"])

    existing = (
        await session.execute(
            text(
                "SELECT id, name, archived_at FROM applications "
                "WHERE project_id::text = :pid AND platform = :platform AND identifier = :identifier"
            ),
            {"pid": pid, "platform": platform, "identifier": package},
        )
    ).mappings().first()
    if existing is not None:
        raise identity_conflict(
            "application",
            str(existing["id"]),
            f"同一项目与目标端下已存在标识为 {package} 的应用「{existing['name']}」"
            "（归档记录同样占用标识）；请查看原对象或改用其他标识",
        )

    row = (
        await session.execute(
            text(
                "INSERT INTO applications (id, project_id, platform, name, identifier) "
                "VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :platform, :name, :identifier) "
                "RETURNING id, project_id, platform, name, identifier, archived_at, created_at"
            ),
            {"id": str(uuid.uuid4()), "pid": pid, "platform": platform, "name": display_name, "identifier": package},
        )
    ).mappings().one()
    return dict(row)


async def rename_application(
    session: AsyncSession, application_id: str, *, name: Any
) -> dict[str, Any]:
    display_name = validate_name(name, entity="应用")
    row = (
        await session.execute(
            text(
                "UPDATE applications SET name = :name WHERE id::text = :id "
                "RETURNING id, project_id, platform, name, identifier, archived_at, created_at"
            ),
            {"name": display_name, "id": application_id},
        )
    ).mappings().first()
    if row is None:
        raise not_found("application", application_id)
    return dict(row)


# --------------------------------------------------------------------------- #
# 归档守卫：占用清单与业务写入保护
# --------------------------------------------------------------------------- #
async def _project_blockers(session: AsyncSession, project_id: str) -> dict[str, list[dict[str, Any]]]:
    active_ph = ", ".join(f"'{s}'" for s in ACTIVE_RUN_STATES)
    open_ph = ", ".join(f"'{s}'" for s in OPEN_SESSION_STATES)
    runs = (
        await session.execute(
            text(
                "SELECT id::text AS id, state, display_no FROM test_runs "
                f"WHERE project_id::text = :pid AND state IN ({active_ph}) ORDER BY created_at LIMIT 20"
            ),
            {"pid": project_id},
        )
    ).mappings().all()
    sessions = (
        await session.execute(
            text(
                "SELECT s.id::text AS id, s.state, s.resource_id::text AS resource_id "
                f"FROM debug_sessions s WHERE s.project_id::text = :pid AND s.state IN ({open_ph}) "
                "ORDER BY s.created_at LIMIT 20"
            ),
            {"pid": project_id},
        )
    ).mappings().all()
    leases = (
        await session.execute(
            text(
                "SELECT l.id::text AS id, l.resource_id::text AS resource_id, l.run_id::text AS run_id, "
                "l.debug_session_id::text AS debug_session_id FROM resource_leases l "
                "WHERE l.project_id::text = :pid AND l.released_at IS NULL AND l.expires_at > now() "
                "ORDER BY l.created_at LIMIT 20"
            ),
            {"pid": project_id},
        )
    ).mappings().all()
    return {
        "active_runs": [dict(r) for r in runs],
        "open_debug_sessions": [dict(s) for s in sessions],
        "active_leases": [dict(lease) for lease in leases],
    }


async def collect_archive_blockers(
    session: AsyncSession, *, entity: str, entity_id: str
) -> dict[str, list[dict[str, Any]]]:
    """归档影响检查：项目看整个项目；应用看自己的运行，会话与租约按项目保守检查。"""
    if entity == "project":
        return await _project_blockers(session, entity_id)
    if entity == "application":
        row = (
            await session.execute(
                text("SELECT project_id::text AS pid FROM applications WHERE id::text = :id"),
                {"id": entity_id},
            )
        ).mappings().first()
        if row is None:
            raise not_found("application", entity_id)
        pid = row["pid"]
        active_ph = ", ".join(f"'{s}'" for s in ACTIVE_RUN_STATES)
        runs = (
            await session.execute(
                text(
                    "SELECT id::text AS id, state, display_no FROM test_runs "
                    f"WHERE application_id::text = :aid AND state IN ({active_ph}) ORDER BY created_at LIMIT 20"
                ),
                {"aid": entity_id},
            )
        ).mappings().all()
        # 调试会话没有应用归属列：项目内存在未关闭会话时保守阻止应用归档（规格 §5.2）
        open_ph = ", ".join(f"'{s}'" for s in OPEN_SESSION_STATES)
        sessions = (
            await session.execute(
                text(
                    "SELECT s.id::text AS id, s.state, s.resource_id::text AS resource_id "
                    f"FROM debug_sessions s WHERE s.project_id::text = :pid AND s.state IN ({open_ph}) "
                    "ORDER BY s.created_at LIMIT 20"
                ),
                {"pid": pid},
            )
        ).mappings().all()
        leases = (
            await session.execute(
                text(
                    "SELECT l.id::text AS id, l.resource_id::text AS resource_id, l.run_id::text AS run_id, "
                    "l.debug_session_id::text AS debug_session_id FROM resource_leases l "
                    "WHERE l.project_id::text = :pid AND l.released_at IS NULL AND l.expires_at > now() "
                    "ORDER BY l.created_at LIMIT 20"
                ),
                {"pid": pid},
            )
        ).mappings().all()
        return {
            "active_runs": [dict(r) for r in runs],
            "open_debug_sessions": [dict(s) for s in sessions],
            "active_leases": [dict(lease) for lease in leases],
        }
    raise ValueError(f"未知的归档实体: {entity}")


def _has_blockers(blockers: dict[str, list[dict[str, Any]]]) -> bool:
    return any(blockers.values())


async def archive_entity(
    session: AsyncSession, *, entity: str, entity_id: str
) -> dict[str, Any]:
    """归档项目或应用。幂等：已归档返回稳定结果；被占用 409 archive_blocked。

    事务内先锁身份行再检查占用，UPDATE 条件带 archived_at IS NULL，
    与 assert_scope_active 的 FOR UPDATE 形成同一把锁：归档提交后，
    运行提交的锁读必然看到 archived_at 非空。
    """
    table = "projects" if entity == "project" else "applications"
    locked = (
        await session.execute(
            text(f"SELECT id, name, archived_at FROM {table} WHERE id::text = :id FOR UPDATE"),
            {"id": entity_id},
        )
    ).mappings().first()
    if locked is None:
        raise not_found(entity, entity_id)
    if locked["archived_at"] is not None:
        return {"id": entity_id, "name": locked["name"], "archived_at": locked["archived_at"], "already": True}

    blockers = await collect_archive_blockers(session, entity=entity, entity_id=entity_id)
    if _has_blockers(blockers):
        raise archive_blocked(entity, entity_id, blockers)

    updated = (
        await session.execute(
            text(
                f"UPDATE {table} SET archived_at = now() "
                "WHERE id::text = :id AND archived_at IS NULL "
                "RETURNING id, name, archived_at"
            ),
            {"id": entity_id},
        )
    ).mappings().one()
    return {"id": str(updated["id"]), "name": updated["name"], "archived_at": updated["archived_at"], "already": False}


async def restore_entity(
    session: AsyncSession, *, entity: str, entity_id: str
) -> dict[str, Any]:
    """恢复项目或应用。父项目仍归档时拒绝恢复子应用（规格 §5.2）。"""
    if entity == "application":
        parent = (
            await session.execute(
                text(
                    "SELECT p.id::text AS id, p.name, p.archived_at "
                    "FROM applications a JOIN projects p ON p.id = a.project_id "
                    "WHERE a.id::text = :id"
                ),
                {"id": entity_id},
            )
        ).mappings().first()
        if parent is not None and parent["archived_at"] is not None:
            raise conflict(
                "state_conflict",
                f"所属项目「{parent['name']}」仍处于归档状态，请先恢复项目",
                {"project_id": parent["id"], "reason": "project_archived"},
            )
    table = "projects" if entity == "project" else "applications"
    previous = (
        await session.execute(
            text(f"SELECT archived_at FROM {table} WHERE id::text = :id FOR UPDATE"),
            {"id": entity_id},
        )
    ).mappings().first()
    if previous is None:
        raise not_found(entity, entity_id)
    already = previous["archived_at"] is None
    updated = (
        await session.execute(
            text(
                f"UPDATE {table} SET archived_at = NULL WHERE id::text = :id "
                "RETURNING id, name, archived_at"
            ),
            {"id": entity_id},
        )
    ).mappings().first()
    if updated is None:
        raise not_found(entity, entity_id)
    return {
        "id": str(updated["id"]),
        "name": updated["name"],
        "archived_at": updated["archived_at"],
        "already": already,
    }


async def archive_impact(
    session: AsyncSession, *, entity: str, entity_id: str
) -> dict[str, Any]:
    """归档预览：关联记录数量与当前占用（不执行归档）。"""
    if entity == "project":
        row = (
            await session.execute(
                text("SELECT id, code, name, archived_at FROM projects WHERE id::text = :id"),
                {"id": entity_id},
            )
        ).mappings().first()
        if row is None:
            raise not_found("project", entity_id)
        counts = dict(
            (
                await session.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM test_runs WHERE project_id::text = :id) AS runs, "
                        "(SELECT count(*) FROM test_tasks WHERE project_id::text = :id) AS tasks, "
                        "(SELECT count(*) FROM applications WHERE project_id::text = :id) AS applications, "
                        "(SELECT count(*) FROM app_builds WHERE project_id::text = :id) AS builds, "
                        "(SELECT count(*) FROM test_suites WHERE project_id::text = :id) AS suites, "
                        "(SELECT count(*) FROM debug_sessions WHERE project_id::text = :id) AS debug_sessions, "
                        "(SELECT count(*) FROM execution_resources WHERE project_id::text = :id) AS resources"
                    ),
                    {"id": entity_id},
                )
            )
            .mappings()
            .one()
        )
    else:
        row = (
            await session.execute(
                text(
                    "SELECT a.id, a.project_id::text AS project_id, a.platform, a.name, a.identifier, a.archived_at "
                    "FROM applications a WHERE a.id::text = :id"
                ),
                {"id": entity_id},
            )
        ).mappings().first()
        if row is None:
            raise not_found("application", entity_id)
        counts = dict(
            (
                await session.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM test_runs WHERE application_id::text = :id) AS runs, "
                        "(SELECT count(*) FROM test_tasks WHERE application_id::text = :id) AS tasks, "
                        "(SELECT count(*) FROM app_builds WHERE application_id::text = :id) AS builds, "
                        "(SELECT count(*) FROM test_suites WHERE application_id::text = :id) AS suites"
                    ),
                    {"id": entity_id},
                )
            )
            .mappings()
            .one()
        )
    blockers = await collect_archive_blockers(session, entity=entity, entity_id=entity_id)
    return {
        "entity": entity,
        "object": dict(row),
        "related_counts": counts,
        "blockers": blockers,
        "archived": row["archived_at"] is not None,
    }


async def assert_scope_active(
    session: AsyncSession,
    *,
    project_id: str | None = None,
    application_id: str | None = None,
) -> None:
    """业务写入守卫：锁身份行并确认项目 / 应用未归档。

    所有「归档后不得开展新业务」的入口（运行提交、任务写、构建/套件/基线登记、
    调试会话创建）都必须先经过这里。FOR UPDATE 与归档事务互斥，
    覆盖「提交运行与归档相遇」的普通并发场景。
    """
    if application_id:
        app_row = (
            await session.execute(
                text(
                    "SELECT a.id, a.name, a.archived_at, a.project_id::text AS project_id "
                    "FROM applications a WHERE a.id::text = :id FOR UPDATE"
                ),
                {"id": str(application_id)},
            )
        ).mappings().first()
        if app_row is None:
            raise not_found("application", str(application_id))
        if app_row["archived_at"] is not None:
            raise object_archived("application", str(app_row["id"]), app_row["name"])
        if project_id and str(project_id) != app_row["project_id"]:
            raise bad_request(
                "应用与项目不匹配：请检查提交的 project / application 组合",
                {"project_id": str(project_id), "application_id": str(application_id)},
            )
        project_id = app_row["project_id"]
    if project_id:
        project_row = (
            await session.execute(
                text("SELECT id, name, archived_at FROM projects WHERE id::text = :id FOR UPDATE"),
                {"id": str(project_id)},
            )
        ).mappings().first()
        if project_row is None:
            raise not_found("project", str(project_id))
        if project_row["archived_at"] is not None:
            raise object_archived("project", str(project_row["id"]), project_row["name"])
