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

    # device-registration.md D1：adb 默认走仓库自带的 vendor 二进制，路径可预测。
    # 运行时覆盖用 TESTDOCK_ADB 环境变量（见 integrations/devices.resolve_adb_path）；
    # 不复用 vendor mobile_perf.resolve_adb()——它的随包默认指向另一个文件且依赖
    # 两个当前未设置的 MOBILE_PERF_ADB/ADB 环境变量，平台不跟着 vendor 内部布局漂移。
    adb_path: Path = REPO_ROOT / "vendor" / "mobile_auto" / "tools" / "adb" / "adb.exe"

    runner_python: str = "python"
    run_timeout_s: int = 3600
    stale_run_seconds: int = 60

    #: 产物保留天数（<=0 表示未配置保留策略，登记时不写 expires_at）。
    #: 配置后证据的 expired 状态按 expires_at 真实可达（工单 05）。
    artifact_retention_days: int = 0

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


    # ----------------------------------------------------------------- #
    # P3 追加：运行生命周期 / runner 子进程 / 内部协议
    # ----------------------------------------------------------------- #
    @property
    def repo_root(self) -> Path:
        """仓库根（runner 的 cwd 与 PYTHONPATH 都以它为基准）。"""
        return REPO_ROOT

    @property
    def control_token_path(self) -> Path:
        """内部协议令牌文件（§8.3）：API 启动时生成，runner 经环境变量 TESTDOCK_CONTROL_TOKEN 获得。"""
        return self.data_dir / "control.token"


# --------------------------------------------------------------------------- #
# P3 追加：后台调度开关 / 假 runner 开关
# --------------------------------------------------------------------------- #
#: TESTDOCK_SCHEDULER=0 时 API 不启动 dispatcher / reconciler 后台循环。
#: 单元测试用（domain 层测试不需要一个偷跑的后台循环去抢库里的 queued run）。
#: 默认开启：P3 验收要求 POST /runs 之后真的被派发。
SCHEDULER_ENV = "TESTDOCK_SCHEDULER"

#: TESTDOCK_FAKE_RUNNER=1 时 runner 走假执行（不需要真机/ADB）。
#: 这是 P3 集成测试能在无真机环境下全绿的前提，也是演示通道。
FAKE_RUNNER_ENV = "TESTDOCK_FAKE_RUNNER"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in _TRUTHY


def scheduler_enabled() -> bool:
    """后台调度是否启用（默认启用）。"""
    import os

    return _truthy(os.environ.get(SCHEDULER_ENV), default=True)


def fake_runner_enabled() -> bool:
    """是否使用假 runner（默认关闭）。"""
    import os

    return _truthy(os.environ.get(FAKE_RUNNER_ENV))


settings = Settings()
