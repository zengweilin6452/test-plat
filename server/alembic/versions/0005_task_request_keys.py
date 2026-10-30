"""0005 任务创建幂等键（工单 07）。

POST /tasks 的幂等键必须跨进程、跨重启有效（spec §9.1），不能只靠进程内字典，
而 0001 已冻结、test_tasks 没有 request_key 列，所以追加一张键表：

- (project_id, request_key) 唯一：同一个键在一个项目内只能绑定一次；
- fingerprint 存规范化业务内容的 sha256：同键同内容复用原任务，同键不同内容
  返回 409 idempotency_conflict 且不产生新副作用；
- task_id 指向键首次绑定的任务；project_id + task_id 复合外键保证不会跨项目串键。

写入顺序是"先占键、再建任务"（同一事务），因此不会留下指向半成品的键行：
事务失败时键行随任务一起回滚。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_request_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "project_id", "request_key", name="uq_task_request_keys_project_id_request_key"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "task_id"],
            ["test_tasks.project_id", "test_tasks.id"],
            name="fk_task_request_keys_project_id_task_id_test_tasks",
        ),
        sa.CheckConstraint(
            "length(request_key) > 0", name="ck_task_request_keys_request_key_not_empty"
        ),
    )
    op.create_index(
        "task_request_keys_task", "task_request_keys", ["task_id"], unique=False
    )
    op.execute("COMMENT ON TABLE task_request_keys IS '任务创建幂等键；跨重启复用'")
    op.execute("COMMENT ON COLUMN task_request_keys.request_key IS '项目内请求幂等键'")
    op.execute("COMMENT ON COLUMN task_request_keys.fingerprint IS '规范化创建内容摘要'")
    op.execute("COMMENT ON COLUMN task_request_keys.task_id IS '键首次绑定的任务'")


def downgrade() -> None:
    op.drop_index("task_request_keys_task", table_name="task_request_keys")
    op.drop_table("task_request_keys")
