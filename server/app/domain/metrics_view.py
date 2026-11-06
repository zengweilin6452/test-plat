"""metric_summaries 行 -> API 视图的单一映射口径。

三个端点（/runs/{id}/metrics、/runs/{id}/analysis、baselines 预览）共用同一批
DB 列；这里集中两件事：

- **缺失语义**（缺失指标不写 0）：`supported` 的判定与 `missing_reason` /
  `missing_reason_text` 的透出口径，只在本文件定义一次。
- **列名 -> 视图键名**：`metric_key` 同时出口为 `key`（历史契约）。

各端点的响应字段集不同（有的带 id/component_id，有的带 median 别名），
因此提供两个显式视图函数而不是开关参数；新增端点请复用本文件，
不要再手抄映射。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def missing_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """supported + missing_reason + missing_reason_text（设备不支持的额外带 supported=false）。"""
    return {
        # 缺失指标这里是 None，前端显示「—」而不是 0
        "supported": row.get("missing_reason") != "device_unsupported",
        "missing_reason": row.get("missing_reason"),
        "missing_reason_text": row.get("missing_reason_text"),
    }


def metric_row_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """一行 metric_summaries -> 完整 API 视图（GET /runs/{id}/metrics 口径）。"""
    return {
        "id": row["id"],
        "component_id": row["component_id"],
        "key": row["metric_key"],
        "metric_key": row["metric_key"],
        "metric_version": row["metric_version"],
        "unit": row["unit"],
        "scope": row["scope"],
        "window_key": row["window_key"],
        "statistic": row["statistic"],
        "sample_count": row["sample_count"],
        "value": row["value"],
        **missing_fields(row),
    }


def median_metric_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """analysis 端点用：不含 id/component_id，`value` 另以 `median` 别名出口。"""
    view = metric_row_view(row)
    view.pop("id")
    view.pop("component_id")
    view["median"] = row["value"]
    return view
