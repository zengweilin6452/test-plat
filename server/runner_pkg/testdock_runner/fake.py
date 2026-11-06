"""fake runner：无真机也能走完整生命周期（TESTDOCK_FAKE_RUNNER=1）。

为什么需要它
------------
P3 的验收里"真实跑一次失败用例拿到失败截图"必须有真机，但 CI/本地集成测试
没有真机。fake runner 走**同一条**代码路径：同样的 stage 事件、同样的
artifacts_dir 布局（junit.xml + evidence/<16hex>/{failure-frame.png,ui-tree.xml,
meta.json} + run-manifest.jsonl）、同样的 complete/fail 上报与退出码。
唯一被替换的是"adb + pytest"这一段。

所以集成测试验证的是真正的产物登记链路（API 侧 sha256、artifacts 行、
outcome 判定、WS 帧），而不是 mock 出来的假数据。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .artifacts import EVIDENCE_DIR, JUNIT_XML, RUN_MANIFEST

#: 1x1 PNG（真实 PNG 头 + IDAT，确保 API 侧能按魔数识别成 screenshot）
_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000b4944415478da63f8ffff3f0005fe02fea736d0e4"
    "0000000049454e44ae426082"
)

UI_TREE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.example.xinghe">
    <node index="0" text="首页" resource-id="com.example.xinghe:id/title"
          class="android.widget.TextView" bounds="[48,120][540,180]" />
    <node index="1" text="进入详情" resource-id="com.example.xinghe:id/enter"
          class="android.widget.Button" bounds="[48,240][540,320]" />
  </node>
</hierarchy>
"""


@dataclass
class FakeCase:
    key: str
    outcome: str = "passed"
    duration_s: float = 0.01
    message: str = ""


def _junit_xml(cases: list[FakeCase], suite_name: str = "testdock.fake") -> str:
    failures = sum(1 for c in cases if c.outcome == "failed")
    errors = sum(1 for c in cases if c.outcome == "errored")
    skipped = sum(1 for c in cases if c.outcome == "skipped")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<testsuites>',
        '  <testsuite name="%s" tests="%d" failures="%d" errors="%d" skipped="%d">'
        % (escape(suite_name), len(cases), failures, errors, skipped),
    ]
    for case in cases:
        classname, _, name = case.key.partition("::")
        lines.append(
            '    <testcase classname="%s" name="%s" time="%.3f">'
            % (escape(classname), escape(name or case.key), case.duration_s)
        )
        if case.outcome in ("failed", "errored"):
            tag = "failure" if case.outcome == "failed" else "error"
            lines.append('      <%s message="%s" />' % (tag, escape(case.message or 'assertion failed')))
        elif case.outcome == "skipped":
            lines.append("      <skipped />")
        lines.append("    </testcase>")
    lines.append("  </testsuite>")
    lines.append("</testsuites>")
    return "\n".join(lines) + "\n"


def write_evidence(artifacts_dir: Path, *, serial: str, case_key: str) -> dict[str, Any]:
    """写一条证据（布局与 vendor collector 完全一致）。"""
    root = Path(artifacts_dir)
    evidence_id = hashlib.sha256(("%s|%s" % (serial, case_key)).encode("utf-8")).hexdigest()[:16]
    target = root / EVIDENCE_DIR / evidence_id
    target.mkdir(parents=True, exist_ok=True)
    frame = target / "failure-frame.png"
    frame.write_bytes(_PNG_1X1)
    ui_tree = target / "ui-tree.xml"
    ui_tree.write_text(UI_TREE_XML, encoding="utf-8")
    meta = target / "meta.json"
    entry = {
        "evidence_id": evidence_id,
        "created_at": datetime.now(UTC).isoformat(),
        "device_serial": serial,
        "app_package": "com.example.xinghe",
        "failure_type": "assertion",
        "frame_source": "fake",
        "case_key": case_key,
        "artifacts": ["failure-frame.png", "ui-tree.xml"],
        "not_captured": [],
    }
    meta.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def run_fake_job(
    *,
    artifacts_dir: Path,
    serial: str,
    outcome: str = "passed",
    cases: int = 2,
    fail_at: int = 0,
) -> dict[str, Any]:
    """产出一整套产物并返回摘要（供 __main__ 上报 complete）。"""
    root = Path(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    fake_cases: list[FakeCase] = []
    for index in range(max(1, cases)):
        case_outcome = "failed" if (fail_at and index == (fail_at - 1)) else "passed"
        fake_cases.append(
            FakeCase(
                key="tests.test_ui_flow::test_case_%d" % (index + 1),
                outcome=case_outcome,
                message="expected <首页> but found <错误页>" if case_outcome == "failed" else "",
            )
        )
    if outcome == "failed" and not any(c.outcome == "failed" for c in fake_cases):
        fake_cases[-1].outcome = "failed"
        fake_cases[-1].message = "expected <首页> but found <错误页>"

    junit_path = root / JUNIT_XML
    junit_path.write_text(_junit_xml(fake_cases), encoding="utf-8")

    manifest_path = root / RUN_MANIFEST
    failures = [c for c in fake_cases if c.outcome in ("failed", "errored")]
    with manifest_path.open("a", encoding="utf-8") as handle:
        for case in failures:
            entry = write_evidence(root, serial=serial, case_key=case.key)
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()

    return {
        "junit": {
            "tests": len(fake_cases),
            "failed": len(failures),
            "skipped": sum(1 for c in fake_cases if c.outcome == "skipped"),
        },
        "cases": [
            {
                "case_key": c.key,
                "outcome": c.outcome,
                "duration_ms": int(c.duration_s * 1000),
                "error_summary": c.message or None,
            }
            for c in fake_cases
        ],
    }


__all__ = ["FakeCase", "UI_TREE_XML", "run_fake_job", "write_evidence"]
