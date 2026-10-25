#!/usr/bin/env python3
"""演示种子数据（对齐原型 展示的一套数据）。

写入内容（docs/plan/data-model.md §7）:
  - 1 个项目 testdock-demo
  - 3 个应用：Android 星河 / iOS 星河 / Web 星河（后两个仅配置，无适配器）
  - 2 个资源档案（Android 旗舰、Android 中端）
  - 6 台设备：4 ready + 1 unauthorized + 1 offline（对齐原型 6 台设备四态）
  - 4 个套件（核心链路回归 12 / 登录与账号 6 / 下单链路 8 / 个人中心 5）
  - 3 个性能场景任务（首页滑动 / 商品详情 / 搜索）
  - 1 个基线与 1 套门禁策略

用法: python scripts/seed_demo.py [--database-url ...]
幂等：按业务唯一键 upsert，可重复执行。
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

PROJECT_ID = "testdock-demo"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="写入 TestDock 演示种子数据")
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "TESTDOCK_DATABASE_URL", "postgresql+psycopg://testdock@127.0.0.1:55432/testdock"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将要写入的内容")
    args = parser.parse_args(argv[1:])

    plan = build_plan()
    if args.dry_run:
        for table, rows in plan.items():
            print(f"{table}: {len(rows)} 行")
        return 0

    print(f"目标库: {args.database_url.split('@')[-1]}")
    written = write_all(args.database_url, plan)
    for table, n in written.items():
        print(f"  {table}: {n} 行")
    print("种子数据写入完成。")
    return 0


# ---------------------------------------------------------------------------
# 真正的写入实现
# ---------------------------------------------------------------------------

# 固定 UUID 前缀，保证反复执行命中同一批行（幂等 upsert 依赖固定 id）
_NS = uuid.UUID("6f1b2c34-0000-4000-8000-000000000000")


def _uid(name: str) -> str:
    """由业务键派生稳定 UUID。"""
    return str(uuid.uuid5(_NS, name))


def _sync_url(database_url: str) -> str:
    """psycopg 3 同步连接串（Alembic/脚本用同步驱动，与 API 的异步共用同一 URL）。"""
    return database_url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )


def write_all(database_url: str, plan: dict[str, list[dict[str, object]]]) -> dict[str, int]:
    """按固定 id 幂等 upsert 全部种子数据。"""
    import psycopg

    project_uuid = _uid("project:" + PROJECT_ID)
    platform_app = {a["id"]: _uid("application:" + str(a["id"])) for a in plan["applications"]}
    profile_uuid = {
        p["id"]: _uid("profile:" + str(p["id"])) for p in plan["resource_profiles"]
    }
    suite_uuid = {s["id"]: _uid("suite:" + str(s["id"])) for s in plan["suites"]}
    counts: dict[str, int] = {}

    with psycopg.connect(_sync_url(database_url)) as conn:
        with conn.cursor() as cur:
            # 项目（schema: id, code, name, archived_at, created_at）
            cur.execute(
                """
                INSERT INTO projects (id, code, name)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET code = EXCLUDED.code, name = EXCLUDED.name
                """,
                (project_uuid, PROJECT_ID, "星河 Demo"),
            )
            counts["projects"] = cur.rowcount

            # 应用（id, project_id, platform, name, identifier）
            for app in plan["applications"]:
                cur.execute(
                    """
                    INSERT INTO applications (id, project_id, platform, name, identifier)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                       SET platform = EXCLUDED.platform,
                           name = EXCLUDED.name,
                           identifier = EXCLUDED.identifier
                    """,
                    (
                        platform_app[str(app["id"])],
                        project_uuid,
                        app["platform"],
                        app["name"],
                        app["identifier"],
                    ),
                )
            counts["applications"] = len(plan["applications"])

            # 资源档案（id, project_id, platform, name, fingerprint, spec）
            import hashlib
            import json as _json

            for prof in plan["resource_profiles"]:
                spec = {
                    "os_name": prof["os_name"],
                    "os_version": prof["os_version"],
                    "screen_resolution": prof["screen_resolution"],
                }
                fingerprint = hashlib.sha256(
                    _json.dumps(spec, sort_keys=True).encode("utf-8")
                ).hexdigest()
                cur.execute(
                    """
                    INSERT INTO resource_profiles (id, project_id, platform, name, fingerprint, spec)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE
                       SET name = EXCLUDED.name,
                           fingerprint = EXCLUDED.fingerprint,
                           spec = EXCLUDED.spec
                    """,
                    (
                        profile_uuid[str(prof["id"])],
                        project_uuid,
                        "android",
                        prof["name"],
                        fingerprint,
                        _json.dumps(spec),
                    ),
                )
            counts["resource_profiles"] = len(plan["resource_profiles"])

            # 执行节点（id, project_id, name, agent_version, capabilities, status）
            node_uuid = _uid("node:local")
            cur.execute(
                """
                INSERT INTO execution_nodes (id, project_id, name, agent_version, capabilities, status)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status
                """,
                (
                    node_uuid,
                    project_uuid,
                    "本机执行节点",
                    "0.1.0",
                    _json.dumps({"adb": True, "scrcpy": True}),
                    "online",
                ),
            )
            counts["execution_nodes"] = 1

            # 执行资源（id, project_id, node_id, profile_id, platform, resource_key, kind, status）
            for res in plan["execution_resources"]:
                cur.execute(
                    """
                    INSERT INTO execution_resources
                        (id, project_id, node_id, profile_id, platform, resource_key, kind, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                       SET resource_key = EXCLUDED.resource_key,
                           status = EXCLUDED.status,
                           profile_id = EXCLUDED.profile_id
                    """,
                    (
                        _uid("resource:" + str(res["id"])),
                        project_uuid,
                        node_uuid,
                        profile_uuid[str(res["resource_profile_id"])],
                        "android",
                        res["serial"],
                        "device",
                        res["status"],
                    ),
                )
            counts["execution_resources"] = len(plan["execution_resources"])

            # 套件（id, project_id, application_id, name, test_type）
            for suite in plan["suites"]:
                cur.execute(
                    """
                    INSERT INTO test_suites (id, project_id, application_id, name, test_type)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                    """,
                    (
                        suite_uuid[str(suite["id"])],
                        project_uuid,
                        platform_app["xinghe-android"],
                        suite["name"],
                        "ui",
                    ),
                )
            counts["test_suites"] = len(plan["suites"])

        conn.commit()
    return counts


def build_plan() -> dict[str, list[dict[str, object]]]:
    return {
        "projects": [{"id": PROJECT_ID, "name": "星河 Demo", "slug": "demo"}],
        "applications": [
            {"id": "xinghe-android", "platform": "android", "name": "星河 Android", "identifier": "com.example.xinghe"},
            {"id": "xinghe-ios", "platform": "ios", "name": "星河 iOS", "identifier": "com.example.xinghe.ios"},
            {"id": "xinghe-web", "platform": "web", "name": "星河 Web", "identifier": "https://staging.example.test/"},
        ],
        "resource_profiles": [
            {"id": "profile-flagship", "name": "Android 旗舰", "os_name": "Android", "os_version": "14", "screen_resolution": "1080x2400"},
            {"id": "profile-mid", "name": "Android 中端", "os_name": "Android", "os_version": "13", "screen_resolution": "1080x2340"},
        ],
        "execution_resources": [
            {"id": "res-01", "name": "Pixel 8", "serial": "emulator-5554", "status": "ready", "resource_profile_id": "profile-flagship"},
            {"id": "res-02", "name": "Xiaomi 13", "serial": "ABC123456789", "status": "ready", "resource_profile_id": "profile-flagship"},
            {"id": "res-03", "name": "Redmi Note 12", "serial": "DEF123456789", "status": "ready", "resource_profile_id": "profile-mid"},
            {"id": "res-04", "name": "OPPO Reno 10", "serial": "GHI123456789", "status": "ready", "resource_profile_id": "profile-mid"},
            {"id": "res-05", "name": "Huawei P40", "serial": "JKL123456789", "status": "unauthorized", "resource_profile_id": "profile-mid"},
            {"id": "res-06", "name": "vivo X90", "serial": "MNO123456789", "status": "offline", "resource_profile_id": "profile-flagship"},
        ],
        "suites": [
            {"id": "suite-core", "name": "核心链路回归", "case_count": 12},
            {"id": "suite-auth", "name": "登录与账号", "case_count": 6},
            {"id": "suite-order", "name": "下单链路", "case_count": 8},
            {"id": "suite-profile", "name": "个人中心", "case_count": 5},
        ],
        "perf_scenarios": [
            {"id": "scene-home", "name": "首页滑动场景"},
            {"id": "scene-detail", "name": "商品详情"},
            {"id": "scene-search", "name": "搜索场景"},
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
