"""性能能力接入：metric_summaries.statistic 增加 p90，artifacts.kind 增加 har。

vendor mobile_perf 的聚合报告自带 p90（metricsSummary[key].p90），此前 DB 枚举
没有 p90，每个指标的第 90 百分位被永久丢弃；HAR 抓包文件（network/app.har）
此前只能落 kind='other'，前端无法按类型呈现。两个 CHECK 都按名字重建：
PG 支持按名 DROP + ADD，不重建表、不动数据。
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

STATISTIC_OLD = "ck_metric_summaries_statistic_allowed"
STATISTIC_NEW = "statistic IN ('median','p95','p90','mean','min','max')"
ARTIFACT_OLD = "ck_artifacts_kind_allowed"
ARTIFACT_NEW = (
    "kind IN ('screenshot','ui_tree','video','log','trace','metric_series',"
    "'report_json','report_html','har','other')"
)


def upgrade() -> None:
    op.drop_constraint(STATISTIC_OLD, "metric_summaries", type_="check")
    op.create_check_constraint(STATISTIC_OLD, "metric_summaries", STATISTIC_NEW)
    op.drop_constraint(ARTIFACT_OLD, "artifacts", type_="check")
    op.create_check_constraint(ARTIFACT_OLD, "artifacts", ARTIFACT_NEW)


def downgrade() -> None:
    # 回滚前先清掉 p90 行 / har 行，否则新 CHECK 会拒绝存量数据
    op.execute("DELETE FROM metric_summaries WHERE statistic = 'p90'")
    op.execute("DELETE FROM artifacts WHERE kind = 'har'")
    op.drop_constraint(STATISTIC_OLD, "metric_summaries", type_="check")
    op.create_check_constraint(STATISTIC_OLD, "metric_summaries", "statistic IN ('median','p95','mean','min','max')")
    op.drop_constraint(ARTIFACT_OLD, "artifacts", type_="check")
    op.create_check_constraint(ARTIFACT_OLD, "artifacts", "kind IN ('screenshot','ui_tree','video','log','trace','metric_series','report_json','report_html','other')")
