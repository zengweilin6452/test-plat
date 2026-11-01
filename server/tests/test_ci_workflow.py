"""CI 后端作业必须能在 Windows runner 上真正跑到数据库用例（复审缺陷 4/5）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _server_job() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("\n  server:", 1)[1].split("\n  web:", 1)[0]


def test_server_job_keeps_windows_and_uses_portable_postgres():
    job = _server_job()
    assert "runs-on: windows-latest" in job
    assert "\n    services:" not in job, (
        "GitHub 服务容器只支持 Linux，Windows runner 不能声明 services"
    )
    assert "scripts/pg_portable_setup.ps1" in job
    assert "pg17" in job


def test_server_job_wires_test_dsn_and_verifies_database_cases_ran():
    job = _server_job()
    # 测试读的是 TESTDOCK_TEST_DATABASE_URL；alembic/运行期读 TESTDOCK_DATABASE_URL，
    # 两者必须都接到同一个专用库，不能只设置其中一个。
    assert "TESTDOCK_TEST_DATABASE_URL" in job
    assert "TESTDOCK_DATABASE_URL" in job
    assert "--junitxml" in job
    assert "数据库测试被跳过" in job, "必须核对数据库用例不是全量 skip"
    assert "alembic upgrade head" in job
