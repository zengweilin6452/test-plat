"""平台 pytest 适配：用显式运行配置创建会话，不扩展 vendor 参数。"""
import json
import os

import pytest

from .ui_job import UiJobOptions, _open_session
from pathlib import Path


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
