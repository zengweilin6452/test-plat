"""执行资源（设备池）：GET /resources、POST /resources/sync。

表结构真源 = server/alembic/versions/0001_initial.py（对齐
docs/platform-prototype/schema.sql）。注意几个容易写错的真实列名：
  - execution_resources.profile_id（不是 resource_profile_id）
  - execution_resources.resource_key（不是 serial；存 adb serial / 节点侧标识）
  - execution_resources.kind（device / emulator / ...）
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..domain import leases as leases_mod
from ..errors import (
    CLIENT_HEADER,
    CLIENT_HEADER_VALUE,
    client_header_required,
    conflict,
    not_found,
)
from ..integrations import devices as adb_integration
from ..schemas import ResourcesOut
from ..services import resources as resource_service
from .tasks import require_client_header

router = APIRouter(tags=["resources"])

_STATUSES = {"ready", "offline", "unauthorized", "draining"}

#: 短检查租约时长（秒）。检查本身是同步 adb 子进程，通常 < 10s。
READINESS_LEASE_SECONDS = 30
#: 单条只读 adb 命令超时（秒）。
READINESS_COMMAND_TIMEOUT_S = 15.0

#: 按测试类型要求的设备检查项；缺一即阻断对应类型执行。
_REQUIRED_CHECKS: dict[str, tuple[str, ...]] = {
    "ui": ("connection", "identity", "accessibility"),
    "performance": ("connection", "identity", "battery"),
    "joint": ("connection", "identity", "accessibility", "battery"),
}


class ReadinessCheckIn(BaseModel):
    """POST /resources/{id}/readiness 请求体。"""

    test_type: Literal["ui", "performance", "joint"] = "ui"
    app_package: str | None = None


class ResourceSyncIn(BaseModel):
    """POST /resources/sync 请求体（§4.1）：两个键都可选，body 可为 {}。"""

    project_id: str | None = None
    node_id: str | None = None


# --------------------------------------------------------------------------- #
# 只读 readiness 检查（工单 02）
# --------------------------------------------------------------------------- #
# 约束：只发只读 adb 命令；不调用 vendor 的 Keeper.run / PerfKit.ensure_ready，
# 因此不会出现 tcpip/connect、安装、设置修改或前台还原。命令是固定白名单，
# 不接受浏览器传入的任意 shell。所有命令都通过 devices._run 的参数列表执行，
# 不经过 shell，避免拼接注入。

_ACCESSIBILITY_BOUND_RE = re.compile(r"Bound services:\s*(.*)", re.IGNORECASE)
_FOREGROUND_RE = re.compile(
    r"(?:mResumedActivity|mCurrentFocus)[^\n]*?\s([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+"
)
_BATTERY_LEVEL_RE = re.compile(r"level:\s*(\d+)", re.IGNORECASE)
_BATTERY_CHARGING_RE = re.compile(r"(?:AC|USB) powered:\s*true", re.IGNORECASE)


def _readonly_shell(adb_path: Any, serial: str, command: str) -> str:
    """执行一条固定白名单的只读 shell 命令（devices._run 不经过 shell）。"""
    return adb_integration._run(  # noqa: SLF001 - 与 devices 集成共用同一 adb 子进程入口
        adb_path,
        ["-s", serial, "shell", command],
        timeout_s=READINESS_COMMAND_TIMEOUT_S,
    )


def _check_item(
    name: str,
    status: str,
    *,
    reason: str | None = None,
    detail: dict[str, Any] | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"name": name, "status": status}
    if reason:
        item["reason"] = reason
    if detail is not None:
        item["detail"] = detail
    if hint:
        item["hint"] = hint
    return item


def _adb_error_reason(exc: Exception) -> str:
    if isinstance(exc, adb_integration.AdbUnavailableError):
        return "adb_unavailable"
    return "adb_probe_failed"


def run_readiness_check(
    *,
    adb_path: Any,
    serial: str,
    test_type: str,
    app_package: str | None = None,
) -> dict[str, Any]:
    """只读检查一台设备；返回可序列化的检查结论。

    不抛 adb 异常：每项检查独立记录 fail/unknown，由 required 规则汇总成
    blocking。调用方据此返回 200（检查完成但设备不就绪），而不是把设备问题
    伪装成服务端错误。
    """
    checks: list[dict[str, Any]] = []
    degraded_items: list[str] = []
    needs_attention = False
    foreground_package: str | None = None
    clock_offset_s: float | None = None

    # 1) 连接：adb devices -l
    try:
        devices = adb_integration.list_devices(adb_path)
        device = next((d for d in devices if d.serial == serial), None)
        if device is None:
            checks.append(
                _check_item(
                    "connection",
                    "fail",
                    reason="not_listed",
                    detail={"serial": serial},
                    hint="设备未出现在 adb devices -l",
                )
            )
        elif device.state != "device":
            checks.append(
                _check_item(
                    "connection",
                    "fail",
                    reason=f"adb_state:{device.state}",
                    detail={"state": device.state},
                    hint="设备未授权或离线",
                )
            )
        else:
            checks.append(_check_item("connection", "ok", detail={"state": device.state}))
    except Exception as exc:  # noqa: BLE001 - adb 不可用/超时都转成检查结论
        checks.append(
            _check_item(
                "connection",
                "fail",
                reason=_adb_error_reason(exc),
                detail={"error": exc.__class__.__name__},
                hint=str(exc)[:300],
            )
        )

    # 2) 身份：getprop + wm size
    try:
        probe = adb_integration.probe_device(adb_path, serial)
        checks.append(
            _check_item(
                "identity",
                "ok",
                detail={
                    "model": probe.model,
                    "os_version": probe.os_version,
                    "sdk": probe.sdk,
                    "screen_resolution": probe.screen_resolution,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _check_item(
                "identity",
                "fail",
                reason=_adb_error_reason(exc),
                detail={"error": exc.__class__.__name__},
                hint=str(exc)[:300],
            )
        )

    # 3) 电池/充电（性能降级结论）
    try:
        raw = _readonly_shell(adb_path, serial, "dumpsys battery")
        level_match = _BATTERY_LEVEL_RE.search(raw)
        charging = bool(_BATTERY_CHARGING_RE.search(raw))
        if level_match is None:
            checks.append(
                _check_item(
                    "battery",
                    "unknown",
                    reason="battery_unparsed",
                    detail={"raw_tail": raw[-200:]},
                )
            )
        else:
            checks.append(
                _check_item(
                    "battery",
                    "ok" if charging else "degraded",
                    detail={"level": int(level_match.group(1)), "charging": charging},
                    hint=None if charging else "未充电：性能采集可能降级 Battery/Temperature",
                )
            )
            if not charging:
                degraded_items.extend(["Battery", "Temperature"])
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _check_item(
                "battery",
                "fail",
                reason=_adb_error_reason(exc),
                detail={"error": exc.__class__.__name__},
                hint=str(exc)[:300],
            )
        )

    # 4) 无障碍服务（UI 适配器依赖；Bound 为空只提示，不代开）
    try:
        raw = _readonly_shell(adb_path, serial, "dumpsys accessibility")
        bound = _ACCESSIBILITY_BOUND_RE.search(raw)
        if bound is None:
            checks.append(
                _check_item(
                    "accessibility",
                    "unknown",
                    reason="accessibility_unparsed",
                    detail={"raw_tail": raw[-200:]},
                )
            )
        elif not bound.group(1).strip():
            needs_attention = True
            checks.append(
                _check_item(
                    "accessibility",
                    "degraded",
                    reason="accessibility_not_bound",
                    hint="无障碍服务未绑定；平台不代为开启",
                )
            )
        else:
            checks.append(_check_item("accessibility", "ok"))
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _check_item(
                "accessibility",
                "fail",
                reason=_adb_error_reason(exc),
                detail={"error": exc.__class__.__name__},
                hint=str(exc)[:300],
            )
        )

    # 5) 前台包（只读观察，不作为阻断项）
    try:
        raw = _readonly_shell(adb_path, serial, "dumpsys activity activities")
        match = _FOREGROUND_RE.search(raw)
        if match is None:
            checks.append(_check_item("foreground", "unknown", reason="foreground_unparsed"))
        else:
            foreground_package = match.group(1)
            checks.append(
                _check_item("foreground", "ok", detail={"package": foreground_package})
            )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _check_item(
                "foreground",
                "unknown",
                reason=_adb_error_reason(exc),
                hint=str(exc)[:300],
            )
        )

    # 6) 时钟偏差（只读；偏差只降级，不阻断）
    try:
        raw = _readonly_shell(adb_path, serial, "date +%s")
        device_epoch = int(raw.strip().splitlines()[0])
        clock_offset_s = round(device_epoch - time.time(), 1)
        checks.append(
            _check_item(
                "clock",
                "ok" if abs(clock_offset_s) <= 5 else "degraded",
                detail={"offset_s": clock_offset_s},
                hint=None if abs(clock_offset_s) <= 5 else "设备与宿主时钟偏差较大",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _check_item(
                "clock",
                "unknown",
                reason=_adb_error_reason(exc),
                hint=str(exc)[:300],
            )
        )

    # 7) 目标包（浏览器显式给出时才检查）
    if app_package:
        try:
            raw = _readonly_shell(adb_path, serial, f"pm list packages {app_package}")
            present = f"package:{app_package}" in raw.split()
            checks.append(
                _check_item(
                    "package",
                    "ok" if present else "fail",
                    reason=None if present else "package_missing",
                    detail={"app_package": app_package},
                    hint=None if present else "设备上未找到目标包",
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _check_item(
                    "package",
                    "fail",
                    reason=_adb_error_reason(exc),
                    detail={"app_package": app_package},
                    hint=str(exc)[:300],
                )
            )

    # 汇总：required 项 fail/unknown 阻断；package 显式请求时也阻断。
    blocking: list[dict[str, Any]] = []
    by_name = {item["name"]: item for item in checks}
    for name in _REQUIRED_CHECKS.get(test_type, ()):
        item = by_name.get(name)
        if item is None or item["status"] in ("fail", "unknown"):
            blocking.append(
                {
                    "check": name,
                    "reason": (item or {}).get("reason") or "required_check_failed",
                    "detail": (item or {}).get("detail"),
                }
            )
    package_item = by_name.get("package")
    if package_item is not None and package_item["status"] in ("fail", "unknown"):
        blocking.append(
            {
                "check": "package",
                "reason": package_item.get("reason") or "package_unreadable",
                "detail": package_item.get("detail"),
            }
        )

    return {
        "serial": serial,
        "test_type": test_type,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ready": not blocking,
        "blocking": blocking,
        "checks": checks,
        "degraded_items": degraded_items,
        "needs_attention": needs_attention,
        "foreground_package": foreground_package,
        "clock_offset_s": clock_offset_s,
    }


@router.post("/resources/sync")
async def sync_resources(
    payload: ResourceSyncIn,
    x_testdock_client: Annotated[str | None, Header(alias=CLIENT_HEADER)] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """问 adb「现在插着什么设备」，把答案登记进设备池（写操作，web 守卫与 POST /runs 一致）。"""
    if x_testdock_client is None or not x_testdock_client.strip():
        raise client_header_required()
    if x_testdock_client.strip().lower() != CLIENT_HEADER_VALUE:
        raise client_header_required()
    return await resource_service.sync_resources(
        session,
        project_id=payload.project_id,
        node_id=payload.node_id,
    )


async def _lease_holder(
    session: AsyncSession, resource_id: str
) -> dict[str, Any] | None:
    """当前活动租约的占用者（run/debug/check 三通道）。"""
    row = (
        await session.execute(
            text(
                """
                SELECT rl.run_id, rl.debug_session_id, rl.check_id, rl.holder_id,
                       COALESCE(er.resource_key, '') AS display_id
                  FROM resource_leases rl
                  LEFT JOIN execution_resources er ON er.id = rl.resource_id
                 WHERE rl.resource_id = CAST(:rid AS uuid)
                   AND rl.released_at IS NULL
                 ORDER BY rl.created_at DESC
                 LIMIT 1
                """
            ),
            {"rid": str(resource_id)},
        )
    ).mappings().first()
    return dict(row) if row else None


@router.post("/resources/{resource_id}/readiness")
async def check_resource_readiness(
    resource_id: str,
    payload: ReadinessCheckIn,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """手动设备就绪检查：先领 DB 租约，拿不到立即 409（零 adb 访问）。

    顺序固定为：校验资源 -> 插入 device_checks -> 领取 check 租约 ->
    拿不到返回 device_busy（不访问设备）-> 执行只读 adb -> 带 fence 写结果 ->
    释放租约。检查失败也释放租约；只有 fence 失效时才隔离资源。
    """
    resource = (
        await session.execute(
            text(
                """
                SELECT er.id, er.project_id, er.status, er.resource_key
                  FROM execution_resources er
                 WHERE er.id = CAST(:rid AS uuid)
                """
            ),
            {"rid": str(resource_id)},
        )
    ).mappings().first()
    if resource is None:
        raise not_found("resource", resource_id)
    resource = dict(resource)
    if resource["status"] != "ready":
        raise conflict(
            "device_not_ready",
            f"设备 {resource['resource_key']} 当前状态为 {resource['status']!r}，不可检查",
            {"serial": resource["resource_key"], "status": resource["status"]},
        )

    check_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO device_checks (
                id, project_id, resource_id, kind, test_type, holder_id, state, expires_at
            ) VALUES (
                CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),
                'readiness', :test_type, :holder, 'opening',
                now() + make_interval(secs => :lease_seconds)
            )
            """
        ),
        {
            "id": check_id,
            "pid": str(resource["project_id"]),
            "rid": str(resource["id"]),
            "test_type": payload.test_type,
            "holder": _client,
            "lease_seconds": READINESS_LEASE_SECONDS,
        },
    )
    lease = await leases_mod.acquire_lease_for_check(
        session,
        project_id=str(resource["project_id"]),
        check_id=check_id,
        resource_id=str(resource["id"]),
        holder_id=_client,
        lease_seconds=READINESS_LEASE_SECONDS,
    )
    if lease is None:
        holder = await _lease_holder(session, str(resource["id"]))
        raise conflict(
            "device_busy",
            f"设备 {resource['resource_key']} 已被占用",
            {
                "serial": resource["resource_key"],
                "holder": holder or {},
                "holder_display_id": (holder or {}).get("display_id")
                or resource["resource_key"],
            },
        )

    await session.execute(
        text(
            "UPDATE device_checks SET state = 'running', started_at = now()"
            " WHERE id = CAST(:cid AS uuid)"
        ),
        {"cid": check_id},
    )

    adb_path = adb_integration.resolve_adb_path()
    try:
        result = await asyncio.to_thread(
            run_readiness_check,
            adb_path=adb_path,
            serial=str(resource["resource_key"]),
            test_type=payload.test_type,
            app_package=payload.app_package,
        )
        check_state = "finished"
    except Exception as exc:  # noqa: BLE001 - 检查器意外失败也要收口
        result = {
            "serial": resource["resource_key"],
            "test_type": payload.test_type,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "ready": False,
            "blocking": [
                {
                    "check": "readiness",
                    "reason": "checker_error",
                    "detail": {"error": exc.__class__.__name__},
                }
            ],
            "checks": [],
            "degraded_items": [],
            "needs_attention": False,
            "foreground_package": None,
            "clock_offset_s": None,
        }
        check_state = "failed"

    written = await leases_mod.record_check_result(
        session,
        check_id=check_id,
        token=lease.fencing_token,
        state=check_state,
        result=result,
        error_code="checker_error" if check_state == "failed" else None,
    )
    if not written:
        # fence 失效：旧拥有者不得写结果，也不能把设备显示为空闲。
        await leases_mod.release_lease_for_check(
            session,
            check_id=check_id,
            reason="fence_lost",
            token=lease.fencing_token,
            stopped_confirmed=False,
        )
        raise conflict(
            "fence_mismatch",
            "检查租约已失效，拒绝写入结果",
            {"check_id": check_id, "serial": resource["resource_key"]},
        )

    released = await leases_mod.release_lease_for_check(
        session,
        check_id=check_id,
        reason="readiness_complete",
        token=lease.fencing_token,
    )
    return {**result, "check_id": check_id, "lease_released": released is not None}


@router.get("/resources", response_model=ResourcesOut)
async def list_resources(
    status: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """设备列表。status 过滤取值 ready/offline/unauthorized/draining。

    project_id 可选（D5）：不传 = 全部项目（向后兼容）；传了但项目不存在
    返回 404——空列表会被误读成「这个项目没设备」。
    busy 不落库，由「存在未释放租约」实时推导 —— 资源表本身没有 busy 列，
    这是 docs/plan/data-model.md 的明确约定（避免两处状态互相矛盾）。
    """
    if status is not None and status not in _STATUSES:
        raise HTTPException(status_code=422, detail=f"未知 status: {status}")

    params: dict[str, object] = {}
    if project_id is not None:
        exists = (
            await session.execute(
                text("SELECT 1 FROM projects WHERE id = CAST(:pid AS uuid)"),
                {"pid": project_id},
            )
        ).first()
        if exists is None:
            raise not_found("project", project_id)

    sql = """
        SELECT r.id, r.project_id, r.node_id, r.resource_key, r.status, r.kind, r.platform,
               r.profile_id, r.last_seen_at,
               l.run_id AS lease_run_id, l.debug_session_id AS lease_debug_id,
               l.check_id AS lease_check_id,
               p.name AS profile_name, p.spec
          FROM execution_resources r
          LEFT JOIN resource_leases l
                 ON l.resource_id = r.id AND l.released_at IS NULL
          LEFT JOIN resource_profiles p
                 ON p.id = r.profile_id AND p.project_id = r.project_id
    """
    conditions = []
    if status is not None:
        conditions.append("r.status = :status")
        params["status"] = status
    if project_id is not None:
        conditions.append("r.project_id = CAST(:pid AS uuid)")
        params["pid"] = project_id
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY r.resource_key"

    rows = (await session.execute(text(sql), params)).mappings().all()

    items = []
    for row in rows:
        spec = row["spec"] or {}
        items.append(
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "node_id": row["node_id"],
                "name": row["resource_key"],
                "resource_key": row["resource_key"],
                "status": row["status"],
                "kind": row["kind"] or "device",
                "platform": row["platform"] or "android",
                "profile_id": row["profile_id"],
                "last_seen_at": row["last_seen_at"],
                "profile": {
                    "name": row["profile_name"],
                    "os_name": spec.get("os_name"),
                    "os_version": spec.get("os_version"),
                    "screen_resolution": spec.get("screen_resolution"),
                }
                if row["profile_name"]
                else None,
                "busy": any(
                    (
                        row["lease_run_id"],
                        row["lease_debug_id"],
                        row["lease_check_id"],
                    )
                ),
                "lease": {
                    "run_id": row["lease_run_id"],
                    "debug_session_id": row["lease_debug_id"],
                    "check_id": row["lease_check_id"],
                }
                if any(
                    (
                        row["lease_run_id"],
                        row["lease_debug_id"],
                        row["lease_check_id"],
                    )
                )
                else None,
            }
        )

    # AC-RES-01：五个状态 × 空闲/占用的准确计数。busy 由"存在未释放租约"实时推导，
    # 与每行的 busy 字段同一口径；counts 覆盖完整过滤集合，前端不再自己数。
    counts = {
        "ready_idle": sum(1 for i in items if i["status"] == "ready" and not i["busy"]),
        "ready_busy": sum(1 for i in items if i["status"] == "ready" and i["busy"]),
        "offline": sum(1 for i in items if i["status"] == "offline"),
        "unauthorized": sum(1 for i in items if i["status"] == "unauthorized"),
        "draining": sum(1 for i in items if i["status"] == "draining"),
    }
    return {
        "items": items,
        "total": len(items),
        "ready": counts["ready_idle"] + counts["ready_busy"],
        "counts": counts,
        "summary": (
            f"{counts['ready_idle']} 台可用 / {counts['ready_busy']} 台占用中"
            f" / {counts['offline'] + counts['unauthorized'] + counts['draining']} 台不可用"
            f"（共 {len(items)} 台）"
        ),
    }
