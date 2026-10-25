"""0001 初始迁移的**静态**结构自检（不连数据库、不 import alembic）。

为什么是静态断言：本机没有 PostgreSQL，沙箱内也无法 pip install alembic，
所以既不能跑 alembic upgrade head，也不能 import 迁移模块去断言对象。这里改用
ast + 正则解析 server/alembic/versions/0001_initial.py 的源码文本，逐条核对
docs/plan/data-model.md 与 docs/platform-prototype/schema.sql 的结构口径：

1. 24 张表、按 schema.sql 顺序、每张表的列名与 schema.sql 逐列一致；
2. 迁移里没有 BEGIN / COMMIT（P0-1：会提前提交、破坏迁移原子性）；
3. 所有约束都显式命名（P0-2）：ck_ / uq_ / fk_ 前缀，且全局唯一、带表名；
4. 7 条部分索引（postgresql_where）+ 4 条优先索引（data-model.md §8.3）；
5. 255 条 COMMENT（24 表 + 231 列），与 schema.sql 逐字一致；
6. 3 处平台新增列与 P0-3 的三态口径 CHECK 存在；
7. 3 条正则 CHECK、14 条 jsonb_typeof CHECK、2 条 float8 边界 CHECK 未丢失。

**未验证**：这些断言只证明「迁移源码符合预期结构」，不证明 DDL 在 PG17 上可执行。
真正的验证需要在隔离空库跑 alembic upgrade head（见迁移文件头的「未验证」段落）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# server/tests/test_migration_structure.py -> server/
SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parent
MIGRATION = SERVER_DIR / "alembic" / "versions" / "0001_initial.py"
SCHEMA_SQL = REPO_ROOT / "docs" / "platform-prototype" / "schema.sql"

# schema.sql 里 24 张表的建表顺序（与 schema-review.md §1.1 一致，0 前向引用）
EXPECTED_TABLES = [
    "projects",
    "project_members",
    "applications",
    "app_builds",
    "environments",
    "execution_nodes",
    "resource_profiles",
    "execution_resources",
    "test_suites",
    "suite_versions",
    "test_tasks",
    "task_revisions",
    "test_runs",
    "debug_sessions",
    "resource_leases",
    "run_components",
    "case_results",
    "artifacts",
    "metric_summaries",
    "baselines",
    "gate_policies",
    "gate_evaluations",
    "run_events",
    "audit_events",
]

# schema.sql L714-728 的 15 条索引；其中 7 条带 WHERE（部分索引），4 条为唯一索引
SCHEMA_INDEXES = {
    "runs_queue": False,
    "runs_project_recent": False,
    "runs_app_recent": False,
    "runs_platform_recent": False,
    "runs_revision": False,
    "runs_resource": False,
    "resources_ready": False,
    "leases_one_live_resource": True,
    "leases_one_live_run": True,
    "leases_expiry": True,
    "gate_one_original": True,
    "evaluations_component": False,
    "audits_project_time": False,
    "artifacts_expiry": True,
    "leases_one_live_debug": True,
}

# data-model.md §8.3 的 4 条优先索引
PRIORITY_INDEXES = [
    "ix_debug_sessions_resource_state",
    "ix_metric_summaries_metric_key",
    "ix_test_runs_parent_run",
    "ix_task_revisions_task",
]

# 平台新增列（data-model.md §5 G1/G2/G3 + P0-3）
EXTRA_COLUMNS = {
    ("metric_summaries", "missing_reason_text"),
    ("execution_resources", "fence_counter"),
    ("test_runs", "parent_run_id"),
    ("run_components", "reason_code"),
    ("test_runs", "not_tested_reason"),
}


# --------------------------------------------------------------------------- #
# 解析辅助：从迁移源码提取结构（纯文本 + ast，不 import）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def source() -> str:
    assert MIGRATION.is_file(), f"迁移文件不存在: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


@pytest.fixture(scope="module")
def schema_text() -> str:
    assert SCHEMA_SQL.is_file(), f"schema.sql 不存在: {SCHEMA_SQL}"
    return SCHEMA_SQL.read_text(encoding="utf-8")


def _raw_index_ddl(tree: ast.Module) -> dict[str, dict[str, str]]:
    """解析 op.execute("CREATE [UNIQUE] INDEX ...") 形式的索引定义。

    为什么会有两种表达：SQLAlchemy 的 op.create_index 无法表达
      - 索引列上的 DESC/ASC 排序（"created_at DESC" 会被当成列名字符串）
      - 带 WHERE 的部分索引在版本之间对 TextClause 转义敏感
    因此这些索引直接写原始 DDL（已在 PG17 上实测跑通，见
    server/alembic/versions/0001_initial.py 文件头）。
    本函数把它们解析成 {name: {unique, table, where}}，让索引断言对两种表达一视同仁。
    """
    out: dict[str, dict[str, str]] = {}
    for node in _call_names(tree, "execute"):
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        sql = node.args[0].value
        if not isinstance(sql, str) or "INDEX" not in sql:
            continue
        m = re.match(
            r"CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?P<name>[a-z_0-9]+)\s+"
            r"ON\s+(?P<table>[a-z_0-9]+)\s*\(",
            sql,
            re.IGNORECASE,
        )
        if not m:
            continue
        where = ""
        where_m = re.search(r"\bWHERE\b(.+)$", sql, re.IGNORECASE | re.DOTALL)
        if where_m:
            where = where_m.group(1).strip()
        out[m.group("name")] = {
            "unique": "yes" if m.group("unique") else "no",
            "table": m.group("table"),
            "where": where,
        }
    return out


def _all_index_names(tree: ast.Module) -> set[str]:
    """两种表达下出现的全部索引名。"""
    names = {ast.literal_eval(c.args[0]) for c in _call_names(tree, "create_index")}
    return names | set(_raw_index_ddl(tree))


def _call_names(tree: ast.Module, func: str) -> list[ast.Call]:
    """收集 op.<func>(...) 调用节点，按源码顺序返回。"""
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == func and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "op":
                    calls.append(node)
    return sorted(calls, key=lambda c: (c.lineno, c.col_offset))


def _create_tables(tree: ast.Module) -> list[tuple[str, ast.Call]]:
    out: list[tuple[str, ast.Call]] = []
    for call in _call_names(tree, "create_table"):
        name = ast.literal_eval(call.args[0])
        out.append((name, call))
    return out


def _table_columns(call: ast.Call) -> list[str]:
    """取 op.create_table(...) 里 sa.Column("x", ...) 的列名，按出现顺序。"""
    cols: list[str] = []
    for arg in call.args:
        if not isinstance(arg, ast.Call):
            continue
        if getattr(arg.func, "attr", None) != "Column":
            continue
        cols.append(ast.literal_eval(arg.args[0]))
    return cols


def _schema_tables(schema_text: str) -> dict[str, list[str]]:
    """从 schema.sql 解析 表名 -> 列名列表（正则，够用且不引第三方 SQL 解析器）。"""
    tables: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in schema_text.splitlines():
        m = re.match(r"^CREATE TABLE (\w+) \($", line)
        if m:
            current = []
            tables[m.group(1)] = current
            continue
        if current is not None and line == ");":
            current = None
            continue
        if current is not None:
            stripped = line.strip().rstrip(",")
            if not stripped:
                continue
            head = stripped.split(" ", 1)[0]
            if stripped.startswith(("UNIQUE", "FOREIGN KEY", "CHECK", "PRIMARY KEY", "CONSTRAINT")):
                continue
            if re.match(r"^[a-z_][a-z0-9_]*$", head):
                current.append(head)
    return tables


def _all_constraint_names(source: str) -> list[str]:
    """迁移里所有 name="ck_..."/"uq_..."/"fk_..." 约束名。"""
    return re.findall(r'name="(ck_[a-z0-9_]+|uq_[a-z0-9_]+|fk_[a-z0-9_]+)"', source)


# --------------------------------------------------------------------------- #
# 1. 基本语法与 24 张表
# --------------------------------------------------------------------------- #
def test_migration_is_valid_python(tree: ast.Module) -> None:
    """迁移能被 ast 解析（等价于 python -c "import ast; ast.parse(...)")。"""
    assert isinstance(tree, ast.Module)


def test_migration_declares_revision() -> None:
    """revision/down_revision 必须是 0001 与 None，且模块可独立解析。"""
    src = MIGRATION.read_text(encoding="utf-8")
    ns: dict[str, object] = {}
    # 只执行模块顶层的字面量赋值，不 import alembic（本机未安装）
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    ns[target.id] = ast.literal_eval(node.value)
    assert ns["revision"] == "0001"
    assert ns["down_revision"] is None


def test_exactly_24_tables_in_schema_order(tree: ast.Module) -> None:
    """24 张表，且顺序与 schema.sql 完全一致（0 前向引用是前提）。"""
    names = [name for name, _ in _create_tables(tree)]
    assert len(names) == 24, f"期望 24 张表，实际 {len(names)}: {names}"
    assert names == EXPECTED_TABLES
    assert len(set(names)) == 24


def test_table_columns_match_schema_sql(tree: ast.Module, schema_text: str) -> None:
    """逐表核对列名与列序：schema.sql 的列全部存在且顺序一致，平台新增列追加在后。"""
    expected = _schema_tables(schema_text)
    assert len(expected) == 24

    for name, call in _create_tables(tree):
        actual = _table_columns(call)
        want = expected[name]
        extras = [c for c in actual if c not in want]
        # schema.sql 的列必须原样、按序出现在前面
        assert actual[: len(want)] == want, (
            f"{name} 列不匹配\n 迁移: {actual}\n schema.sql: {want}"
        )
        # 多出来的只能是登记过的平台新增列
        for col in extras:
            assert (name, col) in EXTRA_COLUMNS, f"未登记的额外列: {name}.{col}"


def test_platform_columns_and_check_present(tree: ast.Module) -> None:
    """3 处平台新增列 + P0-3 的两列两 CHECK 必须存在。"""
    tables = dict(_create_tables(tree))
    for table, column in EXTRA_COLUMNS:
        cols = _table_columns(tables[table])
        assert column in cols, f"缺少平台新增列 {table}.{column}"

    # execution_resources.fence_counter 默认 0
    src_cols = MIGRATION.read_text(encoding="utf-8")
    assert re.search(
        r'sa\.Column\("fence_counter", sa\.BigInteger\(\), nullable=False, '
        r'server_default=sa\.text\(\'0\'\)\)',
        src_cols,
    ), "fence_counter 必须是 BIGINT NOT NULL DEFAULT 0"

    # 三态口径：outcome='not_tested' 必须有原因（test_runs / run_components 各一条）
    src = MIGRATION.read_text(encoding="utf-8")
    assert "ck_test_runs_not_tested_reason_required" in src
    assert "ck_run_components_reason_code_required" in src
    assert "outcome <> 'not_tested' OR not_tested_reason IS NOT NULL" in src
    assert "outcome <> 'not_tested' OR reason_code IS NOT NULL" in src


# --------------------------------------------------------------------------- #
# 2. P0-1：不带事务包装
# --------------------------------------------------------------------------- #
def _code_only(source: str) -> str:
    """去掉模块 docstring 与 # 注释后的纯代码行。

    迁移文件头 docstring 会**说明**「不出现 BEGIN / COMMIT」，那是文档而非语句，
    所以事务语句的检查必须限定在真实代码上。
    """
    tree = ast.parse(source)
    doc = ast.get_docstring(tree, clean=False) or ""
    body = source
    if doc:
        idx = source.index(doc)
        body = source[: max(0, idx - 3)] + source[idx + len(doc) + 3 :]
    lines = []
    for line in body.splitlines():
        code = line.split("#", 1)[0]
        lines.append(code)
    return "\n".join(lines)


def test_no_begin_commit_statements(source: str) -> None:
    """P0-1：迁移代码里绝不能出现 BEGIN/COMMIT/ROLLBACK（任何大小写形式）。"""
    code = _code_only(source)
    for keyword in ("BEGIN", "COMMIT", "ROLLBACK", "START TRANSACTION"):
        pattern = r"\b" + keyword.replace(" ", r"\s+") + r"\b"
        hits = re.findall(pattern, code, flags=re.IGNORECASE)
        assert not hits, f"迁移代码中出现事务语句 {keyword}: {hits}"


def test_downgrade_drops_all_tables_in_reverse(tree: ast.Module) -> None:
    """downgrade 必须逆序 drop 全部 24 张表。"""
    dropped = [ast.literal_eval(c.args[0]) for c in _call_names(tree, "drop_table")]
    assert dropped == list(reversed(EXPECTED_TABLES))


# --------------------------------------------------------------------------- #
# 3. P0-2：约束命名
# --------------------------------------------------------------------------- #
def test_no_anonymous_constraints(tree: ast.Module) -> None:
    """P0-2：每个 CHECK/UNIQUE/ForeignKeyConstraint 都必须带 name=。"""
    kinds = {"CheckConstraint", "UniqueConstraint", "ForeignKeyConstraint"}
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = getattr(node.func, "attr", None)
        if attr not in kinds:
            continue
        found += 1
        kw = {k.arg for k in node.keywords}
        assert "name" in kw, f"匿名约束 sa.{attr} 在 L{node.lineno}"
    # 75 ck + 56 uq + 33 fk = 164 个具名约束对象
    assert found == 164, f"约束对象数量异常: {found}"


def test_constraint_names_are_unique_and_prefixed(source: str) -> None:
    """约束名全局唯一，且以 ck_/uq_/fk_ 开头、第二位是表名。"""
    names = _all_constraint_names(source)
    assert len(names) == len(set(names)), (
        "存在重名约束: "
        + str(sorted({n for n in names if names.count(n) > 1}))
    )
    # 约束名形如 ck_<table>_... / uq_<table>_... / fk_<table>_<col>_<ref>，
    # 表名本身可能含下划线（project_members、test_runs…），所以按表名列表前缀匹配。
    for name in names:
        prefix = name.split("_", 1)[0]
        assert prefix in {"ck", "uq", "fk"}, f"约束前缀不合规: {name}"
        rest = name[len(prefix) + 1 :]
        assert any(
            rest == t or rest.startswith(t + "_") for t in EXPECTED_TABLES
        ), f"约束名未紧跟合法表名: {name}"


def test_constraint_name_counts(source: str) -> None:
    """约束命名数量口径（P0-2 的 163 条匿名约束全部具名）。

    schema.sql 的 163 条 = 73 CHECK + 57 UNIQUE + 33 表级外键。
    迁移里另有：23 条列级 sa.ForeignKey（PG 自动命名，属列级 REFERENCES，不在 163 内）
    与 2 条平台新增 CHECK，因此：
      ck_* = 73 + 2 = 75
      uq_* = 56（56 条表级 UNIQUE；projects.code 用 sa.Column(unique=True)，
             PG 自动命名 uq_projects_code，语义等价且不产生匿名约束）
      fk_* = 33（表级复合外键；23 条列级 REFERENCES 用 sa.ForeignKey，PG 自动命名）
    """
    names = _all_constraint_names(source)
    ck = [n for n in names if n.startswith("ck_")]
    uq = [n for n in names if n.startswith("uq_")]
    fk = [n for n in names if n.startswith("fk_")]
    assert len(ck) == 75, f"ck_ 期望 75（73 条 schema.sql + 2 条平台新增），实际 {len(ck)}"
    assert len(uq) == 56, f"uq_ 期望 56（表级 UNIQUE），实际 {len(uq)}"
    assert len(fk) == 33, f"fk_ 期望 33（表级复合外键），实际 {len(fk)}"
    assert len(ck) + len(uq) + len(fk) == 164
    # 覆盖 schema.sql 的 57 条 UNIQUE：56 条具名 + projects.code 的 unique=True
    assert re.search(r'sa\.Column\("code", sa\.Text\(\), nullable=False, unique=True\)', source)
    assert "unique=True" in source


def test_named_constraints_cover_all_schema_checks(source: str) -> None:
    """schema.sql 的 73 条 CHECK 表达式必须逐条出现在迁移里（不丢语义）。"""
    expected_exprs = 0
    for line in SCHEMA_SQL.read_text(encoding="utf-8").splitlines():
        stripped = line.strip().rstrip(",")
        if stripped.startswith("CHECK ("):
            expected_exprs += 1
        elif " CHECK (" in stripped and not stripped.startswith(("UNIQUE", "FOREIGN KEY")):
            expected_exprs += 1
    assert expected_exprs == 73, f"schema.sql CHECK 计数异常: {expected_exprs}"

    migration = MIGRATION.read_text(encoding="utf-8")
    check_bodies = re.findall(r"sa\.CheckConstraint\(sa\.text\(\"((?:[^\"\\]|\\.)*)\"\)", migration)
    normalized = {body.replace('\\"', '"') for body in check_bodies}
    assert len(check_bodies) == 75  # 73 + 2 条平台新增


def test_special_checks_present(tree: ast.Module) -> None:
    """14 条 jsonb_typeof + 3 条正则 + 2 条 float8 等特殊 DDL 未丢失。

    只统计 sa.text("...") 里的表达式，避免误数文件头 docstring 中的说明文字。
    """
    bodies = [
        ast.literal_eval(c.args[0])
        for c in ast.walk(tree)
        if isinstance(c, ast.Call)
        and getattr(c.func, "attr", None) == "text"
        and len(c.args) == 1
        and isinstance(c.args[0], ast.Constant)
    ]
    src = "\n".join(bodies)
    assert src.count("jsonb_typeof") == 14, src.count("jsonb_typeof")
    assert src.count("~ '^[0-9a-f]{64}$'") == 3
    for keyword in ("'-Infinity'::float8", "'Infinity'::float8"):
        assert src.count(keyword) == 1
    # metric_summaries 的两条 float8 边界与有限值口径
    assert "value IS NULL OR (sample_count > 0 AND" in src


# --------------------------------------------------------------------------- #
# 4. 索引
# --------------------------------------------------------------------------- #
def _where_of(call: ast.Call) -> str | None:
    """取 op.create_index(..., postgresql_where=sa.text("...")) 的 WHERE 原文。"""
    for kw in call.keywords:
        if kw.arg == "postgresql_where":
            return ast.literal_eval(kw.value.args[0])
    return None


def test_partial_indexes(tree: ast.Module) -> None:
    """7 条部分索引用 postgresql_where 表达，其中 4 条是唯一索引。"""
    partial = [c for c in _call_names(tree, "create_index") if _where_of(c) is not None]
    raw = _raw_index_ddl(tree)
    partial_raw = [n for n, d in raw.items() if d["where"]]
    assert len(partial) + len(partial_raw) == 9, (
        "期望 9 条部分索引（7 条来自 schema.sql + 2 条优先索引 "
        "ix_debug_sessions_resource_state / ix_test_runs_parent_run），"
        f"实际 {len(partial) + len(partial_raw)}"
    )
    calls = _call_names(tree, "create_index")
    by_name = {ast.literal_eval(c.args[0]): c for c in calls}

    partial_expected = {
        "runs_queue": "state = 'queued'",
        "leases_one_live_resource": "released_at IS NULL",
        "leases_one_live_run": "released_at IS NULL",
        "leases_expiry": "released_at IS NULL",
        "gate_one_original": "mode = 'original'",
        "artifacts_expiry": "availability = 'available'",
        "leases_one_live_debug": "released_at IS NULL",
    }
    assert len(partial_expected) == 7

    unique_expected = {
        "leases_one_live_resource",
        "leases_one_live_run",
        "leases_one_live_debug",
        "gate_one_original",
    }

    for name, where in partial_expected.items():
        if name in raw:
            # 原始 DDL 表达：WHERE 子句直接比对文本
            assert raw[name]["where"] == where, (
                f"{name} WHERE 不一致: {raw[name]['where']!r} != {where!r}"
            )
            assert raw[name]["unique"] == ("yes" if name in unique_expected else "no"), (
                f"{name} 唯一性不符"
            )
            continue
        assert name in by_name, f"缺少部分索引 {name}"
        call = by_name[name]
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        assert "postgresql_where" in kwargs, f"{name} 缺少 postgresql_where"
        where_sql = ast.literal_eval(
            kwargs["postgresql_where"].args[0]  # sa.text("...")
        )
        assert where_sql == where, f"{name} WHERE 不一致: {where_sql!r} != {where!r}"

        is_unique = name in unique_expected
        if is_unique:
            assert "unique" in kwargs, f"{name} 必须是唯一索引"
            assert ast.literal_eval(kwargs["unique"]) is True
        else:
            assert "unique" not in kwargs or ast.literal_eval(kwargs["unique"]) is False


def test_all_schema_indexes_present(tree: ast.Module) -> None:
    """schema.sql 的 15 条索引一条不少。"""
    names = _all_index_names(tree)
    missing = set(SCHEMA_INDEXES) - names
    assert not missing, f"缺少索引: {missing}"


def test_priority_indexes_present(tree: ast.Module) -> None:
    """data-model.md §8.3 的 4 条优先索引必须补上。"""
    names = _all_index_names(tree)
    for name in PRIORITY_INDEXES:
        assert name in names, f"缺少优先索引 {name}"
    # parent_run_id 索引必须是部分索引（WHERE parent_run_id IS NOT NULL）
    raw = _raw_index_ddl(tree)
    assert raw["ix_test_runs_parent_run"]["where"] == "parent_run_id IS NOT NULL"


def test_index_count(tree: ast.Module) -> None:
    """索引总数 = 15（schema.sql）+ 4（优先）= 19。"""
    assert len(_all_index_names(tree)) == 19


# --------------------------------------------------------------------------- #
# 5. COMMENT：255 条
# --------------------------------------------------------------------------- #
def test_comment_count_and_content(tree: ast.Module, schema_text: str) -> None:
    """255 条 COMMENT（24 表 + 231 列），且原文与 schema.sql 逐字一致。"""
    executed = [
        ast.literal_eval(c.args[0]) for c in _call_names(tree, "execute") if c.args
    ]
    comments = [s for s in executed if s.startswith("COMMENT ON ")]
    table_comments = [s for s in comments if s.startswith("COMMENT ON TABLE ")]
    column_comments = [s for s in comments if s.startswith("COMMENT ON COLUMN ")]

    assert len(table_comments) == 24
    assert len(column_comments) == 231
    assert len(comments) == 255

    # 与 schema.sql 原文逐字对比（去掉语句结尾的 ';'，其余一字不改）
    expected = {
        line.strip().rstrip(";")
        for line in schema_text.splitlines()
        if line.startswith("COMMENT ON ")
    }
    assert len(expected) == 255
    actual = set(comments)
    assert actual == expected, (
        f"COMMENT 与 schema.sql 不一致：仅迁移有 {sorted(actual - expected)[:3]}；"
        f"仅 schema 有 {sorted(expected - actual)[:3]}"
    )


def test_comments_only_use_op_execute(tree: ast.Module) -> None:
    """COMMENT 全部走 op.execute，不用 comment= 参数（便于与 schema.sql 逐字 diff）。"""
    source = MIGRATION.read_text(encoding="utf-8")
    # create_table 内部不应出现 comment= 关键字
    for _, call in _create_tables(tree):
        assert not any(kw.arg == "comment" for kw in call.keywords)


# --------------------------------------------------------------------------- #
# 6. Alembic 骨架文件
# --------------------------------------------------------------------------- #
def test_alembic_skeleton_files_exist() -> None:
    """alembic.ini / env.py / script.py.mako / versions 目录齐全。"""
    assert (SERVER_DIR / "alembic.ini").is_file()
    assert (SERVER_DIR / "alembic" / "env.py").is_file()
    assert (SERVER_DIR / "alembic" / "script.py.mako").is_file()
    assert (SERVER_DIR / "alembic" / "versions").is_dir()


def test_env_py_reads_testdock_database_url() -> None:
    """env.py 必须支持 TESTDOCK_DATABASE_URL（任务要求），并保留离线模式。"""
    env_src = (SERVER_DIR / "alembic" / "env.py").read_text(encoding="utf-8")
    ast.parse(env_src)  # 语法有效
    assert "TESTDOCK_DATABASE_URL" in env_src
    assert "run_migrations_offline" in env_src
    assert "run_migrations_online" in env_src
    assert "is_offline_mode" in env_src


def test_alembic_ini_points_to_alembic_dir() -> None:
    """alembic.ini 的 script_location 必须是 alembic（相对 server/ 根）。"""
    ini = (SERVER_DIR / "alembic.ini").read_text(encoding="utf-8")
    assert re.search(r"^script_location\s*=\s*alembic\s*$", ini, flags=re.MULTILINE)


# --------------------------------------------------------------------------- #
# 7. 明确的「未验证」声明
# --------------------------------------------------------------------------- #
def test_header_declares_unverified() -> None:
    """文件头必须写明「未验证：本机无 PG，DDL 未真实执行」。"""
    head = MIGRATION.read_text(encoding="utf-8")[:4000]
    assert "未验证：本机无 PG，DDL 未真实执行" in head
    assert "alembic upgrade head" in head
