"""报告在线视图：把平台报告快照渲染成自包含 HTML（GET /runs/{id}/report/view）。

设计纪律：
- 纯渲染、无数据库依赖：输入是 routers/runs._report_view 的快照 dict，
  可以在没有数据库的单元测试里直接构造调用。
- 自包含：内联样式、零脚本、零外链。视图端点会带 CSP sandbox 头，
  脚本本就不允许执行，页面也不能依赖任何外部资源。
- 如实展示：缺失字段显示破折号或「未记录」，不用 0 冒充样本、
  不用设备 serial 冒充档案（AC-REP-03、AC-REP-04 的同一口径）。
- 所有插值一律 html.escape：logical_key 等字段可能来自导入通道的
  任意文件名，绝不能当 HTML 输出。
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any

DASH = "—"

_VERDICT_LABELS = {
    "passed": "通过",
    "failed": "未通过",
    "not_tested": "未产生门禁结论",
}

_STATE_LABELS = {
    "queued": "排队中",
    "dispatching": "派发中",
    "running": "执行中",
    "finalizing": "归档中",
    "completed": "已完成",
    "errored": "执行出错",
    "cancelled": "已取消",
}

_MODULE_LABELS = {
    "ui": "UI",
    "performance": "性能",
    "joint": "联动",
}

_MODE_LABELS = {
    "live": "真跑产物（live）",
    "imported": "导入补录（imported）",
}

_AVAILABILITY_LABELS = {
    "available": "可用",
    "missing": "缺失",
    "expired": "已过期",
}

_UNAVAILABLE_REASON_LABELS = {
    "file_missing": "文件已不在产物目录",
    "retention_expired": "已超过保留期",
    "storage_unresolvable": "存储路径无效",
}


def esc(value: Any) -> str:
    """HTML 转义：None/空串原样返回空（由调用方决定破折号）。"""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def text_or_dash(value: Any) -> str:
    """展示文本：空白/缺失一律破折号，绝不写成空串或 0。"""
    if value is None:
        return DASH
    text = str(value).strip()
    return html.escape(text, quote=True) if text else DASH


def fmt_bytes(value: Any) -> str:
    """字节数展示；未知/非法返回破折号（与前端 formatBytes 同口径）。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return DASH
    size = int(value)
    if size < 0:
        return DASH
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def fmt_number(value: Any) -> str:
    """指标数值：整数不带小数点，浮点保留必要位数；缺失返回破折号。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DASH
    if isinstance(value, int):
        return str(value)
    return f"{value:g}"


def verdict_label(verdict: Any) -> str:
    if not verdict:
        return "后端尚未给出结论"
    return _VERDICT_LABELS.get(str(verdict), str(verdict))


def metric_row(key: str, entry: Mapping[str, Any] | None) -> str:
    """单条指标行：median 缺失时给原因（notTestedReason 优先于 missingReason）。"""
    if not isinstance(entry, Mapping):
        entry = {}
    median = entry.get("median")
    if isinstance(median, (int, float)) and not isinstance(median, bool):
        cell = fmt_number(median)
        unit = str(entry.get("unit") or "").strip()
        if unit:
            cell += " " + esc(unit)
    else:
        cell = DASH
    reason = str(entry.get("notTestedReason") or entry.get("missingReason") or "").strip()
    return (
        "<tr>"
        f"<td class=\"mono\">{text_or_dash(entry.get('labelZh') or key)}</td>"
        f"<td class=\"mono\">{cell}</td>"
        f"<td class=\"mono\">{fmt_number(entry.get('sampleCount'))}</td>"
        f"<td class=\"muted\">{esc(reason) if reason else DASH}</td>"
        "</tr>"
    )


def junit_text(junit: Mapping[str, Any] | None) -> str:
    """junit 计数文本：未产出（present=false 或缺字段）显示破折号，不写 0。"""
    if not isinstance(junit, Mapping) or junit.get("present") is False:
        return DASH
    tests = junit.get("tests")
    failed = junit.get("failed")
    if failed is None:
        failed = (junit.get("failures") or 0) + (junit.get("errors") or 0)
    skipped = junit.get("skipped")
    if not isinstance(tests, (int, float)) or isinstance(tests, bool):
        return DASH
    parts = [f"共 {fmt_number(tests)} 个"]
    parts.append(f"失败 {fmt_number(failed) if failed is not None else DASH}")
    if skipped is not None:
        parts.append(f"跳过 {fmt_number(skipped)}")
    return esc(" · ".join(parts))


def suite_text(suite: Mapping[str, Any] | None) -> str:
    """套件版本：版本号 · source_ref · commit 前 12 位；缺失时如实说明。"""
    if not isinstance(suite, Mapping):
        return "未绑定套件版本"
    parts: list[str] = []
    version = suite.get("version")
    parts.append(f"v{version}" if isinstance(version, int) else "版本号未记录")
    for key in ("source_ref", "source_commit"):
        value = str(suite.get(key) or "").strip()
        if key == "source_commit" and value:
            value = value[:12]
        if value:
            parts.append(value)
    return esc(" · ".join(parts))


def code_copy_text(code_copy: Any) -> str:
    """固定代码副本摘要；缺失时如实说明，不拿当前目录现算值冒充。"""
    if not isinstance(code_copy, Mapping):
        return "未记录固定代码副本"
    tree = str(code_copy.get("tree_sha256") or "").strip()
    if not tree:
        return "副本摘要缺失"
    count = code_copy.get("file_count")
    label = tree[:12] if tree else DASH
    if isinstance(count, int):
        return esc(f"{label} · {count} 个文件")
    return esc(label)


def build_text(build: Mapping[str, Any] | None) -> str:
    if not isinstance(build, Mapping):
        return "未绑定构建"
    parts: list[str] = []
    version = str(build.get("version") or "").strip()
    if version:
        parts.append(f"v{version}")
    build_key = str(build.get("build_key") or "").strip()
    if build_key:
        parts.append(build_key)
    commit = str(build.get("source_commit") or "").strip()
    if commit:
        parts.append(commit[:12])
    return esc(" · ".join(parts)) if parts else "构建信息未记录"


def profile_text(profile: Any) -> str:
    """资源档案：档案名 · 指纹前 12 位；缺失时明确为未绑定。"""
    if not isinstance(profile, Mapping):
        return "未绑定资源档案"
    parts: list[str] = []
    name = str(profile.get("name") or profile.get("id") or "").strip()
    if name:
        parts.append(name)
    fingerprint = str(profile.get("fingerprint") or "").strip()
    if fingerprint:
        parts.append(fingerprint[:12])
    return esc(" · ".join(parts)) if parts else "档案信息未记录"


def evidence_rows(evidence: list[Mapping[str, Any]] | None) -> str:
    """证据链行。产物路径只展示 logical_key；view_url/download_url 由后端拼好才给。"""
    if not evidence:
        return (
            "<p class=\"muted\">该运行没有登记产物。</p>"
        )
    rows = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        availability = str(item.get("availability") or "")
        label = _AVAILABILITY_LABELS.get(availability, availability or DASH)
        reason_code = str(item.get("unavailable_reason") or "").strip()
        reason = _UNAVAILABLE_REASON_LABELS.get(reason_code, reason_code) if reason_code else ""
        rows.append(
            "<tr>"
            f"<td class=\"mono\">{text_or_dash(item.get('logical_key'))}</td>"
            f"<td>{text_or_dash(item.get('kind'))}</td>"
            f"<td>{esc(label)}</td>"
            f"<td class=\"muted\">{esc(reason) if reason else DASH}</td>"
            f"<td class=\"mono\">{fmt_bytes(item.get('byte_size'))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>产物</th><th>类型</th><th>可用性</th><th>说明</th><th>大小</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def gate_rows(gates: list[Mapping[str, Any]] | None) -> str:
    if not gates:
        return "<p class=\"muted\">没有门禁评估记录。</p>"
    rows = []
    for gate in gates:
        if not isinstance(gate, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td>{text_or_dash(gate.get('mode'))}</td>"
            f"<td>{esc(verdict_label(gate.get('verdict')))}</td>"
            f"<td class=\"mono\">{text_or_dash(gate.get('reason_code'))}</td>"
            f"<td class=\"muted\">{text_or_dash(gate.get('created_at'))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>模式</th><th>结论</th><th>原因码</th><th>评估时间</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def metric_rows(metrics: Mapping[str, Any] | None) -> str:
    if not metrics:
        return (
            "<p class=\"muted\">报告没有指标数据：该运行没有性能组件，"
            "或 vendor 未产出 metricsSummary。</p>"
        )
    rows = "".join(
        metric_row(key, value if isinstance(value, Mapping) else None)
        for key, value in metrics.items()
    )
    return (
        "<table>"
        "<thead><tr><th>指标</th><th>中位数</th><th>样本数</th><th>说明</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 40px 64px; font: 14px/1.6 "Segoe UI", "Microsoft YaHei", sans-serif;
       color: #1c2430; background: #f5f7fb; }
main { max-width: 960px; margin: 0 auto; }
.kicker { font-size: 12px; color: #6b7686; letter-spacing: .04em; margin: 0 0 6px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.meta { color: #6b7686; font-size: 12px; margin: 0 0 14px; }
.verdict { display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.verdict-passed { background: #e2f5ea; color: #177245; }
.verdict-failed { background: #fbe5e5; color: #b3261e; }
.verdict-not_tested { background: #edeff3; color: #5a6472; }
.verdict-none { background: #edeff3; color: #5a6472; }
section { background: #fff; border: 1px solid #e3e8ef; border-radius: 12px; padding: 18px 22px; margin-top: 16px; }
h2 { font-size: 14px; margin: 0 0 12px; color: #3c4658; }
dl { display: grid; grid-template-columns: 130px 1fr; gap: 6px 16px; margin: 0; }
dt { color: #6b7686; }
dd { margin: 0; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #edf0f5; }
th { color: #6b7686; font-weight: 600; font-size: 12px; }
.mono { font-family: Consolas, "Courier New", monospace; font-size: 12px; }
.muted { color: #8b94a3; }
footer { margin-top: 24px; color: #98a1af; font-size: 12px; text-align: center; }
"""


def render_platform_report_html(report: Mapping[str, Any]) -> str:
    """把 GET /runs/{id}/report 的快照渲染成自包含 HTML（在线查看的兜底页面）。

    与前端 ReportDrawer 同一信息结构（结论 / 追溯 / 指标汇总 / 门禁评估 /
    证据链），缺失字段同样如实显示破折号；页面不含脚本与外链，可在
    CSP sandbox 下完整呈现。
    """
    run_id = text_or_dash(report.get("runId"))
    name = text_or_dash(report.get("name"))
    platform = text_or_dash(report.get("platform"))
    module = str(report.get("module") or "").strip()
    module_label = _MODULE_LABELS.get(module, module or DASH)
    mode_value = str(report.get("mode") or "").strip()
    mode_label = _MODE_LABELS.get(mode_value, mode_value or DASH)
    verdict = report.get("verdict")
    verdict_class = str(verdict or "none")
    state = str(report.get("status") or "").strip()
    state_label = _STATE_LABELS.get(state, state)

    suite = report.get("suite") if isinstance(report.get("suite"), Mapping) else None
    current_names = (
        report.get("currentNames") if isinstance(report.get("currentNames"), Mapping) else None
    )

    metrics = report.get("metricsSummary")
    metrics = metrics if isinstance(metrics, Mapping) else None
    junit = report.get("junit") if isinstance(report.get("junit"), Mapping) else None
    gates = report.get("gateEvaluations")
    gates = gates if isinstance(gates, list) else None
    evidence = report.get("evidence")
    evidence = evidence if isinstance(evidence, list) else None

    duration = report.get("durationS")
    duration_text = (
        f"{fmt_number(duration)} 秒"
        if isinstance(duration, (int, float)) and not isinstance(duration, bool)
        else DASH
    )
    build_raw = report.get("build")
    build_value = build_text(build_raw if isinstance(build_raw, Mapping) else None)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>TestDock {esc(report.get('runId'))} 报告</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
  <header>
    <p class="kicker">TestDock 在线报告 · {esc(mode_label)}</p>
    <h1>{name}</h1>
    <p class="meta">{run_id} · {platform} · {esc(module_label)} · 状态 {esc(state_label)}</p>
    <span class="verdict verdict-{esc(verdict_class)}">{esc(verdict_label(verdict))}</span>
  </header>

  <section>
    <h2>结论</h2>
    <dl>
      <dt>门禁结论</dt><dd>{esc(verdict_label(verdict))}</dd>
      <dt>原因</dt><dd class="mono">{text_or_dash(report.get('reasonText') or report.get('reason'))}</dd>
      <dt>报告模式</dt><dd>{esc(mode_label)}</dd>
      <dt>用例（junit）</dt><dd>{junit_text(junit)}</dd>
      <dt>耗时</dt><dd>{esc(duration_text)}</dd>
      <dt>设备档案</dt><dd class="mono">{text_or_dash(report.get('deviceProfile'))}</dd>
      <dt>判定时间</dt><dd>{text_or_dash(report.get('evaluatedAt'))}</dd>
    </dl>
  </section>

  <section>
    <h2>追溯</h2>
    <dl>
      <dt>项目当前名称</dt><dd>{text_or_dash(current_names.get('project') if current_names else None)}</dd>
      <dt>应用当前名称</dt><dd>{text_or_dash(current_names.get('application') if current_names else None)}</dd>
      <dt>套件版本</dt><dd class="mono">{suite_text(suite)}</dd>
      <dt>固定副本</dt><dd class="mono">{code_copy_text(suite.get('code_copy') if suite else None)}</dd>
      <dt>构建</dt><dd class="mono">{build_value}</dd>
      <dt>资源档案</dt><dd class="mono">{profile_text(report.get('resourceProfile'))}</dd>
    </dl>
  </section>

  <section>
    <h2>指标汇总</h2>
    {metric_rows(metrics)}
  </section>

  <section>
    <h2>门禁评估</h2>
    {gate_rows(gates)}
  </section>

  <section>
    <h2>证据链</h2>
    {evidence_rows(evidence)}
    <p class="muted">证据文件请在平台的报告抽屉中下载；本页面为只读视图。</p>
  </section>

  <footer>由 TestDock 平台渲染 · 与 GET /api/v1/runs/{esc(report.get('runId'))}/report 为同一份快照</footer>
</main>
</body>
</html>
"""


__all__ = [
    "DASH",
    "code_copy_text",
    "evidence_rows",
    "esc",
    "fmt_bytes",
    "fmt_number",
    "gate_rows",
    "junit_text",
    "metric_rows",
    "render_platform_report_html",
    "suite_text",
    "text_or_dash",
    "verdict_label",
]
