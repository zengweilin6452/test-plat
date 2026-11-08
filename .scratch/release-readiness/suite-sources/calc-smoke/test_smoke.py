"""TestDock 首期真机验收用的受控 UI 套件（非客户套件）。

它只依赖平台派发时注入的事实：
- `mobile_session` / `mobile_adapter` 由 vendor 插件提供；
- `TESTDOCK_JOB_CONFIG` 里的 serial 与 app_package 来自已验证修订与构建。

用例保持最小但真实：真的连上设备、真的冷启动被测应用、真的截取一帧画面。
"""

from __future__ import annotations

import asyncio
import json
import os

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def job_config() -> dict:
    return json.loads(os.environ.get("TESTDOCK_JOB_CONFIG", "{}"))


def test_session_is_bound_to_dispatch_device(mobile_session):
    expected = job_config().get("serial")
    assert expected, "平台必须通过 TESTDOCK_JOB_CONFIG 传入 serial"
    assert mobile_session.serial == expected


def test_app_launches_and_screenshot_is_a_real_frame(mobile_adapter):
    cfg = job_config()
    package = cfg.get("app_package")
    assert package, "平台必须通过 TESTDOCK_JOB_CONFIG 传入 app_package"

    asyncio.run(mobile_adapter.goto("", package=package))
    asyncio.run(asyncio.sleep(1.0))
    png = asyncio.run(mobile_adapter.screenshot())

    assert png[:8] == PNG_MAGIC, "截图必须是 PNG"
    assert len(png) > 10_000, f"截图过小，可能不是真实画面：{len(png)} bytes"


def test_ui_stays_foreground_long_enough_for_perf_sampling(mobile_adapter):
    """联动采集窗需要真实时长：UI 保持在前台 15 秒，期间反复截帧。"""
    for _ in range(3):
        asyncio.run(asyncio.sleep(5.0))
        assert asyncio.run(mobile_adapter.screenshot())[:8] == PNG_MAGIC
