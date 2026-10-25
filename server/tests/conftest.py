"""测试夹具（P2 起）。

为什么需要 conftest：P2 的集成测试要往库里写 test_tasks，而 demo 数据所在的
testdock 库是 Lead 在用的共享库（可能同时被 API server 读写）。因此所有集成
测试都在**独立的临时 PostgreSQL 实例**上跑：

    1. 用 .runtime/pg17/pgsql/bin/initdb 建一个空集群（端口 55433）
    2. 在上面建 testdock 库并跑 alembic upgrade head（拿到真实 schema）
    3. monkeypatch settings.database_url，让 app.db 建到临时实例上
    4. 测试结束停实例、删目录

绝不复用 127.0.0.1:55432 那个真库，也不碰它的数据目录。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

if sys.platform == "win32":
    # pytest-asyncio 1.x：policy 必须在导入期设置（见 _p3_common.py 同款注释）。
    import asyncio as _asyncio

    _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_BIN = REPO_ROOT / ".runtime" / "pg17" / "pgsql" / "bin"
# 固定端口会让并发的两份 pytest（Lead 跑全量、我这边单跑）互相踩 socket：
# 第二份 initdb 失败 -> pg_ctl 起在别人的数据目录上 -> 直接把手上的实例踹掉。
# 所以端口和数据目录都按进程随机生成，并在 pg_ctl 命令行上以 -D 显式绑定。
TMP_PORT = int(os.environ.get("TESTDOCK_PG_PORT") or 0) or (56000 + uuid.uuid4().int % 3000)
TMP_DATA = REPO_ROOT / ".runtime" / "pg17" / f"data_pt_task9_{os.getpid()}"


def _pg_bin(name: str) -> Path:
    return PG_BIN / (name + (".exe" if sys.platform == "win32" else ""))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _wait_ready(port: int, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _port_free(port):
            return True
        time.sleep(0.2)
    return False


#: TESTDOCK_TEST_DATABASE_URL 指向的共享库（Lead 的 API server 正在用同一个实例）。
_EXTERNAL_DSN = "postgresql+psycopg://testdock@127.0.0.1:55432/testdock"


def _external_instance_ready() -> str | None:
    """探测共享库是否可用且已迁移（有 test_runs 表）；可用则返回 DSN。

    优先级：TESTDOCK_TEST_DATABASE_URL > 默认 55432 共享库。
    """
    dsn = os.environ.get("TESTDOCK_TEST_DATABASE_URL") or _EXTERNAL_DSN
    try:
        import psycopg

        libpq = dsn.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(libpq, connect_timeout=3) as conn:
            row = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'test_runs'"
            ).fetchone()
        return dsn if row is not None else None
    except Exception:  # noqa: BLE001
        return None

@pytest.fixture(scope="session")
def pg_instance():
    """起一个临时 PG 实例，yield 它的 DSN；结束时清理。

    P3 起：TESTDOCK_TEST_DATABASE_URL 指定的库（Lead 的共享 testdock 库）如果可用
    且已迁移，就直接复用它 —— 便携集群在 55433 上被 Lead 的 API server 占着，
    重跑 initdb 会撞端口。复用模式下只写测试自己的数据（唯一 request_key /
    随机后缀），绝不 drop 库、绝不碰 PG 进程。
    """
    external = _external_instance_ready()
    if external:
        yield external
        return

    """起一个临时 PG 实例，yield 它的 DSN；结束时清理。"""
    if not PG_BIN.exists():
        pytest.skip(f"缺少便携 PostgreSQL：{PG_BIN}")

    if TMP_DATA.exists():
        shutil.rmtree(TMP_DATA, ignore_errors=True)
    TMP_DATA.parent.mkdir(parents=True, exist_ok=True)

    pwfile = TMP_DATA.parent / "pg_pass_task9.txt"
    pwfile.write_text("testdock", encoding="utf-8")
    try:
        subprocess.run(
            [
                str(_pg_bin("initdb")),
                "--no-sync",
                "-D",
                str(TMP_DATA),
                "-U",
                "testdock",
                "-A",
                "trust",
                "-E",
                "UTF8",
                "--locale=C",
                f"--pwfile={pwfile}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        pwfile.unlink(missing_ok=True)

    logfile = TMP_DATA.parent / "pg_task9.log"
    started = subprocess.run(
        [
            str(_pg_bin("pg_ctl")),
            "-D",
            str(TMP_DATA),
            "-l",
            str(logfile),
            "-o",
            f"-p {TMP_PORT} -c listen_addresses=127.0.0.1",
            "-w",
            "start",
        ],
        capture_output=True,
        text=True,
    )
    if started.returncode != 0:
        raise RuntimeError(f"临时 PG 启动失败：{started.stdout}\n{started.stderr}")

    try:
        if not _wait_ready(TMP_PORT):
            raise RuntimeError("临时 PG 端口未就绪")
        created = subprocess.run(
            [
                str(_pg_bin("createdb")),
                "-h",
                "127.0.0.1",
                "-p",
                str(TMP_PORT),
                "-U",
                "testdock",
                "testdock",
            ],
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            raise RuntimeError(f"建库失败：{created.stderr}")
        yield f"postgresql+psycopg://testdock@127.0.0.1:{TMP_PORT}/testdock"
    finally:
        subprocess.run(
            [str(_pg_bin("pg_ctl")), "-D", str(TMP_DATA), "-m", "immediate", "stop"],
            capture_output=True,
            text=True,
        )
        time.sleep(0.5)
        shutil.rmtree(TMP_DATA, ignore_errors=True)
        logfile.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def migrated_dsn(pg_instance):
    """在临时实例上跑 alembic upgrade head。"""
    env = dict(os.environ)
    env["TESTDOCK_DATABASE_URL"] = pg_instance
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT / "server"),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade 失败：{result.stdout}\n{result.stderr}")
    return pg_instance
