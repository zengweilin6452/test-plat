"""「数据设计」页数据源（P6，api-design.md §2.8 GET /api/v1/schema）。

数据来源：构建期由 scripts/gen_schema_doc.py 从 0001_initial.py 的 ast 抽取
并落盘到 app/static_data/schema_doc.json（不 import 执行迁移）。运行期只读
该 JSON，不做任何数据库查询 —— 表结构是静态事实，没必要每次请求都算。
分组徽章计数在返回前按表清单重算一遍，保证与 tables 不漂移。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ..errors import ApiError

router = APIRouter(tags=["schema"])

#: 构建期产物位置（随包发布，运行期只读）。
_SCHEMA_DOC_PATH = Path(__file__).resolve().parent.parent / "static_data" / "schema_doc.json"


def _load_doc() -> dict[str, Any]:
    try:
        return json.loads(_SCHEMA_DOC_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ApiError(
            status_code=500,
            code="schema_doc_missing",
            message="schema_doc.json 缺失，请先运行 python scripts/gen_schema_doc.py",
        ) from exc


@router.get("/schema")
async def get_schema() -> dict[str, Any]:
    """返回 24 表字段/索引/约束 + 7 组徽章计数 + 4 泳道 + 4 写入流程。"""
    doc = _load_doc()
    # 徽章计数直接从分组常量推导（gen 时已校验每张表都在迁移里出现）
    groups = [
        {
            "name": g["name"],
            "count": len(g["tables"]),
            "tables": g["tables"],
        }
        for g in doc["groups"]
    ]
    return {
        "version": doc["version"],
        "table_count": doc["table_count"],
        "index_count": doc["index_count"],
        "source_sha256": doc["source_sha256"],
        "groups": groups,
        "lanes": doc["lanes"],
        "flows": doc["flows"],
        "tables": doc["tables"],
    }
