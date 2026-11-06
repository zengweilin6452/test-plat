"""工作空间设置域逻辑（正式化改造工单 01）。

单工作空间、无租户：workspace_settings 表只有 id=1 一行。默认名称
「默认工作空间」由 0009 迁移写入；首次读取遇到缺行（极旧库手工迁移等）
时补建默认行，保证 GET /workspace 永远可用。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import bad_request
from .identity import NAME_MAX_LEN, NAME_MIN_LEN, normalize_name

DEFAULT_WORKSPACE_NAME = "默认工作空间"


async def ensure_row(session: AsyncSession) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT id, name, customized_at, updated_at FROM workspace_settings WHERE id = 1")
        )
    ).mappings().first()
    if row is None:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workspace_settings (id, name) VALUES (1, :name) "
                    "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name "
                    "RETURNING id, name, customized_at, updated_at"
                ),
                {"name": DEFAULT_WORKSPACE_NAME},
            )
        ).mappings().one()
    return dict(row)


async def get_workspace(session: AsyncSession) -> dict[str, Any]:
    return await ensure_row(session)


async def rename_workspace(session: AsyncSession, *, name: Any) -> dict[str, Any]:
    display_name = normalize_name(name)
    if not (NAME_MIN_LEN <= len(display_name) <= NAME_MAX_LEN):
        raise bad_request(
            "工作空间名称需为 1-60 个字符（去首尾空白）",
            {"field": "name", "length": len(display_name)},
        )
    await ensure_row(session)
    row = (
        await session.execute(
            text(
                "UPDATE workspace_settings SET name = :name, customized_at = now(), updated_at = now() "
                "WHERE id = 1 RETURNING id, name, customized_at, updated_at"
            ),
            {"name": display_name},
        )
    ).mappings().one()
    return dict(row)
