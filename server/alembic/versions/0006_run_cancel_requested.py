"""0006 运行取消受理事实（工单 08）。

取消必须是**持久化事实**，不能靠"最近 500 条事件里有没有 cancel_requested"推断：
事件可能被分页截断、被清理，而取消一旦受理就不能丢（spec §9.3、AC-CONTRACT-03）。

0001 已冻结，所以在 test_runs 上追加两列：

- cancel_requested_at：首次受理时间。重复取消用 COALESCE 保持第一次的值，
  不会因为重复点击改变事实；
- cancel_requested_by：受理人（审计用）。

事件流里的 cancel_requested 仍然写，供时间线展示；判定改读列。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True))
    )
    op.add_column("test_runs", sa.Column("cancel_requested_by", sa.Text()))
    op.execute(
        "COMMENT ON COLUMN test_runs.cancel_requested_at IS '取消受理时间；持久化事实，重复受理不改写'"
    )
    op.execute("COMMENT ON COLUMN test_runs.cancel_requested_by IS '取消受理人'")
    # 把历史上只存在于事件流里的取消事实补到列上，迁移后判定口径立即一致。
    op.execute(
        """
        UPDATE test_runs r
           SET cancel_requested_at = e.occurred_at
          FROM (
                SELECT run_id, min(occurred_at) AS occurred_at
                  FROM run_events
                 WHERE event_type = 'cancel_requested'
                 GROUP BY run_id
               ) e
         WHERE r.id = e.run_id
           AND r.cancel_requested_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("test_runs", "cancel_requested_by")
    op.drop_column("test_runs", "cancel_requested_at")
