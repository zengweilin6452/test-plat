"""_report_json_payload 的失败边界：可预期的数据库/文件错误降级为空，编程错误不吞。"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app import runtime

RUN_ID = "00000000-0000-0000-0000-000000000000"


def test_database_failure_degrades_to_empty(monkeypatch):
    def boom(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    monkeypatch.setattr("sqlalchemy.create_engine", boom)
    assert runtime._report_json_payload(RUN_ID) == {}


def test_unexpected_error_is_not_swallowed(monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("编程错误不应被当成'没有报告'")

    monkeypatch.setattr("sqlalchemy.create_engine", boom)
    with pytest.raises(ValueError):
        runtime._report_json_payload(RUN_ID)
