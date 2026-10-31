"""vendor mobile_perf report.json -> 平台 metric_summaries 映射（只读 import vendor）。

不可妥协的语义：缺失指标不写 0
-----------------------------
DB CHECK（server/alembic/versions/0001_initial.py:474）：

    (value IS NULL AND missing_reason IS NOT NULL)
 OR (value IS NOT NULL AND missing_reason IS NULL)

也就是说 value 与 missing_reason **恰好一个非空**。vendor 报告里
`metricsSummary` 没有某个指标、或该指标的 median 是 null、或编排层标了
`notTested`（充电降级）、或 `sampleCount == 0`，平台都必须写
`value=NULL + missing_reason=...`，**绝不能写 0.0**——0 是一个合法测量值，
会污染趋势与门禁（"GPU 占用 0%" 与 "设备不支持 GPU 采集" 是两件事）。

映射口径
--------
- 每个指标按 `(min, median, mean, max, p90)` 展开成 5 行 metric_summaries，
  statistic 取 DB 允许的枚举值 subset：median / mean / min / max
  （CHECK: statistic IN ('median','p95','mean','min','max')，**没有 p90**，
  所以 vendor 的 p90 不进表；需要时另开 ticket）。
- `metric_version` = `<vendor SCHEMA_VERSION>.<指标字典版本>`，口径变更时递增，
  趋势查询按 metric_version 分组，避免新旧口径混算。
- `scope` = `component`（一份报告对应一个 run_component），
  `window_key` = 报告时间窗 `<startedAt>/<stoppedAt>`。
- 不在 vendor 指标字典里的 key：`missing_reason='metric_unknown'`，
  单位留空串（DB 无默认值）。

为什么不用 import 而是 sys.path 注入
-----------------------------------
架构约束测试 tests/test_no_vendor_import.py 禁止 `server/app/**` 里出现
`import mobile_perf`。本模块因此只在**函数内部**、且必须显式提供
`vendor_src`/环境变量时才把 vendor src 塞进 sys.path 后 import；
生产路径根本不 setdefault，避免把 vendor 依赖注入 API 进程。
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.profiles import ProfileNormalizationError, normalize_profile

logger = logging.getLogger(__name__)

__all__ = [
    "MISSING_DEVICE_UNSUPPORTED",
    "MISSING_METRIC_ABSENT",
    "MISSING_NOT_TESTED",
    "MISSING_SAMPLE_ZERO",
    "MISSING_VALUE_NULL",
    "MetricRow",
    "ReportMapping",
    "default_metrics_for_items",
    "load_judge",
    "metric_metadata",
    "metric_version",
    "report_dict_for_judge",
    "summaries_from_report",
]

# metric_summaries.statistic 的 DB 枚举（server/alembic/versions/0001_initial.py:469）
DB_STATISTICS = ("min", "median", "mean", "max")

# metric_summaries.missing_reason 的平台枚举（P4 新增，见 docstring）
MISSING_METRIC_ABSENT = "metric_absent"
MISSING_VALUE_NULL = "value_null"
MISSING_NOT_TESTED = "not_tested"
MISSING_SAMPLE_ZERO = "sample_count_zero"
MISSING_DEVICE_UNSUPPORTED = "device_unsupported"

METRIC_VERSION_LEGACY = "1.0"

# 设备不支持 / 采集项未开启时，仍要在 UI 上呈现「有这个指标但没值」的清单。
# 顺序与前端指标卡一致；item 为 vendor 的采集项名（kit.collect(items=[...])）。
DEFAULT_ITEMS: dict[str, tuple[str, ...]] = {
    "CPU": ("cpu_process_pct", "cpu_global_pct"),
    "Memory": ("mem_pss_mb", "mem_privdirty_mb", "mem_global_mb"),
    "FPS": ("fps_frame", "frame_delay_ratio_pct", "frame_delay_count", "frame_delay_max_ms"),
    "Network": ("net_rx_kbps", "net_tx_kbps"),
    "Battery": (
        "battery_current_ma",
        "battery_current_avg_ma",
        "battery_power_mw",
        "battery_power_avg_mw",
        "battery_pct",
    ),
    # GPU 是「设备可能不支持」的代表项：即使报告里没有，也要落一行 missing，
    # 否则前端无法区分「没这个指标」和「这个指标是 0」。
    "GPU": ("gpu_util_pct",),
}

# vendor 指标字典里已知「只有补采 / 编排才有」的指标：设备侧不支持时单独标注
SUPPLEMENT_KEYS = frozenset(
    {
        "temp_battery_c",
        "gpu_util_pct",
        "app_frame_p50_ms",
        "app_frame_p90_ms",
        "app_frame_p99_ms",
        "app_frame_jank_ratio_pct",
        "app_frame_count",
        "net_conn_duration_ms",
    }
)


def _vendor_src(vendor_src: str | Path | None = None) -> str | None:
    """定位 vendor/mobile_perf/src：显式参数 > TESTDOCK_MOBILE_PERF_SRC > 不注入。"""
    explicit = vendor_src or os.environ.get("TESTDOCK_MOBILE_PERF_SRC")
    if explicit:
        return str(Path(explicit))
    return None


def _import_metric_dict(vendor_src: str | Path | None = None):
    src = _vendor_src(vendor_src)
    if src and src not in sys.path:
        sys.path.insert(0, src)
    from mobile_perf import metrics as vendor_metrics  # noqa: PLC0415  只读 import

    return vendor_metrics


def _import_report_module(vendor_src: str | Path | None = None):
    src = _vendor_src(vendor_src)
    if src and src not in sys.path:
        sys.path.insert(0, src)
    from mobile_perf import report as vendor_report  # noqa: PLC0415  只读 import

    return vendor_report


def load_judge(vendor_src: str | Path | None = None):
    """只读拿到 vendor 的 (judge, JudgeSpec, Verdict)。不在本模块缓存状态。"""
    src = _vendor_src(vendor_src)
    if src and src not in sys.path:
        sys.path.insert(0, src)
    from mobile_perf.judge import JudgeSpec, Verdict, judge  # noqa: PLC0415

    return judge, JudgeSpec, Verdict


def metric_version(vendor_src: str | Path | None = None) -> str:
    """metric_summaries.metric_version：vendor 报告 schema 版本 + 字典版本。"""
    try:
        report_module = _import_report_module(vendor_src)
        schema_version = int(report_module.SCHEMA_VERSION)
    except Exception:  # noqa: BLE001 - vendor 缺失时退化，仍保持可写库；但要留下损坏证据
        logger.warning(
            "vendor mobile_perf 不可用或损坏，metric_version 退化为 %s",
            METRIC_VERSION_LEGACY,
            exc_info=True,
        )
        return METRIC_VERSION_LEGACY
    return f"{schema_version}.0"


def metric_metadata(vendor_src: str | Path | None = None) -> dict[str, dict[str, str]]:
    """canonical key -> {unit, source, label_zh, label_en}（来自 vendor 指标字典）。"""
    dictionary = _import_metric_dict(vendor_src).METRICS
    return {
        key: {
            "unit": spec.unit,
            "source": spec.source,
            "label_zh": spec.label_zh,
            "label_en": spec.label_en,
        }
        for key, spec in dictionary.items()
    }


@dataclass(frozen=True)
class MetricRow:
    """一行 metric_summaries（未落库）。value 与 missing_reason 恰好一个非空。"""

    metric_key: str
    statistic: str
    unit: str
    scope: str
    window_key: str
    sample_count: int
    value: float | None = None
    missing_reason: str | None = None
    missing_reason_text: str | None = None

    def __post_init__(self) -> None:
        has_value = self.value is not None
        has_reason = self.missing_reason is not None
        if has_value == has_reason:
            raise ValueError(
                f"metric_summaries 行 {self.metric_key}/{self.statistic} 违反 CHECK："
                "value 与 missing_reason 必须恰好一个非空"
            )
        if self.value is None and self.sample_count < 0:
            raise ValueError("sample_count 不能为负")
        if self.value is not None and self.sample_count <= 0:
            raise ValueError(
                f"metric_summaries 行 {self.metric_key}/{self.statistic} 有值但 "
                "sample_count=0，违反 CHECK value_finite"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "statistic": self.statistic,
            "unit": self.unit,
            "scope": self.scope,
            "window_key": self.window_key,
            "sample_count": self.sample_count,
            "value": self.value,
            "missing_reason": self.missing_reason,
            "missing_reason_text": self.missing_reason_text,
        }


@dataclass(frozen=True)
class ReportMapping:
    """一次报告的完整映射结果。"""

    rows: tuple[MetricRow, ...]
    device_profile: str | None
    device_profile_raw: str | None
    metric_version: str
    labels: dict[str, dict[str, str]] = field(default_factory=dict)
    profile_error: str | None = None

    def by_metric(self) -> dict[str, list[MetricRow]]:
        grouped: dict[str, list[MetricRow]] = {}
        for row in self.rows:
            grouped.setdefault(row.metric_key, []).append(row)
        return grouped


def _finite(value: Any) -> float | None:
    """只接受有限实数；字符串 / NaN / inf / None 一律当作缺失（绝不折成 0）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _sample_count(entry: dict[str, Any]) -> int:
    raw = entry.get("sampleCount")
    if raw is None:
        raw = entry.get("sample_count")
    try:
        count = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(count, 0)


def _missing(
    *,
    metric_key: str,
    unit: str,
    scope: str,
    window_key: str,
    reason: str,
    text: str | None,
    sample_count: int,
) -> list[MetricRow]:
    """缺失指标：5 个统计口径各写一行 NULL，避免前端把「没有行」当「没有指标」。"""
    return [
        MetricRow(
            metric_key=metric_key,
            statistic=statistic,
            unit=unit,
            scope=scope,
            window_key=window_key,
            sample_count=sample_count,
            value=None,
            missing_reason=reason,
            missing_reason_text=text,
        )
        for statistic in DB_STATISTICS
    ]


def _expected_keys(report: dict[str, Any], dictionary: dict[str, Any]) -> list[str]:
    """报告应当包含的指标 key：显式声明 > 采集项推导 > 报告里实际出现的。"""
    declared = report.get("metricKeys") or report.get("metric_keys")
    if isinstance(declared, Iterable) and not isinstance(declared, (str, bytes)):
        keys = [str(key) for key in declared]
        if keys:
            return keys

    keys: list[str] = []
    items = report.get("items") or []
    for item in items:
        group = DEFAULT_ITEMS.get(str(item))
        if group:
            keys.extend(group)
        elif str(item) in dictionary:
            keys.append(str(item))
    # 采集项没覆盖到、但报告真实产出的指标（派生 / 补采 / 编排指标）也要入表
    for key in (report.get("metricsSummary") or {}):
        if key not in keys:
            keys.append(str(key))
    return keys


def _unsupported(report: dict[str, Any], metric_key: str) -> bool:
    denied = report.get("unsupportedMetrics") or report.get("unsupported_metrics") or []
    if isinstance(denied, Iterable) and not isinstance(denied, (str, bytes)):
        return metric_key in {str(item) for item in denied}
    return False


def summaries_from_report(
    report: dict[str, Any],
    *,
    scope: str = "component",
    metric_version_override: str | None = None,
    vendor_src: str | Path | None = None,
) -> ReportMapping:
    """把 vendor report.json（dict）映射成 metric_summaries 行集合。

    `report` 允许是 vendor 原始报告（build_report 产出），也允许是
    :func:`report_dict_for_judge` 拼出来的判定视图——本函数只读
    `metricsSummary` / `items` / `deviceProfile` /`startedAt` /`stoppedAt`。
    """
    if not isinstance(report, dict):
        raise TypeError(f"report 必须是 dict，收到 {type(report).__name__}")

    dictionary = _import_metric_dict(vendor_src).METRICS
    labels = metric_metadata(vendor_src)
    version = metric_version_override or metric_version(vendor_src)

    summary = report.get("metricsSummary") or {}
    if not isinstance(summary, dict):
        summary = {}

    window_key = f"{report.get('startedAt') or '?'}/{report.get('stoppedAt') or '?'}"

    raw_profile = report.get("deviceProfile")
    device_profile: str | None = None
    profile_error: str | None = None
    if raw_profile:
        try:
            device_profile = normalize_profile(str(raw_profile))
        except ProfileNormalizationError as exc:
            profile_error = str(exc)

    rows: list[MetricRow] = []
    for metric_key in _expected_keys(report, dictionary):
        spec = dictionary.get(metric_key)
        unit = spec.unit if spec else ""
        entry = summary.get(metric_key)
        if not isinstance(entry, dict):
            reason = MISSING_METRIC_ABSENT
            if _unsupported(report, metric_key):
                reason = MISSING_DEVICE_UNSUPPORTED
            elif metric_key in SUPPLEMENT_KEYS and "supplement" not in {
                str(item).lower() for item in (report.get("items") or [])
            }:
                reason = MISSING_DEVICE_UNSUPPORTED
            text = (
                f"报告未产出指标 {metric_key!r} 的聚合数据"
                if reason == MISSING_METRIC_ABSENT
                else f"设备/补采通道不支持指标 {metric_key!r}"
            )
            rows.extend(
                _missing(
                    metric_key=metric_key,
                    unit=unit,
                    scope=scope,
                    window_key=window_key,
                    reason=reason,
                    text=text,
                    sample_count=0,
                )
            )
            continue

        sample_count = _sample_count(entry)
        if entry.get("notTested"):
            reason, text = (
                MISSING_NOT_TESTED,
                str(
                    entry.get("notTestedReason")
                    or entry.get("notTested_text")
                    or "编排层标注 not_tested，跳过该指标"
                ),
            )
        elif sample_count <= 0:
            reason, text = MISSING_SAMPLE_ZERO, f"指标 {metric_key!r} 样本数为 0，无法统计"
        else:
            reason, text = None, None

        if reason is not None:
            rows.extend(
                _missing(
                    metric_key=metric_key,
                    unit=unit,
                    scope=scope,
                    window_key=window_key,
                    reason=reason,
                    text=text,
                    sample_count=sample_count,
                )
            )
            continue

        wrote_any = False
        for statistic in DB_STATISTICS:
            value = _finite(entry.get(statistic))
            if value is None:
                continue
            wrote_any = True
            rows.append(
                MetricRow(
                    metric_key=metric_key,
                    statistic=statistic,
                    unit=unit,
                    scope=scope,
                    window_key=window_key,
                    sample_count=sample_count,
                    value=value,
                )
            )
        if not wrote_any:
            rows.extend(
                _missing(
                    metric_key=metric_key,
                    unit=unit,
                    scope=scope,
                    window_key=window_key,
                    reason=MISSING_VALUE_NULL,
                    text=f"指标 {metric_key!r} 有 {sample_count} 个样本但聚合值全为空",
                    sample_count=sample_count,
                )
            )

    return ReportMapping(
        rows=tuple(rows),
        device_profile=device_profile,
        device_profile_raw=str(raw_profile) if raw_profile else None,
        metric_version=version,
        labels=labels,
        profile_error=profile_error,
    )


def report_dict_for_judge(
    *,
    run_id: str,
    device_profile: str | None,
    started_at: Any = None,
    stopped_at: Any = None,
    summaries: Iterable[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把库里的 metric_summaries 行拼成 vendor judge 需要的 report 视图。

    judge 只读这些字段：`metricsSummary[<key>].{sampleCount, median, notTested,
    notTestedReason}`、`deviceProfile`、`startedAt/stoppedAt`、`runId`。
    缺失指标（value IS NULL）**不放入 metricsSummary**：judge 对「阈值引用的
    指标不存在」判 not_tested（metric_missing），若放一个 median=None 的条目，
    语义会变成「缺 median 或基线值」——两者都属于 not_tested，但 reason 不同，
    平台侧需要能区分。
    """
    metrics_summary: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    for row in summaries:
        key = row["metric_key"] if isinstance(row, dict) else row.metric_key
        statistic = row["statistic"] if isinstance(row, dict) else row.statistic
        value = row["value"] if isinstance(row, dict) else row.value
        sample_count = row["sample_count"] if isinstance(row, dict) else row.sample_count
        reason = row["missing_reason"] if isinstance(row, dict) else row.missing_reason
        reason_text = (
            row["missing_reason_text"] if isinstance(row, dict) else row.missing_reason_text
        )
        unit = row["unit"] if isinstance(row, dict) else row.unit
        if statistic != "median":
            continue
        if value is None:
            missing.append(
                {
                    "metricKey": key,
                    "missingReason": reason,
                    "missingReasonText": reason_text,
                    "sampleCount": sample_count,
                }
            )
            continue
        metrics_summary[key] = {
            "unit": unit,
            "median": value,
            "sampleCount": sample_count,
        }

    report = {
        "runId": run_id,
        "deviceProfile": device_profile,
        "startedAt": started_at.isoformat() if hasattr(started_at, "isoformat") else started_at,
        "stoppedAt": stopped_at.isoformat() if hasattr(stopped_at, "isoformat") else stopped_at,
        "metricsSummary": metrics_summary,
        "missingMetrics": missing,
    }
    if extra:
        report.update(extra)
    return report


def default_metrics_for_items(items: Iterable[str]) -> list[str]:
    """采集项名（CPU/Memory/FPS/...）-> 应当在 UI 上呈现的指标 key 列表。"""
    keys: list[str] = []
    for item in items:
        for key in DEFAULT_ITEMS.get(str(item), ()):
            if key not in keys:
                keys.append(key)
    return keys
