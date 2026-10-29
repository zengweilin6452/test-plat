"""0003 契约基线占位迁移（工单 01）。

本迁移**不修改任何表结构**，只作为后续工单（02–23）追加迁移的锚点。
0001 是冻结的原件（sha256 见 docs/contracts/migration-baseline.json）；
0002 已用于 execution_resources.last_seen_at，故本骨架接在其后。
所有结构变更一律追加 0003 之后的新迁移，不回头改 0001。
"""

from __future__ import annotations

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
