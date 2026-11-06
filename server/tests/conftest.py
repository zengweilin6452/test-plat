"""测试夹具（P2 起）。

为什么需要 conftest：P2 的集成测试要往库里写 test_tasks，而 demo 数据所在的
testdock 库是共享开发库（可能同时被 API server 读写）。因此所有集成测试都在
**独立的临时 PostgreSQL 实例**上跑：

    1. 用 .runtime/pg17/pgsql/bin/initdb 建一个空集群（端口按进程随机）
    2. 在上面建 testdock 库并跑 alembic upgrade head（拿到真实 schema）
    3. monkeypatch settings.database_url，让 app.db 建到临时实例上
    4. 测试结束停实例、删目录

绝不复用 127.0.0.1:55432 那个真库，也不碰它的数据目录。

实例在 pytest_configure 阶段就绪（device-registration.md D6 改动二）：
_p3_common 在**模块导入期**读取 TESTDOCK_TEST_DATABASE_URL 算 HAVE_DB，而
fixture 在收集之后才创建——若等到 fixture 才起实例，TEST_DB 是空串，
requires_db 会让 P3 全部 skip（209 个用例"全绿的空跑"）。所以临时实例 +
alembic 必须在收集开始前完成，并把 DSN 写进环境变量。

只有显式设置 TESTDOCK_TEST_DATABASE_URL 才复用外部库（且必须已迁移可达，
否则直接报错）；没有默认值——device-registration.md D6 改动一。
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

#: pytest_configure 与 pg_instance / pytest_unconfigure 之间传递实例状态。
_STATE: dict[str, object] = {"dsn": None, "owned": False, "unavailable_reason": ""}


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


def _external_ready(dsn: str) -> bool:
    """显式指定的外部库必须可用且已迁移（有 test_runs 表），否则报错而非静默换库。"""
    try:
        import psycopg

        libpq = dsn.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(libpq, connect_timeout=3) as conn:
            row = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'test_runs'"
            ).fetchone()
        return row is not None
    except Exception:  # noqa: BLE001 - 连不上/没迁移都算不可用
        return False


def _run_alembic(dsn: str) -> None:
    env = dict(os.environ)
    env["TESTDOCK_DATABASE_URL"] = dsn
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT / "server"),
        env=env,
        capture_output=True,
        # Windows 上子进程失败信息是 GBK：不显式给编码+errors 时，text 解码线程
        # 会抛 UnicodeDecodeError 静默死掉，subprocess.run 永久挂起（实测踩过）。
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade 失败：{result.stdout}\n{result.stderr}")


def _start_temp_instance() -> str:
    """initdb + 起实例 + 建库 + 迁移，返回可用的 DSN。失败时清理后抛错。"""
    if not PG_BIN.exists():
        raise RuntimeError(f"缺少便携 PostgreSQL：{PG_BIN}")

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
            encoding="utf-8",  # 见 _run_alembic 的注释：GBK 输出会让 text 解码线程挂死
            errors="replace",
            text=True,
        )
    finally:
        pwfile.unlink(missing_ok=True)

    logfile = TMP_DATA.parent / f"pg_task9_{os.getpid()}.log"
    # pg_ctl start 必须 DEVNULL，不能 capture_output：pg_ctl 退出后它拉起的
    # postgres 继承了管道写端，reader 线程永远等不到 EOF，communicate() 挂死
    # （py-spy 实测卡在 _communicate）。启动失败的信息在本进程的 pg_task9_<pid>.log 里。
    try:
        subprocess.run(
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
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"临时 PG 启动超时（pg_ctl -w 60s），详见 {logfile}") from exc

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
            encoding="utf-8",
            errors="replace",
            text=True,
        )
        if created.returncode != 0:
            raise RuntimeError(f"建库失败：{created.stderr}\n{created.stdout}")
        dsn = f"postgresql+psycopg://testdock@127.0.0.1:{TMP_PORT}/testdock"
        _run_alembic(dsn)
        return dsn
    except Exception:
        _stop_temp_instance()
        raise


def _stop_temp_instance() -> None:
    subprocess.run(
        [str(_pg_bin("pg_ctl")), "-D", str(TMP_DATA), "-m", "immediate", "stop"],
        capture_output=True,
        encoding="utf-8",  # 见 _run_alembic 的注释
        errors="replace",
        text=True,
    )
    time.sleep(0.5)
    shutil.rmtree(TMP_DATA, ignore_errors=True)
    (TMP_DATA.parent / f"pg_task9_{os.getpid()}.log").unlink(missing_ok=True)


def pytest_configure(config: pytest.Config) -> None:
    """在收集开始前把测试库备好（_p3_common 在导入期读环境变量）。"""
    external = os.environ.get("TESTDOCK_TEST_DATABASE_URL", "").strip()
    if external:
        if not _external_ready(external):
            raise RuntimeError(
                "TESTDOCK_TEST_DATABASE_URL 指向的库不可用或未迁移"
                "（没有 test_runs 表）。请检查该库，或去掉这个变量改用临时实例。"
            )
        _STATE["dsn"] = external
        os.environ.setdefault("TESTDOCK_DATABASE_URL", external)
        return

    if not PG_BIN.exists():
        # 不在 configure 里抛错：纯静态用例（P2 静态约束等）不需要数据库，
        # 让 pg_instance fixture 按需 skip，静态测试仍然能跑。
        _STATE["unavailable_reason"] = f"缺少便携 PostgreSQL：{PG_BIN}"
        return

    dsn = _start_temp_instance()
    _STATE["dsn"] = dsn
    _STATE["owned"] = True
    os.environ["TESTDOCK_TEST_DATABASE_URL"] = dsn
    os.environ["TESTDOCK_DATABASE_URL"] = dsn


def pytest_unconfigure(config: pytest.Config) -> None:
    if _STATE["owned"]:
        _stop_temp_instance()
    _STATE["dsn"] = None
    _STATE["owned"] = False


@pytest.fixture(scope="session")
def pg_instance():
    """yield 已就绪的实例 DSN；结束时清理由 pytest_unconfigure 负责。"""
    dsn = _STATE.get("dsn")
    if not dsn:
        pytest.skip(str(_STATE["unavailable_reason"]) or "测试数据库不可用")
    yield str(dsn)


@pytest.fixture(scope="session")
def migrated_dsn(pg_instance):
    """迁移已在 pytest_configure 完成（收集开始前必须就绪，见模块 docstring）。"""
    return pg_instance
