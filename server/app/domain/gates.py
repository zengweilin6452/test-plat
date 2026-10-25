"""三态门禁：判定逻辑只调 vendor judge，平台侧只负责组装与归一。

铁律（三条不可妥协语义之二）
----------------------------
1. **三态不压二态**：verdict 有 passed / failed / not_tested 三态。
   not_tested 不是「失败」，也不是「通过」；它必须带 reason_code 说明为什么
   没测出来（样本不足 / 跨档案 / 指标缺失 / 策略缺失 / 运行未完成）。
2. **阈值逻辑不重写**：所有比较运算都发生在
   vendor/mobile_perf/src/mobile_perf/judge.py 的 `judge()` 里。
   本模块只做三件事：从 gate_policies.rules 构造 JudgeSpec、把
   metric_summaries 行拼成 judge 认得的 report 视图、把 vendor 的
   Verdict 映射成平台 reason_code / reason_text。
3. **original 不可变**：original 行每组件唯一（DB 部分唯一索引 gate_one_original），
   改阈值只能新增 mode='reanalysis' 行，绝不 UPDATE original。

reason_code 平台枚举
--------------------
profile_mismatch / sample_count_below_minimum / metric_missing /
device_degraded / gate_policy_missing / run_incomplete

vendor 的中文原文一律放 reason_text（`gate_evaluations` 没有 reason_text 列，
它落在 checks['reason_text'] 与 API 的 reasonText 字段里），不丢信息。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..integrations.mobile_perf import report_dict_for_judge
from .profiles import ProfileNormalizationError, normalize_profile

__all__ = [
    "DEFAULT_MIN_SAMPLES",
    "REASON_CODES",
    "REASON_DEVICE_DEGRADED",
    "REASON_GATE_POLICY_MISSING",
    "REASON_METRIC_MISSING",
    "REASON_PROFILE_MISMATCH",
    "REASON_RUN_INCOMPLETE",
    "REASON_SAMPLE_BELOW_MIN",
    "REASON_TEXT_FIELD",
    "GateOutcome",
    "classify_reason",
    "evaluation_fingerprint",
    "evaluation_hash",
    "gate_outcome",
    "build_report_view",
    "judge_spec",
    "policy_rules_to_thresholds",
    "rules_fingerprint",
    "snapshot_from_rows",
]

# vendor 的默认最小样本数（vendor/mobile_perf/src/mobile_perf/judge.py）
DEFAULT_MIN_SAMPLES = 10

REASON_PROFILE_MISMATCH = "profile_mismatch"
REASON_SAMPLE_BELOW_MIN = "sample_count_below_minimum"
REASON_METRIC_MISSING = "metric_missing"
REASON_DEVICE_DEGRADED = "device_degraded"
REASON_GATE_POLICY_MISSING = "gate_policy_missing"
REASON_RUN_INCOMPLETE = "run_incomplete"

REASON_CODES = (
    REASON_PROFILE_MISMATCH,
    REASON_SAMPLE_BELOW_MIN,
    REASON_METRIC_MISSING,
    REASON_DEVICE_DEGRADED,
    REASON_GATE_POLICY_MISSING,
    REASON_RUN_INCOMPLETE,
)

# gate_evaluations 没有 reason_text 列；vendor 原文随 checks 落库
REASON_TEXT_FIELD = "reason_text"

_OPS = frozenset({"lt", "le", "gt", "ge"})
_LEVELS = frozenset({"fail", "warn"})


class GateError(ValueError):
    """门禁输入非法（策略规则畸形、基线快照不可用等）。"""


@dataclass(frozen=True)
class GateOutcome:
    """一次判定的结果（对应一行 gate_evaluations）。"""

    verdict: str
    reason_code: str | None
    reason_text: str | None
    checks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def as_checks_payload(self) -> list[dict[str, Any]]:
        """落库到 gate_evaluations.checks 的 jsonb 数组。"""
        payload: list[dict[str, Any]] = [dict(check) for check in self.checks]
        if self.reason_text and not any(REASON_TEXT_FIELD in c for c in payload):
            payload.append({REASON_TEXT_FIELD: self.reason_text})
        return payload


def _to_float(value: Any) -> float:
    if isinstance(value, bool):
        raise GateError(f"阈值必须是数字，收到 bool: {value!r}")
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise GateError(f"阈值必须是数字，收到 {value!r}") from exc
    raise GateError(f"阈值必须是数字，收到 {type(value).__name__}")


def policy_rules_to_thresholds(rules: Any) -> dict[str, tuple[str, float, str]]:
    """gate_policies.rules -> vendor JudgeSpec.thresholds。

    支持两种写法（都归一到同一个 dict，vendor 侧格式不变）：

    1. 对象：`{"mem_pss_mb": {"op": "lt", "threshold": 240, "level": "fail"}}`
    2. 数组（api-design.md 的 thresholdsAtRun 口径）：
       `[{"metric_key": "mem_pss_mb", "op": "lt", "threshold": 240, "level": "fail"}]`
    3. 三元组兼容：`{"mem_pss_mb": ["lt", 240, "fail"]}`

    rules 也可能是整份策略对象（含 thresholds/min_samples 等键），
    一并接受，便于 gate_policies.rules 直接存策略对象。
    """
    if rules is None:
        return {}
    if isinstance(rules, list):
        return _thresholds_from_list(rules)
    if not isinstance(rules, Mapping):
        raise GateError(f"gate_policies.rules 必须是对象或数组，收到 {type(rules).__name__}")

    if "thresholds" in rules and isinstance(rules["thresholds"], (list, Mapping)):
        return _thresholds_from_list(rules["thresholds"])

    thresholds: dict[str, tuple[str, float, str]] = {}
    for key, raw in rules.items():
        if key in {"min_samples", "minSamples", "name", "description", "version"}:
            continue
        thresholds[str(key)] = _threshold_entry(str(key), raw)
    return thresholds


def _thresholds_from_list(items: Any) -> dict[str, tuple[str, float, str]]:
    if isinstance(items, Mapping):
        return {str(k): _threshold_entry(str(k), v) for k, v in items.items()}
    thresholds: dict[str, tuple[str, float, str]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise GateError(f"阈值项必须是对象，收到 {type(item).__name__}")
        key = item.get("metric_key") or item.get("metricKey") or item.get("metric")
        if not key:
            raise GateError(f"阈值项缺少 metric_key: {item!r}")
        thresholds[str(key)] = _threshold_entry(
            str(key),
            {
                "op": item.get("op"),
                "threshold": item.get("threshold", item.get("value")),
                "level": item.get("level", "fail"),
            },
        )
    return thresholds


def _threshold_entry(metric_key: str, raw: Any) -> tuple[str, float, str]:
    if isinstance(raw, Mapping):
        op = raw.get("op")
        threshold = raw.get("threshold", raw.get("value"))
        level = raw.get("level", "fail")
    elif isinstance(raw, (list, tuple)) and len(raw) == 3:
        op, threshold, level = raw
    else:
        raise GateError(f"指标 {metric_key!r} 的阈值格式不支持: {raw!r}")
    op_text = str(op or "").lower()
    level_text = str(level or "").lower()
    if op_text not in _OPS:
        raise GateError(f"指标 {metric_key!r} 的比较符只支持 lt/le/gt/ge，收到 {op!r}")
    if level_text not in _LEVELS:
        raise GateError(f"指标 {metric_key!r} 的级别只支持 fail/warn，收到 {level!r}")
    return (op_text, _to_float(threshold), level_text)


def _min_samples(policy_rules: Any) -> int | None:
    if not isinstance(policy_rules, Mapping):
        return None
    raw = policy_rules.get("min_samples", policy_rules.get("minSamples"))
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise GateError(f"min_samples 必须是整数，收到 {raw!r}") from exc
    if value < 1:
        raise GateError(f"min_samples 必须 >= 1，收到 {value}")
    return value


def _normalized_or_none(profile: str | None) -> str | None:
    """规范化设备档案；无法规范化时返回 None（交由调用方按不可比处理）。"""
    if profile is None:
        return None
    try:
        return normalize_profile(profile)
    except ProfileNormalizationError:
        return None


def judge_spec(
    *,
    baseline_name: str,
    policy_rules: Any,
    baseline_profile: str | None,
    baseline_metrics: Mapping[str, Any],
):
    """用 gate_policies 的 rules + 基线行构造 vendor JudgeSpec（不重写阈值逻辑）。"""
    from ..integrations.mobile_perf import load_judge

    _judge, JudgeSpec, _Verdict = load_judge()
    thresholds = policy_rules_to_thresholds(policy_rules)
    return JudgeSpec(
        baseline=baseline_name,
        thresholds=thresholds,
        min_samples=_min_samples(policy_rules),
        # 喂给 vendor 的是**规范化后**的档案：vendor 只做字符串相等，
        # 直接传原始字符串会把 'Android 13|1080*2400' 判成跨档案。
        baseline_profile=_normalized_or_none(baseline_profile),
        baseline_data=dict(baseline_metrics),
    )


def snapshot_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """metric_summaries 行（median）-> vendor 的 baseline_data 形态。

    `{"mem_pss_mb": {"value": 180.0, "sourceRunId": "...", "profile": "..."}}`
    只有 value 非空（真的测到了）的指标才进 baseline_data；缺失指标不进，
    judge 会因为「阈值引用的指标在基线里不存在」判 not_tested。
    """
    snapshot: dict[str, dict[str, Any]] = {}
    for row in rows:
        statistic = row.get("statistic")
        if statistic not in (None, "median"):
            continue
        value = row.get("value")
        if value is None:
            continue
        key = str(row["metric_key"])
        snapshot[key] = {
            "value": float(value),
            "sourceRunId": row.get("source_run_id") or row.get("component_id"),
            "sampleCount": row.get("sample_count"),
            "unit": row.get("unit"),
            "profile": row.get("profile"),
        }
    return snapshot


def _report_metrics(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    summary = report.get("metricsSummary") or {}
    return summary if isinstance(summary, Mapping) else {}


def classify_reason(verdict_text: str | None, report: Mapping[str, Any]) -> str:
    """把 vendor Verdict.reason 归一成平台 reason_code。

    vendor 只给中文原文，平台需要稳定枚举；这里按「先看数据、再看原文」的
    顺序判定，避免把中文当 API 契约。
    """
    metrics = _report_metrics(report)
    text = verdict_text or ""

    if "metricsSummary" not in report or not metrics:
        return REASON_METRIC_MISSING
    if "样本" in text or "sampleCount" in text:
        return REASON_SAMPLE_BELOW_MIN

    for entry in metrics.values():
        if not isinstance(entry, Mapping):
            continue
        if entry.get("notTested"):
            return REASON_DEVICE_DEGRADED
        if entry.get("median") is None:
            return REASON_METRIC_MISSING
        sample = entry.get("sampleCount")
        if sample is not None and int(sample) < DEFAULT_MIN_SAMPLES:
            return REASON_SAMPLE_BELOW_MIN

    if "profile" in text or "档案" in text:
        return REASON_PROFILE_MISMATCH
    if "基线" in text:
        return REASON_METRIC_MISSING
    if "median" in text:
        return REASON_METRIC_MISSING
    return REASON_METRIC_MISSING


def gate_outcome(
    *,
    report: Mapping[str, Any],
    spec,
    run_complete: bool = True,
    policy_rules: Any = None,
    run_profile: str | None = None,
    baseline_profile: str | None = None,
    baseline_data: Mapping[str, Any] | None = None,
) -> GateOutcome:
    """执行一次三态判定。

    平台侧前置检查（这些情况 vendor 表达不了，或不应当在 vendor 里表达）：

    - 策略没有任何阈值 -> not_tested + gate_policy_missing（不是「通过」）；
    - 运行未完成 -> not_tested + run_incomplete（半截数据不参与判定）；
    - 档案不可比 -> not_tested + profile_mismatch。vendor 只做字符串相等，
      平台先用 normalize_profile 规范化再比（同一台设备的脏写法不该判跨档案）。
      这里**不把档案改写后喂给 vendor**，避免掩盖跨档案事实；预检命中直接短路。

    其余一切判定都交给 vendor `judge()`。
    """
    from ..integrations.mobile_perf import load_judge

    judge, _JudgeSpec, _Verdict = load_judge()

    rules = policy_rules if policy_rules is not None else {}
    thresholds = policy_rules_to_thresholds(rules)
    if not thresholds:
        return GateOutcome(
            verdict="not_tested",
            reason_code=REASON_GATE_POLICY_MISSING,
            reason_text="门禁策略没有任何阈值规则，无法判定",
        )

    if not run_complete:
        return GateOutcome(
            verdict="not_tested",
            reason_code=REASON_RUN_INCOMPLETE,
            reason_text="运行尚未完成，不参与门禁判定",
        )

    if baseline_profile is None:
        return GateOutcome(
            verdict="not_tested",
            reason_code=REASON_PROFILE_MISMATCH,
            reason_text="基线没有设备档案，无法确认可比性",
        )

    try:
        comparable = normalize_profile(baseline_profile) == normalize_profile(run_profile)
    except ProfileNormalizationError as exc:
        return GateOutcome(
            verdict="not_tested",
            reason_code=REASON_PROFILE_MISMATCH,
            reason_text=f"设备档案无法规范化，无法确认可比性: {exc}",
        )
    if not comparable:
        return GateOutcome(
            verdict="not_tested",
            reason_code=REASON_PROFILE_MISMATCH,
            reason_text=(
                f"本次运行档案 {normalize_profile(run_profile)} 与基线档案 "
                f"{normalize_profile(baseline_profile)} 不一致，跨档案不可比"
            ),
        )

    if not baseline_data:
        return GateOutcome(
            verdict="not_tested",
            reason_code=REASON_METRIC_MISSING,
            reason_text="基线没有任何可用指标值（全部缺失）",
        )

    # 喂给 vendor 的报告里 deviceProfile 也换成规范化写法（其余字段原样），
    # 平台自己保留原始 report 用于 reason 归一。
    fed = dict(report)
    fed_profile = _normalized_or_none(run_profile)
    if fed_profile is not None:
        fed["deviceProfile"] = fed_profile

    verdict = judge(fed, spec)
    verdict_text = getattr(verdict, "verdict", None)
    reason = getattr(verdict, "reason", None)
    checks = list(getattr(verdict, "checks", ()) or ())
    warnings = list(getattr(verdict, "warnings", ()) or ())
    if verdict_text == "not_tested":
        return GateOutcome(
            verdict="not_tested",
            reason_code=classify_reason(reason, report),
            reason_text=reason,
            checks=checks,
            warnings=warnings,
        )
    # vendor 把「编排层标注 notTested」的指标降级成 warning 后仍可能给 passed。
    # 平台口径：关键指标根本没测，结论必须是 not_tested + device_degraded，
    # 否则「设备降级」会被压成绿色通过（三态不压二态）。
    degraded = [
        item
        for item in warnings
        if isinstance(item, Mapping) and item.get("notTested")
    ]
    if verdict_text == "passed" and degraded:
        detail = "; ".join(
            f"{item.get('metricKey')}（{item.get('reason')}）" for item in degraded
        )
        return GateOutcome(
            verdict="not_tested",
            reason_code=REASON_DEVICE_DEGRADED,
            reason_text=f"设备降级，关键指标未完成采集: {detail}",
            checks=checks,
            warnings=warnings,
        )
    return GateOutcome(
        verdict=verdict_text or "not_tested",
        reason_code=None,
        reason_text=None,
        checks=checks,
        warnings=warnings,
    )


def rules_fingerprint(rules: Any) -> str:
    """策略规则的稳定指纹（改阈值必然变化，用于证明「阈值真的变了」）。"""
    normalized = json.dumps(rules, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def evaluation_fingerprint(
    *,
    mode: str,
    policy_id: Any,
    policy_version: Any,
    rules: Any,
    baseline_id: Any,
    baseline_name: Any,
    baseline_version: Any,
    baseline_profile: str | None,
    verdict: str,
    reason_code: str | None,
    checks: Iterable[Mapping[str, Any]],
) -> str:
    """一次判定的内容指纹：original 行冻结后该指纹不得变化。"""
    payload = {
        "mode": mode,
        "policy": {"id": str(policy_id), "version": policy_version},
        "rules": rules,
        "rules_sha256": rules_fingerprint(rules),
        "baseline": {
            "id": str(baseline_id) if baseline_id else None,
            "name": baseline_name,
            "version": baseline_version,
            "profile": baseline_profile,
        },
        "verdict": verdict,
        "reason_code": reason_code,
        "checks": [dict(check) for check in checks],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


# evaluation_hash 是本模块对外的别名，API 与测试都用这个名字
evaluation_hash = evaluation_fingerprint


def build_report_view(
    *,
    run_id: str,
    device_profile: str | None,
    started_at: Any,
    stopped_at: Any,
    summary_rows: Iterable[Mapping[str, Any]],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """metric_summaries 行 -> vendor judge 认得的 report 视图（薄封装）。"""
    return report_dict_for_judge(
        run_id=run_id,
        device_profile=device_profile,
        started_at=started_at,
        stopped_at=stopped_at,
        summaries=summary_rows,
        extra=dict(extra) if extra else None,
    )
