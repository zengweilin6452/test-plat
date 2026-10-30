"""0007 稳定运行展示编号（工单 09）。

为什么要落列
------------
此前 `display_id` 是查询期用 `row_number() OVER (ORDER BY created_at, id)` 现算的：
插入一条更早的记录、删掉历史数据或换一种过滤/分页，同一个运行就会换号 ——
而编号会出现在链接、报告、导出和告警里，换号等于让这些引用指向别处
（spec INV-10 / §9.3、AC-ID-01）。

所以把编号**持久分配**一次：

- `display_no`：全局递增的展示序号，`RUN-0001` 由它格式化而来；
- 默认值取序列 `test_run_display_no_seq`，新运行插入即得号，并发下也不会撞；
- 唯一索引保证不会有两个运行共用同一编号。

历史回填
--------
回填只按 `(created_at, id)` 升序排一次，与旧的动态算法同一口径 —— 这样已经
流出去的 `RUN-xxxx` 引用在迁移后仍然指向同一个运行。回填语句带
`WHERE display_no IS NULL`，重复执行是空操作（只回填一次、幂等）。

UUID 仍是精确身份：接口路径继续用 UUID，展示编号只用于人读。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

#: 只回填尚未编号的行：重复执行不改变已有编号（迁移重跑/补数据的幂等保证）。
BACKFILL_SQL = """
    UPDATE test_runs r
       SET display_no = n.rn
      FROM (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn
              FROM test_runs
           ) n
     WHERE r.id = n.id
       AND r.display_no IS NULL
"""


def upgrade() -> None:
    op.execute("CREATE SEQUENCE test_run_display_no_seq")
    op.add_column("test_runs", sa.Column("display_no", sa.BigInteger(), nullable=True))
    op.execute(
        "COMMENT ON COLUMN test_runs.display_no IS "
        "'全局展示序号，RUN-0001 由它格式化；持久分配，历史变动不重编号'"
    )
    op.execute(BACKFILL_SQL)
    # 新运行由序列发号；历史行已经回填，之后不再允许空号。
    op.execute(
        "ALTER TABLE test_runs ALTER COLUMN display_no"
        " SET DEFAULT nextval('test_run_display_no_seq')"
    )
    op.execute("ALTER TABLE test_runs ALTER COLUMN display_no SET NOT NULL")
    op.execute("CREATE UNIQUE INDEX test_runs_display_no_key ON test_runs (display_no)")
    # 序列推进到现有最大值之后；表为空时下一个号是 1（setval 不接受 0）。
    op.execute(
        """
        SELECT setval(
            'test_run_display_no_seq',
            COALESCE((SELECT max(display_no) FROM test_runs), 0) + 1,
            false
        )
        """
    )
    op.execute("ALTER SEQUENCE test_run_display_no_seq OWNED BY test_runs.display_no")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS test_runs_display_no_key")
    # OWNED BY 让 drop column 一并删掉序列
    op.drop_column("test_runs", "display_no")
