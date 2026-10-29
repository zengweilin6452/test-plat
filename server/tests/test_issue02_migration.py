"""工单 02：短检查租约迁移（0004）的结构与只追加约束。

两层证据：
1. 静态：revision 接在 0003 之后，声明了 device_checks / check_id /
   三选一 XOR / leases_one_live_check。
2. 真实 PG（临时实例）：alembic upgrade head 后列、约束、部分唯一索引确实存在。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

from tests._p3_common import libpq_dsn, requires_db
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - fixture 复用

SERVER_DIR = Path(__file__).resolve().parents[1]
VERSIONS_DIR = SERVER_DIR / "alembic" / "versions"
MIGRATION = VERSIONS_DIR / "0004_device_readiness_checks.py"


def _literals(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return values


def test_0004_revision_follows_0003() -> None:
    assert MIGRATION.is_file(), "缺少 0004 迁移"
    values = _literals(MIGRATION)
    assert values.get("revision") == "0004"
    assert values.get("down_revision") == "0003"


def test_0004_declares_check_lease_channel() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "device_checks" in source
    assert "check_id" in source
    assert "num_nonnulls(run_id, debug_session_id, check_id) = 1" in source
    assert "leases_one_live_check" in source


@requires_db
def test_schema_exposes_check_lease_channel(sync_engine) -> None:
    with sync_engine.connect() as conn:
        lease_columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'resource_leases'"
                )
            )
        }
        assert "check_id" in lease_columns

        check_columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'device_checks'"
                )
            )
        }
        assert {
            "id",
            "project_id",
            "resource_id",
            "kind",
            "test_type",
            "holder_id",
            "state",
            "expires_at",
            "result",
        } <= check_columns

        indexes = {
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'resource_leases'")
            )
        }
        assert "leases_one_live_check" in indexes
        # 既有互斥索引必须保留：check 与 run/debug 共享同一资源锁
        assert "leases_one_live_resource" in indexes

        constraints = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint"
                    " WHERE conrelid = 'resource_leases'::regclass"
                )
            )
        }
        assert "ck_resource_leases_single_holder" in constraints
        assert (
            "fk_resource_leases_project_check_id_device_checks"
            in constraints
        )


@requires_db
def test_0004_downgrade_and_upgrade_roundtrip() -> None:
    """在独立临时数据库上演练 0004 回退与重放，不碰测试库本身。"""
    import psycopg

    libpq = libpq_dsn()
    base, _, _ = libpq.rpartition("/")
    dbname = f"migration_rt_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base + "/postgres", autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    target = f"{base}/{dbname}"
    env = dict(os.environ)
    env["TESTDOCK_DATABASE_URL"] = target.replace(
        "postgresql://", "postgresql+psycopg://"
    )
    env["PYTHONUTF8"] = "1"

    def run(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=str(SERVER_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def has_check_channel() -> bool:
        with psycopg.connect(target) as conn:
            column = conn.execute(
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_name = 'resource_leases' AND column_name = 'check_id'"
            ).fetchone()
            table = conn.execute(
                "SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'device_checks'"
            ).fetchone()
        return column is not None and table is not None

    try:
        run("upgrade", "head")
        assert has_check_channel()
        run("downgrade", "0003")
        assert not has_check_channel()
        run("upgrade", "head")
        assert has_check_channel()
    finally:
        with psycopg.connect(base + "/postgres", autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
