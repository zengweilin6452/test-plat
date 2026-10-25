"""运行收敛：把"跑完了/跑挂了"落成 (产物 + 事件 + 状态 + 租约) 四件事。

为什么抽出来
------------
有 4 条路径会把 run 推到终态：
  1. runner 正常上报 /internal/runs/{id}/complete|fail
  2. runner 进程退出但没上报（崩溃、被 kill）
  3. reconciler 判定心跳超时
  4. POST /runs/import 降级通道

如果每条各自写一遍"登记产物 + 写事件 + transition + 释放租约"，它们一定会
慢慢长歪（比如某条忘了释放租约，设备就永久卡住）。这里只保留一份实现。

顺序（唯一正确顺序）
--------------------
  先登记产物 -> 再写事件 -> 再 transition 到终态 -> 最后释放租约

为什么产物必须在 state 变更之前：前端看到 completed 就会去请求 /artifacts，
若产物还没入库，页面就是"已完成但零产物"，且没有任何自愈机会。反过来，产物
先入库但状态没改（进程在中间崩），重跑一次 finalize 靠 logical_key 幂等即可。

为什么释放租约必须在最后：租约释放代表"设备空闲可被别的 run 领取"。如果先释放，
下一个 run 可能在旧 run 还在写产物时抢到同一台设备，证据目录就会互相污染。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text

from .config import settings
from .db import get_sessionmaker
from .domain import artifacts as artifacts_mod
from .domain import events as events_mod
from .domain import leases as leases_mod
from .domain import runs as runs_mod
from .integrations import leases as local_leases

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinalizeResult:
    """一次 finalize 的结果（测试断言用）。"""

    run_id: str
    state: str
    outcome: str | None
    artifact_count: int
    sha256s: dict[str, str]
    already_terminal: bool = False


async def _run_row(session, run_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id, project_id, state, outcome, resource_id, revision_id,
                       application_id, started_at
                  FROM test_runs WHERE id = :id
                """
            ),
            {"id": str(run_id)},
        )
    ).mappings().first()
    return dict(row) if row else None


def read_junit_summary(path: Path) -> dict[str, Any]:
    """从 junit.xml 取用例计数（不依赖第三方 XML 绑定）。"""
    if not path.exists():
        return {"present": False}
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return {"present": True, "parse_error": str(exc)}
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            try:
                totals[key] += int(suite.get(key) or 0)
            except ValueError:
                pass
    totals["present"] = True
    totals["failed"] = totals["failures"] + totals["errors"]
    return totals


def _terminal_expect_states(run: dict[str, Any], default: tuple[str, ...]) -> tuple[str, ...]:
    """终态迁移的前置状态集合。

    ck_test_runs_state_executing_needs_resource 要求 running / finalizing / completed
    必须有 resource_id 与 started_at。导入通道（POST /runs/import）没有设备，completed
    就插不进去 —— 它必须跳过执行态，直接 queued/dispatching -> completed。这里按行内
    事实裁剪，调用方不必各处重复判断。
    """
    if run.get("resource_id") and run.get("started_at"):
        return default
    trimmed: list[str] = []
    for state in default:
        if state in (runs_mod.STATE_RUNNING, runs_mod.STATE_FINALIZING):
            continue
        trimmed.append(state)
    for extra in (runs_mod.STATE_QUEUED, runs_mod.STATE_DISPATCHING):
        if extra not in trimmed:
            trimmed.append(extra)
    return tuple(trimmed)


def derive_outcome(
    *,
    state: str,
    explicit_outcome: str | None,
    junit: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> str | None:
    """收敛出最终 outcome。

    只在 state=completed 时给值（DB CHECK 兜底，绝不绕过）：
      - 显式给了 outcome 就用它
      - 否则看 junit：有失败 -> failed，有测试且全绿 -> passed
      - 既没 outcome 也没 junit 有用例 -> not_tested（并写 not_tested_reason）
    """
    if state != runs_mod.STATE_COMPLETED:
        return None
    if explicit_outcome in runs_mod.ALL_OUTCOMES:
        return explicit_outcome
    if junit and junit.get("present"):
        if int(junit.get("failed") or 0) > 0:
            return runs_mod.OUTCOME_FAILED
        if int(junit.get("tests") or 0) > 0:
            return runs_mod.OUTCOME_PASSED
        return runs_mod.OUTCOME_NOT_TESTED
    return runs_mod.OUTCOME_NOT_TESTED


async def finalize_run(
    *,
    run_id: str | uuid.UUID,
    state: str,
    outcome: str | None = None,
    reason: str | None = None,
    project_id: str | uuid.UUID | None = None,
    artifacts_dir: Path | str | None = None,
    release_lease_reason: str | None = None,
    extra_event: Mapping[str, Any] | None = None,
    expect_states: tuple[str, ...] = (
        runs_mod.STATE_DISPATCHING,
        runs_mod.STATE_RUNNING,
        runs_mod.STATE_FINALIZING,
    ),
    actor: str = "runtime",
) -> FinalizeResult:
    """把 run 收敛到终态。幂等：已是同一终态时直接返回 already_terminal。

    返回 FinalizeResult；state 不是终态时抛 409（由 domain.transition 给出）。
    """
    rid = str(run_id)
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        row = await _run_row(session, rid)
    if row is None:
        from .errors import not_found

        raise not_found("run", rid)
    pid = str(project_id or row["project_id"])

    if row["state"] in runs_mod.TERMINAL_STATES:
        return FinalizeResult(
            run_id=rid,
            state=row["state"],
            outcome=row["outcome"],
            artifact_count=0,
            sha256s={},
            already_terminal=True,
        )

    sha_map: dict[str, str] = {}
    artifact_count = 0
    junit: dict[str, Any] = {"present": False}

    if artifacts_dir is not None and Path(artifacts_dir).is_dir():
        junit = read_junit_summary(Path(artifacts_dir) / "junit.xml")

    final_outcome = derive_outcome(
        state=state, explicit_outcome=outcome, junit=junit, reason=reason
    )

    # 1) 先在**独立事务**里登记产物：产物只依赖磁盘，不依赖状态机的并发结果。
    #    即使后面 transition 因并发 409 失败，产物行也是幂等的（logical_key 去重）。
    if artifacts_dir is not None and Path(artifacts_dir).is_dir():
        async with sessionmaker() as session:
            async with session.begin():
                result = await artifacts_mod.finalize_artifacts(
                    session,
                    project_id=pid,
                    run_id=rid,
                    artifacts_dir=artifacts_dir,
                    artifacts_root=settings.artifacts_dir,
                )
        artifact_count = int(result["files"])
        sha_map = dict(result["sha256s"])

    not_tested_reason = reason if final_outcome == runs_mod.OUTCOME_NOT_TESTED else None

    # 2) 事件 + 状态 + 租约释放放在同一事务里
    async with sessionmaker() as session:
        async with session.begin():
            payload = {
                "stage": "finish",
                "state": state,
                "outcome": final_outcome,
                "reason": reason,
                "artifact_count": artifact_count,
                "junit": junit,
            }
            if extra_event:
                payload.update({str(k): v for k, v in extra_event.items()})
            await events_mod.append_event(
                session,
                project_id=pid,
                run_id=rid,
                source_key=events_mod.SOURCE_RECONCILER if actor == "reconciler" else "runtime",
                source_event_id=events_mod.event_id_for("finish", rid, state, reason),
                event_type="error" if state == runs_mod.STATE_ERRORED else "finish",
                payload=payload,
            )
            await runs_mod.transition(
                session,
                rid,
                _terminal_expect_states(row, expect_states),
                state,
                outcome=final_outcome,
                reason=not_tested_reason or reason,
                actor=actor,
            )
            if release_lease_reason:
                await leases_mod.release_lease(
                    session, run_id=rid, reason=release_lease_reason
                )

    # 3) 设备本机锁收尾（DB 租约已释放，本地锁也要清，否则下次派发会被误判 busy）
    await release_local_lock_for_run(rid)

    return FinalizeResult(
        run_id=rid,
        state=state,
        outcome=final_outcome,
        artifact_count=artifact_count,
        sha256s=sha_map,
    )


async def release_local_lock_for_run(run_id: str) -> bool:
    """清理该 run 占用设备的本机兜底锁。"""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        serial = (
            await session.execute(
                text(
                    """
                    SELECT er.resource_key
                      FROM test_runs tr
                      JOIN execution_resources er ON er.id = tr.resource_id
                     WHERE tr.id = :id
                    """
                ),
                {"id": str(run_id)},
            )
        ).scalar_one_or_none()
    if not serial:
        return False
    return local_leases.release(str(serial), settings.runtime_dir)


async def read_report_source(run_id: str | uuid.UUID) -> dict[str, Any] | None:
    """report 所需的 run + 应用 + 资源 + 组件快照（GET /runs/{id}/report 用）。"""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT tr.id, tr.project_id, tr.application_id, tr.platform,
                           tr.resource_id, tr.state, tr.outcome, tr.reason_code,
                           tr.not_tested_reason, tr.started_at, tr.ended_at,
                           tr.created_at, tr.revision_id, tr.config_snapshot,
                           a.name AS application_name, a.identifier AS app_identifier,
                           er.resource_key AS resource_name,
                           rp.name AS profile_name, rp.fingerprint AS profile_fingerprint,
                           trv.test_type
                      FROM test_runs tr
                      LEFT JOIN applications a ON a.id = tr.application_id
                      LEFT JOIN execution_resources er ON er.id = tr.resource_id
                      LEFT JOIN resource_profiles rp ON rp.id = tr.profile_id
                      LEFT JOIN task_revisions trv ON trv.id = tr.revision_id
                     WHERE tr.id = :id
                    """
                ),
                {"id": str(run_id)},
            )
        ).mappings().first()
    if not row:
        return None
    data = dict(row)
    # vendor 侧 report.json（业务指标 / 阈值快照）若已登记成产物，就把内容并进来，
    # 让 GET /report 的 metricsSummary / thresholdsAtRun 有真实来源，而不是空对象。
    data.update(_report_json_payload(str(run_id)))
    return data


def _report_json_payload(run_id: str) -> dict[str, Any]:
    """读取该 run 已登记的 report.json 产物内容（缺失时返回空字典）。

    这里用同步引擎：read_report_source 既被异步请求调用，也可能被同步 TestClient
    路径调用，同步引擎不挑事件循环策略（Windows Proactor 下 psycopg async 不可用）。
    """
    from sqlalchemy import create_engine

    try:
        engine = create_engine(str(settings.database_url))
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT storage_key FROM artifacts "
                        " WHERE run_id = :run_id AND kind = :kind "
                        "   AND logical_key LIKE :pattern "
                        " ORDER BY logical_key LIMIT 1"
                    ),
                    {"run_id": run_id, "kind": "report_json", "pattern": "%report.json"},
                ).first()
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001 - 报告是只读视图，取不到就降级为空
        return {}
    if not row:
        return {}
    path = artifacts_mod.resolve_storage_path(str(row[0]), settings.artifacts_dir)
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    # 只取报告需要的字段，避免把任意 JSON 原样塞进 API 响应
    picked: dict[str, Any] = {}
    if isinstance(payload.get("metricsSummary"), dict):
        picked["metricsSummary"] = payload["metricsSummary"]
    elif isinstance(payload.get("metrics"), dict):
        picked["metricsSummary"] = payload["metrics"]
    if isinstance(payload.get("thresholdsAtRun"), dict):
        picked["thresholdsAtRun"] = payload["thresholdsAtRun"]
    elif isinstance(payload.get("thresholds"), dict):
        picked["thresholdsAtRun"] = payload["thresholds"]
    if isinstance(payload.get("junit"), dict):
        picked["junit"] = payload["junit"]
    if payload.get("mode"):
        picked["mode"] = str(payload["mode"])
    return picked


__all__ = [
    "FinalizeResult",
    "_terminal_expect_states",
    "derive_outcome",
    "finalize_run",
    "read_junit_summary",
    "read_report_source",
    "release_local_lock_for_run",
]
