"""0004 设备短检查租约通道（工单 02）。

短检查（手动 readiness）与运行/调试共用同一张 resource_leases 作为权威互斥：
- 新表 device_checks 记录一次检查的持有者、状态与结果；
- resource_leases 增加 check_id 通道，并把原来的 run/debug 二选一 CHECK
  升级为 run/debug/check 三选一；
- 既有 leases_one_live_resource 部分唯一索引保持不变，因此 check 与 run/debug
  天然互斥；leases_one_live_check 保证一次检查最多一条活动租约。

0001 是冻结原件，本迁移只追加；downgrade 反向恢复旧的二选一 CHECK。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_CHECK_KINDS = "kind IN ('readiness','identity')"
_TEST_TYPES = "test_type IN ('ui','performance','joint')"
_CHECK_STATES = "state IN ('opening','running','finished','failed','lost')"


def upgrade() -> None:
    op.create_table(
        "device_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("test_type", sa.Text(), nullable=False),
        sa.Column("holder_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error_code", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(_CHECK_KINDS, name="ck_device_checks_kind_allowed"),
        sa.CheckConstraint(_TEST_TYPES, name="ck_device_checks_test_type_allowed"),
        sa.CheckConstraint(_CHECK_STATES, name="ck_device_checks_state_allowed"),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_device_checks_expires_at_after_created"
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="ck_device_checks_finished_at_not_before_created",
        ),
        sa.UniqueConstraint("project_id", "id", name="uq_device_checks_project_id_id"),
        sa.UniqueConstraint(
            "project_id",
            "id",
            "resource_id",
            name="uq_device_checks_project_id_id_resource_id",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "resource_id"],
            ["execution_resources.project_id", "execution_resources.id"],
            name="fk_device_checks_project_id_resource_id_execution_resources",
        ),
    )

    op.add_column(
        "resource_leases",
        sa.Column(
            "check_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="短检查（device_checks）通道；与 run_id/debug_session_id 三选一",
        ),
    )
    op.drop_constraint(
        "ck_resource_leases_run_id_xor_debug_session", "resource_leases", type_="check"
    )
    op.create_check_constraint(
        "ck_resource_leases_single_holder",
        "resource_leases",
        "num_nonnulls(run_id, debug_session_id, check_id) = 1",
    )
    op.create_foreign_key(
        "fk_resource_leases_project_check_id_device_checks",
        "resource_leases",
        "device_checks",
        ["project_id", "check_id", "resource_id"],
        ["project_id", "id", "resource_id"],
    )
    op.execute(
        "CREATE UNIQUE INDEX leases_one_live_check"
        " ON resource_leases (project_id, check_id)"
        " WHERE released_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS leases_one_live_check")
    op.drop_constraint(
        "fk_resource_leases_project_check_id_device_checks",
        "resource_leases",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_resource_leases_single_holder", "resource_leases", type_="check"
    )
    op.create_check_constraint(
        "ck_resource_leases_run_id_xor_debug_session",
        "resource_leases",
        "(run_id IS NOT NULL) <> (debug_session_id IS NOT NULL)",
    )
    op.drop_column("resource_leases", "check_id")
    op.drop_table("device_checks")
