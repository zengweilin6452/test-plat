"""产物收集：junit.xml + artifacts/evidence/** + run-manifest.jsonl（§10.2）。

证据目录布局由 vendor mobile_auto/evidence/collector.py 决定，不是我们发明的：
    <artifacts_dir>/evidence/<16hex>/failure-frame.png
    <artifacts_dir>/evidence/<16hex>/ui-tree.xml
    <artifacts_dir>/evidence/<16hex>/meta.json
    <artifacts_dir>/run-manifest.jsonl      （每行一条证据索引）
    <artifacts_dir>/junit.xml               （pytest --junit-xml 输出）

runner 只负责**保证这些文件存在且完整**（flush/close），登记与 sha256 由 API
侧 domain/artifacts.py 统一做 —— 因为 API 才是权威：runner 上报的哈希不可信，
而且 import 通道（用既有产物目录）没有 runner 参与，必须走同一套登记逻辑。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JUNIT_XML = "junit.xml"
RUN_MANIFEST = "run-manifest.jsonl"
EVIDENCE_DIR = "evidence"
REPORT_JSON = "report.json"


@dataclass
class JUnitSummary:
    """junit.xml 的用例计数。present=False 表示没有产物（既非通过也非失败）。"""

    present: bool = False
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    parse_error: str | None = None
    cases: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return self.failures + self.errors

    def outcome(self) -> str | None:
        """只有真正跑过才有结论：无用例 -> None（API 侧落 not_tested）。"""
        if not self.present or self.tests <= 0:
            return None
        return "failed" if self.failed > 0 else "passed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "tests": self.tests,
            "failures": self.failures,
            "errors": self.errors,
            "skipped": self.skipped,
            "failed": self.failed,
            "parse_error": self.parse_error,
        }


def read_junit(path: Path) -> JUnitSummary:
    """解析 junit.xml（容忍 <testsuites> 与裸 <testsuite> 两种根）。"""
    path = Path(path)
    if not path.exists():
        return JUnitSummary(present=False)
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return JUnitSummary(present=True, parse_error=str(exc))
    summary = JUnitSummary(present=True)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            try:
                setattr(summary, key, getattr(summary, key) + int(suite.get(key) or 0))
            except ValueError:
                pass
        for case in suite.iter("testcase"):
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            if failure is not None:
                outcome = "failed"
            elif error is not None:
                outcome = "errored"
            elif skipped is not None:
                outcome = "skipped"
            else:
                outcome = "passed"
            detail = failure if failure is not None else error
            summary.cases.append(
                {
                    "case_key": "%s::%s" % (case.get("classname") or "", case.get("name") or ""),
                    "outcome": outcome,
                    "duration_ms": _duration_ms(case.get("time")),
                    "error_summary": (
                        (detail.get("message") or (detail.text or ""))[:500]
                        if detail is not None
                        else None
                    ),
                }
            )
    return summary


def _duration_ms(raw: str | None) -> int | None:
    try:
        return int(float(raw) * 1000) if raw is not None else None
    except ValueError:
        return None


def read_manifest(path: Path) -> list[dict[str, Any]]:
    """读 run-manifest.jsonl（坏行跳过，不能因为一行坏了丢全部证据索引）。"""
    path = Path(path)
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def collect_layout(artifacts_dir: Path) -> dict[str, Any]:
    """给 API 的产物清单（相对路径 + 大小），API 侧再自己算 sha256。"""
    root = Path(artifacts_dir)
    files: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                try:
                    files.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "size": path.stat().st_size,
                        }
                    )
                except OSError:
                    continue
    evidence_dirs = sorted(
        {p.parent.name for p in (root / EVIDENCE_DIR).glob("*/meta.json")} if root.is_dir() else []
    )
    return {
        "files": files,
        "evidence_ids": evidence_dirs,
        "has_junit": (root / JUNIT_XML).exists(),
        "has_manifest": (root / RUN_MANIFEST).exists(),
    }


def write_report_json(artifacts_dir: Path, payload: dict[str, Any]) -> Path:
    """写 report.json（平台侧 report 端点也会重新计算，这里只是给人和工具看）。"""
    path = Path(artifacts_dir) / REPORT_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


__all__ = [
    "EVIDENCE_DIR",
    "JUNIT_XML",
    "JUnitSummary",
    "REPORT_JSON",
    "RUN_MANIFEST",
    "collect_layout",
    "read_junit",
    "read_manifest",
    "write_report_json",
]
