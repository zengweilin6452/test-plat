"""dispatcher：每 2s 领 queued 并 spawn runner（development-plan.md §7.1）。

一次派发的事务边界
------------------
领取设备（行锁 + fence_counter+1 + 插租约）和 state=dispatching 必须在**同一个
事务**里。分开写的话会存在一个窗口：租约已建、run 还是 queued —— 此时
reconciler 看到 queued 却没人领，或者反过来看到租约有主而 run 没动，两种误判
都会把好好的任务打成 errored。

设备忙与设备不可用
------------------
ready 设备被租约占用或并发领取时保留 queued；指定设备不会被其它空闲设备替换。
指定设备时按原因分开收敛，避免排查时把"指错设备"当成"设备掉线"：

  requested_device_not_found           设备不存在或不属于本项目
  requested_device_platform_mismatch   设备存在但平台与运行不符
  device_unavailable                   设备存在但非 ready（离线/未授权/维护）
  resource_busy                        设备可用只是暂时被占 —— 留在 queued

未指定设备时只可能是"没有 ready 设备"(device_unavailable) 或暂时被占
(resource_busy)。前三种都不可重试，直接 errored。

为什么 spawn 失败要回滚成 errored 且必须释放租约
------------------------------------------------
runner 起不来（python 路径错、vendor 缺依赖）是**平台故障**，不是设备故障。
此时必须先把租约释放掉，否则这台设备会被一个从未启动的 run 永久占住 ——
这是 P3 最容易踩的坑。
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from ..config import settings
from ..db import get_sessionmaker
from ..domain import events as events_mod
from ..domain import leases as leases_mod
from ..domain import runs as runs_mod
from ..domain.templates import pinned_templates, verify_template_pins
from ..integrations import leases as local_leases
from ..runner import dispatch_runner

if TYPE_CHECKING:  # 只为注解；运行时保持 services 的懒导入
    from ..services.suites import ExecutionCopy

logger = logging.getLogger(__name__)

DISPATCH_INTERVAL_SECONDS = 2.0
DISPATCH_BATCH = 8
HOLDER_PREFIX = "dispatcher"


@dataclass
class DispatchOutcome:
    """一次派发的可观测结果（测试与日志都用它，不依赖返回值字符串）。"""

    run_id: str
    ok: bool
    reason: str = ""
    lease: dict[str, Any] | None = None


_QUEUED_SQL = text(
    """
    SELECT tr.id, tr.project_id, tr.platform, tr.application_id, tr.revision_id,
           tr.config_snapshot
      FROM test_runs tr
     WHERE tr.state = 'queued'
       -- 导入运行（POST /runs/import）先以 queued 提交、后在本请求里 finalize；
       -- 这个窗口若被 dispatcher 领走，外部产物会被当成真跑派给 runner。
       -- source 记在 config_snapshot JSON 里，没有独立列，用 ->> 判别（NULL 安全）。
       AND (tr.config_snapshot->>'source') IS DISTINCT FROM 'import'
     ORDER BY tr.created_at, tr.id
     LIMIT :limit
    """
)


async def _resolve_config(session, run: dict[str, Any]) -> dict[str, Any]:
    """合并 config_snapshot 与运行所需的最小上下文（应用标识、串口等）。"""
    snapshot = run.get("config_snapshot") or {}
    if isinstance(snapshot, str):
        import json

        try:
            snapshot = json.loads(snapshot)
        except ValueError:
            snapshot = {}
    app_row = (
        await session.execute(
            text("SELECT name, identifier FROM applications WHERE id = :id"),
            {"id": str(run["application_id"])},
        )
    ).mappings().first()
    merged: dict[str, Any] = dict(snapshot)
    merged.setdefault("platform", run.get("platform"))
    if app_row:
        merged.setdefault("application_name", app_row["name"])
        merged.setdefault("app_package", app_row["identifier"])
    return merged


async def _prepare_suite_copy(session, revision_id: str) -> ExecutionCopy | None:
    """解析修订引用的套件版本并复验固定代码副本，返回 ExecutionCopy。

    返回结构里带 suite_version_id 与 tree_sha256，避免调用方二次查询或自己
    重算摘要（摘要真源只有 discover 一处）。

    performance 是声明式场景（工单 06）：套件版本按设计没有代码副本，也没有
    用例要跑，所以返回 None——不伪造副本根，也不把"没有副本"当成故障。
    ui / joint 仍必须有固定副本：缺了照旧抛错，由调用方收敛成
    errored(execution_copy_missing)。
    """
    if not revision_id:
        raise ValueError("修订缺失，无法定位套件版本")
    row = (
        await session.execute(
            text(
                "SELECT suite_version_id, test_type FROM task_revisions"
                " WHERE id = CAST(:rid AS uuid)"
            ),
            {"rid": revision_id},
        )
    ).mappings().first()
    if row is None:
        raise ValueError(f"修订 {revision_id} 不存在")
    if str(row["test_type"] or "") == "performance":
        return None
    from ..services import suites as suite_service

    if row["suite_version_id"] is None:
        raise ValueError("修订未绑定套件版本")
    return await suite_service.prepare_execution_copy(session, str(row["suite_version_id"]))


async def _verify_build_identity(run_id: str, *, serial: str) -> dict[str, Any]:
    """运行租约内复核构建安装身份（只读 dumpsys，不安装不修改）。

    返回 {verdict, detail, reason, ...}，verdict 取值与派发动作：
    - skipped：修订未绑定构建 / 构建身份未学习（pending）/ 基准不完整
      —— 无从复核，不阻断也不冒充通过；
    - verified：包名、versionName（及基准里的 versionCode）与固定基准一致；
    - mismatch：设备上的安装身份与基准不一致 —— 阻断；
    - unreadable：adb 不可读、包未安装或 dumpsys 没有 versionName —— 阻断。

    核对等级只到设备上已安装包的字段；不声称 APK 文件摘要已验证。
    """
    from ..integrations import devices as adb_integration

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT tr.build_id, b.metadata
                      FROM test_runs r
                      LEFT JOIN task_revisions tr ON tr.id = r.revision_id
                      LEFT JOIN app_builds b ON b.id = tr.build_id
                     WHERE r.id = CAST(:rid AS uuid)
                    """
                ),
                {"rid": run_id},
            )
        ).mappings().first()
    if row is None or row["build_id"] is None:
        return {
            "verdict": "skipped",
            "reason": "no_build",
            "detail": "修订未绑定构建，运行前无从复核安装身份",
        }
    metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
    identity = metadata.get("identity") if isinstance(metadata, dict) else None
    # 基准在 confirm 时固定到 identity.baseline（工单 04）；state != confirmed
    # 视为"身份未学习"——不冒充通过，也不阻断（无从复核）。
    if not isinstance(identity, dict) or identity.get("state") != "confirmed":
        return {
            "verdict": "skipped",
            "reason": "build_identity_pending",
            "detail": "构建身份尚未确认，运行前无从复核设备安装版本",
        }
    declared = identity.get("baseline")
    if not isinstance(declared, dict) or not declared.get("package_name"):
        return {
            "verdict": "skipped",
            "reason": "baseline_missing",
            "detail": "构建身份缺少固定基准（包名），运行前无从复核",
        }

    package = str(declared["package_name"])
    # 包名进的是 `adb shell "<命令>"` 的单个参数：必须先按包名白名单校验，
    # 否则基准里被写入的 `; reboot` 之类会被设备端 shell 解释执行（只读边界）。
    from ..services.builds import PACKAGE_NAME_RE

    if PACKAGE_NAME_RE.match(package) is None:
        return {
            "verdict": "unreadable",
            "reason": "package_name_invalid",
            "detail": f"固定基准里的包名 {package!r} 不是合法 Android 包名，拒绝拼入只读命令",
            "package_name": package,
            "serial": serial,
        }
    expected = str(declared.get("version_name") or "").strip()
    expected_code = declared.get("version_code")
    if not expected:
        return {
            "verdict": "skipped",
            "reason": "baseline_incomplete",
            "detail": "固定基准缺少 versionName，运行前无从复核",
            "package_name": package,
        }
    result: dict[str, Any] = {
        "package_name": package,
        "expected_version_name": expected,
        "expected_version_code": expected_code,
        "serial": serial,
    }
    try:
        adb_path = adb_integration.resolve_adb_path()
        raw = await asyncio.to_thread(
            adb_integration._run,  # noqa: SLF001 - 与 readiness 共用只读 adb 入口
            adb_path,
            ["-s", serial, "shell", f"dumpsys package {package}"],
            timeout_s=15,
        )
    except Exception as exc:  # noqa: BLE001 - 不可读阻断
        return {
            **result,
            "verdict": "unreadable",
            "reason": "adb_read_failed",
            "detail": f"无法读取设备 {serial} 的安装身份：{exc}",
        }
    if re.search(rf"Package \[{re.escape(package)}\]", raw or "") is None:
        return {
            **result,
            "verdict": "unreadable",
            "reason": "package_not_installed",
            "detail": f"设备 {serial} 上没有安装 {package}（dumpsys 未列出该包）",
        }
    match = re.search(r"versionName=(\S+)", raw or "")
    if match is None:
        return {
            **result,
            "verdict": "unreadable",
            "reason": "version_name_unreadable",
            "detail": f"dumpsys package {package} 的输出里没有 versionName，无法核对",
        }
    observed = match.group(1).strip().strip('"')
    result["observed_version_name"] = observed
    code_match = re.search(r"\bversionCode=(\d+)\b", raw or "")
    observed_code = int(code_match.group(1)) if code_match else None
    result["observed_version_code"] = observed_code
    if observed != expected:
        return {
            **result,
            "verdict": "mismatch",
            "reason": "version_name_mismatch",
            "detail": f"versionName 不一致：固定基准 {expected}，设备 {serial} 实际 {observed}",
        }
    if expected_code is not None and observed_code is None:
        # 基准固定了 versionCode，但这次读不到：不能把"没读到"写成"已验证"。
        return {
            **result,
            "verdict": "unreadable",
            "reason": "version_code_unreadable",
            "detail": (
                f"dumpsys package {package} 的输出里没有 versionCode，"
                f"无法核对固定基准 {expected_code}"
            ),
        }
    if expected_code is not None and observed_code is not None and int(expected_code) != observed_code:
        return {
            **result,
            "verdict": "mismatch",
            "reason": "version_code_mismatch",
            "detail": (
                f"versionCode 不一致：固定基准 {expected_code}，设备 {serial} 实际 {observed_code}"
                f"（versionName 相同）"
            ),
        }
    return {
        **result,
        "verdict": "verified",
        "reason": "identity_match",
        "detail": f"versionName={observed} 与固定基准一致（仅核对安装包字段，未验证 APK 摘要）",
    }


#: 身份复核结论 -> 事件类型（事件时间线直接可读，不把未复核写成已验证）。
_IDENTITY_EVENT_TYPES = {
    "verified": "identity_verified",
    "mismatch": "identity_mismatch",
    "unreadable": "identity_unreadable",
    "skipped": "identity_unverified",
}


async def _record_identity_result(
    run_id: str, *, project_id: str, result: dict[str, Any]
) -> None:
    """把运行前的身份复核结论写成事件（pending/skipped 明确标记为未复核）。"""
    verdict = str(result.get("verdict"))
    verified = verdict == "verified"
    payload = {
        "stage": "identity",
        "verdict": verdict,
        "reason": result.get("reason"),
        "detail": result.get("detail"),
        "serial": result.get("serial"),
        "package_name": result.get("package_name"),
        "expected_version_name": result.get("expected_version_name"),
        "observed_version_name": result.get("observed_version_name"),
        "expected_version_code": result.get("expected_version_code"),
        "observed_version_code": result.get("observed_version_code"),
        "execution_allowed": verified,
        "verification_level": (
            "package_identity_observed" if verdict in ("verified", "mismatch") else "none"
        ),
        "apk_digest_verified": False,
        "note": (
            "已核对设备上已安装包的包名/versionName/versionCode；未验证 APK 文件摘要"
            if verified
            else "本次运行未完成安装身份复核，不能声称已核对设备安装版本"
        ),
    }
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            await events_mod.append_event(
                session,
                project_id=project_id,
                run_id=run_id,
                source_key=events_mod.SOURCE_DISPATCHER,
                source_event_id=events_mod.event_id_for("identity", run_id, verdict),
                event_type=_IDENTITY_EVENT_TYPES.get(verdict, "identity_unverified"),
                payload=payload,
            )



async def dispatch_one(run_id: str | uuid.UUID | None = None) -> DispatchOutcome:
    """派发一个 run（run_id 为空时挑最早的 queued）。

    返回 DispatchOutcome；设备暂忙时保留 queued，其余派发故障收敛到 errored。
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            if run_id is None:
                candidates = (
                    await session.execute(
                        text(str(_QUEUED_SQL) + " FOR UPDATE SKIP LOCKED"), {"limit": 1}
                    )
                ).mappings().all()
                if not candidates:
                    return DispatchOutcome(run_id="", ok=False, reason="no_queued_run")
                run = dict(candidates[0])
            else:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT id, project_id, platform, application_id, revision_id,
                                   config_snapshot, state
                              FROM test_runs WHERE id = :id FOR UPDATE SKIP LOCKED
                            """
                        ),
                        {"id": str(run_id)},
                    )
                ).mappings().first()
                if row is None:
                    return DispatchOutcome(run_id=str(run_id), ok=False, reason="run_not_found")
                if row["state"] != runs_mod.STATE_QUEUED:
                    return DispatchOutcome(
                        run_id=str(run_id), ok=False, reason="not_queued:%s" % row["state"]
                    )
                run = dict(row)

            rid = str(run["id"])
            # 显式指派的纵深防御：轮询 SQL 已排除导入运行，这里再挡一道，
            # 防止测试/手动调用把导入产物当成真跑派出去。
            snapshot = run.get("config_snapshot") or {}
            if isinstance(snapshot, str):
                import json

                try:
                    snapshot = json.loads(snapshot)
                except ValueError:
                    snapshot = {}
            if isinstance(snapshot, dict) and snapshot.get("source") == "import":
                return DispatchOutcome(run_id=rid, ok=False, reason="import_not_dispatchable")
            project_id = str(run["project_id"])
            holder = "%s:%d" % (HOLDER_PREFIX, os_pid())

            lease = await leases_mod.acquire_lease(
                session,
                project_id=project_id,
                run_id=rid,
                holder_id=holder,
                resource_id=(run.get("config_snapshot") or {}).get("requested_resource_id"),
                platform=run["platform"],
            )
            if lease is None:
                # 领取失败要分三种情况，否则都挤进 device_unavailable，排查时分不清
                # 是设备没了、指错了设备，还是设备只是暂时被占：
                #   - 指定设备不存在/不属于本项目 -> 不可重试，errored
                #   - 指定设备存在但平台不符       -> 不可重试，errored（平台不符）
                #   - 设备存在且平台对但被占/并发锁 -> 保留 queued 等下一轮
                reason, message = await _explain_lease_failure(
                    session, project_id=project_id, run=run
                )
                if reason == "resource_busy":
                    return DispatchOutcome(run_id=rid, ok=False, reason=reason)
                await _fail_run_in_tx(
                    session,
                    run=run,
                    reason=reason,
                    message=message,
                    source=events_mod.SOURCE_DISPATCHER,
                )
                logger.warning("run %s 领取设备失败 -> errored(%s)", rid, reason)
                return DispatchOutcome(run_id=rid, ok=False, reason=reason)

            # 本地兜底锁：DB 给了这台设备，但宿主上仍有进程占着（vendor 锁残留）
            local = local_leases.probe(str(lease.serial or ""), settings.runtime_dir)
            if local.held:
                await leases_mod.release_lease(session, run_id=rid, reason="local_lease_busy")
                await _fail_run_in_tx(
                    session,
                    run=run,
                    reason="local_lease_busy",
                    message="设备 %s 被本机另一进程持有（pid=%s）"
                    % (lease.serial, local.holder_pid),
                    source=events_mod.SOURCE_DISPATCHER,
                )
                return DispatchOutcome(run_id=rid, ok=False, reason="local_lease_busy")

            config = await _resolve_config(session, run)
            # 工单 24：派发前把执行目录固定到套件版本的代码副本——缺失/损坏
            # 阻断派发（errored），绝不回退到可变来源目录（工单 05 的接线缺口）。
            # 工单 01：同时把套件版本 id 与树摘要交给 runner，供事件/报告追溯
            # 本次实际执行的版本，并让 runner 以副本为 pytest 工作目录。
            try:
                execution_copy = await _prepare_suite_copy(
                    session, str(run.get("revision_id") or "")
                )
            except Exception as exc:  # noqa: BLE001 - ApiError 与意外失败都阻断
                await leases_mod.release_lease(session, run_id=rid, reason="execution_copy_missing")
                await _fail_run_in_tx(
                    session,
                    run=run,
                    reason="execution_copy_missing",
                    message=f"固定代码副本不可用：{exc}",
                    source=events_mod.SOURCE_DISPATCHER,
                )
                logger.warning("run %s 固定副本不可用 -> errored(execution_copy_missing)", rid)
                return DispatchOutcome(run_id=rid, ok=False, reason="execution_copy_missing")
            # performance 返回 None：声明式场景没有代码副本（工单 06），
            # 不传 suite_root，execution_copy_missing 只针对 ui / joint。
            if execution_copy is not None:
                config["suite_root"] = str(execution_copy.root)
                config["suite_version_id"] = execution_copy.suite_version_id
                config["suite_sha256"] = execution_copy.tree_sha256
            lease_details = lease.as_details()
            # acquire_lease 已在同一事务内绑定资源，随后迁移状态。
            await runs_mod.transition(
                session,
                rid,
                runs_mod.STATE_QUEUED,
                runs_mod.STATE_DISPATCHING,
                reason="lease_acquired",
                actor=holder,
            )
            await events_mod.append_event(
                session,
                project_id=project_id,
                run_id=rid,
                source_key=events_mod.SOURCE_DISPATCHER,
                source_event_id=events_mod.event_id_for("lease", rid, lease.fencing_token),
                event_type="lease_acquired",
                payload={
                    "stage": "lease",
                    "resource_id": lease.resource_id,
                    "serial": lease.serial,
                    "fencing_token": lease.fencing_token,
                },
            )
            lease_details = lease.as_details()

    # 工单 24：运行租约内的构建身份复核（只读 adb，不申请第二把租约——
    # leases_one_live_resource 不允许两条活动租约并存）。冲突/不可读阻断，
    # 身份未学习（pending）不阻断，但事件里明确写成「未复核」。
    identity_result = await _verify_build_identity(
        rid, serial=str(lease_details.get("serial") or "")
    )
    await _record_identity_result(rid, project_id=project_id, result=identity_result)
    if identity_result["verdict"] in ("mismatch", "unreadable"):
        reason = "identity_" + str(identity_result["verdict"])
        await mark_spawn_failed(
            rid,
            error=reason + ": " + str(identity_result.get("detail"))[:400],
            lease=lease_details,
            reason=reason,
            stage="identity",
        )
        return DispatchOutcome(run_id=rid, ok=False, reason=reason)

    # 工单 25：执行锁定模板版本——修订 config.image_templates 声明的
    # logical/version_id/sha256 与共享模板库当前版本逐条核对；缺失或不符
    # 一律 errored，绝不静默改用别的版本。
    pin_result = verify_template_pins(pinned_templates(config))
    if pin_result["verdict"] in ("mismatch", "missing"):
        await mark_spawn_failed(
            rid,
            error="template_pin_mismatch: " + str(pin_result.get("detail"))[:400],
            lease=lease_details,
        )
        return DispatchOutcome(run_id=rid, ok=False, reason="template_pin_mismatch")

    # 事务已提交：此时镜像里一定有"租约 + dispatching"。spawn 放在事务外，
    # 因为拉起子进程是不可回滚的副作用，绝不能让它发生在一个还会回滚的事务里。
    try:
        pid = await dispatch_runner.spawn(
            run_id=rid,
            config={**config, "revision_id": run.get("revision_id")},
            lease=lease_details,
        )
    except Exception as exc:  # noqa: BLE001 - spawn 失败必须收敛成 errored
        logger.exception("run %s spawn 失败", rid)
        await mark_spawn_failed(rid, error=str(exc), lease=lease_details)
        return DispatchOutcome(run_id=rid, ok=False, reason="runner_spawn_failed")

    logger.info("run %s 已派发 pid=%s serial=%s", rid, pid, lease_details.get("serial"))
    return DispatchOutcome(
        run_id=rid, ok=True, reason="spawned", lease=lease_details
    )


async def mark_spawn_failed(
    run_id: str | uuid.UUID,
    *,
    error: str,
    lease: dict[str, Any] | None,
    reason: str = "runner_spawn_failed",
    stage: str = "spawn",
) -> None:
    """派发阶段失败：释放租约 + run=errored。必须两步都做，否则设备被永久占用。

    reason 同时写入 test_runs.reason_code 与事件 payload，页面「原因」才显示
    真实原因（identity_mismatch / identity_unreadable），而不是笼统的
    runner_spawn_failed。
    """
    sessionmaker = get_sessionmaker()
    rid = str(run_id)
    async with sessionmaker() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text("SELECT project_id, state FROM test_runs WHERE id = :id"),
                    {"id": rid},
                )
            ).mappings().first()
            if row is None:
                return
            await leases_mod.release_lease(session, run_id=rid, reason=reason)
            if row["state"] in (runs_mod.STATE_DISPATCHING, runs_mod.STATE_QUEUED):
                await runs_mod.transition(
                    session,
                    rid,
                    (runs_mod.STATE_DISPATCHING, runs_mod.STATE_QUEUED),
                    runs_mod.STATE_ERRORED,
                    reason=reason,
                    actor="dispatcher",
                )
                await events_mod.append_event(
                    session,
                    project_id=str(row["project_id"]),
                    run_id=rid,
                    source_key=events_mod.SOURCE_DISPATCHER,
                    source_event_id=events_mod.event_id_for("spawn_failed", rid),
                    event_type="error",
                    payload={
                        "stage": stage,
                        "reason": reason,
                        "message": error[:2000],
                        "lease": lease,
                    },
                )


async def _explain_lease_failure(
    session, *, project_id: str, run: dict[str, Any]
) -> tuple[str, str]:
    """领取租约失败的原因分类，返回 (reason, message)。

    区分"暂时领不到"与"这台设备根本用不了"：只有前者能靠下一轮重试自愈。
    指定设备时按 id 回查（不带 platform 条件），才能把"平台不符"从
    "设备不存在"里分出来；未指定设备时只可能是无 ready 设备。
    """
    requested = (run.get("config_snapshot") or {}).get("requested_resource_id")
    platform = run["platform"]

    if requested:
        row = (
            await session.execute(
                text(
                    "SELECT er.platform, er.status FROM execution_resources er "
                    "WHERE er.id = CAST(:rid AS uuid) AND er.project_id = :pid"
                ),
                {"rid": requested, "pid": project_id},
            )
        ).mappings().first()
        if row is None:
            return (
                "requested_device_not_found",
                f"指定的设备 {requested} 不存在或不属于本项目",
            )
        if row["platform"] != platform:
            return (
                "requested_device_platform_mismatch",
                f"指定的设备平台为 {row['platform']}，与运行的 {platform} 不符",
            )
        # 设备存在、平台相符：状态不是 ready 是执行期故障，不可重试。
        if row["status"] != "ready":
            return (
                "device_unavailable",
                f"指定设备当前状态为 {row['status']}，不可调度",
            )
        # ready 却领不到，只可能是租约或并发锁暂时占用。
        return ("resource_busy", "")

    ready = (
        await session.execute(
            text(
                "SELECT id FROM execution_resources "
                "WHERE project_id = :pid AND platform = :platform AND status = 'ready' LIMIT 1"
            ),
            {"pid": project_id, "platform": platform},
        )
    ).first()
    if ready:
        return ("resource_busy", "")
    return ("device_unavailable", "没有可用设备（全部离线、未授权或被占用）")


async def _fail_run_in_tx(
    session,
    *,
    run: dict[str, Any],
    reason: str,
    message: str,
    source: str,
) -> None:
    rid = str(run["id"])
    await runs_mod.transition(
        session,
        rid,
        runs_mod.STATE_QUEUED,
        runs_mod.STATE_ERRORED,
        reason=reason,
        actor="dispatcher",
    )
    await events_mod.append_event(
        session,
        project_id=str(run["project_id"]),
        run_id=rid,
        source_key=source,
        source_event_id=events_mod.event_id_for(reason, rid),
        event_type="error",
        payload={"stage": "dispatch", "reason": reason, "message": message},
    )


def os_pid() -> int:
    import os

    return os.getpid()


async def dispatch_pending(limit: int = DISPATCH_BATCH) -> list[DispatchOutcome]:
    """一轮派发：最多 limit 个 queued。逐个处理，任一失败不影响后续。"""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = (
            await session.execute(_QUEUED_SQL, {"limit": int(limit)})
        ).mappings().all()
    outcomes: list[DispatchOutcome] = []
    for row in rows:
        try:
            outcomes.append(await dispatch_one(str(row["id"])))
        except Exception as exc:  # noqa: BLE001 - 单个 run 失败不能拖垮整轮
            logger.exception("派发 run %s 异常", row["id"])
            outcomes.append(
                DispatchOutcome(run_id=str(row["id"]), ok=False, reason="exception:%s" % exc)
            )
    return outcomes


async def run_forever(
    *,
    interval: float = DISPATCH_INTERVAL_SECONDS,
    stop: asyncio.Event | None = None,
) -> None:
    """每 2s 领一次。stop 事件用于 API 关闭时优雅退出。"""
    while True:
        if stop is not None and stop.is_set():
            return
        try:
            await dispatch_pending()
        except Exception:  # noqa: BLE001 - 循环必须活下去
            logger.exception("dispatcher 轮次失败")
        try:
            await asyncio.wait_for(stop.wait() if stop else asyncio.sleep(interval), interval)
        except asyncio.TimeoutError:
            pass


__all__ = [
    "DISPATCH_BATCH",
    "DISPATCH_INTERVAL_SECONDS",
    "DispatchOutcome",
    "dispatch_one",
    "dispatch_pending",
    "mark_spawn_failed",
    "run_forever",
]
