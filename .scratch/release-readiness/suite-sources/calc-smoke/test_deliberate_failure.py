"""收口验收用：故意断言失败用例。

目的：验证失败用例在平台上保留失败结论与证据产物（截图 / UI 树 / junit 断言消息），
不是测试对象的功能缺陷。断言消息写明「预期内的故意失败」，便于在报告里辨认。
"""

from __future__ import annotations


def test_deliberate_assertion_failure_for_evidence():
    """永远失败：进入报告的失败证据链路（预期内，非产品缺陷）。"""
    assert False, "预期内的故意失败：用于验证失败结论与证据产物保留（release-readiness 02）"
