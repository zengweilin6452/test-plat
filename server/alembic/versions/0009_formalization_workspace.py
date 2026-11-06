"""0009 正式化改造（工单 01/02/07）：工作空间设置与业务对象来源标记。

只追加，不修改历史迁移：

1. 新表 workspace_settings：单行（id=1）保存唯一工作空间的显示名称。
   正式初始化只建立这一条必要系统设置，不写任何业务演示数据；
   默认名称「默认工作空间」，customized_at 记录用户显式改名的时间
   （首用引导的完成状态由它计算，见 /onboarding/status）。
2. projects.origin / applications.origin：可信来源标记，仅服务于**以后**
   显式演示导入的数据（seed_demo 写 'demo_seed'）；存量行保持 NULL，
   不倒填「已确认演示」（规格 §8）。

唯一性沿用既有约束：projects.code 全局唯一、applications 的
uq_applications_project_id_platform_identifier 在归档后仍占用唯一键，
满足「归档记录仍占用唯一键」的规格要求，无需新增约束。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_settings",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("customized_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(sa.text("id = 1"), name="ck_workspace_settings_singleton"),
        sa.CheckConstraint(sa.text("char_length(btrim(name)) BETWEEN 1 AND 60"), name="ck_workspace_settings_name_length"),
    )
    op.execute(
        "INSERT INTO workspace_settings (id, name) VALUES (1, '默认工作空间')"
    )
    op.execute("COMMENT ON TABLE workspace_settings IS '工作空间设置（单行）：唯一工作空间的显示名称'")
    op.execute("COMMENT ON COLUMN workspace_settings.id IS '单行固定值 1'")
    op.execute("COMMENT ON COLUMN workspace_settings.name IS '工作空间显示名称（去空白后 1-60 字符）'")
    op.execute("COMMENT ON COLUMN workspace_settings.customized_at IS '用户显式改名时间；NULL 表示仍是默认名称'")
    op.execute("COMMENT ON COLUMN workspace_settings.updated_at IS '最近更新时间'")

    op.add_column("projects", sa.Column("origin", sa.Text(), nullable=True))
    op.execute(
        "ALTER TABLE projects ADD CONSTRAINT ck_projects_origin_allowed"
        " CHECK (origin IN ('manual', 'demo_seed'))"
    )
    op.execute(
        "COMMENT ON COLUMN projects.origin IS "
        "'来源标记：manual=页面/接口建立，demo_seed=显式演示导入；存量行 NULL=未标记'"
    )
    op.add_column("applications", sa.Column("origin", sa.Text(), nullable=True))
    op.execute(
        "ALTER TABLE applications ADD CONSTRAINT ck_applications_origin_allowed"
        " CHECK (origin IN ('manual', 'demo_seed'))"
    )
    op.execute(
        "COMMENT ON COLUMN applications.origin IS "
        "'来源标记：manual=页面/接口建立，demo_seed=显式演示导入；存量行 NULL=未标记'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE applications DROP CONSTRAINT IF EXISTS ck_applications_origin_allowed")
    op.drop_column("applications", "origin")
    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS ck_projects_origin_allowed")
    op.drop_column("projects", "origin")
    op.drop_table("workspace_settings")
