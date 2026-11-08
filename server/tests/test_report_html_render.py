"""report_html 渲染的纯单元测试（无数据库）：转义、缺失字段、如实展示。

在线报告页是把后端字段拼成 HTML 的最后一道闸：任何字段都可能来自导入通道的
任意文件名 / vendor 报告，进 HTML 前必须转义；缺失字段显示破折号，
不用 0 冒充样本（与前端 ReportDrawer 的硬约束同口径）。
"""

from __future__ import annotations

from app.domain import report_html as rh


def test_renders_minimal_report_without_faking():
    """只有 runId 的快照也能渲染：缺失字段给破折号/未记录，不抛异常不编造。"""
    html = rh.render_platform_report_html({"runId": "RUN-0001", "name": "任务"})
    assert "RUN-0001" in html
    assert "后端尚未给出结论" in html
    assert "未绑定套件版本" in html
    assert "未绑定构建" in html
    assert "未绑定资源档案" in html
    assert rh.DASH in html


def test_escapes_html_from_evidence_and_names():
    """logical_key / 名称里的 HTML 必须被转义，不允许出现可执行的 <script>。"""
    report = {
        "runId": "RUN-0042",
        "name": "<script>alert('x')</script>",
        "currentNames": {"application": "<img src=x onerror=alert(1)>", "project": "p"},
        "evidence": [
            {
                "id": "a1",
                "kind": "report_html",
                "logical_key": "\"><script>steal()</script>",
                "availability": "available",
                "byte_size": 2048,
            }
        ],
        "metricsSummary": {
            "fps": {"labelZh": "<b>帧率</b>", "median": 59.5, "unit": "fps", "sampleCount": 120}
        },
    }
    html = rh.render_platform_report_html(report)
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;帧率&lt;/b&gt;" in html


def test_junit_counts_never_fake_zero():
    """junit 未产出（present=false / 缺字段）显示破折号，不把没跑写成 0 个失败。"""
    assert rh.junit_text(None) == rh.DASH
    assert rh.junit_text({"present": False, "tests": 0}) == rh.DASH
    assert rh.junit_text({}) == rh.DASH
    assert "共 3 个" in rh.junit_text({"present": True, "tests": 3, "failed": 1, "skipped": 0})


def test_metric_missing_shows_reason_not_zero():
    """median 缺失时说明原因（notTestedReason 优先于 missingReason），不写 0。"""
    row = rh.metric_row("fps", {"notTestedReason": "整项未测", "missingReason": "单项缺失"})
    assert "整项未测" in row
    assert "missingReason" not in row
    row = rh.metric_row("fps", {"missingReason": "采集窗口缺一段"})
    assert "采集窗口缺一段" in row
    row = rh.metric_row("fps", {"median": 20, "unit": "%"})
    assert "20 %" in row


def test_evidence_and_gate_rows_render_states():
    html = rh.render_platform_report_html(
        {
            "runId": "RUN-0007",
            "name": "n",
            "verdict": "failed",
            "gateEvaluations": [{"mode": "ui", "verdict": "failed", "reason_code": "assert_failed"}],
            "evidence": [
                {
                    "id": "a1",
                    "kind": "log",
                    "logical_key": "evidence/run.log",
                    "availability": "expired",
                    "unavailable_reason": "retention_expired",
                }
            ],
        }
    )
    assert "已超过保留期" in html
    assert "assert_failed" in html
    assert "未通过" in html
    assert "verdict-failed" in html
