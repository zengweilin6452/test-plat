"""套件与套件版本的持久化操作。

表结构真源（0001_initial.py）
-----------------------------
- test_suites：id / project_id / application_id / name / test_type / archived_at / created_at。
  **没有"配置"列**，所以 discover 的 suite_root 只能来自请求体（见 routers/suites.py）。
- suite_versions：version 单调递增（UNIQUE(project_id, suite_id, version)），
  manifest jsonb（用例清单就存在这里，因为 schema 里没有 cases 表）。
  这些行是**不可变**的：重新 discover 只会追加新版本，绝不覆盖旧版本，
  否则已经绑定旧版本的任务会在无提示的情况下换掉用例集（审计灾难）。
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import suite as suite_domain
from ..errors import bad_request, not_found, validation_error
from .tasks import as_uuid

_SUITE_SQL = """
    SELECT s.id, s.project_id, s.application_id, s.name, s.test_type,
           s.archived_at, s.created_at,
           a.name AS application_name, a.platform,
           (SELECT count(*) FROM suite_versions sv WHERE sv.suite_id = s.id) AS version_count,
           latest.id AS latest_version_id,
           latest.version AS latest_version_no,
           latest.manifest AS latest_manifest,
           latest.created_at AS latest_created_at
      FROM test_suites s
      JOIN applications a ON a.id = s.application_id AND a.project_id = s.project_id
      LEFT JOIN LATERAL (
           SELECT sv.id, sv.version, sv.manifest, sv.created_at
             FROM suite_versions sv
            WHERE sv.suite_id = s.id
            ORDER BY sv.version DESC
            LIMIT 1
      ) latest ON TRUE
"""


def _suite_dict(row: Any) -> dict[str, Any]:
    latest_manifest = row["latest_manifest"]
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]),
        "name": row["name"],
        "test_type": row["test_type"],
        "application": {
            "id": str(row["application_id"]),
            "name": row["application_name"],
            "platform": row["platform"],
        },
        "created_at": row["created_at"],
        "archived_at": row["archived_at"],
        "version_count": int(row["version_count"] or 0),
        "latest_version": (
            {
                "id": str(row["latest_version_id"]),
                "version": row["latest_version_no"],
                "case_count": suite_domain.case_total(latest_manifest),
                "created_at": row["latest_created_at"],
            }
            if row["latest_version_id"] is not None
            else None
        ),
    }


def _version_dict(row: Any) -> dict[str, Any]:
    manifest = row["manifest"] or {}
    return {
        "id": str(row["id"]),
        "suite_id": str(row["suite_id"]),
        "version": row["version"],
        "source_ref": row["source_ref"],
        "source_commit": row["source_commit"],
        "case_count": suite_domain.case_total(manifest),
        "case_keys": suite_domain.case_keys(manifest),
        "manifest": manifest,
        "created_at": row["created_at"],
    }


async def list_suites(session: AsyncSession, *, test_type: str | None = None) -> dict[str, Any]:
    """套件列表；test_type 精确过滤，不做模糊匹配（枚举值只有三种）。"""
    params: dict[str, Any] = {}
    sql = _SUITE_SQL
    if test_type:
        if test_type not in suite_domain.TEST_TYPES:  # pragma: no cover - Literal 已挡
            raise validation_error([f"test_type 只支持 {', '.join(suite_domain.TEST_TYPES)}"])
        sql += " WHERE s.test_type = :test_type"
        params["test_type"] = test_type
    sql += " ORDER BY a.platform, s.name"
    rows = (await session.execute(text(sql), params)).mappings().all()
    items = [_suite_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


async def get_suite(session: AsyncSession, suite_id: str) -> Any:
    sid = as_uuid(suite_id)
    if sid is None:
        raise not_found("suite", suite_id)
    row = (await session.execute(text(_SUITE_SQL + " WHERE s.id = :sid"), {"sid": sid})).mappings().first()
    if row is None:
        raise not_found("suite", suite_id)
    return row


async def list_versions(session: AsyncSession, suite_id: str) -> dict[str, Any]:
    """套件版本列表：version 倒序（最新在前），与任务修订列表口径一致。"""
    sid = as_uuid(suite_id)
    if sid is None:
        raise not_found("suite", suite_id)
    exists = (await session.execute(text("SELECT 1 FROM test_suites WHERE id = :sid"), {"sid": sid})).first()
    if exists is None:
        raise not_found("suite", suite_id)
    rows = (
        await session.execute(
            text(
                "SELECT id, suite_id, version, source_ref, source_commit, manifest, created_at "
                "  FROM suite_versions WHERE suite_id = :sid ORDER BY version DESC"
            ),
            {"sid": sid},
        )
    ).mappings().all()
    return {"items": [_version_dict(r) for r in rows], "total": len(rows)}


async def create_version(
    session: AsyncSession,
    *,
    suite_row: Any,
    node_ids: list[str],
    source_ref: str | None,
    source_commit: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """追加一个 suite_version（不可变），manifest 里带上用例清单。

    version 序号用 MAX+1；UNIQUE(project_id, suite_id, version) 兜住并发重复。
    """
    project_id = str(suite_row["project_id"])
    suite_id = str(suite_row["id"])
    application_id = str(suite_row["application_id"])

    current_max = (
        await session.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM suite_versions WHERE suite_id = :sid"),
            {"sid": suite_id},
        )
    ).scalar_one()
    version_no = suite_domain.next_version(int(current_max or 0))
    manifest = suite_domain.build_manifest(node_ids, extra=extra)

    row = (
        await session.execute(
            text(
                """
                INSERT INTO suite_versions
                    (id, project_id, application_id, suite_id, version,
                     source_ref, source_commit, manifest)
                VALUES (:id, :pid, :aid, :sid, :ver, :ref, :commit, :manifest)
                RETURNING id, suite_id, version, source_ref, source_commit, manifest, created_at
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": project_id,
                "aid": application_id,
                "sid": suite_id,
                "ver": version_no,
                # 两列都是 NOT NULL，缺省给一个稳定可追溯的值而不是空串
                "ref": source_ref or f"suite:{suite_id}",
                "commit": source_commit or "local",
                "manifest": Jsonb(manifest),
            },
        )
    ).mappings().first()
    if row is None:  # pragma: no cover
        raise bad_request("创建套件版本失败")
    return _version_dict(row)
