"""性能能力接入（2026-11）的回归测试。

覆盖四条新链路：
1. 场景能力字段（start_mode / capture_har / net_* / frame_poll / page_marks）
   在平台 domain 与 runner perf_config 两端镜像校验；
2. runner 场景 -> vendor kit.collect kwargs 只透传已启用能力；
3. vendor 报告能力块（startup/pages/network/api）-> metric_summaries 期望 key
   推导与 p90 统计位；HAR 文件 -> artifacts.kind='har'；
4. joint 报告透传能力块（此前 metricsSummary/thresholds 之外的块全部丢失）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/runner_pkg"))

from app.domain import suite as suite_domain  # noqa: E402
from app.domain.artifacts import classify
from app.integrations.mobile_perf import summaries_from_report  # noqa: E402

from testdock_runner import perf_config  # noqa: E402


VENDOR_SRC = str(Path(__file__).resolve().parents[2] / "vendor" / "mobile_perf" / "src")


# ── 1. 两端镜像：能力字段校验 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "scenario",
    [
        {"duration_s": 60, "items": ["CPU"], "start_mode": "cold"},
        {"duration_s": 60, "items": ["CPU"], "start_mode": "warm"},
        {"duration_s": 60, "items": ["CPU"], "capture_har": True},
        {"duration_s": 60, "items": ["CPU"], "net_profile": "weak", "net_tier": "decrypt"},
        {"duration_s": 60, "items": ["CPU"], "net_profile": "custom",
         "net_overrides": {"latency_ms": 400, "down_kbps": 400, "up_kbps": 200, "loss_pct": 2}},
        {"duration_s": 60, "items": ["CPU"], "frame_poll": True,
         "page_marks": [{"page": "home", "at_s": 5}, {"page": "detail", "at_s": 20}]},
        {"duration_s": 60, "items": ["CPU"], "net_port": 8080},
    ],
)
def test_capability_fields_accepted_by_both_ends(scenario: dict):
    assert suite_domain.scenario_problems(scenario) == []
    assert perf_config.scenario_problems(scenario) == []


@pytest.mark.parametrize(
    "scenario",
    [
        {"duration_s": 60, "items": ["CPU"], "start_mode": "hot"},
        {"duration_s": 60, "items": ["CPU"], "capture_har": "yes"},
        {"duration_s": 60, "items": ["CPU"], "net_profile": "bogus"},
        {"duration_s": 60, "items": ["CPU"], "net_tier": "transparent"},
        {"duration_s": 60, "items": ["CPU"], "net_port": 0},
        {"duration_s": 60, "items": ["CPU"], "net_profile": "custom"},
        {"duration_s": 60, "items": ["CPU"], "net_profile": "custom",
         "net_overrides": {"latency_ms": 1, "down_kbps": 1, "up_kbps": 1, "loss_pct": 101}},
        {"duration_s": 60, "items": ["CPU"], "page_marks": [{"page": "", "at_s": 1}]},
        {"duration_s": 60, "items": ["CPU"], "page_marks": [{"page": "home", "at_s": -1}]},
        {"duration_s": 60, "items": ["CPU"], "unknown_field": 1},
        {"duration_s": 60, "items": ["CPU"], "net_mitmdump": "   "},
    ],
)
def test_capability_fields_rejected_by_both_ends(scenario: dict):
    assert suite_domain.scenario_problems(scenario), scenario
    assert perf_config.scenario_problems(scenario), scenario


# ── 2. 场景 -> vendor kwargs ─────────────────────────────────────────────


def test_collect_kwargs_only_carries_enabled_capabilities():
    kwargs = perf_config.collect_kwargs_from_scenario({"duration_s": 60, "items": ["CPU"]})
    assert kwargs == {}

    kwargs = perf_config.collect_kwargs_from_scenario({
        "duration_s": 60,
        "items": ["CPU"],
        "start_mode": "cold",
        "capture_har": True,
        "net_profile": "3g",
        "net_tier": "passthrough",
        "net_port": 8888,
        "frame_poll": True,
        "net_overrides": {"latency_ms": 1, "down_kbps": 2, "up_kbps": 3, "loss_pct": 4},
    })
    assert kwargs == {
        "start_mode": "cold",
        "capture_har": True,
        "net_profile": "3g",
        "net_tier": "passthrough",
        "net_port": 8888,
        "frame_poll": True,
        "net_overrides": {"latency_ms": 1.0, "down_kbps": 2.0, "up_kbps": 3.0, "loss_pct": 4.0},
    }


def test_page_marks_sorted_and_filtered():
    marks = perf_config.page_marks_from_scenario({
        "page_marks": [
            {"page": "detail", "at_s": 20},
            {"page": "home", "at_s": 5},
            {"page": "", "at_s": 9},  # 非法条目被校验层拒绝；这里防御性过滤
        ],
    })
    assert marks == [(5.0, "home"), (20.0, "detail")]


# ── 3. 报告映射：能力块推导期望 key + p90 ────────────────────────────────


def _report(blocks: dict) -> dict:
    return {
        "items": ["CPU", "Memory", "FPS"],
        "deviceProfile": "Android 13|1080*2400|Pixel 7 Pro",
        "startedAt": "2026-11-08T10:00:00+08:00",
        "stoppedAt": "2026-11-08T10:01:00+08:00",
        "metricsSummary": {"mem_pss_mb": {"unit": "MB", "median": 268.0, "p90": 300.0, "sampleCount": 12}},
        **blocks,
    }


def test_p90_statistic_is_mapped_not_dropped():
    mapping = summaries_from_report(_report({}), vendor_src=VENDOR_SRC)
    stats = {row.statistic: row.value for row in mapping.rows if row.metric_key == "mem_pss_mb"}
    assert stats.get("p90") == 300.0
    assert stats.get("median") == 268.0


def test_startup_block_generates_expected_key_with_missing_row():
    # vendor 的形态：启动编排失败时 metricsSummary[key] = {notTested: true, ...}
    report = _report({
        "startup": {"mode": "cold", "metricKey": "app_cold_start_ms", "status": "failed"},
        "metricsSummary": {"mem_pss_mb": {"unit": "MB", "median": 268.0, "p90": 300.0, "sampleCount": 12},
                           "app_cold_start_ms": {"notTested": True, "notTestedReason": "启动编排失败"}},
    })
    mapping = summaries_from_report(report, vendor_src=VENDOR_SRC)
    rows = [row for row in mapping.rows if row.metric_key == "app_cold_start_ms"]
    assert rows, "启动编排开启后即使 notTested 也要有「有指标没值」的行"
    assert {row.missing_reason for row in rows} == {"not_tested"}
    assert all("启动编排失败" in (row.missing_reason_text or "") for row in rows)

    # 块在、metricsSummary 里连条目都没有：也要落「有指标没值」行（metric_absent）
    mapping2 = summaries_from_report(
        _report({"startup": {"mode": "cold", "metricKey": "app_cold_start_ms", "status": "failed"}}),
        vendor_src=VENDOR_SRC,
    )
    rows2 = [row for row in mapping2.rows if row.metric_key == "app_cold_start_ms"]
    assert rows2 and {row.missing_reason for row in rows2} == {"metric_absent"}


def test_pages_and_network_blocks_generate_expected_keys():
    mapping = summaries_from_report(
        _report({
            "pages": {"status": "no_frames", "pages": []},
            "network": {"profile": "3g", "tier": "passthrough",
                        "har": {"status": "not_tested", "notTestedReason": "mitmdump 不可用"}},
        }),
        vendor_src=VENDOR_SRC,
    )
    by_key = {row.metric_key: row.missing_reason for row in mapping.rows}
    assert "page_load_ms" in by_key
    assert "net_conn_duration_ms" in by_key


def test_api_block_generates_interface_metric_keys():
    mapping = summaries_from_report(
        _report({"api": {"status": "not_tested", "notTestedReason": "App 不信任代理 CA"}}),
        vendor_src=VENDOR_SRC,
    )
    keys = {row.metric_key for row in mapping.rows}
    assert {"api_req_duration_ms", "api_req_count", "api_error_rate_pct", "api_payload_kb"} <= keys


def test_fps_group_includes_jank_derived_counts_as_absent_rows():
    mapping = summaries_from_report(_report({}), vendor_src=VENDOR_SRC)
    jank_rows = [row for row in mapping.rows if row.metric_key == "app_jank_light_count"]
    assert jank_rows, "选了 FPS 就该有卡顿分级的行（缺失也如实呈现）"
    assert {row.missing_reason for row in jank_rows} == {"metric_absent"}


# ── 4. HAR 产物分类 ──────────────────────────────────────────────────────


def test_har_file_classified_as_har_kind(tmp_path: Path):
    har = tmp_path / "network" / "app.har"
    har.parent.mkdir(parents=True)
    har.write_text("{}", encoding="utf-8")
    assert classify(har, "network/app.har") == "har"
    # 非 HAR 的 json 不受影响
    other = tmp_path / "report.json"
    other.write_text("{}", encoding="utf-8")
    assert classify(other, "report.json") == "report_json"


# ── 5. DB CHECK：p90 / har 入枚举（migration 0011）────────────────────────
# 这两条在 test_perf_gate_api.py 里跑（复用其 seed 夹具的真实外键链）。


# ── 6. joint 报告透传能力块 ──────────────────────────────────────────────


def test_joint_report_passes_through_capability_blocks(tmp_path: Path):
    from testdock_runner.joint_job import _write_joint_report
    from testdock_runner.ui_job import UiJobOptions

    options = UiJobOptions(run_id="run-x", serial="s", app_package="pkg", artifacts_dir=tmp_path)
    vendor_report = {
        "metricsSummary": {"fps_frame": {"unit": "fps", "median": 58.0, "p90": 60.0, "sampleCount": 9}},
        "thresholdsAtRun": {},
        "items": ["CPU", "Memory", "FPS"],
        "deviceProfile": "android-13",
        "startedAt": "2026-11-08T10:00:00+08:00",
        "stoppedAt": "2026-11-08T10:03:00+08:00",
        "startup": {"mode": "cold", "metricKey": "app_cold_start_ms", "ms": 812, "status": "ok"},
        "pages": {"pages": [{"page": "home", "status": "ok", "pageLoadMs": 640}]},
        "network": {"profile": "3g", "tier": "passthrough",
                    "har": {"status": "complete", "entries": 12, "path": "/x/app.har"}},
    }
    window = {"collect_started_at": "a", "collect_stopped_at": "b", "ui": {"started_at": "c", "ended_at": "d", "timeout_s": 600}}
    _write_joint_report(options, window, vendor_report, fake=False)

    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["startup"]["ms"] == 812
    assert payload["pages"]["pages"][0]["pageLoadMs"] == 640
    assert payload["network"]["har"]["status"] == "complete"
    assert payload["startedAt"] == "2026-11-08T10:00:00+08:00"
    # 映射层能从透传后的 joint 报告推导出启动/整页 key（端到端前提）
    mapping = summaries_from_report(payload, vendor_src=VENDOR_SRC)
    keys = {row.metric_key for row in mapping.rows}
    assert "app_cold_start_ms" in keys and "page_load_ms" in keys
