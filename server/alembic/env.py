"""Alembic 运行环境。

数据库 URL 解析顺序（与 server/app/config.py 保持一致）：

1. 环境变量 TESTDOCK_DATABASE_URL（容器 / CI / 测试注入）
2. app.config.settings.database_url（读同一组 TESTDOCK_* 环境变量 + .env）
3. alembic.ini 的 sqlalchemy.url（本机默认值）

注意：本项目用 psycopg 3 的**同步**驱动跑迁移（postgresql+psycopg://），与 API 侧的
异步引擎共用同一个 URL —— Alembic 的 DDL 是顺序执行的，同步连接更简单，也更贴近
schema.sql 的逐句语义。若传入只支持异步的 URL，这里显式报错而不是静默降级。

不连库也能离线生成 DDL：alembic upgrade head --sql（见 run_migrations_offline）。
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---- 让 env.py 能 import app.config（alembic.ini 位于 server/ 根） ----------------
SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# ---- Windows 中文环境修复 ------------------------------------------------
# Alembic 用 configparser 读 alembic.ini，其 read() 默认 encoding="locale"。
# 在 GBK 代码页的 Windows 上，含中文注释的 alembic.ini 会直接
# UnicodeDecodeError: 'gbk' codec can't decode byte 0x82。
# 这里把 configparser 的默认编码强制为 UTF-8，使 alembic.ini 始终按 UTF-8 解析，
# 不受 PYTHONUTF8 / 控制台代码页影响。
import configparser as _configparser

if not getattr(_configparser, "_testdock_utf8_patched", False):
    _orig_read = _configparser.RawConfigParser.read

    def _read_utf8(self, filenames, encoding=None, **kwargs):  # noqa: ANN001
        return _orig_read(self, filenames, encoding=encoding or "utf-8")

    _configparser.RawConfigParser.read = _read_utf8  # type: ignore[method-assign]
    _configparser._testdock_utf8_patched = True  # type: ignore[attr-defined]
# -------------------------------------------------------------------------

# Alembic Config 对象，提供对 alembic.ini 的访问
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# ---- 目标元数据：本项目初始迁移是**手写**的（见 0001_initial.py 文件头），不依赖
# ---- ORM 模型，因此 target_metadata 保持 None。后续若引入与 schema.sql 对齐的 ORM
# ---- 模型，可改为 Base.metadata；autogenerate 目前不在计划内。
target_metadata = None


def _resolve_database_url() -> str:
    """按 环境变量 -> app.config -> alembic.ini 的顺序解析数据库 URL。"""

    from_env = os.environ.get("TESTDOCK_DATABASE_URL", "").strip()
    if from_env:
        return from_env

    try:  # 软依赖：让 alembic 在没有 pydantic-settings 的极简环境里也能 --sql
        from app.config import settings

        url = (settings.database_url or "").strip()
        if url:
            return url
    except Exception:
        pass

    fallback = (config.get_main_option("sqlalchemy.url") or "").strip()
    if not fallback:
        raise RuntimeError(
            "未找到数据库 URL：请设置环境变量 TESTDOCK_DATABASE_URL，"
            "或在 server/alembic.ini 里填写 sqlalchemy.url。"
        )
    return fallback


def _assert_sync_driver(url: str) -> str:
    """迁移走同步驱动；只拒绝明确只支持异步的方言。"""

    async_only = ("+asyncpg", "+aiosqlite", "+aiomysql", "+asyncmy", "+aioodbc")
    for marker in async_only:
        if marker in url:
            raise RuntimeError(
                marker + " 是异步驱动，Alembic 迁移需要同步驱动。"
                "请改用 postgresql+psycopg:// （psycopg 3 同步模式）。"
            )
    return url


def run_migrations_offline() -> None:
    """离线模式：只把 SQL 打印到标准输出，不连库（alembic upgrade head --sql）。

    本机无 PostgreSQL 时，这是唯一能「看到」迁移 DDL 的方式；但它**不校验**
    DDL 在 PG 上是否可执行（见 0001_initial.py 文件头的「未验证」段落）。
    """

    url = _assert_sync_driver(_resolve_database_url())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：建真实连接，在单个事务里按序执行迁移。"""

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _assert_sync_driver(_resolve_database_url())

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_schemas=False,
            include_object=None,
            # 单文件迁移内部不再按 migration 拆事务，整体原子（P0-1 的前提）
            transaction_per_migration=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
