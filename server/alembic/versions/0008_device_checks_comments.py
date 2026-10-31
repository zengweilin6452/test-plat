"""0008 device_checks 注释（工单 22 / 数据设计口径）。

0004 建 device_checks 时没写 COMMENT，导致「每张表都有中文注释」的数据设计
口径对新表失效（/schema 的 comment 为空）。本迁移只补注释，不改结构；
downgrade 把注释清空，回到 0004 之后的状态。

注释一律写成字面量 SQL：scripts/gen_schema_doc.py 用 ast 解析迁移里的
op.execute("COMMENT ON ...")，f-string 拼出来的语句它读不到。
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "COMMENT ON TABLE device_checks IS "
        "'设备短检查（readiness / identity）；与运行、调试共用 resource_leases 互斥'"
    )
    op.execute("COMMENT ON COLUMN device_checks.id IS '检查 id'")
    op.execute("COMMENT ON COLUMN device_checks.project_id IS '所属项目'")
    op.execute("COMMENT ON COLUMN device_checks.resource_id IS '被检查的执行资源'")
    op.execute("COMMENT ON COLUMN device_checks.kind IS '检查类型：readiness / identity'")
    op.execute("COMMENT ON COLUMN device_checks.test_type IS '检查目标测试类型'")
    op.execute("COMMENT ON COLUMN device_checks.holder_id IS '检查持有者标识'")
    op.execute(
        "COMMENT ON COLUMN device_checks.state IS "
        "'检查状态：opening / running / finished / failed / lost'"
    )
    op.execute("COMMENT ON COLUMN device_checks.requested_at IS '请求时间'")
    op.execute("COMMENT ON COLUMN device_checks.started_at IS '开始时间'")
    op.execute("COMMENT ON COLUMN device_checks.finished_at IS '结束时间'")
    op.execute(
        "COMMENT ON COLUMN device_checks.expires_at IS '租约到期时间；过期即视为丢失'"
    )
    op.execute(
        "COMMENT ON COLUMN device_checks.result IS '检查结果（readiness / identity 判定）'"
    )
    op.execute("COMMENT ON COLUMN device_checks.error_code IS '失败错误码'")
    op.execute("COMMENT ON COLUMN device_checks.created_at IS '创建时间'")


def downgrade() -> None:
    op.execute("COMMENT ON TABLE device_checks IS NULL")
    for column in (
        "id",
        "project_id",
        "resource_id",
        "kind",
        "test_type",
        "holder_id",
        "state",
        "requested_at",
        "started_at",
        "finished_at",
        "expires_at",
        "result",
        "error_code",
        "created_at",
    ):
        op.execute(f"COMMENT ON COLUMN device_checks.{column} IS NULL")
