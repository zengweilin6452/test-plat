#!/usr/bin/env python3
"""生成「数据设计」页静态数据 schema_doc.json（P6，development-plan.md §P6）。

用法（构建期执行一次，产物入库；运行期 API 只读该 JSON，不重新解析）::

    python scripts/gen_schema_doc.py

原理：用 ast 解析 server/alembic/versions/0001_initial.py（**不 import 执行**，
迁移里没有可安全复用的副作用，且 gen 独立运行不应依赖 alembic 环境），抽取：

  - 表清单与建表顺序、列（名/类型/可空/默认/主键）、CHECK / UNIQUE / FK 约束；
    0001 之后由 0002+ 追加的迁移补齐（新表 / 新列 / COMMENT），当前 head = 0008；
  - 19 条索引（op.create_index 与 op.execute("CREATE ... INDEX ...") 两种写法）；
  - 表与列的 COMMENT（表用途 / 字段中文说明）。

表分组（7 组）、泳道（4 条）与写入流程（4 条）的归属依据
docs/platform-prototype/database-design.md §3 与原型 index.html 的
databaseTables / databaseOverview.lanes / databaseFlows，在此固化为常量。

产物：server/app/static_data/schema_doc.json
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "server" / "alembic" / "versions" / "0001_initial.py"
# 迁移 0002+（工单 22：字典必须覆盖当前迁移 head，而不是只解析 0001）
MIGRATIONS_DIR = REPO_ROOT / "server" / "alembic" / "versions"

OUT_PATH = REPO_ROOT / "server" / "app" / "static_data" / "schema_doc.json"

# --------------------------------------------------------------------------- #
# 表分组 / 业务名称 / 泳道 / 写入流程：与原型 index.html、database-design.md 对齐
# --------------------------------------------------------------------------- #
TABLE_GROUPS: dict[str, list[str]] = {
    "基础资产": ["projects", "project_members", "applications", "app_builds", "environments"],
    "执行资源": [
        "execution_nodes",
        "resource_profiles",
        "execution_resources",
        "device_checks",
        "debug_sessions",
        "resource_leases",
    ],
    "测试定义": ["test_suites", "suite_versions"],
    "任务运行": ["test_tasks", "task_revisions", "task_request_keys", "test_runs"],
    "结果证据": ["run_components", "case_results", "artifacts"],
    "性能质量": ["metric_summaries", "baselines", "gate_policies", "gate_evaluations"],
    "治理追溯": ["run_events", "audit_events"],
}

TABLE_TITLES: dict[str, str] = {
    "projects": "项目",
    "project_members": "项目成员",
    "applications": "应用",
    "app_builds": "应用构建",
    "environments": "测试环境",
    "execution_nodes": "执行节点",
    "resource_profiles": "资源档案",
    "execution_resources": "执行实例",
    "test_suites": "测试套件",
    "suite_versions": "套件版本",
    "test_tasks": "测试任务",
    "task_revisions": "任务配置版本",
    "task_request_keys": "任务幂等键",
    "test_runs": "测试运行",
    "debug_sessions": "调试会话",
    "resource_leases": "资源租约",
    "device_checks": "设备短检查",
    "run_components": "运行组件",
    "case_results": "用例结果",
    "artifacts": "证据文件",
    "metric_summaries": "性能摘要",
    "baselines": "基线版本",
    "gate_policies": "门禁规则版本",
    "gate_evaluations": "门禁判定",
    "run_events": "运行事件",
    "audit_events": "审计事件",
}

LANES: list[dict[str, object]] = [
    {
        "title": "从配置到运行",
        "description": "一条任务可以有多个配置版本，每个版本可以运行多次。",
        "tables": ["projects", "applications", "test_tasks", "task_revisions"],
    },
    {
        "title": "一次运行的可追溯结果",
        "description": "运行和结论分离，重跑不覆盖历史。",
        "tables": ["test_runs", "run_components", "case_results", "artifacts"],
    },
    {
        "title": "共用资源，保留各端差异",
        "description": "实例引用当前档案，历史运行固定当时档案；人工调试与运行共用租约。",
        "tables": ["resource_profiles", "execution_resources", "debug_sessions", "resource_leases"],
    },
    {
        "title": "性能口径与历史判定",
        "description": "基线、规则和原始结论均保留版本。后续试算独立保存。",
        "tables": ["metric_summaries", "baselines", "gate_policies", "gate_evaluations"],
    },
]

FLOWS: list[dict[str, object]] = [
    {
        "key": "save",
        "title": "保存配置与重跑",
        "steps": [
            {"title": "保存草稿", "description": "锁定逻辑任务并校验乐观锁，新增配置版本。Web / iOS 未接入时保持 draft。", "tables": ["test_tasks", "task_revisions"]},
            {"title": "验证并提交", "description": "校验应用、构建、套件、环境与适配器，把当前配置固定为运行快照。幂等键重复时不重复创建。", "tables": ["app_builds", "suite_versions", "test_runs"]},
            {"title": "执行和归档", "description": "每次运行拥有自己的组件结果与证据。通过、失败、未判定与执行错误分开记录。", "tables": ["run_components", "case_results", "artifacts"]},
            {"title": "重新运行", "description": "创建新的 test_run，parent_run_id 指向原运行。默认复用原配置版本，保留全部历史。", "tables": ["test_runs", "task_revisions"]},
        ],
    },
    {
        "key": "lease",
        "title": "资源分配与人工调试",
        "steps": [
            {"title": "竞争同一资源", "description": "运行或人工调试申请同一独占实例。只读预览与可发送输入的会话分别处理。", "tables": ["test_runs", "debug_sessions"]},
            {"title": "事务领取租约", "description": "锁定资源、验证就绪状态，递增 fencing token。部分唯一索引阻止同时出现两条未释放租约。", "tables": ["execution_resources", "resource_leases"]},
            {"title": "执行并续租", "description": "Agent 每次命令和写回检查 holder 与 token。平台租约仍需遵循宿主 DeviceSession / DeviceGate。", "tables": ["resource_leases", "run_events"]},
            {"title": "确认后释放", "description": "超时只触发检查。旧进程未停止或隔离时，资源保持不可分配，避免两个执行者同时控制设备。", "tables": ["execution_resources", "resource_leases"]},
        ],
    },
    {
        "key": "report",
        "title": "结果与证据归档",
        "steps": [
            {"title": "固定运行来源", "description": "记录平台 run ID、组件 external_run_id、适配器版本和完整性信息。", "tables": ["test_runs", "run_components"]},
            {"title": "先校验文件", "description": "将截图、录像、原始曲线和日志写入私有文件存储，校验摘要；数据库保存键和元数据。", "tables": ["artifacts"]},
            {"title": "写入可查询摘要", "description": "保留用例尝试和指标窗口、单位、scope、样本数。缺失指标为 NULL，不补零。", "tables": ["case_results", "metric_summaries"]},
            {"title": "完成与对账", "description": "证据策略满足后完成运行。文件丢失标记 missing，后续对账处理，不修改原始测试结论。", "tables": ["test_runs", "artifacts", "run_events"]},
        ],
    },
    {
        "key": "gate",
        "title": "基线与规则试算",
        "steps": [
            {"title": "选择可比基线", "description": "匹配应用、环境、场景、资源档案、指标单位与统计窗口。不同端不能直接比较。", "tables": ["baselines", "resource_profiles", "metric_summaries"]},
            {"title": "固定规则版本", "description": "阈值、比较符、样本下限和 warn/fail 级别随版本保存。已有规则版本不可覆盖。", "tables": ["gate_policies"]},
            {"title": "保留原始判定", "description": "每个性能组件最多一个 original 判定；样本不足或基线不可比得到 not_tested。", "tables": ["gate_evaluations", "run_components"]},
            {"title": "追加试算", "description": "新规则生成 reanalysis 记录，原运行 outcome 和原始报告保持不变。", "tables": ["gate_evaluations", "test_runs", "artifacts"]},
        ],
    },
]

# sa 类型表达式 -> 文档用的 PG 类型名
_TYPE_MAP = {
    "postgresql.UUID(as_uuid=True)": "uuid",
    "sa.Text()": "text",
    "sa.DateTime(timezone=True)": "timestamptz",
    "sa.Integer()": "integer",
    "sa.BigInteger()": "bigint",
    "sa.Float(precision=53)": "float8",
    "postgresql.JSONB(astext_type=sa.Text())": "jsonb",
}

# --------------------------------------------------------------------------- #
# ast 抽取
# --------------------------------------------------------------------------- #
_COLUMN_RE = re.compile(r"^sa.(Column)$")


def _seg(node: ast.AST, src: str) -> str:
    return ast.get_source_segment(src, node) or ""


def _type_name(node: ast.expr, src: str) -> str:
    raw = _seg(node, src)
    return _TYPE_MAP.get(raw, raw)


def _text_arg(node: ast.expr | None) -> str | None:
    """sa.text("...") 的内层字符串。"""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "text":
        if node.args and isinstance(node.args[0], ast.Constant):
            return str(node.args[0].value)
    return None


def _const(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract(source: str) -> dict[str, object]:
    tree = ast.parse(source)
    tables: dict[str, dict[str, object]] = {}
    indexes: list[dict[str, object]] = []
    comments: dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "op"):
            continue
        if func.attr == "create_table" and node.args:
            name = _const(node.args[0])
            if not name:
                continue
            columns: list[dict[str, object]] = []
            constraints: list[dict[str, object]] = []
            for arg in node.args[1:] + [kw.value for kw in node.keywords]:
                if not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Attribute):
                    continue
                cls = arg.func.attr
                if cls == "Column":
                    col = _parse_column(arg, source)
                    columns.append(col)
                    if col.get("foreign_key"):
                        ref = col["foreign_key"]
                        constraints.append(
                            {
                                "kind": "foreign_key",
                                "name": f"{name}_{col['name']}_fkey",
                                "columns": [col["name"]],
                                "references": ref,
                            }
                        )
                    if col.get("unique"):
                        # projects.code unique=True：PG 隐式命名 <table>_<col>_key
                        constraints.append(
                            {"kind": "unique", "name": f"{name}_{col['name']}_key", "columns": [col["name"]]}
                        )
                elif cls == "CheckConstraint":
                    expr = _text_arg(arg.args[0]) if arg.args else None
                    constraints.append(
                        {"kind": "check", "name": _kwarg(arg, "name"), "expression": expr}
                    )
                elif cls == "UniqueConstraint":
                    cols = [c for c in (_const(a) for a in arg.args) if c]
                    constraints.append({"kind": "unique", "name": _kwarg(arg, "name"), "columns": cols})
                elif cls == "ForeignKeyConstraint":
                    cols = [c for c in (_const(a) for a in arg.args[0].elts) if c] if arg.args else []
                    ref_cols = []
                    if len(arg.args) > 1 and isinstance(arg.args[1], ast.Tuple):
                        ref_cols = [c for c in (_const(a) for a in arg.args[1].elts) if c]
                    ref_table = None
                    if arg.args and isinstance(arg.args[1], ast.Attribute):
                        ref_table = arg.args[1].attr
                    constraints.append(
                        {
                            "kind": "foreign_key",
                            "name": _kwarg(arg, "name"),
                            "columns": cols,
                            "references": {"table": ref_table, "columns": ref_cols},
                        }
                    )
            tables[name] = {
                "name": name,
                "title": TABLE_TITLES.get(name, name),
                "columns": columns,
                "constraints": constraints,
                "indexes": [],
            }
        elif func.attr == "create_index":
            idx_name = _const(node.args[0]) if node.args else None
            table = _const(node.args[1]) if len(node.args) > 1 else None
            cols: list[dict[str, object]] = []
            if len(node.args) > 2 and isinstance(node.args[2], (ast.List, ast.Tuple)):
                for elt in node.args[2].elts:
                    txt = _text_arg(elt)
                    cols.append({"name": txt if txt else _const(elt), "expression": txt is not None})
            where = _text_arg(_kwarg_node(node, "postgresql_where"))
            indexes.append(
                {
                    "name": idx_name,
                    "table": table,
                    "columns": cols,
                    "unique": _kwarg(node, "unique") is True,
                    "where": where,
                }
            )
        elif func.attr == "execute" and node.args:
            sql = _const(node.args[0])
            if not sql:
                continue
            if sql.lstrip().upper().startswith("COMMENT ON"):
                m = re.match(
                    r"COMMENT ON (TABLE|COLUMN) ([\w.]+) IS '((?:[^']|'')*)'", sql.strip()
                )
                if m:
                    comments[f"{m.group(1).lower()}:{m.group(2)}"] = m.group(3).replace("''", "'")
            else:
                m = re.match(
                    r"CREATE\s+(UNIQUE\s+)?INDEX\s+(\w+)\s+ON\s+(\w+)\s*\(([^)]*)\)(?:\s+WHERE\s+(.*))?",
                    sql.strip(),
                    re.S,
                )
                if m:
                    cols = []
                    for part in m.group(4).split(","):
                        part = part.strip()
                        if not part:
                            continue
                        desc = part.endswith(" DESC")
                        col = part.removesuffix(" DESC").removesuffix(" ASC").strip()
                        cols.append({"name": col, "expression": desc, "direction": "DESC" if desc else None})
                    indexes.append(
                        {
                            "name": m.group(2),
                            "table": m.group(3),
                            "columns": cols,
                            "unique": bool(m.group(1)),
                            "where": m.group(5).strip() if m.group(5) else None,
                        }
                    )

    # 挂接注释与索引
    for tname, table in tables.items():
        table["comment"] = comments.get(f"table:{tname}", "")
        for col in table["columns"]:  # type: ignore[index]
            col["description"] = comments.get(f"column:{tname}.{col['name']}", "")
    for idx in indexes:
        tname = idx.get("table")
        if tname in tables:
            tables[tname]["indexes"].append(idx)  # type: ignore[index]

    return {"tables": tables, "indexes": indexes}


def _parse_column(call: ast.Call, src: str) -> dict[str, object]:
    name = _const(call.args[0]) if call.args else None
    type_name = _type_name(call.args[1], src) if len(call.args) > 1 else None
    nullable = _kwarg(call, "nullable")
    primary = _kwarg(call, "primary_key") is True
    unique = _kwarg(call, "unique") is True
    default = _text_arg(_kwarg_node(call, "server_default"))
    if default is None:
        raw_default = _kwarg_node(call, "server_default")
        if isinstance(raw_default, ast.Constant):
            default = str(raw_default.value)
    # 列级内联外键（sa.ForeignKey("projects.id") 形式）：也抽成约束记录，
    # 避免 23 条指向 projects.id 的列级 FK 在文档里缺席。PG 会自动命名
    # <table>_<col>_fkey，这里按同样规则补名。
    fk_ref: dict[str, object] | None = None
    for extra in call.args[2:]:
        if (
            isinstance(extra, ast.Call)
            and isinstance(extra.func, ast.Attribute)
            and extra.func.attr == "ForeignKey"
            and extra.args
            and isinstance(extra.args[0], ast.Constant)
        ):
            target = str(extra.args[0].value)  # 形如 "projects.id"
            ref_table, _, ref_col = target.partition(".")
            fk_ref = {"table": ref_table, "columns": [ref_col] if ref_col else []}
            break
    return {
        "name": name,
        "type": type_name,
        "nullable": True if nullable is None else bool(nullable),
        "primary_key": primary,
        "unique": unique,
        "default": default,
        "foreign_key": fk_ref,
        "description": _kwarg(call, "comment") or "",
    }


def _kwarg_node(call: ast.Call, key: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == key:
            return kw.value
    return None


def _kwarg(call: ast.Call, key: str) -> object:
    node = _kwarg_node(call, key)
    if isinstance(node, ast.Constant):
        return node.value
    return None


def apply_migration_ast(tables: dict[str, dict[str, object]], source: str) -> None:
    """把一个 0002+ 迁移的 op.create_table / op.add_column 应用到字典草稿上。

    结构事实（列/主键/可空/默认）来自 create_table / add_column；
    op.execute 只解析 COMMENT ON TABLE|COLUMN —— 新表的注释只可能写在这里，
    跳过会让「每张表都有中文注释」的数据设计口径对新表失效（回填与序列仍不解析）。
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id == "op"):
            continue
        if func.attr == "execute" and node.args:
            sql = _const(node.args[0])
            if sql and sql.lstrip().upper().startswith("COMMENT ON"):
                m = re.match(
                    r"COMMENT ON (TABLE|COLUMN) ([\w.]+) IS '((?:[^']|'')*)'", sql.strip()
                )
                if m:
                    kind, target, text = m.group(1).lower(), m.group(2), m.group(3).replace("''", "'")
                    if kind == "table" and target in tables:
                        tables[target]["comment"] = text
                    elif kind == "column":
                        tname, _, colname = target.partition(".")
                        table = tables.get(tname)
                        if table:
                            for col in table["columns"]:  # type: ignore[index]
                                if col["name"] == colname:
                                    col["description"] = text
        elif func.attr == "add_column" and len(node.args) >= 2:
            table_name = _const(node.args[0])
            column = _parse_column(node.args[1], source) if isinstance(node.args[1], ast.Call) else None
            if table_name and column and table_name in tables:
                columns = tables[table_name].setdefault("columns", [])  # type: ignore[union-attr]
                if not any(c["name"] == column["name"] for c in columns):  # type: ignore[index]
                    columns.append(column)  # type: ignore[index]
        elif func.attr == "create_table" and node.args:
            name = _const(node.args[0])
            if not name or name in tables:
                continue
            columns = []
            constraints = []
            for arg in node.args[1:]:
                if not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Attribute):
                    continue
                if arg.func.attr == "Column":
                    columns.append(_parse_column(arg, source))
                elif arg.func.attr in ("ForeignKey", "CheckConstraint", "UniqueConstraint"):
                    parsed = _extract_constraint(arg, source) if "_extract_constraint" in globals() else None
                    if parsed:
                        constraints.append(parsed)
            tables[name] = {
                "name": name,
                "title": TABLE_TITLES.get(name, name),
                "columns": columns,
                "constraints": constraints,
                "indexes": [],
                "comment": "",
            }


def main() -> int:
    source = MIGRATION.read_text(encoding="utf-8")
    extracted = _extract(source)
    tables: dict[str, dict[str, object]] = extracted["tables"]  # type: ignore[assignment]
    indexes = extracted["indexes"]  # type: ignore[assignment]
    # 工单 22：把 0002+ 的追加迁移也走一遍（op.create_table / op.add_column），
    # 字典覆盖当前迁移 head；字段的可空/默认以迁移声明为准。
    for migration in sorted(MIGRATIONS_DIR.glob("[0-9]*.py")):
        if migration.name.startswith("0001"):
            continue
        apply_migration_ast(tables, migration.read_text(encoding="utf-8"))
    order = [t for g in TABLE_GROUPS.values() for t in g]
    order += [t for t in TABLE_GROUPS.get("任务运行", []) if t not in order]
    missing = [t for t in order if t not in tables]
    if missing:
        raise SystemExit(f"迁移中缺少表: {missing}")

    groups = [
        {
            "name": gname,
            "count": len(tlist),
            "tables": tlist,
        }
        for gname, tlist in TABLE_GROUPS.items()
    ]
    doc = {
        "version": 1,
        "generated_from": "server/alembic/versions/0001_initial.py",
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "table_count": len(tables),
        "index_count": len(extracted["indexes"]),  # type: ignore[index]
        "groups": groups,
        "lanes": LANES,
        "flows": FLOWS,
        "tables": [tables[t] for t in order],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    col_total = sum(len(t["columns"]) for t in tables.values())  # type: ignore[arg-type]
    ck_total = sum(1 for t in tables.values() for c in t["constraints"] if c["kind"] == "check")  # type: ignore[index]
    uq_total = sum(1 for t in tables.values() for c in t["constraints"] if c["kind"] == "unique")  # type: ignore[index]
    fk_total = sum(1 for t in tables.values() for c in t["constraints"] if c["kind"] == "foreign_key")  # type: ignore[index]
    print(
        f"[gen_schema_doc] 表={len(tables)} 列={col_total} 索引={len(extracted['indexes'])} "  # type: ignore[index]
        f"CHECK={ck_total} UNIQUE={uq_total} FK={fk_total} -> {OUT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
