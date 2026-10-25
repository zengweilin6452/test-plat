"""运行时配置。环境变量优先，带安全默认值。

默认值对齐 docs/plan/development-plan.md：
- 数据库: EDB 便携 PG 17.6，端口 55432，用户 testdock（无密码，trust，仅回环）
- 产物目录: data/artifacts/<project_id>/<run_id>/
- 绑定: 127.0.0.1:8000（首期无登录，仅回环，D5）
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TESTDOCK_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://testdock@127.0.0.1:55432/testdock"
    host: str = "127.0.0.1"
    port: int = 8000

    data_dir: Path = REPO_ROOT / "data"
    runtime_dir: Path = REPO_ROOT / ".runtime"
    vendor_dir: Path = REPO_ROOT / "vendor"

    runner_python: str = "python"
    run_timeout_s: int = 3600
    stale_run_seconds: int = 60

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def runner_logs_dir(self) -> Path:
        return self.data_dir / "runner-logs"

    @property
    def tmp_dir(self) -> Path:
        """给 runner 子进程注入的 TMP/TEMP/HOME（F17）。"""
        return self.runtime_dir / "tmp"


settings = Settings()
