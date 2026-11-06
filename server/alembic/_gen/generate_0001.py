"""从 docs/platform-prototype/schema.sql 生成 server/alembic/versions/0001_initial.py。

一次性工序工具（不是运行时依赖）：把评审稿 DDL 逐字搬成 Alembic 迁移，并叠加
P1-A 要求的 4 个阻塞项修正与 3 处平台新增列。生成后迁移文件是唯一真源
（docs/plan/data-model.md §8.1 P0-4），本脚本仅保留以便复核与再生成。

用法: python server/alembic/_gen/generate_0001.py
前置: python server/alembic/_gen/parse_schema.py（产出 parsed.json）
输出: server/alembic/versions/0001_initial.py
"""

from __future__ import annotations

import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = json.loads((HERE / "parsed.json").read_text(encoding="utf-8"))

TABLES = DATA["tables"]
TCOM = DATA["table_comments"]
CCOM = DATA["column_comments"]
INDEXES = DATA["indexes"]
OUT = ROOT / "server" / "alembic" / "versions" / "0001_initial.py"

# ---------------------------------------------------------------- 命名映射表
# 列级 CHECK：约束名 = ck_<table>_<col>_<slug>
CHECK_SLUG = {
    ("project_members", "role"): "allowed",
    ("applications", "platform"): "allowed",
    ("execution_nodes", "status"): "allowed",
    ("resource_profiles", "platform"): "allowed",
    ("execution_resources", "platform"): "allowed",
    ("execution_resources", "kind"): "allowed",
    ("execution_resources", "status"): "allowed",
    ("test_suites", "test_type"): "allowed",
    ("suite_versions", "version"): "positive",
    ("test_tasks", "lifecycle"): "allowed",
    ("test_tasks", "lock_version"): "positive",
    ("task_revisions", "revision"): "positive",
    ("task_revisions", "test_type"): "allowed",
    ("task_revisions", "readiness"): "allowed",
    ("test_runs", "platform"): "allowed",
    ("test_runs", "state"): "allowed",
    ("test_runs", "outcome"): "allowed",
    ("test_runs", "lock_version"): "positive",
    ("debug_sessions", "state"): "allowed",
    ("resource_leases", "fencing_token"): "positive",
    ("run_components", "kind"): "allowed",
    ("run_components", "state"): "allowed",
    ("run_components", "outcome"): "allowed",
    ("case_results", "attempt"): "positive",
    ("case_results", "outcome"): "allowed",
    ("case_results", "duration_ms"): "non_negative",
    ("artifacts", "kind"): "allowed",
    ("artifacts", "byte_size"): "non_negative",
    ("artifacts", "availability"): "allowed",
    ("metric_summaries", "statistic"): "allowed",
    ("metric_summaries", "sample_count"): "non_negative",
    ("baselines", "version"): "positive",
    ("gate_policies", "version"): "positive",
    ("gate_evaluations", "mode"): "allowed",
    ("gate_evaluations", "verdict"): "allowed",
    ("run_events", "sequence"): "positive",
    # 正则摘要列
    ("app_builds", "sha256"): "hex64",
    ("resource_profiles", "fingerprint"): "hex64",
    ("artifacts", "sha256"): "hex64",
    # 平台新增列
    ("execution_resources", "fence_counter"): "non_negative",
}

# 表级 CHECK：约束名 = ck_<table>_<查列>_<查语义>
TABLE_CHECK_SLUG = {
    ("app_builds", 0): ("metadata", "object"),
    ("environments", 0): ("config", "object"),
    ("execution_nodes", 0): ("capabilities", "object"),
    ("resource_profiles", 0): ("spec", "object"),
    ("execution_resources", 0): ("platform_kind", "pair"),
    ("suite_versions", 0): ("manifest", "object"),
    ("task_revisions", 0): ("config", "object"),
    ("task_revisions", 1): ("readiness", "requires_build_and_suite"),
    ("test_runs", 0): ("config_snapshot", "object"),
    ("test_runs", 1): ("state", "outcome_pair"),
    ("test_runs", 2): ("state", "terminal_needs_ended_at"),
    ("test_runs", 3): ("state", "executing_needs_resource"),
    ("test_runs", 4): ("resource_id", "profile_pair"),
    ("test_runs", 5): ("ended_at", "not_before_created"),
    ("test_runs", 6): ("started_at", "not_before_created"),
    ("test_runs", 7): ("ended_at", "not_before_started"),
    ("debug_sessions", 0): ("expires_at", "after_created"),
    ("debug_sessions", 1): ("state", "closed_pair"),
    ("debug_sessions", 2): ("closed_at", "not_before_created"),
    ("resource_leases", 0): ("expires_at", "after_created"),
    ("resource_leases", 1): ("released_at", "not_before_created"),
    ("resource_leases", 2): ("run_id", "xor_debug_session"),
    ("run_components", 0): ("summary", "object"),
    ("run_components", 1): ("state", "outcome_pair"),
    ("case_results", 0): ("steps", "array"),
    ("metric_summaries", 0): ("value", "missing_reason_pair"),
    ("metric_summaries", 1): ("value", "finite"),
    ("baselines", 0): ("metrics_snapshot", "object"),
    ("gate_policies", 0): ("rules", "object"),
    ("gate_evaluations", 0): ("checks", "array"),
    ("gate_evaluations", 1): ("verdict", "not_tested_reason"),
    ("run_events", 0): ("payload", "object"),
    ("audit_events", 0): ("changes", "object"),
}

# 平台新增列（data-model.md §5 的 G1/G2/G3 + P0-3）。按 schema.sql 列序的末尾追加。
EXTRA_COLUMNS = {
    "run_components": [("reason_code", "text")],
    "test_runs": [("not_tested_reason", "text")],
    "metric_summaries": [("missing_reason_text", "text")],
}

# 平台新增表级 CHECK（P0-3：三态结论必须给原因）
EXTRA_TABLE_CHECKS = {
    "run_components": [
        ("ck_run_components_reason_code_required",
         "outcome <> 'not_tested' OR reason_code IS NOT NULL"),
    ],
    "test_runs": [
        ("ck_test_runs_not_tested_reason_required",
         "outcome <> 'not_tested' OR not_tested_reason IS NOT NULL"),
    ],
}

# 4 个优先索引（data-model.md §8.3 G1/G2/G3/G5）
PRIORITY_INDEXES = [
    ("ix_debug_sessions_resource_state", "debug_sessions",
     ["project_id", "resource_id"], "state IN ('opening','active','closing')", False),
    ("ix_metric_summaries_metric_key", "metric_summaries",
     ["project_id", "metric_key", "metric_version", "scope", "window_key"], None, False),
    ("ix_test_runs_parent_run", "test_runs",
     ["project_id", "parent_run_id"], "parent_run_id IS NOT NULL", False),
    ("ix_task_revisions_task", "task_revisions",
     ["project_id", "task_id"], None, False),
]

TYPE_MAP = {
    "uuid": "postgresql.UUID(as_uuid=True)",
    "timestamptz": "sa.DateTime(timezone=True)",
    "jsonb": "postgresql.JSONB(astext_type=sa.Text())",
    "double precision": "sa.Float(precision=53)",
    "integer": "sa.Integer()",
    "bigint": "sa.BigInteger()",
    "text": "sa.Text()",
}


def py_str(s: str) -> str:
    """SQL 片段 -> 单行 Python 字符串字面量（双引号包裹，转义内部双引号/反斜杠）。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sq(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def split_nested(s: str) -> list[str]:
    """按顶层逗号切分（忽略括号内逗号）。"""
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def take_paren(tail: str) -> tuple[str, str]:
    """从 tail 的 '(' 起做括号配对，返回 (表达式体, 剩余)。"""
    start = tail.index("(")
    depth = 0
    end = -1
    for k in range(start, len(tail)):
        if tail[k] == "(":
            depth += 1
        elif tail[k] == ")":
            depth -= 1
            if depth == 0:
                end = k
                break
    return tail[start + 1:end], tail[end + 1:].strip()


def render_column(table: str, raw: str) -> tuple[list[str], list[str]]:
    """渲染单列定义，返回 (sa.Column 行, 该列派生出的约束行)。"""
    cname = raw.split(" ", 1)[0]
    rest = raw[len(cname):].strip()
    chosen = None
    for k in sorted(TYPE_MAP, key=len, reverse=True):
        if rest == k or rest.startswith(k + " "):
            chosen = k
            break
    if chosen is None:
        raise SystemExit(f"未知类型 {table}.{cname}: {rest!r}")
    rest = rest[len(chosen):].strip()

    args = [f'"{cname}"', TYPE_MAP[chosen]]
    # sa.Column 的位置参数必须排在关键字参数之前：外键与 UNIQUE 这两类
    # "位置型" 参数先攒在这里，待修饰符扫完再接到 args 尾部（此时仍在关键字之前）。
    positional_tail: list[str] = []
    constraints: list[str] = []
    inline_checks: list[str] = []
    inline_refs: list[tuple[str, str]] = []
    inline_unique = False

    while rest:
        if rest.startswith("PRIMARY KEY"):
            args.append("primary_key=True")
            rest = rest[len("PRIMARY KEY"):].strip()
        elif rest.startswith("NOT NULL"):
            args.append("nullable=False")
            rest = rest[len("NOT NULL"):].strip()
        elif rest.startswith("DEFAULT now()"):
            args.append("server_default=sa.text('now()')")
            rest = rest[len("DEFAULT now()"):].strip()
        elif rest.startswith("DEFAULT "):
            rest = rest[len("DEFAULT "):].strip()
            matched = False
            for lit in ("'{}'::jsonb", "'[]'::jsonb"):
                if rest.startswith(lit):
                    args.append("server_default=sa.text(" + py_str(lit) + ")")
                    rest = rest[len(lit):].strip()
                    matched = True
                    break
            if matched:
                pass
            elif rest.startswith("'"):
                end = rest.index("'", 1)
                args.append("server_default=sa.text(" + py_str(rest[: end + 1]) + ")")
                rest = rest[end + 1:].strip()
            else:
                m = re.match(r"-?\d+", rest)
                args.append("server_default=sa.text('" + m.group(0) + "')")
                rest = rest[m.end():].strip()
        elif rest.startswith("UNIQUE"):
            inline_unique = True
            rest = rest[len("UNIQUE"):].strip()
        elif rest.startswith("REFERENCES"):
            m = re.match(r"REFERENCES\s+(\w+)\((\w+)\)", rest)
            inline_refs.append((m.group(1), m.group(2)))
            rest = rest[m.end():].strip()
        elif rest.startswith("CHECK"):
            body, rest = take_paren(rest)
            inline_checks.append(body)
        else:
            raise SystemExit(f"未解析修饰符 {table}.{cname}: {rest!r}")

    for rt, rc in inline_refs:
        positional_tail.append(f"sa.ForeignKey({py_str(rt + '.' + rc)})")
    if inline_unique:
        # 列级 UNIQUE 也是位置参数；用 unique=True 关键字（PG 自动命名
        # uq_/key 约束，满足「不出现匿名约束」的要求）。
        args.append("unique=True")

    # 关键顺序：位置参数（类型/外键）在前，关键字参数在后，否则 Python 报
    # "positional argument follows keyword argument"。
    ordered = args[:2] + positional_tail + args[2:]
    lines = [f'        sa.Column({", ".join(ordered)}),']

    for expr in inline_checks:
        slug = CHECK_SLUG.get((table, cname))
        if slug is None:
            raise SystemExit(f"缺列级 CHECK 命名 {table}.{cname}: {expr}")
        constraints.append(
            f'        sa.CheckConstraint(sa.text({py_str(expr)}), '
            f'name="ck_{table}_{cname}_{slug}"),'
        )
    return lines, constraints


def render_table(t: dict) -> tuple[str, int]:
    name = t["name"]
    col_lines: list[str] = []
    tac_lines: list[str] = []
    ncols = 0
    table_check_idx = 0

    for raw in t["body"]:
        if raw.startswith("UNIQUE ("):
            cols = split_nested(raw[len("UNIQUE ("):-1])
            tac_lines.append(
                "        sa.UniqueConstraint("
                + ", ".join('"' + c + '"' for c in cols)
                + ', name="uq_' + name + "_" + "_".join(cols) + '"),'
            )
        elif raw.startswith("FOREIGN KEY"):
            left, right = raw.split("REFERENCES")
            local = split_nested(left.split("(", 1)[1].rstrip(") ").strip())
            rm = re.match(r"\s*(\w+)\(([^)]*)\)", right)
            ref_table = rm.group(1)
            ref_cols = [c.strip() for c in rm.group(2).split(",")]
            tac_lines.append(
                "        sa.ForeignKeyConstraint(["
                + ", ".join('"' + c + '"' for c in local)
                + "], ["
                + ", ".join('"' + ref_table + "." + c + '"' for c in ref_cols)
                + '], name="fk_' + name + "_" + "_".join(local) + "_" + ref_table + '"),'
            )
        elif raw.startswith("CHECK "):
            body = raw[len("CHECK ("):-1]
            key = (name, table_check_idx)
            if key not in TABLE_CHECK_SLUG:
                raise SystemExit(f"缺表级 CHECK 命名 {key}: {body}")
            collabel, slug = TABLE_CHECK_SLUG[key]
            tac_lines.append(
                f'        sa.CheckConstraint(sa.text({py_str(body)}), '
                f'name="ck_{name}_{collabel}_{slug}"),'
            )
            table_check_idx += 1
        elif raw.startswith(("PRIMARY KEY", "CONSTRAINT")):
            raise SystemExit(f"未预期构造 {name}: {raw}")
        else:
            lines, cons = render_column(name, raw)
            col_lines.extend(lines)
            tac_lines.extend(cons)
            ncols += 1

    for cname, ctype in EXTRA_COLUMNS.get(name, []):
        col_lines.append(f'        sa.Column("{cname}", {TYPE_MAP[ctype]}),')
        ncols += 1

    for ckname, expr in EXTRA_TABLE_CHECKS.get(name, []):
        tac_lines.append(
            f'        sa.CheckConstraint(sa.text({py_str(expr)}), name="{ckname}"),'
        )

    block = "\n".join(
        ["    op.create_table(", '        "' + name + '",'] + col_lines + tac_lines + ["    )"]
    )
    return block, ncols


def render_index(ix: dict) -> str:
    cols = split_nested(ix["cols"])
    arg_lines = ['        "' + ix["name"] + '",', '        "' + ix["table"] + '",']
    if len(cols) == 1:
        arg_lines.append('        "' + cols[0] + '",')
    else:
        arg_lines.append("        [")
        for c in cols:
            arg_lines.append('            "' + c + '",')
        arg_lines.append("        ],")
    if ix["where"]:
        arg_lines.append(
            "        unique=True," if ix["unique"] else "        unique=False,"
        )
        arg_lines.append(
            "        postgresql_where=sa.text(" + py_str(ix["where"]) + "),"
        )
    return "    op.create_index(\n" + "\n".join(arg_lines + ["    )"])


def render_priority_index(spec) -> str:
    iname, table, cols, where, unique = spec
    arg_lines = ['        "' + iname + '",', '        "' + table + '",']
    if len(cols) == 1:
        arg_lines.append('        "' + cols[0] + '",')
    else:
        arg_lines.append("        [")
        for c in cols:
            arg_lines.append('            "' + c + '",')
        arg_lines.append("        ],")
    if where:
        arg_lines.append("        postgresql_where=sa.text(" + py_str(where) + "),")
    if unique:
        arg_lines.append("        unique=True,")
    return "    op.create_index(\n" + "\n".join(arg_lines + ["    )"])


HEADER = '''"""0001 初始迁移：TestDock 平台 24 张表 + 索引 + 注释。

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
'''


def main() -> None:
    table_blocks: list[str] = []
    ncols_total = 0
    for t in TABLES:
        block, ncols = render_table(t)
        table_blocks.append(block)
        ncols_total += ncols

    body = [HEADER.rstrip("\n")]
    for b in table_blocks:
        body.append(b)
        body.append("")

    body.append("    # ----------------------------------------------------------------- #")
    body.append("    # 索引：schema.sql L714-728 共 15 条，其中 7 条为部分索引")
    body.append("    # ----------------------------------------------------------------- #")
    for ix in INDEXES:
        body.append(render_index(ix))
        body.append("")

    body.append("    # ----------------------------------------------------------------- #")
    body.append("    # 优先索引（data-model.md §8.3 G1/G2/G3/G5）")
    body.append("    # ----------------------------------------------------------------- #")
    for spec in PRIORITY_INDEXES:
        body.append(render_priority_index(spec))
        body.append("")

    body.append("    # ----------------------------------------------------------------- #")
    body.append("    # COMMENT：24 表 + 231 列 = 255 条，原文逐字来自 schema.sql")
    body.append("    # ----------------------------------------------------------------- #")
    for tbl in TABLES:
        tname = tbl["name"]
        body.append(
            "    op.execute("
            + py_str("COMMENT ON TABLE " + tname + " IS " + sq(TCOM[tname]))
            + ")"
        )
        for t2, cname, text in CCOM:
            if t2 != tname:
                continue
            body.append(
                "    op.execute("
                + py_str("COMMENT ON COLUMN " + t2 + "." + cname + " IS " + sq(text))
                + ")"
            )
        body.append("")

    drop_lines = [
        "",
        "",
        "def downgrade() -> None:",
        '    """逆序删除 24 张表：索引随所属表一起 DROP，无需单独 drop_index。"""',
    ]
    for t in reversed(TABLES):
        drop_lines.append('    op.drop_table("' + t["name"] + '")')

    text = "\n".join(body) + "\n".join(drop_lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print("written:", OUT)
    print("tables:", len(TABLES), "columns:", ncols_total)
    print("lines:", len(text.splitlines()))


if __name__ == "__main__":
    main()
