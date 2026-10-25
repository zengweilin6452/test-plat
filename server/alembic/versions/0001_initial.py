"""0001 初始迁移：TestDock 平台 24 张表 + 索引 + 注释。

从评审稿 docs/platform-prototype/schema.sql（730 行，PG17）逐字搬迁，并落实
docs/plan/data-model.md §8.1 与 docs/plan/research/schema-review.md §6/§7.1 的修正。

## 生成方式
手写（本题由 server/alembic/_gen/generate_0001.py 生成后人工复核），**不使用
alembic revision --autogenerate**：autogenerate 只能从 ORM 反推，会静默丢掉跨列
CHECK（(state='completed') = (outcome IS NOT NULL)）、部分唯一索引
（WHERE released_at IS NULL）等语义（data-model.md:16）。

## 相对 schema.sql 的 4 处阻塞项修正（P0-1..P0-4）
1. P0-1 去掉事务包装：不出现 BEGIN / COMMIT。Alembic 的 upgrade 本身在事务中
   执行，迁移内再提交会提前提交并破坏原子性；alembic_version 天然拦截重复执行。
2. P0-2 约束全部显式命名（schema.sql 里 0 个 CONSTRAINT 名）：
   pk_<table>（主键）/ uq_<table>_<cols> / fk_<table>_<cols>_<ref> /
   ck_<table>_<col>_<slug>。带名字后才可稳定写 ALTER TABLE ... DROP CONSTRAINT
   与增量迁移。
3. P0-3 三态口径补齐：run_components 补 reason_code TEXT NULL、
   test_runs 补 not_tested_reason TEXT NULL，并各加
   CHECK (outcome <> 'not_tested' OR <reason> IS NOT NULL)，对齐
   database-design.md:98/216 与 gate_evaluations 的既有范式。
4. P0-4 单一真源：本迁移 = 可执行真源；schema.sql 保留为评审快照。

## 平台新增 3 列（data-model.md §5，唯一的「允许新增」范围）
- metric_summaries.missing_reason_text (G1)：vendor 只给中文原因，枚举不足以对人解释。
- execution_resources.fence_counter (G2)：租约 fencing token 来源（原型缺失）。
- test_runs.parent_run_id (G3)：重跑追溯链（原型抽屉有「重新运行自 RUN-x」文案但无字段）。

## 注释与特殊 CHECK 的实现方式
- 255 条 COMMENT ON TABLE/COLUMN（24 表 + 231 列）逐条 op.execute，原文来自
  schema.sql、与评审稿逐字一致，便于 diff 与中文 UTF-8 保真（schema-review.md §6.3-1）。
- jsonb_typeof、正则 ~、float8 边界这三类 CHECK 用 sa.CheckConstraint(sa.text(...))
  承载（不进 op.execute）：文本原样穿过 SQLAlchemy，避免 :: 与 % 占位符转义问题
  （schema-review.md §6.3-3/4/5 允许两种写法）。

## 索引
- 15 条来自 schema.sql L714-728，其中 7 条部分索引用
  op.create_index(..., postgresql_where=sa.text(...))；PG 的 UNIQUE 约束不支持 WHERE，
  因此 4 条唯一部分索引必须写成唯一索引。
- 追加 4 条优先索引（data-model.md §8.3）：debug_sessions 活动会话查找（G1）、
  metric_summaries 趋势查询（G2）、test_runs.parent_run_id 重跑链（G3）、
  task_revisions(task_id) 复合外键列（G5）。

## 未验证：本机无 PG，DDL 未真实执行
- 执行环境无 PostgreSQL、沙箱内无法 pip install，因此**未跑过** alembic upgrade head。
  本文件只经过：① Python ast 语法解析；② server/tests/test_migration_structure.py
  的静态结构断言（表数/约束命名/部分索引/COMMENT 数）。
- 未验证项（转 R 系列风险，data-model.md §8.6）：
  * CHECK 表达式在 PG17 上的求值语义（三值逻辑、<> 与 NULL）；
  * jsonb_typeof / ~ '^[0-9a-f]{64}$' / '-Infinity'::float8 的实际可用性；
  * 7 条部分唯一索引的实际冲突行为；4 条新增索引的收益；
  * 迁移往返 upgrade head -> downgrade base -> upgrade head 幂等性；
  * pg_dump --schema-only 与本文件的 diff（scripts/schema_diff.py 尚未实现）。
- 上述任一项要在隔离空库（EDB 便携 PG17，端口 55432）跑一次才能消除。

Revision ID: 0001
Revises: None
Create Date: 2026-10-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# --------------------------------------------------------------------------- #
# 24 张表：严格按 schema.sql 的 CREATE TABLE 顺序（0 前向引用，56 个外键全部指向
# 更早的父表；唯一的自引用是 test_runs.parent_run_id -> test_runs）。
# --------------------------------------------------------------------------- #


def upgrade() -> None:
    """建 24 表 -> 19 条索引 -> 255 条注释。整体在 Alembic 的单个事务内执行。"""
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        "project_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("identity_issuer", sa.Text(), nullable=False),
        sa.Column("identity_subject", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("role IN ('owner','maintainer','runner','viewer')"), name="ck_project_members_role_allowed"),
        sa.UniqueConstraint("project_id", "identity_issuer", "identity_subject", name="uq_project_members_project_id_identity_issuer_identity_subject"),
    )

    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("identifier", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("platform IN ('android','ios','web')"), name="ck_applications_platform_allowed"),
        sa.UniqueConstraint("project_id", "id", name="uq_applications_project_id_id"),
        sa.UniqueConstraint("project_id", "id", "platform", name="uq_applications_project_id_id_platform"),
        sa.UniqueConstraint("project_id", "platform", "identifier", name="uq_applications_project_id_platform_identifier"),
    )

    op.create_table(
        "app_builds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("build_key", sa.Text(), nullable=False),
        sa.Column("source_commit", sa.Text()),
        sa.Column("storage_key", sa.Text()),
        sa.Column("sha256", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("sha256 ~ '^[0-9a-f]{64}$'"), name="ck_app_builds_sha256_hex64"),
        sa.UniqueConstraint("project_id", "id", name="uq_app_builds_project_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "id", name="uq_app_builds_project_id_application_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "build_key", name="uq_app_builds_project_id_application_id_build_key"),
        sa.ForeignKeyConstraint(["project_id", "application_id"], ["applications.project_id", "applications.id"], name="fk_app_builds_project_id_application_id_applications"),
        sa.CheckConstraint(sa.text("jsonb_typeof(metadata) = 'object'"), name="ck_app_builds_metadata_object"),
    )

    op.create_table(
        "environments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("secret_ref", sa.Text()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint("project_id", "id", name="uq_environments_project_id_id"),
        sa.UniqueConstraint("project_id", "name", name="uq_environments_project_id_name"),
        sa.CheckConstraint(sa.text("jsonb_typeof(config) = 'object'"), name="ck_environments_config_object"),
    )

    op.create_table(
        "execution_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("agent_version", sa.Text(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("status IN ('online','offline','draining')"), name="ck_execution_nodes_status_allowed"),
        sa.UniqueConstraint("project_id", "id", name="uq_execution_nodes_project_id_id"),
        sa.UniqueConstraint("project_id", "name", name="uq_execution_nodes_project_id_name"),
        sa.CheckConstraint(sa.text("jsonb_typeof(capabilities) = 'object'"), name="ck_execution_nodes_capabilities_object"),
    )

    op.create_table(
        "resource_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("platform IN ('android','ios','web')"), name="ck_resource_profiles_platform_allowed"),
        sa.CheckConstraint(sa.text("fingerprint ~ '^[0-9a-f]{64}$'"), name="ck_resource_profiles_fingerprint_hex64"),
        sa.UniqueConstraint("project_id", "id", name="uq_resource_profiles_project_id_id"),
        sa.UniqueConstraint("project_id", "id", "platform", name="uq_resource_profiles_project_id_id_platform"),
        sa.UniqueConstraint("project_id", "platform", "fingerprint", name="uq_resource_profiles_project_id_platform_fingerprint"),
        sa.CheckConstraint(sa.text("jsonb_typeof(spec) = 'object'"), name="ck_resource_profiles_spec_object"),
    )

    op.create_table(
        "execution_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("resource_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("fence_counter", sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("platform IN ('android','ios','web')"), name="ck_execution_resources_platform_allowed"),
        sa.CheckConstraint(sa.text("kind IN ('device','simulator','browser_slot')"), name="ck_execution_resources_kind_allowed"),
        sa.CheckConstraint(sa.text("status IN ('ready','offline','unauthorized','draining')"), name="ck_execution_resources_status_allowed"),
        sa.CheckConstraint(sa.text("fence_counter >= 0"), name="ck_execution_resources_fence_counter_non_negative"),
        sa.UniqueConstraint("project_id", "id", name="uq_execution_resources_project_id_id"),
        sa.UniqueConstraint("project_id", "id", "platform", name="uq_execution_resources_project_id_id_platform"),
        sa.UniqueConstraint("project_id", "node_id", "resource_key", name="uq_execution_resources_project_id_node_id_resource_key"),
        sa.ForeignKeyConstraint(["project_id", "node_id"], ["execution_nodes.project_id", "execution_nodes.id"], name="fk_execution_resources_project_id_node_id_execution_nodes"),
        sa.ForeignKeyConstraint(["project_id", "profile_id", "platform"], ["resource_profiles.project_id", "resource_profiles.id", "resource_profiles.platform"], name="fk_execution_resources_project_id_profile_id_platform_2498e5db"),
        sa.CheckConstraint(sa.text("(platform = 'web' AND kind = 'browser_slot') OR (platform <> 'web' AND kind IN ('device','simulator'))"), name="ck_execution_resources_platform_kind_pair"),
    )

    op.create_table(
        "test_suites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("test_type", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("test_type IN ('ui','performance','joint')"), name="ck_test_suites_test_type_allowed"),
        sa.UniqueConstraint("project_id", "id", name="uq_test_suites_project_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "id", name="uq_test_suites_project_id_application_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "name", name="uq_test_suites_project_id_application_id_name"),
        sa.ForeignKeyConstraint(["project_id", "application_id"], ["applications.project_id", "applications.id"], name="fk_test_suites_project_id_application_id_applications"),
    )

    op.create_table(
        "suite_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("source_commit", sa.Text(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("version > 0"), name="ck_suite_versions_version_positive"),
        sa.UniqueConstraint("project_id", "id", name="uq_suite_versions_project_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "id", name="uq_suite_versions_project_id_application_id_id"),
        sa.UniqueConstraint("project_id", "suite_id", "version", name="uq_suite_versions_project_id_suite_id_version"),
        sa.ForeignKeyConstraint(["project_id", "application_id", "suite_id"], ["test_suites.project_id", "test_suites.application_id", "test_suites.id"], name="fk_suite_versions_project_id_application_id_suite_id_t_73de23ad"),
        sa.CheckConstraint(sa.text("jsonb_typeof(manifest) = 'object'"), name="ck_suite_versions_manifest_object"),
    )

    op.create_table(
        "test_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("lifecycle", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("lifecycle IN ('draft','ready','archived')"), name="ck_test_tasks_lifecycle_allowed"),
        sa.CheckConstraint(sa.text("lock_version > 0"), name="ck_test_tasks_lock_version_positive"),
        sa.UniqueConstraint("project_id", "id", name="uq_test_tasks_project_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "id", name="uq_test_tasks_project_id_application_id_id"),
        sa.ForeignKeyConstraint(["project_id", "application_id"], ["applications.project_id", "applications.id"], name="fk_test_tasks_project_id_application_id_applications"),
    )

    op.create_table(
        "task_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("build_id", postgresql.UUID(as_uuid=True)),
        sa.Column("suite_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("test_type", sa.Text(), nullable=False),
        sa.Column("readiness", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("revision > 0"), name="ck_task_revisions_revision_positive"),
        sa.CheckConstraint(sa.text("test_type IN ('ui','performance','joint')"), name="ck_task_revisions_test_type_allowed"),
        sa.CheckConstraint(sa.text("readiness IN ('draft','validated')"), name="ck_task_revisions_readiness_allowed"),
        sa.UniqueConstraint("project_id", "id", name="uq_task_revisions_project_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "id", name="uq_task_revisions_project_id_application_id_id"),
        sa.UniqueConstraint("project_id", "task_id", "revision", name="uq_task_revisions_project_id_task_id_revision"),
        sa.ForeignKeyConstraint(["project_id", "application_id", "task_id"], ["test_tasks.project_id", "test_tasks.application_id", "test_tasks.id"], name="fk_task_revisions_project_id_application_id_task_id_test_tasks"),
        sa.ForeignKeyConstraint(["project_id", "environment_id"], ["environments.project_id", "environments.id"], name="fk_task_revisions_project_id_environment_id_environments"),
        sa.ForeignKeyConstraint(["project_id", "application_id", "build_id"], ["app_builds.project_id", "app_builds.application_id", "app_builds.id"], name="fk_task_revisions_project_id_application_id_build_id_app_builds"),
        sa.ForeignKeyConstraint(["project_id", "application_id", "suite_version_id"], ["suite_versions.project_id", "suite_versions.application_id", "suite_versions.id"], name="fk_task_revisions_project_id_application_id_suite_vers_7280bd99"),
        sa.CheckConstraint(sa.text("jsonb_typeof(config) = 'object'"), name="ck_task_revisions_config_object"),
        sa.CheckConstraint(sa.text("readiness = 'draft' OR (build_id IS NOT NULL AND suite_version_id IS NOT NULL)"), name="ck_task_revisions_readiness_requires_build_and_suite"),
    )

    op.create_table(
        "test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("outcome", sa.Text()),
        sa.Column("reason_code", sa.Text()),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column("not_tested_reason", sa.Text()),
        sa.CheckConstraint(sa.text("platform IN ('android','ios','web')"), name="ck_test_runs_platform_allowed"),
        sa.CheckConstraint(sa.text("state IN ('queued','dispatching','running','finalizing','completed','errored','cancelled')"), name="ck_test_runs_state_allowed"),
        sa.CheckConstraint(sa.text("outcome IN ('passed','failed','not_tested')"), name="ck_test_runs_outcome_allowed"),
        sa.CheckConstraint(sa.text("lock_version > 0"), name="ck_test_runs_lock_version_positive"),
        sa.UniqueConstraint("project_id", "id", name="uq_test_runs_project_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "id", name="uq_test_runs_project_id_application_id_id"),
        sa.UniqueConstraint("project_id", "id", "resource_id", name="uq_test_runs_project_id_id_resource_id"),
        sa.UniqueConstraint("project_id", "request_key", name="uq_test_runs_project_id_request_key"),
        sa.ForeignKeyConstraint(["project_id", "application_id", "platform"], ["applications.project_id", "applications.id", "applications.platform"], name="fk_test_runs_project_id_application_id_platform_applications"),
        sa.ForeignKeyConstraint(["project_id", "application_id", "revision_id"], ["task_revisions.project_id", "task_revisions.application_id", "task_revisions.id"], name="fk_test_runs_project_id_application_id_revision_id_tas_e43fae07"),
        sa.ForeignKeyConstraint(["project_id", "application_id", "parent_run_id"], ["test_runs.project_id", "test_runs.application_id", "test_runs.id"], name="fk_test_runs_project_id_application_id_parent_run_id_test_runs"),
        sa.ForeignKeyConstraint(["project_id", "resource_id", "platform"], ["execution_resources.project_id", "execution_resources.id", "execution_resources.platform"], name="fk_test_runs_project_id_resource_id_platform_execution_be04ac1d"),
        sa.ForeignKeyConstraint(["project_id", "profile_id", "platform"], ["resource_profiles.project_id", "resource_profiles.id", "resource_profiles.platform"], name="fk_test_runs_project_id_profile_id_platform_resource_profiles"),
        sa.CheckConstraint(sa.text("jsonb_typeof(config_snapshot) = 'object'"), name="ck_test_runs_config_snapshot_object"),
        sa.CheckConstraint(sa.text("(state = 'completed' AND outcome IS NOT NULL) OR (state <> 'completed' AND outcome IS NULL)"), name="ck_test_runs_state_outcome_pair"),
        sa.CheckConstraint(sa.text("(state IN ('completed','errored','cancelled')) = (ended_at IS NOT NULL)"), name="ck_test_runs_state_terminal_needs_ended_at"),
        sa.CheckConstraint(sa.text("state NOT IN ('running','finalizing','completed') OR (resource_id IS NOT NULL AND started_at IS NOT NULL)"), name="ck_test_runs_state_executing_needs_resource"),
        sa.CheckConstraint(sa.text("(resource_id IS NULL) = (profile_id IS NULL)"), name="ck_test_runs_resource_id_profile_pair"),
        sa.CheckConstraint(sa.text("ended_at IS NULL OR ended_at >= created_at"), name="ck_test_runs_ended_at_not_before_created"),
        sa.CheckConstraint(sa.text("started_at IS NULL OR started_at >= created_at"), name="ck_test_runs_started_at_not_before_created"),
        sa.CheckConstraint(sa.text("ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at"), name="ck_test_runs_ended_at_not_before_started"),
        sa.CheckConstraint(sa.text("outcome <> 'not_tested' OR not_tested_reason IS NOT NULL"), name="ck_test_runs_not_tested_reason_required"),
    )

    op.create_table(
        "debug_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_ref", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("state IN ('opening','active','closing','closed','lost')"), name="ck_debug_sessions_state_allowed"),
        sa.UniqueConstraint("project_id", "id", name="uq_debug_sessions_project_id_id"),
        sa.UniqueConstraint("project_id", "id", "resource_id", name="uq_debug_sessions_project_id_id_resource_id"),
        sa.ForeignKeyConstraint(["project_id", "resource_id"], ["execution_resources.project_id", "execution_resources.id"], name="fk_debug_sessions_project_id_resource_id_execution_resources"),
        sa.CheckConstraint(sa.text("expires_at > created_at"), name="ck_debug_sessions_expires_at_after_created"),
        sa.CheckConstraint(sa.text("(state IN ('closed','lost')) = (closed_at IS NOT NULL)"), name="ck_debug_sessions_state_closed_pair"),
        sa.CheckConstraint(sa.text("closed_at IS NULL OR closed_at >= created_at"), name="ck_debug_sessions_closed_at_not_before_created"),
    )

    op.create_table(
        "resource_leases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("debug_session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("holder_id", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("release_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("fencing_token > 0"), name="ck_resource_leases_fencing_token_positive"),
        sa.UniqueConstraint("project_id", "id", name="uq_resource_leases_project_id_id"),
        sa.UniqueConstraint("project_id", "resource_id", "fencing_token", name="uq_resource_leases_project_id_resource_id_fencing_token"),
        sa.ForeignKeyConstraint(["project_id", "run_id", "resource_id"], ["test_runs.project_id", "test_runs.id", "test_runs.resource_id"], name="fk_resource_leases_project_id_run_id_resource_id_test_runs"),
        sa.CheckConstraint(sa.text("expires_at > created_at"), name="ck_resource_leases_expires_at_after_created"),
        sa.CheckConstraint(sa.text("released_at IS NULL OR released_at >= created_at"), name="ck_resource_leases_released_at_not_before_created"),
        sa.ForeignKeyConstraint(["project_id", "debug_session_id", "resource_id"], ["debug_sessions.project_id", "debug_sessions.id", "debug_sessions.resource_id"], name="fk_resource_leases_project_id_debug_session_id_resourc_3b7f9216"),
        sa.CheckConstraint(sa.text("(run_id IS NOT NULL) <> (debug_session_id IS NOT NULL)"), name="ck_resource_leases_run_id_xor_debug_session"),
    )

    op.create_table(
        "run_components",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("adapter_key", sa.Text(), nullable=False),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column("external_run_id", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text()),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column("reason_code", sa.Text()),
        sa.CheckConstraint(sa.text("kind IN ('ui','performance')"), name="ck_run_components_kind_allowed"),
        sa.CheckConstraint(sa.text("state IN ('pending','running','completed','errored','cancelled')"), name="ck_run_components_state_allowed"),
        sa.CheckConstraint(sa.text("outcome IN ('passed','failed','not_tested')"), name="ck_run_components_outcome_allowed"),
        sa.UniqueConstraint("project_id", "id", name="uq_run_components_project_id_id"),
        sa.UniqueConstraint("project_id", "run_id", "id", name="uq_run_components_project_id_run_id_id"),
        sa.UniqueConstraint("project_id", "run_id", "kind", name="uq_run_components_project_id_run_id_kind"),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["test_runs.project_id", "test_runs.id"], name="fk_run_components_project_id_run_id_test_runs"),
        sa.CheckConstraint(sa.text("jsonb_typeof(summary) = 'object'"), name="ck_run_components_summary_object"),
        sa.CheckConstraint(sa.text("(state = 'completed' AND outcome IS NOT NULL) OR (state <> 'completed' AND outcome IS NULL)"), name="ck_run_components_state_outcome_pair"),
        sa.CheckConstraint(sa.text("outcome <> 'not_tested' OR reason_code IS NOT NULL"), name="ck_run_components_reason_code_required"),
    )

    op.create_table(
        "case_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_key", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("error_summary", sa.Text()),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("attempt > 0"), name="ck_case_results_attempt_positive"),
        sa.CheckConstraint(sa.text("outcome IN ('passed','failed','skipped','errored')"), name="ck_case_results_outcome_allowed"),
        sa.CheckConstraint(sa.text("duration_ms >= 0"), name="ck_case_results_duration_ms_non_negative"),
        sa.UniqueConstraint("project_id", "id", name="uq_case_results_project_id_id"),
        sa.UniqueConstraint("project_id", "component_id", "case_key", "attempt", name="uq_case_results_project_id_component_id_case_key_attempt"),
        sa.ForeignKeyConstraint(["project_id", "component_id"], ["run_components.project_id", "run_components.id"], name="fk_case_results_project_id_component_id_run_components"),
        sa.CheckConstraint(sa.text("jsonb_typeof(steps) = 'array'"), name="ck_case_results_steps_array"),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True)),
        sa.Column("logical_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text()),
        sa.Column("availability", sa.Text(), nullable=False, server_default=sa.text("'available'")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("kind IN ('screenshot','ui_tree','video','log','trace','metric_series','report_json','report_html','other')"), name="ck_artifacts_kind_allowed"),
        sa.CheckConstraint(sa.text("byte_size >= 0"), name="ck_artifacts_byte_size_non_negative"),
        sa.CheckConstraint(sa.text("sha256 ~ '^[0-9a-f]{64}$'"), name="ck_artifacts_sha256_hex64"),
        sa.CheckConstraint(sa.text("availability IN ('available','missing','expired')"), name="ck_artifacts_availability_allowed"),
        sa.UniqueConstraint("project_id", "id", name="uq_artifacts_project_id_id"),
        sa.UniqueConstraint("project_id", "run_id", "logical_key", name="uq_artifacts_project_id_run_id_logical_key"),
        sa.UniqueConstraint("project_id", "storage_key", name="uq_artifacts_project_id_storage_key"),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["test_runs.project_id", "test_runs.id"], name="fk_artifacts_project_id_run_id_test_runs"),
        sa.ForeignKeyConstraint(["project_id", "run_id", "component_id"], ["run_components.project_id", "run_components.run_id", "run_components.id"], name="fk_artifacts_project_id_run_id_component_id_run_components"),
    )

    op.create_table(
        "metric_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("metric_version", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("window_key", sa.Text(), nullable=False),
        sa.Column("statistic", sa.Text(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(precision=53)),
        sa.Column("missing_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column("missing_reason_text", sa.Text()),
        sa.CheckConstraint(sa.text("statistic IN ('median','p95','mean','min','max')"), name="ck_metric_summaries_statistic_allowed"),
        sa.CheckConstraint(sa.text("sample_count >= 0"), name="ck_metric_summaries_sample_count_non_negative"),
        sa.UniqueConstraint("project_id", "id", name="uq_metric_summaries_project_id_id"),
        sa.UniqueConstraint("project_id", "component_id", "metric_key", "metric_version", "scope", "window_key", "statistic", name="uq_metric_summaries_project_id_component_id_metric_key_44fb8051"),
        sa.ForeignKeyConstraint(["project_id", "component_id"], ["run_components.project_id", "run_components.id"], name="fk_metric_summaries_project_id_component_id_run_components"),
        sa.CheckConstraint(sa.text("(value IS NULL AND missing_reason IS NOT NULL) OR (value IS NOT NULL AND missing_reason IS NULL)"), name="ck_metric_summaries_value_missing_reason_pair"),
        sa.CheckConstraint(sa.text("value IS NULL OR (sample_count > 0 AND value > '-Infinity'::float8 AND value < 'Infinity'::float8)"), name="ck_metric_summaries_value_finite"),
    )

    op.create_table(
        "baselines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metrics_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("version > 0"), name="ck_baselines_version_positive"),
        sa.UniqueConstraint("project_id", "id", name="uq_baselines_project_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "name", "version", name="uq_baselines_project_id_application_id_name_version"),
        sa.ForeignKeyConstraint(["project_id", "application_id"], ["applications.project_id", "applications.id"], name="fk_baselines_project_id_application_id_applications"),
        sa.ForeignKeyConstraint(["project_id", "environment_id"], ["environments.project_id", "environments.id"], name="fk_baselines_project_id_environment_id_environments"),
        sa.ForeignKeyConstraint(["project_id", "application_id", "suite_version_id"], ["suite_versions.project_id", "suite_versions.application_id", "suite_versions.id"], name="fk_baselines_project_id_application_id_suite_version_i_bf7806e1"),
        sa.ForeignKeyConstraint(["project_id", "profile_id"], ["resource_profiles.project_id", "resource_profiles.id"], name="fk_baselines_project_id_profile_id_resource_profiles"),
        sa.ForeignKeyConstraint(["project_id", "source_component_id"], ["run_components.project_id", "run_components.id"], name="fk_baselines_project_id_source_component_id_run_components"),
        sa.CheckConstraint(sa.text("jsonb_typeof(metrics_snapshot) = 'object'"), name="ck_baselines_metrics_snapshot_object"),
    )

    op.create_table(
        "gate_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("version > 0"), name="ck_gate_policies_version_positive"),
        sa.UniqueConstraint("project_id", "id", name="uq_gate_policies_project_id_id"),
        sa.UniqueConstraint("project_id", "application_id", "name", "version", name="uq_gate_policies_project_id_application_id_name_version"),
        sa.ForeignKeyConstraint(["project_id", "application_id"], ["applications.project_id", "applications.id"], name="fk_gate_policies_project_id_application_id_applications"),
        sa.CheckConstraint(sa.text("jsonb_typeof(rules) = 'object'"), name="ck_gate_policies_rules_object"),
    )

    op.create_table(
        "gate_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("baseline_id", postgresql.UUID(as_uuid=True)),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text()),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("mode IN ('original','reanalysis')"), name="ck_gate_evaluations_mode_allowed"),
        sa.CheckConstraint(sa.text("verdict IN ('passed','failed','not_tested')"), name="ck_gate_evaluations_verdict_allowed"),
        sa.UniqueConstraint("project_id", "id", name="uq_gate_evaluations_project_id_id"),
        sa.UniqueConstraint("project_id", "request_key", name="uq_gate_evaluations_project_id_request_key"),
        sa.ForeignKeyConstraint(["project_id", "component_id"], ["run_components.project_id", "run_components.id"], name="fk_gate_evaluations_project_id_component_id_run_components"),
        sa.ForeignKeyConstraint(["project_id", "policy_id"], ["gate_policies.project_id", "gate_policies.id"], name="fk_gate_evaluations_project_id_policy_id_gate_policies"),
        sa.ForeignKeyConstraint(["project_id", "baseline_id"], ["baselines.project_id", "baselines.id"], name="fk_gate_evaluations_project_id_baseline_id_baselines"),
        sa.CheckConstraint(sa.text("jsonb_typeof(checks) = 'array'"), name="ck_gate_evaluations_checks_array"),
        sa.CheckConstraint(sa.text("verdict <> 'not_tested' OR reason_code IS NOT NULL"), name="ck_gate_evaluations_verdict_not_tested_reason"),
    )

    op.create_table(
        "run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint(sa.text("sequence > 0"), name="ck_run_events_sequence_positive"),
        sa.UniqueConstraint("project_id", "id", name="uq_run_events_project_id_id"),
        sa.UniqueConstraint("project_id", "run_id", "sequence", name="uq_run_events_project_id_run_id_sequence"),
        sa.UniqueConstraint("project_id", "run_id", "source_key", "source_event_id", name="uq_run_events_project_id_run_id_source_key_source_event_id"),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["test_runs.project_id", "test_runs.id"], name="fk_run_events_project_id_run_id_test_runs"),
        sa.CheckConstraint(sa.text("jsonb_typeof(payload) = 'object'"), name="ck_run_events_payload_object"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_ref", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint("project_id", "id", name="uq_audit_events_project_id_id"),
        sa.CheckConstraint(sa.text("jsonb_typeof(changes) = 'object'"), name="ck_audit_events_changes_object"),
    )

    # ----------------------------------------------------------------- #
    # 索引：schema.sql L714-728 共 15 条，其中 7 条为部分索引
    # ----------------------------------------------------------------- #
    op.execute(
        "CREATE INDEX runs_queue ON test_runs (created_at, id) WHERE state = 'queued'",
    )


    op.create_index(
        "runs_project_recent",
        "test_runs",
        [
            "project_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )

    op.create_index(
        "runs_app_recent",
        "test_runs",
        [
            "project_id",
            "application_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )

    op.create_index(
        "runs_platform_recent",
        "test_runs",
        [
            "project_id",
            "platform",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )

    op.create_index(
        "runs_revision",
        "test_runs",
        [
            "project_id",
            "revision_id",
        ],
    )

    op.create_index(
        "runs_resource",
        "test_runs",
        [
            "project_id",
            "resource_id",
        ],
    )

    op.create_index(
        "resources_ready",
        "execution_resources",
        [
            "project_id",
            "platform",
            "status",
        ],
    )

    op.execute(
        "CREATE UNIQUE INDEX leases_one_live_resource ON resource_leases (project_id, resource_id) WHERE released_at IS NULL",
    )


    op.execute(
        "CREATE UNIQUE INDEX leases_one_live_run ON resource_leases (project_id, run_id) WHERE released_at IS NULL",
    )


    op.execute(
        "CREATE INDEX leases_expiry ON resource_leases (expires_at) WHERE released_at IS NULL",
    )


    op.execute(
        "CREATE UNIQUE INDEX gate_one_original ON gate_evaluations (project_id, component_id) WHERE mode = 'original'",
    )


    op.create_index(
        "evaluations_component",
        "gate_evaluations",
        [
            "project_id",
            "component_id",
            sa.text("created_at DESC"),
        ],
    )

    op.create_index(
        "audits_project_time",
        "audit_events",
        [
            "project_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )

    op.execute(
        "CREATE INDEX artifacts_expiry ON artifacts (expires_at) WHERE availability = 'available'",
    )


    op.execute(
        "CREATE UNIQUE INDEX leases_one_live_debug ON resource_leases (project_id, debug_session_id) WHERE released_at IS NULL",
    )


    # ----------------------------------------------------------------- #
    # 优先索引（data-model.md §8.3 G1/G2/G3/G5）
    # ----------------------------------------------------------------- #
    op.execute(
        "CREATE INDEX ix_debug_sessions_resource_state ON debug_sessions (project_id, resource_id) WHERE state IN ('opening','active','closing')",
    )


    op.create_index(
        "ix_metric_summaries_metric_key",
        "metric_summaries",
        [
            "project_id",
            "metric_key",
            "metric_version",
            "scope",
            "window_key",
        ],
    )

    op.execute(
        "CREATE INDEX ix_test_runs_parent_run ON test_runs (project_id, parent_run_id) WHERE parent_run_id IS NOT NULL",
    )


    op.create_index(
        "ix_task_revisions_task",
        "task_revisions",
        [
            "project_id",
            "task_id",
        ],
    )

    # ----------------------------------------------------------------- #
    # COMMENT：24 表 + 231 列 = 255 条，原文逐字来自 schema.sql
    # ----------------------------------------------------------------- #
    op.execute("COMMENT ON TABLE projects IS '产品级隔离单元，Android、iOS、Web 应用归属于同一项目。'")
    op.execute("COMMENT ON COLUMN projects.id IS '项目 UUID'")
    op.execute("COMMENT ON COLUMN projects.code IS '稳定项目代号'")
    op.execute("COMMENT ON COLUMN projects.name IS '展示名称'")
    op.execute("COMMENT ON COLUMN projects.archived_at IS '归档时间，保留历史引用'")
    op.execute("COMMENT ON COLUMN projects.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE project_members IS '复用身份提供方，以项目角色授权，不在业务库保存登录口令。 角色必须由后端检查；project_id 外键不等于行级访问控制。'")
    op.execute("COMMENT ON COLUMN project_members.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN project_members.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN project_members.identity_issuer IS '身份提供方标识'")
    op.execute("COMMENT ON COLUMN project_members.identity_subject IS '提供方内稳定用户 ID'")
    op.execute("COMMENT ON COLUMN project_members.role IS '项目角色'")
    op.execute("COMMENT ON COLUMN project_members.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE applications IS '目标端属于应用，不为每种端复制一套任务和报告表。'")
    op.execute("COMMENT ON COLUMN applications.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN applications.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN applications.platform IS '目标端，新增端通过迁移扩展'")
    op.execute("COMMENT ON COLUMN applications.name IS '应用名称'")
    op.execute("COMMENT ON COLUMN applications.identifier IS '包名、Bundle ID 或站点逻辑标识'")
    op.execute("COMMENT ON COLUMN applications.archived_at IS '归档时间'")
    op.execute("COMMENT ON COLUMN applications.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE app_builds IS '固定待测构建；移动包与 Web 部署均采用同一版本记录。'")
    op.execute("COMMENT ON COLUMN app_builds.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN app_builds.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN app_builds.application_id IS '所属应用'")
    op.execute("COMMENT ON COLUMN app_builds.version IS '业务版本'")
    op.execute("COMMENT ON COLUMN app_builds.build_key IS 'CI 构建号或部署版本，不使用可变 latest'")
    op.execute("COMMENT ON COLUMN app_builds.source_commit IS '来源提交号'")
    op.execute("COMMENT ON COLUMN app_builds.storage_key IS '包文件存储键；Web 部署可为空'")
    op.execute("COMMENT ON COLUMN app_builds.sha256 IS '包校验摘要'")
    op.execute("COMMENT ON COLUMN app_builds.metadata IS '包属性或部署元数据'")
    op.execute("COMMENT ON COLUMN app_builds.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE environments IS '保存各环境的非敏感配置，实际站点地址可随环境区分。'")
    op.execute("COMMENT ON COLUMN environments.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN environments.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN environments.name IS 'staging、qa 等环境名'")
    op.execute("COMMENT ON COLUMN environments.config IS '地址映射、变量及 schemaVersion；禁止明文凭据'")
    op.execute("COMMENT ON COLUMN environments.secret_ref IS '密钥管理系统引用，不能是密钥值'")
    op.execute("COMMENT ON COLUMN environments.archived_at IS '归档时间'")
    op.execute("COMMENT ON COLUMN environments.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE execution_nodes IS '宿主 Agent 与可用适配器，初期按项目独占。 宿主凭据不入 capabilities；首期不设计跨项目共享节点池。'")
    op.execute("COMMENT ON COLUMN execution_nodes.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN execution_nodes.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN execution_nodes.name IS '节点名称'")
    op.execute("COMMENT ON COLUMN execution_nodes.agent_version IS 'Agent 版本'")
    op.execute("COMMENT ON COLUMN execution_nodes.capabilities IS '已注册适配器及其版本'")
    op.execute("COMMENT ON COLUMN execution_nodes.status IS '节点状态'")
    op.execute("COMMENT ON COLUMN execution_nodes.heartbeat_at IS '最近心跳时间'")
    op.execute("COMMENT ON COLUMN execution_nodes.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE resource_profiles IS '不可变的可比性档案：系统、设备或浏览器、采集器、分辨率、指标版本。 档案内容变化新增记录，不覆盖旧记录；性能比较还须校验应用、场景和指标口径。'")
    op.execute("COMMENT ON COLUMN resource_profiles.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN resource_profiles.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN resource_profiles.platform IS '目标端'")
    op.execute("COMMENT ON COLUMN resource_profiles.name IS '档案展示名'")
    op.execute("COMMENT ON COLUMN resource_profiles.fingerprint IS '规范化档案的 SHA-256'")
    op.execute("COMMENT ON COLUMN resource_profiles.spec IS '结构化档案及 schemaVersion'")
    op.execute("COMMENT ON COLUMN resource_profiles.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE execution_resources IS '真机、模拟器或浏览器槽位。每个实例只承载一个活动运行。 Web 并发通过多个独立槽位表示；资源重新建档须在无活动租约时处理。'")
    op.execute("COMMENT ON COLUMN execution_resources.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN execution_resources.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN execution_resources.node_id IS '执行节点'")
    op.execute("COMMENT ON COLUMN execution_resources.profile_id IS '当前不可变档案'")
    op.execute("COMMENT ON COLUMN execution_resources.platform IS '目标端'")
    op.execute("COMMENT ON COLUMN execution_resources.resource_key IS '宿主内设备标识或浏览器槽位'")
    op.execute("COMMENT ON COLUMN execution_resources.kind IS '资源类型'")
    op.execute("COMMENT ON COLUMN execution_resources.status IS '连接状态；占用从租约推导'")
    op.execute("COMMENT ON COLUMN execution_resources.fence_counter IS '每次分配递增的隔离令牌'")
    op.execute("COMMENT ON COLUMN execution_resources.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE test_suites IS '登记代码维护的 UI 用例或性能场景，不把脚本正文塞进数据库。'")
    op.execute("COMMENT ON COLUMN test_suites.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN test_suites.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN test_suites.application_id IS '所属应用'")
    op.execute("COMMENT ON COLUMN test_suites.name IS '套件或场景名'")
    op.execute("COMMENT ON COLUMN test_suites.test_type IS '测试类型；joint 为编排'")
    op.execute("COMMENT ON COLUMN test_suites.archived_at IS '归档时间'")
    op.execute("COMMENT ON COLUMN test_suites.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE suite_versions IS '固定仓库、提交及选择器，旧运行可追溯到当时的用例。'")
    op.execute("COMMENT ON COLUMN suite_versions.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN suite_versions.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN suite_versions.application_id IS '应用关联约束'")
    op.execute("COMMENT ON COLUMN suite_versions.suite_id IS '逻辑套件'")
    op.execute("COMMENT ON COLUMN suite_versions.version IS '套件修订序号'")
    op.execute("COMMENT ON COLUMN suite_versions.source_ref IS '不含凭据的仓库或受控用例来源'")
    op.execute("COMMENT ON COLUMN suite_versions.source_commit IS '固定提交标识'")
    op.execute("COMMENT ON COLUMN suite_versions.manifest IS '用例 key、入口、场景及 schemaVersion'")
    op.execute("COMMENT ON COLUMN suite_versions.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE test_tasks IS '用户可编辑的逻辑任务；不存通过或失败结果。 Web/iOS 未接入时只能是 draft；计划能力不能用设备数据冒充已就绪。'")
    op.execute("COMMENT ON COLUMN test_tasks.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN test_tasks.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN test_tasks.application_id IS '所属应用'")
    op.execute("COMMENT ON COLUMN test_tasks.name IS '任务名'")
    op.execute("COMMENT ON COLUMN test_tasks.lifecycle IS '配置生命周期，非执行状态'")
    op.execute("COMMENT ON COLUMN test_tasks.lock_version IS '乐观锁版本'")
    op.execute("COMMENT ON COLUMN test_tasks.created_by IS '身份主体或服务账号引用'")
    op.execute("COMMENT ON COLUMN test_tasks.updated_at IS '服务端更新时显式赋值'")
    op.execute("COMMENT ON COLUMN test_tasks.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE task_revisions IS '每次保存新增不可变修订；运行只引用已验证修订。 只有字段完整不代表可运行；适配器能力、套件类型及配置 schema 仍由提交事务验证。'")
    op.execute("COMMENT ON COLUMN task_revisions.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN task_revisions.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN task_revisions.application_id IS '应用关联约束'")
    op.execute("COMMENT ON COLUMN task_revisions.task_id IS '逻辑任务'")
    op.execute("COMMENT ON COLUMN task_revisions.revision IS '配置版本号'")
    op.execute("COMMENT ON COLUMN task_revisions.environment_id IS '环境'")
    op.execute("COMMENT ON COLUMN task_revisions.build_id IS '草稿可缺构建，提交前校验'")
    op.execute("COMMENT ON COLUMN task_revisions.suite_version_id IS '草稿可缺套件版本，提交前校验'")
    op.execute("COMMENT ON COLUMN task_revisions.test_type IS '类型快照'")
    op.execute("COMMENT ON COLUMN task_revisions.readiness IS '配置校验状态'")
    op.execute("COMMENT ON COLUMN task_revisions.config IS '脱敏配置、资源需求、适配器及 schemaVersion'")
    op.execute("COMMENT ON COLUMN task_revisions.created_by IS '保存者引用'")
    op.execute("COMMENT ON COLUMN task_revisions.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE test_runs IS '一次提交或重跑对应一行，保留执行状态、最终结论和当时配置。 终态只追加新运行或新试算，不改原始结论；这种不可变性及状态转换须由后端写入边界实现。'")
    op.execute("COMMENT ON COLUMN test_runs.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN test_runs.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN test_runs.application_id IS '目标应用'")
    op.execute("COMMENT ON COLUMN test_runs.platform IS '目标端查询维度'")
    op.execute("COMMENT ON COLUMN test_runs.revision_id IS '固定任务修订'")
    op.execute("COMMENT ON COLUMN test_runs.parent_run_id IS '重跑来源；同项目同应用'")
    op.execute("COMMENT ON COLUMN test_runs.request_key IS '项目内提交幂等键'")
    op.execute("COMMENT ON COLUMN test_runs.state IS '执行状态，与测试结论分离'")
    op.execute("COMMENT ON COLUMN test_runs.outcome IS '完成时的测试结论'")
    op.execute("COMMENT ON COLUMN test_runs.reason_code IS '未判定、取消或基础设施错误原因码'")
    op.execute("COMMENT ON COLUMN test_runs.resource_id IS '实际执行实例，排队时为空'")
    op.execute("COMMENT ON COLUMN test_runs.profile_id IS '实际使用的固定档案'")
    op.execute("COMMENT ON COLUMN test_runs.config_snapshot IS '固定配置、版本及脱敏环境快照'")
    op.execute("COMMENT ON COLUMN test_runs.lock_version IS '状态更新 CAS 版本'")
    op.execute("COMMENT ON COLUMN test_runs.started_at IS '实际开始时间'")
    op.execute("COMMENT ON COLUMN test_runs.ended_at IS '终态时间'")
    op.execute("COMMENT ON COLUMN test_runs.created_by IS '触发者引用'")
    op.execute("COMMENT ON COLUMN test_runs.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE debug_sessions IS '人工设备控制使用短期调试会话，与自动运行竞争同一资源租约。 只读预览不占独占租约；会发送输入、冻结采集等操作按宿主冲突规则受控。断线不能立即释放资源。'")
    op.execute("COMMENT ON COLUMN debug_sessions.id IS '调试会话 UUID'")
    op.execute("COMMENT ON COLUMN debug_sessions.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN debug_sessions.resource_id IS '调试实例'")
    op.execute("COMMENT ON COLUMN debug_sessions.actor_ref IS '操作人身份引用'")
    op.execute("COMMENT ON COLUMN debug_sessions.state IS '调试生命周期'")
    op.execute("COMMENT ON COLUMN debug_sessions.expires_at IS '会话过期时间'")
    op.execute("COMMENT ON COLUMN debug_sessions.closed_at IS '关闭或确认失联时间'")
    op.execute("COMMENT ON COLUMN debug_sessions.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE resource_leases IS '保留运行或调试的独占历史，用 fencing token 拒绝过期执行者。 部分唯一索引保证每实例、运行或调试会话最多一条未释放租约；超时回收仍需 Agent 隔离旧进程。'")
    op.execute("COMMENT ON COLUMN resource_leases.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN resource_leases.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN resource_leases.resource_id IS '被占用实例'")
    op.execute("COMMENT ON COLUMN resource_leases.run_id IS '自动运行归属，与调试会话二选一'")
    op.execute("COMMENT ON COLUMN resource_leases.debug_session_id IS '人工调试归属，与运行二选一'")
    op.execute("COMMENT ON COLUMN resource_leases.fencing_token IS '分配时递增并写入实例计数器'")
    op.execute("COMMENT ON COLUMN resource_leases.holder_id IS 'Agent 实例标识，不含凭据'")
    op.execute("COMMENT ON COLUMN resource_leases.expires_at IS '心跳到期时间'")
    op.execute("COMMENT ON COLUMN resource_leases.released_at IS '显式释放，过期不等于安全释放'")
    op.execute("COMMENT ON COLUMN resource_leases.release_reason IS '正常完成、取消确认、失联隔离等'")
    op.execute("COMMENT ON COLUMN resource_leases.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE run_components IS '一次运行下的 UI/性能子结果。联动共用运行和租约，分别保留结论。'")
    op.execute("COMMENT ON COLUMN run_components.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN run_components.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN run_components.run_id IS '平台运行'")
    op.execute("COMMENT ON COLUMN run_components.kind IS '子任务能力'")
    op.execute("COMMENT ON COLUMN run_components.adapter_key IS '适配器名'")
    op.execute("COMMENT ON COLUMN run_components.adapter_version IS '适配器版本'")
    op.execute("COMMENT ON COLUMN run_components.external_run_id IS '组件原始 runId'")
    op.execute("COMMENT ON COLUMN run_components.state IS '组件状态'")
    op.execute("COMMENT ON COLUMN run_components.outcome IS '测试结论'")
    op.execute("COMMENT ON COLUMN run_components.summary IS '计数、警告、完整性、原始 schemaVersion'")
    op.execute("COMMENT ON COLUMN run_components.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE case_results IS '每个用例的执行尝试独立保存，可区分用例重试与整次重跑。 后端只接受 UI 组件的用例记录，校验 case_key 属于固定 suite_version。'")
    op.execute("COMMENT ON COLUMN case_results.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN case_results.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN case_results.component_id IS 'UI 组件结果'")
    op.execute("COMMENT ON COLUMN case_results.case_key IS '套件版本中的稳定用例 key'")
    op.execute("COMMENT ON COLUMN case_results.attempt IS '同一次运行内用例尝试次数'")
    op.execute("COMMENT ON COLUMN case_results.outcome IS '用例结果'")
    op.execute("COMMENT ON COLUMN case_results.duration_ms IS '用例耗时'")
    op.execute("COMMENT ON COLUMN case_results.error_summary IS '脱敏错误摘要'")
    op.execute("COMMENT ON COLUMN case_results.steps IS '小体积步骤摘要；完整日志存证据文件'")
    op.execute("COMMENT ON COLUMN case_results.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE artifacts IS '保存文件元数据和私有存储键，截图、日志、录像、曲线均通过此表归档。 文件先写临时键并校验成功，再提交元数据；无法做到数据库与文件原子提交，需幂等补偿。'")
    op.execute("COMMENT ON COLUMN artifacts.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN artifacts.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN artifacts.run_id IS '运行归属'")
    op.execute("COMMENT ON COLUMN artifacts.component_id IS '可选子组件归属；总体报告为空'")
    op.execute("COMMENT ON COLUMN artifacts.logical_key IS '运行内唯一逻辑键，含用例或步骤路径'")
    op.execute("COMMENT ON COLUMN artifacts.kind IS '证据类型'")
    op.execute("COMMENT ON COLUMN artifacts.storage_key IS '受控文件或对象存储键，不存临时签名 URL'")
    op.execute("COMMENT ON COLUMN artifacts.mime_type IS '内容类型'")
    op.execute("COMMENT ON COLUMN artifacts.byte_size IS '文件字节数'")
    op.execute("COMMENT ON COLUMN artifacts.sha256 IS '完整性摘要'")
    op.execute("COMMENT ON COLUMN artifacts.schema_version IS '原始报告或曲线 schema'")
    op.execute("COMMENT ON COLUMN artifacts.availability IS '文件可用状态'")
    op.execute("COMMENT ON COLUMN artifacts.expires_at IS '保留策略到期时间'")
    op.execute("COMMENT ON COLUMN artifacts.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE metric_summaries IS '按指标、统计窗口和统计量保存查询所需的小体积摘要。 采样率、单位换算、窗口边界属于适配器契约；原始 series 单独归档，不逐点写业务库。'")
    op.execute("COMMENT ON COLUMN metric_summaries.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN metric_summaries.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN metric_summaries.component_id IS '性能组件'")
    op.execute("COMMENT ON COLUMN metric_summaries.metric_key IS '有命名空间的指标键，例如 android.memory.pss'")
    op.execute("COMMENT ON COLUMN metric_summaries.metric_version IS '指标口径版本'")
    op.execute("COMMENT ON COLUMN metric_summaries.unit IS '显式单位，例如 MiB、ms、percent'")
    op.execute("COMMENT ON COLUMN metric_summaries.scope IS 'app、device、page 等测量范围'")
    op.execute("COMMENT ON COLUMN metric_summaries.window_key IS '全程或步骤窗口'")
    op.execute("COMMENT ON COLUMN metric_summaries.statistic IS '统计量，现有 Android 判定使用 median'")
    op.execute("COMMENT ON COLUMN metric_summaries.sample_count IS '有效样本数'")
    op.execute("COMMENT ON COLUMN metric_summaries.value IS '缺失时为 NULL，不能补 0'")
    op.execute("COMMENT ON COLUMN metric_summaries.missing_reason IS '缺失原因'")
    op.execute("COMMENT ON COLUMN metric_summaries.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE baselines IS '不可变的对照版本；源运行和全部可比性信息一并保留。 来源组件的应用、场景、环境、profile 和完整性须由创建基线事务验证；不靠跨表 CHECK。'")
    op.execute("COMMENT ON COLUMN baselines.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN baselines.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN baselines.application_id IS '应用'")
    op.execute("COMMENT ON COLUMN baselines.environment_id IS '环境'")
    op.execute("COMMENT ON COLUMN baselines.suite_version_id IS '场景版本'")
    op.execute("COMMENT ON COLUMN baselines.profile_id IS '可比资源档案'")
    op.execute("COMMENT ON COLUMN baselines.source_component_id IS '来源性能组件'")
    op.execute("COMMENT ON COLUMN baselines.name IS '基线逻辑名'")
    op.execute("COMMENT ON COLUMN baselines.version IS '基线修订号'")
    op.execute("COMMENT ON COLUMN baselines.metrics_snapshot IS '指标口径、统计量、值及 schemaVersion'")
    op.execute("COMMENT ON COLUMN baselines.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE gate_policies IS '平台持有门槛，适配器负责正确的测量与统计。'")
    op.execute("COMMENT ON COLUMN gate_policies.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN gate_policies.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN gate_policies.application_id IS '规则适用应用'")
    op.execute("COMMENT ON COLUMN gate_policies.name IS '逻辑规则名'")
    op.execute("COMMENT ON COLUMN gate_policies.version IS '不可变规则版本'")
    op.execute("COMMENT ON COLUMN gate_policies.rules IS '带 schemaVersion 的指标、单位、窗口、比较符、阈值、warn/fail 和样本下限'")
    op.execute("COMMENT ON COLUMN gate_policies.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE gate_evaluations IS '原始判定与后续试算分开保存；改规则不会覆盖历史结论。 同项目外键不保证规则与基线适用当前应用；服务必须检查完整可比性。'")
    op.execute("COMMENT ON COLUMN gate_evaluations.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN gate_evaluations.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN gate_evaluations.component_id IS '性能组件'")
    op.execute("COMMENT ON COLUMN gate_evaluations.policy_id IS '固定规则版本'")
    op.execute("COMMENT ON COLUMN gate_evaluations.baseline_id IS '可为空，缺失时形成 not_tested 及原因'")
    op.execute("COMMENT ON COLUMN gate_evaluations.mode IS '原始判定或后续试算'")
    op.execute("COMMENT ON COLUMN gate_evaluations.request_key IS '判定请求幂等键'")
    op.execute("COMMENT ON COLUMN gate_evaluations.verdict IS '三态结论'")
    op.execute("COMMENT ON COLUMN gate_evaluations.reason_code IS '未判定原因码'")
    op.execute("COMMENT ON COLUMN gate_evaluations.checks IS '每项实际值、阈值、单位、样本数及结果'")
    op.execute("COMMENT ON COLUMN gate_evaluations.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE run_events IS '状态变化、步骤标记、接入事件按运行顺序追加，支持断线续看。'")
    op.execute("COMMENT ON COLUMN run_events.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN run_events.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN run_events.run_id IS '运行'")
    op.execute("COMMENT ON COLUMN run_events.sequence IS '服务端在运行锁内分配的顺序号'")
    op.execute("COMMENT ON COLUMN run_events.source_key IS '事件生产者'")
    op.execute("COMMENT ON COLUMN run_events.source_event_id IS '生产者侧幂等事件 ID'")
    op.execute("COMMENT ON COLUMN run_events.event_type IS '状态、步骤标记或警告类型'")
    op.execute("COMMENT ON COLUMN run_events.payload IS '小体积脱敏负载；完整日志走 artifacts'")
    op.execute("COMMENT ON COLUMN run_events.occurred_at IS '事件发生时间'")
    op.execute("COMMENT ON COLUMN run_events.created_at IS '创建时间，统一 UTC'")

    op.execute("COMMENT ON TABLE audit_events IS '记录谁修改配置、发起运行或调整规则，不承载完整业务数据。 只追加；审计主体与实体是否合法由授权后的业务事务写入。'")
    op.execute("COMMENT ON COLUMN audit_events.id IS '服务端生成 UUID'")
    op.execute("COMMENT ON COLUMN audit_events.project_id IS '项目归属'")
    op.execute("COMMENT ON COLUMN audit_events.actor_ref IS '稳定用户或服务账号引用'")
    op.execute("COMMENT ON COLUMN audit_events.action IS '业务动作'")
    op.execute("COMMENT ON COLUMN audit_events.entity_type IS '目标实体类型'")
    op.execute("COMMENT ON COLUMN audit_events.entity_id IS '目标 ID，历史追溯引用而非跨表通用外键'")
    op.execute("COMMENT ON COLUMN audit_events.request_id IS '请求关联标识'")
    op.execute("COMMENT ON COLUMN audit_events.changes IS '脱敏差异摘要，禁止存凭据'")
    op.execute("COMMENT ON COLUMN audit_events.created_at IS '创建时间，统一 UTC'")


def downgrade() -> None:
    """逆序删除 24 张表：索引随所属表一起 DROP，无需单独 drop_index。"""
    op.drop_table("audit_events")
    op.drop_table("run_events")
    op.drop_table("gate_evaluations")
    op.drop_table("gate_policies")
    op.drop_table("baselines")
    op.drop_table("metric_summaries")
    op.drop_table("artifacts")
    op.drop_table("case_results")
    op.drop_table("run_components")
    op.drop_table("resource_leases")
    op.drop_table("debug_sessions")
    op.drop_table("test_runs")
    op.drop_table("task_revisions")
    op.drop_table("test_tasks")
    op.drop_table("suite_versions")
    op.drop_table("test_suites")
    op.drop_table("execution_resources")
    op.drop_table("resource_profiles")
    op.drop_table("execution_nodes")
    op.drop_table("environments")
    op.drop_table("app_builds")
    op.drop_table("applications")
    op.drop_table("project_members")
    op.drop_table("projects")
