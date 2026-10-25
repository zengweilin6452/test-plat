"""三态门禁与 report 映射的纯逻辑测试（不需要数据库）。

这里验证三条不可妥协语义：
1. 三态不压二态：样本不足 / 跨档案是 not_tested，不是 failed；
2. 缺失指标不写 0：MetricRow 在 value 与 missing_reason 之间必须恰好有值；
3. 判定逻辑来自 vendor judge，平台只做组装。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.domain import gates
from app.integrations.mobile_perf import (
    MISSING_DEVICE_UNSUPPORTED,
    MISSING_METRIC_ABSENT,
    MetricRow,
    summaries_from_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = REPO_ROOT / "vendor" / "mobile_perf" / "src"

pytestmark = pytest.mark.skipif(
    not (VENDOR_SRC / "mobile_perf" / "judge.py").exists(),
    reason="需要 vendor/mobile_perf（只读依赖）",
)


@pytest.fixture(scope="module", autouse=True)
def _vendor_on_path():
    os.environ.setdefault("TESTDOCK_MOBILE_PERF_SRC", str(VENDOR_SRC))
    yield


def _report(**overrides):
    report = {
        "runId": "run-1",
        "deviceProfile": "android-13|1080x2400|pixel-7-pro",
        "startedAt": "2026-10-25T10:00:00",
        "stoppedAt": "2026-10-25T10:01:00",
        "items": ["CPU", "Memory", "FPS"],
        "metricsSummary": {
            "mem_pss_mb": {"unit": "MB", "median": 150.0, "sampleCount": 30},
            "cpu_process_pct": {"unit": "%", "median": 20.0, "sampleCount": 30},
            "fps_frame": {"unit": "fps", "median": 58.0, "sampleCount": 30},
        },
    }
    report.update(overrides)
    return report


def _rules(**overrides):
    rules = {
        "min_samples": 10,
        "thresholds": [
            {"metric_key": "mem_pss_mb", "op": "lt", "threshold": 240, "level": "fail"},
            {"metric_key": "cpu_process_pct", "op": "lt", "threshold": 35, "level": "warn"},
            {"metric_key": "fps_frame", "op": "ge", "threshold": 50, "level": "fail"},
        ],
    }
    rules.update(overrides)
    return rules


def _baseline(profile="android-13|1080x2400|pixel-7-pro", **overrides):
    data = {
        "mem_pss_mb": {"value": 180.0, "sourceRunId": "run-baseline"},
        "cpu_process_pct": {"value": 25.0, "sourceRunId": "run-baseline"},
        "fps_frame": {"value": 55.0, "sourceRunId": "run-baseline"},
    }
    data.update(overrides.pop("data", {}))
    return profile, data


def _judge(report, rules=None, profile=None, data=None, run_complete=True):
    rules = rules if rules is not None else _rules()
    # 默认：基线档案 = 本次运行档案，只测「档案一致」之外的判定
    bprofile, bdata = _baseline(profile or report.get("deviceProfile"), data=data or {})
    spec = gates.judge_spec(
        baseline_name="run:baseline",
        policy_rules=rules,
        baseline_profile=bprofile,
        baseline_metrics=bdata,
    )
    return gates.gate_outcome(
        report=report,
        spec=spec,
        run_complete=run_complete,
        policy_rules=rules,
        run_profile=report.get("deviceProfile"),
        baseline_profile=bprofile,
        baseline_data=bdata,
    )


# ---------------------------------------------------------------------------
# 样本不足 -> not_tested + sample_count_below_minimum（保留实际 sample_count）
# ---------------------------------------------------------------------------


def test_sample_below_minimum_is_not_tested_and_keeps_sample_count():
    report = _report(
        metricsSummary={
            "mem_pss_mb": {"unit": "MB", "median": 150.0, "sampleCount": 6},
            "cpu_process_pct": {"unit": "%", "median": 20.0, "sampleCount": 6},
            "fps_frame": {"unit": "fps", "median": 58.0, "sampleCount": 6},
        }
    )
    outcome = _judge(report)
    assert outcome.verdict == "not_tested"
    assert outcome.reason_code == gates.REASON_SAMPLE_BELOW_MIN
    # vendor 原文保留，不丢信息
    assert outcome.reason_text
    # 实际样本数留在 report 里，API 层从 metric_summaries 读 sample_count=6
    assert report["metricsSummary"]["mem_pss_mb"]["sampleCount"] == 6


def test_sample_count_six_is_not_zero_or_failed():
    """三态不压二态：样本不足既不是 passed 也不是 failed。"""
    report = _report(
        metricsSummary={"mem_pss_mb": {"unit": "MB", "median": 999.0, "sampleCount": 6}}
    )
    outcome = _judge(report)
    assert outcome.verdict == "not_tested"
    assert outcome.verdict != "failed"
    assert outcome.reason_code == gates.REASON_SAMPLE_BELOW_MIN


# ---------------------------------------------------------------------------
# 跨档案 -> not_tested + profile_mismatch
# ---------------------------------------------------------------------------


def test_cross_profile_is_not_tested_with_profile_mismatch():
    outcome = _judge(
        _report(deviceProfile="android-14|1080x2400|pixel-7-pro"),
        profile="android-13|1080x2400|pixel-7-pro",
    )
    assert outcome.verdict == "not_tested"
    assert outcome.reason_code == gates.REASON_PROFILE_MISMATCH
    assert "档案" in (outcome.reason_text or "")


def test_same_profile_written_differently_is_comparable():
    """同一台设备的脏写法不能判成跨档案。"""
    outcome = _judge(
        _report(deviceProfile="Android 13|1080*2400|Pixel 7 Pro"),
        profile="android-13|1080x2400|pixel-7-pro",
    )
    assert outcome.verdict == "passed", outcome


def test_missing_baseline_profile_is_profile_mismatch():
    report = _report()
    spec = gates.judge_spec(
        baseline_name="run:baseline",
        policy_rules=_rules(),
        baseline_profile=None,
        baseline_metrics=_baseline()[1],
    )
    outcome = gates.gate_outcome(
        report=report,
        spec=spec,
        policy_rules=_rules(),
        run_profile=report["deviceProfile"],
        baseline_profile=None,
        baseline_data=_baseline()[1],
    )
    assert outcome.verdict == "not_tested"
    assert outcome.reason_code == gates.REASON_PROFILE_MISMATCH


# ---------------------------------------------------------------------------
# 其它三态
# ---------------------------------------------------------------------------


def test_passing_run_passes_with_evidence_checks():
    outcome = _judge(_report())
    assert outcome.verdict == "passed"
    assert outcome.reason_code is None
    assert outcome.checks
    assert all("metricKey" in check for check in outcome.checks)


def test_fail_level_violation_fails():
    report = _report(
        metricsSummary={
            "mem_pss_mb": {"unit": "MB", "median": 300.0, "sampleCount": 30},
            "cpu_process_pct": {"unit": "%", "median": 20.0, "sampleCount": 30},
            "fps_frame": {"unit": "fps", "median": 58.0, "sampleCount": 30},
        }
    )
    outcome = _judge(report)
    assert outcome.verdict == "failed"


def test_warn_level_violation_still_passes_but_records_warning():
    report = _report(
        metricsSummary={
            "mem_pss_mb": {"unit": "MB", "median": 150.0, "sampleCount": 30},
            "cpu_process_pct": {"unit": "%", "median": 90.0, "sampleCount": 30},
            "fps_frame": {"unit": "fps", "median": 58.0, "sampleCount": 30},
        }
    )
    outcome = _judge(report)
    assert outcome.verdict == "passed"
    assert outcome.warnings


def test_empty_policy_is_gate_policy_missing():
    outcome = _judge(_report(), rules={})
    assert outcome.verdict == "not_tested"
    assert outcome.reason_code == gates.REASON_GATE_POLICY_MISSING


def test_incomplete_run_is_run_incomplete():
    outcome = _judge(_report(), run_complete=False)
    assert outcome.verdict == "not_tested"
    assert outcome.reason_code == gates.REASON_RUN_INCOMPLETE


def test_missing_metric_in_report_is_metric_missing():
    report = _report(metricsSummary={"cpu_process_pct": {"unit": "%", "median": 20.0, "sampleCount": 30}})
    outcome = _judge(report)
    assert outcome.verdict == "not_tested"
    assert outcome.reason_code == gates.REASON_METRIC_MISSING


def test_not_tested_metric_entry_is_device_degraded():
    report = _report(
        metricsSummary={
            "mem_pss_mb": {"unit": "MB", "median": 150.0, "sampleCount": 30},
            "cpu_process_pct": {"unit": "%", "median": 20.0, "sampleCount": 30},
            "fps_frame": {
                "unit": "fps",
                "median": 58.0,
                "sampleCount": 30,
                "notTested": True,
                "notTestedReason": "充电中降频",
            },
        }
    )
    outcome = _judge(report)
    assert outcome.verdict == "not_tested"
    assert outcome.reason_code == gates.REASON_DEVICE_DEGRADED


def test_all_reason_codes_are_in_platform_enum():
    assert set(gates.REASON_CODES) == {
        "profile_mismatch",
        "sample_count_below_minimum",
        "metric_missing",
        "device_degraded",
        "gate_policy_missing",
        "run_incomplete",
    }


def test_reason_text_is_carried_into_checks_payload():
    """gate_evaluations 没有 reason_text 列：vendor 原文必须随 checks 落库。"""
    report = _report(
        metricsSummary={
            "mem_pss_mb": {"unit": "MB", "median": 150.0, "sampleCount": 6},
            "cpu_process_pct": {"unit": "%", "median": 20.0, "sampleCount": 6},
            "fps_frame": {"unit": "fps", "median": 58.0, "sampleCount": 6},
        }
    )
    outcome = _judge(report)
    payload = outcome.as_checks_payload()
    assert any(gates.REASON_TEXT_FIELD in item for item in payload)


# ---------------------------------------------------------------------------
# 阈值解析
# ---------------------------------------------------------------------------


def test_policy_rules_accept_object_list_and_tuple_forms():
    obj = gates.policy_rules_to_thresholds(
        {"mem_pss_mb": {"op": "lt", "threshold": 240, "level": "fail"}, "min_samples": 10}
    )
    lst = gates.policy_rules_to_thresholds(
        {"thresholds": [{"metric_key": "mem_pss_mb", "op": "lt", "threshold": 240, "level": "fail"}]}
    )
    tup = gates.policy_rules_to_thresholds({"mem_pss_mb": ["lt", 240, "fail"]})
    assert obj == lst == tup == {"mem_pss_mb": ("lt", 240.0, "fail")}


@pytest.mark.parametrize(
    "bad",
    [
        {"mem_pss_mb": {"op": "ne", "threshold": 1, "level": "fail"}},
        {"mem_pss_mb": {"op": "lt", "threshold": 1, "level": "blocker"}},
        {"mem_pss_mb": {"op": "lt", "threshold": "abc", "level": "fail"}},
        {"mem_pss_mb": "240"},
        {"thresholds": [{"op": "lt", "threshold": 1, "level": "fail"}]},
        {"min_samples": 0, "mem_pss_mb": ["lt", 1, "fail"]},
    ],
)
def test_policy_rules_reject_bad_input(bad):
    with pytest.raises(gates.GateError):
        gates.policy_rules_to_thresholds(bad)
        gates.judge_spec(
            baseline_name="b", policy_rules=bad, baseline_profile=None, baseline_metrics={}
        )


# ---------------------------------------------------------------------------
# 缺失指标不写 0
# ---------------------------------------------------------------------------


def test_metric_row_rejects_zero_for_missing_metric():
    """missing_reason 已给时再给 value 必须是错误（而不是把 0 写进去）。"""
    with pytest.raises(ValueError):
        MetricRow(
            metric_key="gpu_util_pct",
            statistic="median",
            unit="%",
            scope="component",
            window_key="a/b",
            sample_count=0,
            value=0.0,
            missing_reason=MISSING_DEVICE_UNSUPPORTED,
        )
    with pytest.raises(ValueError):
        MetricRow(
            metric_key="gpu_util_pct",
            statistic="median",
            unit="%",
            scope="component",
            window_key="a/b",
            sample_count=0,
        )


def test_metric_row_rejects_value_with_zero_samples():
    with pytest.raises(ValueError):
        MetricRow(
            metric_key="mem_pss_mb",
            statistic="median",
            unit="MB",
            scope="component",
            window_key="a/b",
            sample_count=0,
            value=12.0,
        )


def test_summaries_missing_metric_has_null_value_and_reason():
    report = _report(items=["CPU", "Memory", "FPS", "GPU"])
    mapping = summaries_from_report(report, vendor_src=VENDOR_SRC)
    gpu_rows = [row for row in mapping.rows if row.metric_key == "gpu_util_pct"]
    assert gpu_rows, "GPU 不支持时也必须有行，否则前端无法显示「—」"
    for row in gpu_rows:
        assert row.value is None
        assert row.missing_reason is not None


def test_summaries_never_write_zero_for_absent_metric():
    report = _report(items=["CPU", "Memory", "FPS"])
    mapping = summaries_from_report(report, vendor_src=VENDOR_SRC)
    for row in mapping.rows:
        if row.metric_key not in report["metricsSummary"]:
            assert row.value is None, f"{row.metric_key} 缺失却被写成了 {row.value}"
            assert row.missing_reason == MISSING_METRIC_ABSENT


def test_summaries_expand_present_metric_across_statistics():
    mapping = summaries_from_report(_report(), vendor_src=VENDOR_SRC)
    stats = {row.statistic for row in mapping.rows if row.metric_key == "mem_pss_mb"}
    assert stats == {"median"}
    assert all(row.value == 150.0 for row in mapping.rows if row.metric_key == "mem_pss_mb")


def test_summaries_device_profile_is_normalized():
    mapping = summaries_from_report(
        _report(deviceProfile="Android 13|1080*2400|Pixel 7 Pro"), vendor_src=VENDOR_SRC
    )
    assert mapping.device_profile == "android-13|1080x2400|pixel-7-pro"
    assert mapping.profile_error is None


def test_summaries_unparseable_profile_is_reported_not_guessed():
    mapping = summaries_from_report(_report(deviceProfile="whatever"), vendor_src=VENDOR_SRC)
    assert mapping.device_profile is None
    assert mapping.profile_error


def test_report_view_keeps_missing_metrics_out_of_summary():
    mapping = summaries_from_report(_report(items=["CPU", "Memory", "FPS", "GPU"]), vendor_src=VENDOR_SRC)
    view = gates.build_report_view(
        run_id="run-1",
        device_profile=mapping.device_profile,
        started_at="2026-10-25T10:00:00",
        stopped_at="2026-10-25T10:01:00",
        summary_rows=[row.as_dict() for row in mapping.rows],
    )
    assert "gpu_util_pct" not in view["metricsSummary"]
    assert any(item["metricKey"] == "gpu_util_pct" for item in view["missingMetrics"])
    assert view["metricsSummary"]["mem_pss_mb"]["median"] == 150.0
