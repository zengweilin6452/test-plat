"""平台 pytest 适配：用显式运行配置创建会话，不扩展 vendor 参数。"""
import json
import os
from pathlib import Path

import pytest

from .ui_job import UiJobOptions, _open_session


def pytest_addoption(parser):
    """注册 vendor 插件读取的 `--mobile-config`（平台生成的绝对路径配置）。

    vendor 用 `_optional_getoption` 读取它；未注册时传参会报 unrecognized
    arguments，而不传又会按 cwd（固定副本）解析 assets/artifacts。
    """
    group = parser.getgroup("testdock")
    try:
        group.addoption(
            "--mobile-config",
            action="store",
            default=None,
            metavar="PATH",
            help="平台生成的 mobile-auto 配置（assets_dir/artifacts_dir 为绝对路径）",
        )
    except ValueError:
        # 套件自己在 conftest 里注册了同名选项：以套件为准，不重复注册。
        pass


@pytest.fixture(scope="session")
def mobile_session():
    config = json.loads(os.environ.get("TESTDOCK_JOB_CONFIG", "{}"))
    options = UiJobOptions(run_id=os.environ.get("TESTDOCK_RUN_ID", "pytest"),
                           artifacts_dir=Path(config["artifacts_dir"]),
                           serial=config["serial"], app_package=config.get("app_package", ""),
                           app_activity=config.get("app_activity", ""))
    session = _open_session(options.serial, options.artifacts_dir, options)
    try:
        yield session
    finally:
        session.close()
