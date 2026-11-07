"""为没有测试环境的存量项目补齐默认环境。"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

BACKFILL_SQL = """
    INSERT INTO environments (id, project_id, name)
    SELECT gen_random_uuid(), p.id, 'default'
      FROM projects p
     WHERE NOT EXISTS (
           SELECT 1 FROM environments e WHERE e.project_id = p.id
     )
     ORDER BY p.created_at, p.id
"""


def upgrade() -> None:
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    pass
