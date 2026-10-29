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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import suite as suite_domain
from ..errors import bad_request, discover_failed, not_found, validation_error
from ..integrations import discover as discover_integration
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


def _code_copy_api_error(exc: discover_integration.CodeCopyError):
    """CodeCopyError -> 422 discover_failed（details.reason 保留细分原因）。"""
    error = discover_failed(exc.message, [], None)
    error.extra_details = {**error.extra_details, "reason": exc.code, **exc.details}
    return error


def _resolve_code_copy(
    *, suite_test_type: str, extra: dict[str, Any] | None
) -> dict[str, Any] | None:
    """从 discover 结果里取固定代码副本摘要并复验。

    UI / joint 套件必须带 code_copy；performance 声明式场景允许没有代码来源。
    manifest 里不再保留宿主绝对路径（旧 extra.suite_root 被剥离）。
    """
    payload = dict(extra or {})
    suite_root = payload.pop("suite_root", None)
    code_copy = payload.pop("code_copy", None)
    if code_copy is None and suite_root:
        code_copy = discover_integration.load_code_copy_sidecar(Path(str(suite_root)))
    if code_copy is not None:
        try:
            discover_integration.verify_code_copy(code_copy)
        except discover_integration.CodeCopyError as exc:
            raise _code_copy_api_error(exc) from exc
    elif suite_test_type in ("ui", "joint"):
        raise discover_failed(
            "发现结果缺少固定代码副本摘要，未发布版本", [], None
        )
    return code_copy


async def create_version(
    session: AsyncSession,
    *,
    suite_row: Any,
    node_ids: list[str],
    source_ref: str | None,
    source_commit: str | None,
    extra: dict[str, Any] | None = None,
    version_id: str | None = None,
) -> dict[str, Any]:
    """追加一个 suite_version（不可变），manifest 里带上用例清单与固定代码副本。

    version 序号用 MAX+1；UNIQUE(project_id, suite_id, version) 兜住并发重复。
    extra 可带 discover 的 code_copy（或副本旁车路径 suite_root，会被剥离）；
    manifest 只保留相对文件清单与摘要，不写宿主绝对路径。
    """
    project_id = str(suite_row["project_id"])
    suite_id = str(suite_row["id"])
    application_id = str(suite_row["application_id"])

    payload = dict(extra or {})
    code_copy = _resolve_code_copy(
        suite_test_type=str(suite_row["test_type"]), extra=payload
    )
    # 剥离路由传入的宿主路径与旧摘要，manifest 只保留复验后的 code_copy。
    payload = {k: v for k, v in payload.items() if k not in {"suite_root", "code_copy"}}
    if code_copy is not None:
        payload["code_copy"] = code_copy

    current_max = (
        await session.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM suite_versions WHERE suite_id = :sid"),
            {"sid": suite_id},
        )
    ).scalar_one()
    version_no = suite_domain.next_version(int(current_max or 0))
    manifest = suite_domain.build_manifest(node_ids, extra=payload)

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
                "id": str(version_id or uuid.uuid4()),
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


async def prepare_execution_copy(
    session: AsyncSession, suite_version_id: str
) -> Path:
    """执行前解析并复验该版本的固定代码副本，返回副本根目录。

    缺失/损坏一律阻断（422 discover_failed），绝不回退到可变来源目录。
    旧版本没有 code_copy 时明确要求重新发现并创建新版本，不追认。
    """
    sid = as_uuid(suite_version_id)
    if sid is None:
        raise not_found("suite_version", suite_version_id)
    row = (
        await session.execute(
            text("SELECT id, manifest FROM suite_versions WHERE id = :sid"),
            {"sid": sid},
        )
    ).mappings().first()
    if row is None:
        raise not_found("suite_version", suite_version_id)
    manifest = row["manifest"] if isinstance(row["manifest"], dict) else {}
    code_copy = manifest.get("code_copy")
    if not isinstance(code_copy, dict):
        raise discover_failed(
            "该套件版本未保留固定代码副本，请重新发现并创建新版本", [], None
        )
    try:
        return discover_integration.verify_code_copy(code_copy)
    except discover_integration.CodeCopyError as exc:
        raise _code_copy_api_error(exc) from exc


# --------------------------------------------------------------------------- #
# 阶段预算（spec §9.5 / AC-CONTRACT-06）
# --------------------------------------------------------------------------- #
#: 宿主侧阶段预算默认值（秒）。vendor 的启动/停止超时常量约 180/300，
#: 这里给准备 180、启动采集 180、停止 300、归档 120，再加 60s 余量。
DEFAULT_STAGE_BUDGET: dict[str, int] = {
    "prepare_s": 180,
    "collect_start_s": 180,
    "stop_s": 300,
    "archive_s": 120,
    "margin_s": 60,
}


@dataclass(frozen=True)
class StageBudget:
    """一次执行的宿主阶段预算；总 deadline = 执行窗 + 各阶段 + 余量。"""

    prepare_s: int = 180
    collect_start_s: int = 180
    stop_s: int = 300
    archive_s: int = 120
    margin_s: int = 60

    @classmethod
    def default(cls) -> StageBudget:
        return cls(**DEFAULT_STAGE_BUDGET)

    @property
    def host_stage_total_s(self) -> int:
        return (
            self.prepare_s
            + self.collect_start_s
            + self.stop_s
            + self.archive_s
            + self.margin_s
        )

    def deadline_s(self, *, execution_window_s: int) -> int:
        """覆盖执行窗与全部阶段的宿主总 deadline（不得小于执行窗）。"""
        return max(0, int(execution_window_s)) + self.host_stage_total_s

    def validate(self, *, execution_window_s: int, host_timeout_s: int) -> int:
        """宿主预算不足时明确拒绝，返回需要的总 deadline。

        `run_timeout_s=3600` 不能再被当成"执行窗 + 阶段预算"的总和；
        合法 3600s 执行窗要求宿主总预算 >= 3600 + 阶段预算。
        """
        required = self.deadline_s(execution_window_s=execution_window_s)
        if int(host_timeout_s) < required:
            raise validation_error(
                [
                    f"宿主总预算 {int(host_timeout_s)}s 不足以覆盖执行窗 "
                    f"{int(execution_window_s)}s 与阶段预算 {self.host_stage_total_s}s"
                    f"（至少需要 {required}s）"
                ]
            )
        return required


def plan_execution_budget(
    *,
    duration_s: int | float | None = None,
    ui_timeout_s: int | float | None = None,
    host_timeout_s: int,
    stage_budget: StageBudget | None = None,
) -> dict[str, int]:
    """提交/派发前的预算校验：执行窗取 UI/性能两者较大值，阶段预算另行叠加。"""
    window = max(int(duration_s or 0), int(ui_timeout_s or 0))
    budget = stage_budget or StageBudget.default()
    deadline = budget.validate(execution_window_s=window, host_timeout_s=host_timeout_s)
    return {
        "execution_window_s": window,
        "host_stage_total_s": budget.host_stage_total_s,
        "host_deadline_s": deadline,
        "host_timeout_s": int(host_timeout_s),
    }
