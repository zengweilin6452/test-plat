"""旧演示数据预览与受控处理（正式化改造工单 09）。

**默认只预览**：根据 seed 固定身份（uuid5 命名空间的稳定 ID）、原始字段和
关联关系识别候选，绝不仅按「星河」「Demo」名称判定。已改名 / 信息不足的
对象标为 needs_manual_review；真实同名项目不会被当成演示数据。

用户逐项确认后执行 keep / rename / archive：
- 执行前重新校验对象、占用与预览 token；过期或不确定的预览不执行；
- 保留并改名适用于已承载真实运行的演示项目；不搬移数据、不改身份、
  不重建历史；设备/节点等没有安全归档语义的记录只允许保留并说明；
- 重复执行稳定，不物理删除、不改修订 / 原始判定 / 产物路径 / 哈希；
- 不倒填旧数据来源标记；origin 只用于以后显式导入的数据（0009）。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..domain import identity as identity_mod
from ..errors import client_header_required, conflict

router = APIRouter(tags=["legacy-review"])

#: 与 scripts/seed_demo.py 一致；用于从固定身份识别原始 seed 行
SEED_NAMESPACE = uuid.UUID("6f1b2c34-0000-4000-8000-000000000000")
SEED_PROJECT_ID = str(uuid.uuid5(SEED_NAMESPACE, "project:testdock-demo"))
SEED_APP_IDS = {
    str(uuid.uuid5(SEED_NAMESPACE, "application:xinghe-android")),
    str(uuid.uuid5(SEED_NAMESPACE, "application:xinghe-ios")),
    str(uuid.uuid5(SEED_NAMESPACE, "application:xinghe-web")),
}
SEED_NODE_ID = str(uuid.uuid5(SEED_NAMESPACE, "node:local"))
SEED_RESOURCE_IDS = {
    str(uuid.uuid5(SEED_NAMESPACE, f"resource:res-{index:02d}")) for index in range(1, 7)
}
SEED_SUITE_IDS = {
    str(uuid.uuid5(SEED_NAMESPACE, f"suite:{key}"))
    for key in ("suite-core", "suite-auth", "suite-order", "suite-profile")
}
SEED_ORIGINAL_PROJECT_NAME = "星河 Demo"
SEED_ORIGINAL_IDENTIFIERS = {
    "com.example.xinghe",
    "com.example.xinghe.ios",
    "https://staging.example.test/",
}


class LegacyActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    entity: str
    action: str = Field(pattern="^(keep|rename|archive)$")
    name: str | None = None


class LegacyApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_token: str
    actions: list[LegacyActionIn]


async def _preview_items(session: AsyncSession) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    project = (
        await session.execute(
            text("SELECT id::text AS id, code, name, origin, archived_at FROM projects WHERE id::text = :id"),
            {"id": SEED_PROJECT_ID},
        )
    ).mappings().first()
    if project:
        runs = int((await session.execute(text("SELECT count(*) FROM test_runs WHERE project_id::text = :id"), {"id": project["id"]})).scalar() or 0)
        blockers = await identity_mod.collect_archive_blockers(session, entity="project", entity_id=project["id"])
        match_basis = ["固定 ID 与 seeds 命名空间一致", f"编码={project['code']}"]
        if project["name"] == SEED_ORIGINAL_PROJECT_NAME:
            match_basis.append("原始名称字段一致")
        if project["origin"] == "demo_seed":
            match_basis.append("显式演示导入标记")
        confidence = "confirmed" if project["name"] == SEED_ORIGINAL_PROJECT_NAME or project["origin"] == "demo_seed" else "needs_manual_review"
        items.append({
            "id": project["id"],
            "entity": "project",
            "name": SEED_ORIGINAL_PROJECT_NAME,
            "current_name": project["name"],
            "match_basis": match_basis,
            "confidence": confidence,
            "related_counts": {
                "applications": int((await session.execute(text("SELECT count(*) FROM applications WHERE project_id::text = :id"), {"id": project["id"]})).scalar() or 0),
                "test_runs": runs,
                "test_tasks": int((await session.execute(text("SELECT count(*) FROM test_tasks WHERE project_id::text = :id"), {"id": project["id"]})).scalar() or 0),
            },
            "has_real_runs": runs > 0,
            "active_occupancy": any(blockers.values()),
            "real_run_count": runs,
            "allowed_actions": ["keep", "rename", "archive"],
            "note": "已承载真实运行：建议保留并改名，不重建或迁移历史记录。" if runs else "未检测到真实运行；归档仍保留全部历史。",
            "archived": project["archived_at"] is not None,
        })

    app_rows = (
        await session.execute(
            text(
                "SELECT id::text AS id, project_id::text AS project_id, platform, name, identifier, origin, archived_at "
                "FROM applications WHERE id::text = ANY(:ids) OR identifier = ANY(:identifiers)"
            ),
            {"ids": list(SEED_APP_IDS), "identifiers": list(SEED_ORIGINAL_IDENTIFIERS)},
        )
    ).mappings().all()
    for row in app_rows:
        by_id = row["id"] in SEED_APP_IDS
        by_identifier = row["identifier"] in SEED_ORIGINAL_IDENTIFIERS
        runs = int((await session.execute(text("SELECT count(*) FROM test_runs WHERE application_id::text = :id"), {"id": row["id"]})).scalar() or 0)
        blockers = await identity_mod.collect_archive_blockers(session, entity="application", entity_id=row["id"])
        basis = []
        if by_id:
            basis.append("固定 ID 与 seeds 命名空间一致")
        if by_identifier:
            basis.append("原始标识字段一致")
        if row["origin"] == "demo_seed":
            basis.append("显式演示导入标记")
        # 仅名称命中（如真实项目刚好也叫星河）不认定为演示数据
        items.append({
            "id": row["id"],
            "entity": "application",
            "name": row["name"],
            "current_name": row["name"],
            "match_basis": basis or ["原始标识命中，但固定 ID 不一致：需人工判断"],
            "confidence": "confirmed" if (by_id and by_identifier) or row["origin"] == "demo_seed" else "needs_manual_review",
            "related_counts": {"test_runs": runs, "test_tasks": int((await session.execute(text("SELECT count(*) FROM test_tasks WHERE application_id::text = :id"), {"id": row["id"]})).scalar() or 0)},
            "has_real_runs": runs > 0,
            "active_occupancy": any(blockers.values()),
            "real_run_count": runs,
            "allowed_actions": ["keep", "rename", "archive"],
            "note": "历史 iOS / Web 应用保持可读；归档不会改写身份与证据。" if row["platform"] != "android" else "Android 应用已承载的真实运行继续保留。",
            "archived": row["archived_at"] is not None,
        })

    # 设备与执行节点：没有安全归档语义，只允许保留并说明
    resource_rows = (
        await session.execute(
            text(
                "SELECT id::text AS id, resource_key, status FROM execution_resources "
                "WHERE id::text = ANY(:ids) OR resource_key = ANY(:serials)"
            ),
            {
                "ids": list(SEED_RESOURCE_IDS),
                "serials": ["emulator-5554", "ABC123456789", "DEF123456789", "GHI123456789", "JKL123456789", "MNO123456789"],
            },
        )
    ).mappings().all()
    for row in resource_rows:
        items.append({
            "id": row["id"],
            "entity": "resource",
            "name": row["resource_key"],
            "current_name": row["resource_key"],
            "match_basis": ["固定 ID 与原 seed 设备 serial 一致"] if row["id"] in SEED_RESOURCE_IDS else ["原 seed 设备 serial 命中，需人工判断"],
            "confidence": "confirmed" if row["id"] in SEED_RESOURCE_IDS else "needs_manual_review",
            "related_counts": {"debug_sessions": int((await session.execute(text("SELECT count(*) FROM debug_sessions WHERE resource_id::text = :id"), {"id": row["id"]})).scalar() or 0)},
            "has_real_runs": False,
            "active_occupancy": False,
            "real_run_count": 0,
            "allowed_actions": ["keep"],
            "note": "设备记录没有安全归档语义，保持原状；如需清理请按运维流程单独处理。",
            "archived": False,
        })

    node = (
        await session.execute(
            text("SELECT id::text AS id, name FROM execution_nodes WHERE id::text = :id"),
            {"id": SEED_NODE_ID},
        )
    ).mappings().first()
    if node:
        items.append({
            "id": node["id"],
            "entity": "node",
            "name": node["name"],
            "current_name": node["name"],
            "match_basis": ["固定 ID 与原 seed 本机节点一致"],
            "confidence": "confirmed",
            "related_counts": {"execution_resources": int((await session.execute(text("SELECT count(*) FROM execution_resources WHERE node_id::text = :id"), {"id": node["id"]})).scalar() or 0)},
            "has_real_runs": False,
            "active_occupancy": False,
            "real_run_count": 0,
            "allowed_actions": ["keep"],
            "note": "执行节点没有安全归档语义，保持原状并说明。",
            "archived": False,
        })

    suite_rows = (
        await session.execute(
            text("SELECT id::text AS id, name, archived_at FROM test_suites WHERE id::text = ANY(:ids)"),
            {"ids": list(SEED_SUITE_IDS)},
        )
    ).mappings().all()
    for row in suite_rows:
        items.append({
            "id": row["id"],
            "entity": "suite",
            "name": row["name"],
            "current_name": row["name"],
            "match_basis": ["固定 ID 与原 seed 套件一致"],
            "confidence": "confirmed",
            "related_counts": {"suite_versions": int((await session.execute(text("SELECT count(*) FROM suite_versions WHERE suite_id::text = :id"), {"id": row["id"]})).scalar() or 0)},
            "has_real_runs": False,
            "active_occupancy": False,
            "real_run_count": 0,
            "allowed_actions": ["keep", "archive"],
            "note": "套件有归档字段；归档不影响既有版本清单与历史运行。",
            "archived": row["archived_at"] is not None,
        })
    return items


def _token(items: list[dict[str, Any]]) -> str:
    """预览指纹：执行前重新计算，对象或状态变化即过期，不执行。"""
    payload = "|".join(
        f"{item['id']}:{item['entity']}:{item['current_name']}:{item['confidence']}:"
        f"{item['has_real_runs']}:{item['active_occupancy']}:{item['archived']}"
        for item in sorted(items, key=lambda item: item["id"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@router.get("/legacy-review")
async def get_legacy_review(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    items = await _preview_items(session)
    return {"items": items, "total": len(items), "preview_token": _token(items)}


@router.post("/legacy-review/apply")
async def apply_legacy_review(
    body: LegacyApplyIn,
    client: str = Depends(client_header_required),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """逐项确认后执行；失败项返回具体原因，不物理删除，不改历史。"""
    current = await _preview_items(session)
    if body.preview_token != _token(current):
        raise conflict(
            "state_conflict",
            "预览已过期：对象名称、真实运行或活动占用在预览后发生了变化，请重新预览确认",
            {"reason": "stale_preview"},
        )
    by_id = {item["id"]: item for item in current}
    applied: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for action in body.actions:
        item = by_id.get(action.id)
        if item is None or item["entity"] != action.entity:
            rejected.append({"id": action.id, "reason": "对象不在本次预览清单中"})
            continue
        if action.action not in item["allowed_actions"]:
            rejected.append({"id": action.id, "reason": f"{item['entity']} 不支持 {action.action} 操作"})
            continue
        if item["confidence"] != "confirmed" and action.action != "keep":
            rejected.append({"id": action.id, "reason": "信息不足或对象已被修改，需人工判断后才能执行"})
            continue
        if item["active_occupancy"] and action.action == "archive":
            rejected.append({"id": action.id, "reason": "存在进行中的运行 / 调试 / 租约，不能归档"})
            continue
        if action.action == "keep":
            applied.append({"id": action.id, "action": "keep", "result": "保留原状（无写操作）"})
            continue
        if action.action == "rename":
            name = identity_mod.validate_name(action.name, entity=item["entity"])
            if item["entity"] == "project":
                await identity_mod.rename_project(session, action.id, name=name)
            elif item["entity"] == "application":
                await identity_mod.rename_application(session, action.id, name=name)
            else:
                rejected.append({"id": action.id, "reason": "该对象没有安全的改名语义"})
                continue
            applied.append({"id": action.id, "action": "rename", "result": name})
            continue
        if action.action == "archive":
            if item["archived"]:
                applied.append({"id": action.id, "action": "archive", "result": "已归档（重复操作无业务影响）"})
                continue
            if item["entity"] in ("project", "application"):
                await identity_mod.archive_entity(session, entity=item["entity"], entity_id=action.id)
            elif item["entity"] == "suite":
                await session.execute(
                    text("UPDATE test_suites SET archived_at = COALESCE(archived_at, now()) WHERE id::text = :id"),
                    {"id": action.id},
                )
            else:
                rejected.append({"id": action.id, "reason": "该对象没有安全的归档语义"})
                continue
            applied.append({"id": action.id, "action": "archive", "result": "已归档，历史记录与 ID 不变"})
    return {"applied": applied, "rejected": rejected, "preview_token": _token(current)}
