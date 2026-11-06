"""设备池同步：POST /resources/sync 的业务逻辑（device-registration.md §4.1/D2–D4）。

流程（一次请求一个事务，由 db.get_session 提供）：

    1. 解析项目范围（project_id 缺省 = 所有项目，每项目各自登记自己的设备）
    2. adb 探测（不持锁）：devices -l 一次，已授权设备逐台 getprop + wm size
    3. 每个项目 upsert「本机执行节点」（(project_id, name) 唯一索引幂等）
    4. 逐设备：算档案指纹 → 命中即复用/未命中即建档 → upsert 资源行
    5. 消失置 offline（有未释放租约的设备不动，记入 busy_skipped）
    6. 未挂接 local 能力的 online 节点报 unreachable，不碰它们的设备

三条纪律（§7 数据纪律验收）：
    - 从不 DELETE execution_resources；
    - 档案只升级不降级（未识别 → 真实档案，绝不反向）；
    - 有未释放租约的设备不改状态（让既有状态机收敛，sync 不抢在它前面）。
"""

from __future__ import annotations

import datetime as _dt
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import profiles as profiles_domain
from ..errors import ApiError, not_found
from ..integrations import devices as adb_integration

#: 本机执行节点（D2）：agent 与 server 同进程，capabilities 声明可本地探测 adb。
LOCAL_NODE_NAME = "本机执行节点"
LOCAL_NODE_AGENT_VERSION = "testdock-sync"
LOCAL_NODE_CAPABILITIES = {"adb": True, "local": True}

#: 本期只做 adb（android）设备；resource_profiles 的 platform 枚举里的其它值留给后续。
SYNC_PLATFORM = "android"


def _adb_unavailable(path: Any) -> ApiError:
    return ApiError(
        503,
        "adb_unavailable",
        f"adb 不可用：{path} 不存在或不可执行",
        {
            "path": str(path),
            "hint": "设置环境变量 TESTDOCK_ADB 指向可用的 adb 二进制",
        },
    )


def _adb_probe_failed(exc: Exception) -> ApiError:
    tail = str(exc).strip().splitlines()[-5:]
    return ApiError(
        502,
        "adb_probe_failed",
        "adb 探测失败（执行出错或超时）",
        {"stderr_tail": tail},
    )


def _is_local_node(capabilities: Any) -> bool:
    """capabilities 声明了 local + adb 的节点才能在本期被探测。"""
    return bool(isinstance(capabilities, dict) and capabilities.get("local") and capabilities.get("adb"))


def _profile_name_from_probe(probe: dict[str, Any], spec: dict[str, str]) -> str:
    brand = probe.get("brand") or probe.get("manufacturer") or probe["model"]
    return f"{brand} {probe['model']} / Android {probe['os_version']} / {spec['screen_resolution']}"


def _unreachable_node(node_id: str, node_name: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_name": node_name,
        "status": "unreachable",
        "seen": 0,
        "created": 0,
        "updated": 0,
        "offlined": 0,
        "busy_skipped": [],
        "devices": [],
    }


async def _ensure_profile(
    session: AsyncSession,
    project_id: str,
    *,
    fingerprint: str,
    name: str,
    spec: dict[str, Any],
) -> tuple[str, bool]:
    """按 (project_id, platform, fingerprint) 取档案；未命中即建（D3.2）。

    唯一索引兜底并发：撞索引时回读既有行（档案不可变，后来者不覆盖名字）。
    """
    params = {"pid": project_id, "platform": SYNC_PLATFORM, "fp": fingerprint}
    row = (
        await session.execute(
            text(
                "SELECT id FROM resource_profiles"
                " WHERE project_id = CAST(:pid AS uuid) AND platform = :platform AND fingerprint = :fp"
            ),
            params,
        )
    ).first()
    if row is not None:
        return str(row.id), False

    inserted = (
        await session.execute(
            text(
                "INSERT INTO resource_profiles (id, project_id, platform, name, fingerprint, spec)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :platform, :name, :fp, CAST(:spec AS jsonb))"
                " ON CONFLICT (project_id, platform, fingerprint) DO NOTHING"
                " RETURNING id"
            ),
            {**params, "id": str(uuid.uuid4()), "name": name, "spec": _json(spec)},
        )
    ).first()
    if inserted is not None:
        return str(inserted.id), True

    row = (
        await session.execute(
            text(
                "SELECT id FROM resource_profiles"
                " WHERE project_id = CAST(:pid AS uuid) AND platform = :platform AND fingerprint = :fp"
            ),
            params,
        )
    ).first()
    if row is None:  # pragma: no cover - 唯一索引冲突后必然能回读
        raise RuntimeError(f"档案 {fingerprint} 建立后不可读")
    return str(row.id), False


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


async def _upsert_local_node(session: AsyncSession, project_id: str) -> Any:
    """按 (project_id, name) 幂等 upsert 本机执行节点（D2）。"""
    row = (
        await session.execute(
            text(
                "INSERT INTO execution_nodes"
                " (id, project_id, name, agent_version, capabilities, status, heartbeat_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :name, :agent,"
                "         CAST(:caps AS jsonb), 'online', now())"
                " ON CONFLICT (project_id, name) DO UPDATE"
                "   SET status = 'online', heartbeat_at = now(), capabilities = EXCLUDED.capabilities"
                " RETURNING id, name"
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": project_id,
                "name": LOCAL_NODE_NAME,
                "agent": LOCAL_NODE_AGENT_VERSION,
                "caps": _json(LOCAL_NODE_CAPABILITIES),
            },
        )
    ).first()
    if row is None:  # pragma: no cover - upsert 必然返回
        raise RuntimeError("本机执行节点 upsert 未返回行")
    return row


async def sync_resources(
    session: AsyncSession,
    *,
    project_id: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    started_at = _dt.datetime.now(_dt.UTC)

    # ---- 1) 项目范围 -------------------------------------------------- #
    if project_id is not None:
        exists = (
            await session.execute(
                text("SELECT 1 FROM projects WHERE id = CAST(:pid AS uuid)"),
                {"pid": project_id},
            )
        ).first()
        if exists is None:
            raise not_found("project", project_id)
        project_ids = [project_id]
    else:
        rows = (await session.execute(text("SELECT id FROM projects ORDER BY created_at"))).all()
        project_ids = [str(r.id) for r in rows]

    # ---- 2) 节点范围 -------------------------------------------------- #
    adb_path = adb_integration.resolve_adb_path()
    fixed_node: Any | None = None
    if node_id is not None:
        fixed_node = (
            await session.execute(
                text(
                    "SELECT id, project_id, name, capabilities, status"
                    " FROM execution_nodes WHERE id = CAST(:nid AS uuid)"
                ),
                {"nid": node_id},
            )
        ).first()
        if fixed_node is None:
            raise not_found("node", node_id)
        if project_id is not None and str(fixed_node.project_id) != project_id:
            raise not_found("node", node_id)
        if fixed_node.status != "online":
            raise ApiError(
                409,
                "state_conflict",
                f"节点 {node_id} 不在线，不能同步",
                {"node_id": node_id, "status": fixed_node.status},
            )
        project_ids = [str(fixed_node.project_id)]
        if not _is_local_node(fixed_node.capabilities):
            # 指定了远端节点：本期没有 agent 上报，报 unreachable 即可——
            # 绝不能对它的设备做 offline 扫描（节点失联 ≠ 设备消失，D2）
            return {
                "started_at": started_at,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
                "adb_path": str(adb_path),
                "nodes": [_unreachable_node(str(fixed_node.id), fixed_node.name)],
            }

    # ---- 3) adb 探测（不持任何行锁） ---------------------------------- #
    need_adb = fixed_node is None or _is_local_node(fixed_node.capabilities)

    device_list: list[adb_integration.AdbDevice] = []
    probes: dict[str, adb_integration.DeviceProbe] = {}
    if need_adb:
        try:
            device_list = adb_integration.list_devices(adb_path)
            for dev in device_list:
                if dev.state != "device":
                    continue  # 未授权/离线设备读不到特征，走「未识别档案」（D3.3）
                try:
                    probes[dev.serial] = adb_integration.probe_device(adb_path, dev.serial)
                except adb_integration.AdbProbeError:
                    # 单台探测失败不放弃整轮同步：该设备按未识别档案登记
                    pass
        except adb_integration.AdbUnavailableError as exc:
            raise _adb_unavailable(exc) from exc
        except adb_integration.AdbProbeError as exc:
            raise _adb_probe_failed(exc) from exc

    # ---- 4) 逐项目登记 ------------------------------------------------ #
    nodes_out: list[dict[str, Any]] = []
    seen_serials = [d.serial for d in device_list]

    for pid in project_ids:
        if fixed_node is not None:
            node_row = fixed_node
        else:
            node_row = await _upsert_local_node(session, pid)
        current_node_id = str(node_row.id)

        # 同项目下其余 online 节点：本期无 agent，报 unreachable，不动它们的设备
        other_rows = (
            await session.execute(
                text(
                    "SELECT id, name, capabilities FROM execution_nodes"
                    " WHERE project_id = CAST(:pid AS uuid) AND status = 'online' AND id <> CAST(:nid AS uuid)"
                ),
                {"pid": pid, "nid": current_node_id},
            )
        ).mappings().all()

        node_result: dict[str, Any] = {
            "node_id": current_node_id,
            "node_name": node_row.name,
            "status": "ok",
            "seen": len(device_list),
            "created": 0,
            "updated": 0,
            "offlined": 0,
            "busy_skipped": [],
            "devices": [],
        }

        for dev in device_list:
            status = adb_integration.map_adb_state(dev.state)
            probe = probes.get(dev.serial)
            if probe is not None:
                spec = profiles_domain.spec_from_probe(
                    {
                        "os_version": probe.os_version,
                        "screen_resolution": probe.screen_resolution,
                        "model": probe.model,
                    }
                )
                fingerprint = profiles_domain.fingerprint_for(spec)
                profile_name = _profile_name_from_probe(
                    {"brand": probe.brand, "model": probe.model, "os_version": probe.os_version},
                    spec,
                )
                profile_spec = profiles_domain.canonical_profile_spec(spec)
            else:
                fingerprint = profiles_domain.unknown_profile_fingerprint(SYNC_PLATFORM)
                profile_name = "未识别设备"
                profile_spec = profiles_domain.unknown_profile_spec()

            profile_id, profile_created = await _ensure_profile(
                session, pid, fingerprint=fingerprint, name=profile_name, spec=profile_spec
            )

            existing = (
                await session.execute(
                    text(
                        "SELECT r.id, p.fingerprint AS profile_fingerprint"
                        " FROM execution_resources r"
                        " LEFT JOIN resource_profiles p ON p.id = r.profile_id AND p.project_id = r.project_id"
                        " WHERE r.project_id = CAST(:pid AS uuid) AND r.node_id = CAST(:nid AS uuid)"
                        "   AND r.resource_key = :key"
                    ),
                    {"pid": pid, "nid": current_node_id, "key": dev.serial},
                )
            ).first()

            if existing is None:
                resource_id = str(uuid.uuid4())
                await session.execute(
                    text(
                        "INSERT INTO execution_resources"
                        " (id, project_id, node_id, profile_id, platform, resource_key, kind, status, last_seen_at)"
                        " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:nid AS uuid),"
                        "         CAST(:fid AS uuid), :platform, :key, 'device', :status, now())"
                    ),
                    {
                        "id": resource_id,
                        "pid": pid,
                        "nid": current_node_id,
                        "fid": profile_id,
                        "platform": SYNC_PLATFORM,
                        "key": dev.serial,
                        "status": status,
                    },
                )
                action = "created"
                node_result["created"] += 1
            else:
                resource_id = str(existing.id)
                # 档案只升级不降级：未识别 -> 真实档案；真实档案永不被占位档案覆盖
                upgrade = (
                    existing.profile_fingerprint == profiles_domain.unknown_profile_fingerprint(SYNC_PLATFORM)
                    and probe is not None
                )
                if upgrade:
                    await session.execute(
                        text(
                            "UPDATE execution_resources SET status = :status, last_seen_at = now(),"
                            " profile_id = CAST(:fid AS uuid)"
                            " WHERE id = CAST(:rid AS uuid)"
                        ),
                        {"rid": resource_id, "status": status, "fid": profile_id},
                    )
                else:
                    await session.execute(
                        text(
                            "UPDATE execution_resources SET status = :status, last_seen_at = now()"
                            " WHERE id = CAST(:rid AS uuid)"
                        ),
                        {"rid": resource_id, "status": status},
                    )
                action = "updated"
                node_result["updated"] += 1

            node_result["devices"].append(
                {
                    "resource_key": dev.serial,
                    "status": status,
                    "action": action,
                    "profile": {"id": profile_id, "name": profile_name, "created": profile_created},
                }
            )

        # ---- 5) 消失置 offline（D4）：busy 的不动 --------------------- #
        lease_params: dict[str, Any] = {"pid": pid, "nid": current_node_id, "seen": seen_serials}
        busy_rows = (
            await session.execute(
                text(
                    "SELECT r.resource_key FROM execution_resources r"
                    " JOIN resource_leases l ON l.resource_id = r.id AND l.released_at IS NULL"
                    " WHERE r.project_id = CAST(:pid AS uuid) AND r.node_id = CAST(:nid AS uuid)"
                    "   AND r.resource_key <> ALL(CAST(:seen AS text[]))"
                ),
                lease_params,
            )
        ).scalars().all()
        node_result["busy_skipped"] = sorted(busy_rows)

        offlined = (
            await session.execute(
                text(
                    "UPDATE execution_resources r SET status = 'offline'"
                    " WHERE r.project_id = CAST(:pid AS uuid) AND r.node_id = CAST(:nid AS uuid)"
                    "   AND r.status <> 'offline'"
                    "   AND r.resource_key <> ALL(CAST(:seen AS text[]))"
                    "   AND NOT EXISTS ("
                    "     SELECT 1 FROM resource_leases l"
                    "      WHERE l.resource_id = r.id AND l.released_at IS NULL)"
                    " RETURNING r.resource_key"
                ),
                lease_params,
            )
        ).scalars().all()
        node_result["offlined"] = len(offlined)

        nodes_out.append(node_result)
        for other in other_rows:
            if _is_local_node(other["capabilities"]):
                continue  # 理论上只有本机一个 local 节点；出现第二个按可探测处理（本期不发生）
            nodes_out.append(_unreachable_node(str(other["id"]), other["name"]))

    return {
        "started_at": started_at,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
        "adb_path": str(adb_path),
        "nodes": nodes_out,
    }
