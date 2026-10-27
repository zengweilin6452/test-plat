"""0002 设备注册：execution_resources 加 last_seen_at（G4）。

依据 docs/plan/device-registration.md §5.1：api-design.md:82 的 /resources 契约
承诺了 last_seen_at，但 0001 里没有这一列——没有它无法区分「从未同步过」与
「3 天前还在」。G4 是 data-model.md §5 允许新增清单的第 4 项，2026-10-27 签字批准。

只加可空列，不加索引：同步按 (project_id, node_id, resource_key) 定位行，
现有 uq_execution_resources_project_id_node_id_resource_key 已覆盖。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "execution_resources",
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次被节点同步确认在线的时间；NULL = 从未同步过",
        ),
    )
    op.execute(
        "COMMENT ON COLUMN execution_resources.last_seen_at IS"
        " '最近一次被节点同步确认在线的时间；NULL = 从未同步过'"
    )


def downgrade() -> None:
    op.drop_column("execution_resources", "last_seen_at")
