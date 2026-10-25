"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

生成说明：本项目初始迁移（0001_initial.py）为手写，逐字对照
docs/platform-prototype/schema.sql。增量迁移同样要求：

1. 不出现 BEGIN / COMMIT（Alembic 已在事务中，P0-1）；
2. 每条约束显式命名 ck_ / uq_ / fk_ / pk_（P0-2）；
3. 新列/新表先在 docs/plan/data-model.md 登记理由，再改迁移；
4. 文件头写明「未验证」项，直到在隔离空库跑过 upgrade head。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # noqa: F401  (多数列需要 jsonb/uuid 类型)

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
