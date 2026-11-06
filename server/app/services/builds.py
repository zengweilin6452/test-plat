"""构建登记与设备安装身份核对（工单 04）。

设计要点
--------
- 不新增表：构建声明身份仍在 app_builds；核对记录、固定基准与核对等级写在
  `app_builds.metadata.identity`（JSONB）。
- 构建逻辑身份 = project_id + application_id + build_key；version 是业务版本。
  同 key 同身份复用原记录；同 key 不同身份 409 且不改原记录。
- 设备身份只读读取 `dumpsys package <pkg>`，与工单 02 的 readiness 共用
  device_checks / resource_leases 的短检查通道，因此天然与 run/debug 互斥。
- 首次核对经用户显式 confirm 后才固定基准；之后任何设备只用于复核，
  不会自动改写基准（"不从另一设备重新学习"）。
- 核对等级只到"设备上已安装包的包名 / versionName / versionCode"，
  绝不声称 APK 文件摘要已验证。
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import leases as leases_mod
from ..errors import ApiError, conflict, not_found
from ..integrations import devices as adb_integration

#: 短检查租约时长（秒）；身份读取是同步 adb 子进程，通常 < 10s。
IDENTITY_LEASE_SECONDS = 30
#: 单条只读 adb 命令超时（秒）。
IDENTITY_COMMAND_TIMEOUT_S = 15.0

#: 只接受 Android 包名形状；命令用 argv 列表执行，这里仍做白名单校验。
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_VERSION_CODE_RE = re.compile(r"\bversionCode=(\d+)\b")
_VERSION_NAME_RE = re.compile(r"\bversionName=([^\s]+)")

CRITICAL_FIELDS: tuple[str, ...] = ("package_name", "version_name", "version_code")

#: 核对等级说明：只描述实际读取到的安装包字段，不暗示 APK 文件完整性。
VERIFICATION_NOTE = (
    "身份核对等级：设备上已安装包的包名、versionName 与 versionCode（只读读取）；"
    "未验证 APK 文件摘要，sha256 仅为登记声明。"
)
VERIFICATION_LEVEL_OBSERVED = "package_identity_observed"
VERIFICATION_LEVEL_NONE = "none"


# --------------------------------------------------------------------------- #
# 只读设备身份读取（可替换命令：测试用替身 adb）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PackageIdentity:
    """一台设备上某个包的只读观测结果。"""

    package_name: str | None
    version_name: str | None
    version_code: int | None
    installed: bool
    error: str | None = None
    raw_tail: str | None = None

    def as_observed(self) -> dict[str, Any]:
        return {
            "package_name": self.package_name,
            "version_name": self.version_name,
            "version_code": self.version_code,
        }


def read_package_identity(adb_path: Any, serial: str, package_name: str) -> PackageIdentity:
    """只读读取设备上已安装包的包名 / versionName / versionCode。

    只发 `adb -s <serial> shell dumpsys package <pkg>`，不安装、不设置、不重连。
    任何 adb/解析失败都转成 error 观测值，由调用方汇总成 unknown + blocking。
    """
    if not PACKAGE_NAME_RE.match(package_name):
        return PackageIdentity(None, None, None, installed=False, error="invalid_package_name")
    try:
        raw = adb_integration._run(  # noqa: SLF001 - 与 devices 集成共用同一 adb 子进程入口
            adb_path,
            ["-s", serial, "shell", f"dumpsys package {package_name}"],
            timeout_s=IDENTITY_COMMAND_TIMEOUT_S,
        )
    except adb_integration.AdbUnavailableError:
        return PackageIdentity(None, None, None, installed=False, error="adb_unavailable")
    except adb_integration.AdbProbeError:
        return PackageIdentity(None, None, None, installed=False, error="adb_probe_failed")
    except Exception:  # noqa: BLE001 - 读取失败必须成为可报告的阻断，而不是 500
        return PackageIdentity(None, None, None, installed=False, error="identity_read_failed")

    installed = re.search(rf"Package \[{re.escape(package_name)}\]", raw) is not None
    if not installed:
        return PackageIdentity(
            None,
            None,
            None,
            installed=False,
            error="package_not_installed",
            raw_tail=raw[-200:],
        )

    code_match = _VERSION_CODE_RE.search(raw)
    name_match = _VERSION_NAME_RE.search(raw)
    return PackageIdentity(
        package_name=package_name,
        version_name=name_match.group(1) if name_match else None,
        version_code=int(code_match.group(1)) if code_match else None,
        installed=True,
        error=None if code_match and name_match else "identity_unreadable",
        raw_tail=raw[-200:] if not (code_match and name_match) else None,
    )


# --------------------------------------------------------------------------- #
# 核对评估
# --------------------------------------------------------------------------- #
def _identity_of(metadata: dict[str, Any]) -> dict[str, Any]:
    identity = metadata.get("identity")
    return identity if isinstance(identity, dict) else {}


def _state_of(identity: dict[str, Any]) -> str:
    state = identity.get("state")
    return state if state in ("pending", "confirmed") else "pending"


def _baseline_of(identity: dict[str, Any]) -> dict[str, Any] | None:
    baseline = identity.get("baseline")
    return baseline if isinstance(baseline, dict) else None


def _expected_identity(
    *, package_name: str, version: str, identity: dict[str, Any]
) -> dict[str, Any]:
    baseline = _baseline_of(identity) if _state_of(identity) == "confirmed" else None
    return {
        "package_name": package_name,
        "version_name": version,
        "version_code": (baseline or {}).get("version_code"),
    }


def evaluate_identity(
    expected: dict[str, Any], observed: PackageIdentity
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """逐项比较预期与观测，返回 (items, blocking, result)。

    result 优先级：conflict > unknown > match。首次核对没有 version_code 预期时，
    该项记为 observed（记录观测值，不阻断）。
    """
    items: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    observed_values = observed.as_observed()

    def add(name: str, status: str, reason: str | None = None) -> None:
        item: dict[str, Any] = {
            "name": name,
            "status": status,
            "expected": expected.get(name),
            "observed": observed_values.get(name),
        }
        if reason:
            item["reason"] = reason
        items.append(item)
        if status in ("conflict", "unknown"):
            blocking.append(
                {
                    "check": name,
                    "reason": reason
                    or ("identity_conflict" if status == "conflict" else "identity_unreadable"),
                }
            )

    for name in CRITICAL_FIELDS:
        value = observed_values.get(name)
        wanted = expected.get(name)
        if observed.error == "package_not_installed":
            # 包没装：包名是明确冲突；版本字段无法读取，记为 unknown。
            if name == "package_name":
                add(name, "conflict", "package_not_installed")
            else:
                add(name, "unknown", "package_not_installed")
            continue
        if observed.error and value is None:
            add(name, "unknown", observed.error)
            continue
        if not observed.installed:
            add(name, "unknown", "package_not_installed")
            continue
        if value is None:
            add(name, "unknown", "identity_unreadable")
            continue
        if wanted is None:
            add(name, "observed")
            continue
        if str(value) != str(wanted):
            add(name, "conflict", f"{name}_mismatch")
        else:
            add(name, "match")

    if any(item["status"] == "conflict" for item in items):
        result = "conflict"
    elif any(item["status"] == "unknown" for item in items):
        result = "unknown"
    else:
        result = "match"
    return items, blocking, result


def _verification_level(observed: PackageIdentity) -> str:
    complete = (
        not observed.error
        and observed.installed
        and all(observed.as_observed().get(name) is not None for name in CRITICAL_FIELDS)
    )
    return VERIFICATION_LEVEL_OBSERVED if complete else VERIFICATION_LEVEL_NONE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# 构建登记 / 列表
# --------------------------------------------------------------------------- #
async def _fetch_application(session: AsyncSession, application_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT a.id, a.project_id, a.platform, a.name, a.identifier
                  FROM applications a
                 WHERE a.id = CAST(:aid AS uuid)
                """
            ),
            {"aid": application_id},
        )
    ).mappings().first()
    if row is None:
        raise not_found("application", application_id)
    return dict(row)


_BUILD_SELECT = """
    SELECT b.id, b.project_id, b.application_id, b.version, b.build_key,
           b.source_commit, b.storage_key, b.sha256, b.metadata, b.created_at,
           a.name AS application_name, a.platform, a.identifier AS package_name
      FROM app_builds b
      JOIN applications a
        ON a.project_id = b.project_id AND a.id = b.application_id
"""


async def _fetch_build(session: AsyncSession, build_id: str, *, for_update: bool = False) -> dict[str, Any]:
    sql = _BUILD_SELECT + " WHERE b.id = CAST(:bid AS uuid)"
    if for_update:
        sql += " FOR UPDATE OF b"
    row = (await session.execute(text(sql), {"bid": build_id})).mappings().first()
    if row is None:
        raise not_found("build", build_id)
    return dict(row)


async def _fetch_active_build(
    session: AsyncSession, build_id: str, *, for_update: bool = False
) -> dict[str, Any]:
    # Match run submission: scope rows before build rows. Holding a build lock
    # while waiting for the scope can deadlock with a concurrent submission.
    from ..domain.identity import assert_scope_active

    build = await _fetch_build(session, build_id)
    await assert_scope_active(
        session, project_id=str(build["project_id"]),
        application_id=str(build["application_id"]),
    )
    return await _fetch_build(session, build_id, for_update=for_update)


def serialize_build(row: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    identity = _identity_of(metadata)
    checks = identity.get("checks")
    checks = checks if isinstance(checks, list) else []
    baseline = _baseline_of(identity)
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "application_id": row["application_id"],
        "application_name": row.get("application_name"),
        "platform": row.get("platform"),
        "package_name": row.get("package_name"),
        "version": row["version"],
        "build_key": row["build_key"],
        "source_commit": row.get("source_commit"),
        "sha256": row.get("sha256"),
        "created_at": row.get("created_at"),
        "identity_state": _state_of(identity),
        "verification_level": identity.get("verification_level") or VERIFICATION_LEVEL_NONE,
        "apk_digest_verified": False,
        "verification_note": VERIFICATION_NOTE,
        "baseline": baseline,
        "latest_check": checks[-1] if checks else None,
        "checks": checks,
        "duplicate": duplicate,
    }


def _declared_identity(version: str, source_commit: str | None, sha256: str | None) -> dict[str, Any]:
    return {"version": version, "source_commit": source_commit, "sha256": sha256}


async def register_build(
    session: AsyncSession,
    *,
    application_id: str,
    version: str,
    build_key: str,
    source_commit: str | None,
    sha256: str | None,
) -> tuple[dict[str, Any], bool]:
    """登记构建；返回 (构建视图, 是否新建)。

    同 key 同身份返回已有对象；同 key 不同身份 409 且原记录不变。
    用 ON CONFLICT DO NOTHING 避免并发插入时把事务打成 aborted 状态。
    """
    application = await _fetch_application(session, application_id)
    build_id = str(uuid.uuid4())
    inserted = (
        await session.execute(
            text(
                """
                INSERT INTO app_builds (
                    id, project_id, application_id, version, build_key,
                    source_commit, sha256
                ) VALUES (
                    CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:aid AS uuid),
                    :version, :build_key, :source_commit, :sha256
                )
                ON CONFLICT (project_id, application_id, build_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": build_id,
                "pid": str(application["project_id"]),
                "aid": application_id,
                "version": version,
                "build_key": build_key,
                "source_commit": source_commit,
                "sha256": sha256,
            },
        )
    ).first()

    if inserted is not None:
        row = await _fetch_build(session, build_id)
        return serialize_build(row), True

    existing = (
        await session.execute(
            text(
                _BUILD_SELECT
                + " WHERE b.project_id = CAST(:pid AS uuid)"
                + "   AND b.application_id = CAST(:aid AS uuid)"
                + "   AND b.build_key = :build_key"
            ),
            {
                "pid": str(application["project_id"]),
                "aid": application_id,
                "build_key": build_key,
            },
        )
    ).mappings().first()
    if existing is None:  # pragma: no cover - 唯一约束保证存在；竞态窗口兜底
        raise conflict(
            "build_identity_conflict",
            "构建登记冲突，请刷新后重试",
            {"application_id": application_id, "build_key": build_key},
        )

    existing = dict(existing)
    declared = _declared_identity(version, source_commit, sha256)
    current = _declared_identity(
        existing["version"], existing.get("source_commit"), existing.get("sha256")
    )
    differing = sorted(name for name in declared if declared[name] != current[name])
    if differing:
        raise conflict(
            "build_identity_conflict",
            f"构建号 {build_key} 已存在且身份不同：{', '.join(differing)}",
            {
                "application_id": application_id,
                "build_key": build_key,
                "existing_build_id": existing["id"],
                "fields": differing,
            },
        )
    return serialize_build(existing, duplicate=True), False


async def list_builds(
    session: AsyncSession,
    *,
    application_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    conditions: list[str] = []
    if application_id is not None:
        await _fetch_application(session, application_id)
        conditions.append("b.application_id = CAST(:aid AS uuid)")
        params["aid"] = application_id
    if project_id is not None:
        conditions.append("b.project_id = CAST(:pid AS uuid)")
        params["pid"] = project_id

    sql = _BUILD_SELECT
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY b.created_at DESC, b.id DESC"
    rows = (await session.execute(text(sql), params)).mappings().all()
    items = [serialize_build(dict(row)) for row in rows]
    return {"items": items, "total": len(items)}


# --------------------------------------------------------------------------- #
# 设备身份核对
# --------------------------------------------------------------------------- #
async def _lease_holder(session: AsyncSession, resource_id: str) -> dict[str, Any] | None:
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
            {"rid": resource_id},
        )
    ).mappings().first()
    return dict(row) if row else None


def _build_check_record(
    *,
    check_id: str,
    purpose: str,
    test_type: str,
    checked_at: str,
    resource: dict[str, Any],
    expected: dict[str, Any],
    observed: PackageIdentity,
    items: list[dict[str, Any]],
    blocking: list[dict[str, Any]],
    result: str,
    identity_state: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "purpose": purpose,
        "test_type": test_type,
        "checked_at": checked_at,
        "resource": {"id": resource["id"], "serial": resource["resource_key"]},
        "device": {"resource_id": resource["id"], "serial": resource["resource_key"]},
        "expected": expected,
        "observed": observed.as_observed(),
        "items": items,
        "result": result,
        "blocking": blocking,
        "execution_allowed": result == "match",
        "identity_state": identity_state,
        "verification_level": _verification_level(observed),
        "apk_digest_verified": False,
        "verification_note": VERIFICATION_NOTE,
        "superseded_by": None,
        "superseded_at": None,
    }


async def run_identity_check(
    session: AsyncSession,
    *,
    build_id: str,
    resource_id: str,
    purpose: str,
    test_type: str,
    holder_id: str,
) -> dict[str, Any]:
    """在设备互斥下只读核对安装身份；返回可序列化的核对记录。"""
    build = await _fetch_active_build(session, build_id)
    if build.get("platform") != "android":
        raise ApiError(
            422,
            "identity_unsupported",
            "当前只支持读取 Android 安装包身份",
            {"build_id": build_id, "platform": build.get("platform")},
        )

    identity = _identity_of(build.get("metadata") or {})
    identity_state = _state_of(identity)
    if purpose == "pre_run" and identity_state != "confirmed":
        # 正式执行前复核必须先有固定基准；在访问设备前拒绝。
        raise ApiError(
            422,
            "build_identity_not_confirmed",
            "构建身份尚未确认，正式执行前复核被阻断",
            {
                "reason": "not_confirmed",
                "build_id": build_id,
                "identity_state": identity_state,
            },
        )

    resource = (
        await session.execute(
            text(
                """
                SELECT er.id, er.project_id, er.status, er.resource_key, er.platform
                  FROM execution_resources er
                 WHERE er.id = CAST(:rid AS uuid)
                   AND er.project_id = CAST(:pid AS uuid)
                """
            ),
            {"rid": resource_id, "pid": str(build["project_id"])},
        )
    ).mappings().first()
    if resource is None:
        # 跨项目资源一律按不存在处理（INV-09），不泄露其他项目资源信息。
        raise not_found("resource", resource_id)
    resource = dict(resource)
    if resource["status"] != "ready":
        raise conflict(
            "device_not_ready",
            f"设备 {resource['resource_key']} 当前状态为 {resource['status']!r}，不可核对",
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
                'identity', :test_type, :holder, 'opening',
                now() + make_interval(secs => :lease_seconds)
            )
            """
        ),
        {
            "id": check_id,
            "pid": str(build["project_id"]),
            "rid": str(resource["id"]),
            "test_type": test_type,
            "holder": holder_id,
            "lease_seconds": IDENTITY_LEASE_SECONDS,
        },
    )
    lease = await leases_mod.acquire_lease_for_check(
        session,
        project_id=str(build["project_id"]),
        check_id=check_id,
        resource_id=str(resource["id"]),
        holder_id=holder_id,
        lease_seconds=IDENTITY_LEASE_SECONDS,
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
        observed = await asyncio.to_thread(
            read_package_identity,
            adb_path,
            str(resource["resource_key"]),
            str(build["package_name"]),
        )
    except Exception:  # noqa: BLE001 - 检查器意外失败也要收口成可报告结果
        observed = PackageIdentity(None, None, None, installed=False, error="checker_error")

    # 行锁内重新读取 metadata：设备读取期间若基准被确认，version_code 预期要
    # 使用最新基准重新评估，避免用旧预期误判。
    locked = (
        await session.execute(
            text("SELECT metadata FROM app_builds WHERE id = CAST(:bid AS uuid) FOR UPDATE"),
            {"bid": build_id},
        )
    ).mappings().first()
    metadata = dict(locked["metadata"] or {}) if locked is not None else {}
    identity = _identity_of(metadata)
    identity_state = _state_of(identity)
    expected = _expected_identity(
        package_name=str(build["package_name"]),
        version=str(build["version"]),
        identity=identity,
    )
    items, blocking, result = evaluate_identity(expected, observed)
    checked_at = _now_iso()
    check = _build_check_record(
        check_id=check_id,
        purpose=purpose,
        test_type=test_type,
        checked_at=checked_at,
        resource=resource,
        expected=expected,
        observed=observed,
        items=items,
        blocking=blocking,
        result=result,
        identity_state=identity_state,
    )

    checks = identity.get("checks")
    checks = checks if isinstance(checks, list) else []
    for prior in checks:
        prior_resource = (prior.get("resource") or {}).get("id")
        if prior_resource == str(resource["id"]) and not prior.get("superseded_by"):
            prior["superseded_by"] = check_id
            prior["superseded_at"] = checked_at
    checks.append(check)
    identity["checks"] = checks
    identity.setdefault("state", identity_state)
    metadata["identity"] = identity

    written = await leases_mod.record_check_result(
        session,
        check_id=check_id,
        token=lease.fencing_token,
        state="finished",
        result=check,
        error_code=None,
    )
    if not written:
        await leases_mod.release_lease_for_check(
            session,
            check_id=check_id,
            reason="fence_lost",
            token=lease.fencing_token,
            stopped_confirmed=False,
        )
        raise conflict(
            "fence_mismatch",
            "核对租约已失效，拒绝写入结果",
            {"check_id": check_id, "serial": resource["resource_key"]},
        )

    await session.execute(
        text(
            "UPDATE app_builds SET metadata = CAST(:meta AS jsonb)"
            " WHERE id = CAST(:bid AS uuid)"
        ),
        {
            "bid": build_id,
            "meta": json.dumps(metadata, ensure_ascii=False, default=str),
        },
    )
    released = await leases_mod.release_lease_for_check(
        session,
        check_id=check_id,
        reason="identity_complete",
        token=lease.fencing_token,
    )
    return {**check, "identity_state": identity_state, "lease_released": released is not None}


# --------------------------------------------------------------------------- #
# 显式确认并固定基准
# --------------------------------------------------------------------------- #
def _same_identity(observed: dict[str, Any], baseline: dict[str, Any]) -> bool:
    return all(
        observed.get(name) == baseline.get(name) for name in CRITICAL_FIELDS
    )


def _confirmation_rejected(reason: str, *, check: dict[str, Any] | None, **extra: Any) -> ApiError:
    details: dict[str, Any] = {"reason": reason}
    if check is not None:
        details.update(
            {
                "check_id": check.get("check_id"),
                "result": check.get("result"),
                "blocking": check.get("blocking") or [],
            }
        )
    details.update(extra)
    return ApiError(422, "build_identity_not_confirmed", "构建身份核对未满足确认条件", details)


async def confirm_identity(
    session: AsyncSession, *, build_id: str, check_id: str
) -> dict[str, Any]:
    """原子固定基准；只接受同构建、完整、版本一致、未被替代的核对结果。"""
    build = await _fetch_active_build(session, build_id, for_update=True)
    metadata = dict(build.get("metadata") or {})
    identity = _identity_of(metadata)
    checks = identity.get("checks")
    checks = checks if isinstance(checks, list) else []

    check = next((item for item in checks if item.get("check_id") == check_id), None)
    if check is None:
        raise not_found("identity_check", check_id)
    if check.get("superseded_by"):
        raise _confirmation_rejected("superseded", check=check)

    observed = check.get("observed") or {}
    identity_state = _state_of(identity)
    baseline = _baseline_of(identity)
    if identity_state == "confirmed" and baseline is not None:
        # 基准已固定：同身份重复确认幂等；不同身份一律拒绝，不用另一台设备覆盖。
        if _same_identity(observed, baseline):
            return serialize_build(build)
        raise _confirmation_rejected(
            "baseline_already_confirmed",
            check=check,
            baseline=baseline,
        )
    if check.get("result") != "match":
        raise _confirmation_rejected("identity_not_verified", check=check)

    confirmed_at = _now_iso()
    identity["state"] = "confirmed"
    identity["baseline"] = {
        "package_name": observed.get("package_name"),
        "version_name": observed.get("version_name"),
        "version_code": observed.get("version_code"),
        "resource": check.get("resource") or {},
        "check_id": check_id,
        "confirmed_at": confirmed_at,
    }
    identity["verification_level"] = check.get("verification_level") or VERIFICATION_LEVEL_OBSERVED
    identity["apk_digest_verified"] = False
    identity["confirmed_at"] = confirmed_at
    metadata["identity"] = identity
    await session.execute(
        text(
            "UPDATE app_builds SET metadata = CAST(:meta AS jsonb)"
            " WHERE id = CAST(:bid AS uuid)"
        ),
        {
            "bid": build_id,
            "meta": json.dumps(metadata, ensure_ascii=False, default=str),
        },
    )
    refreshed = await _fetch_build(session, build_id)
    return serialize_build(refreshed)
