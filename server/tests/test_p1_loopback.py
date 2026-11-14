"""P1-03：服务绑定地址的回环约束（首期无登录认证，只允许本机访问）。

验收对应（任务书 P1-03）：
| 配置              | 预期 |
|-------------------|------|
| API = 127.0.0.1   | 允许 |
| API = localhost   | 允许 |
| API = 0.0.0.0     | 拒绝 |
| API = 局域网 IP   | 拒绝 |
| Web = 127.0.0.1   | 允许 |
| Web = 0.0.0.0     | 拒绝 |

后端校验在 config.Settings 的字段校验器（导入配置即失败，不依赖启动脚本）；
Web 侧校验在 web/vite.config.ts（vite 启动即失败）；dev_up.ps1 另有启动前
快速失败。最后一条静态断言守住三处名单不漂移。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import REPO_ROOT, Settings, ensure_loopback_host

_ALLOWED = ["127.0.0.1", "localhost", "LocalHost", "::1", "[::1]"]
_REJECTED = [
    "0.0.0.0",
    "::",
    "192.168.1.10",
    "10.0.0.5",
    "172.16.0.9",
    "0.0.0.0:8000",
    "example.com",
    "",
]


@pytest.mark.parametrize("value", _ALLOWED)
def test_loopback_hosts_are_allowed(value: str):
    assert ensure_loopback_host(value) == value.strip("[]").lower()


@pytest.mark.parametrize("value", _REJECTED)
def test_non_loopback_hosts_are_rejected(value: str):
    with pytest.raises(ValueError, match="回环地址"):
        ensure_loopback_host(value)


def _settings_with_host(host: str) -> Settings:
    return Settings(host=host, _env_file=None)  # type: ignore[call-arg]


def test_settings_accept_loopback_api_host():
    for host in ("127.0.0.1", "localhost", "::1"):
        assert _settings_with_host(host).host in {"127.0.0.1", "localhost", "::1"}


def test_settings_reject_non_loopback_api_host():
    """API = 0.0.0.0 / 局域网 IP：配置层直接拒绝启动（应用自身保护）。"""
    for host in ("0.0.0.0", "192.168.1.10", "::"):
        with pytest.raises(ValidationError):
            _settings_with_host(host)


def test_vite_config_and_dev_script_carry_the_same_guard():
    """Web = 0.0.0.0 必须被 vite 配置层拒绝；三处名单必须同时存在。"""
    vite_config = (REPO_ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")
    assert "TESTDOCK_WEB_HOST" in vite_config, "vite 配置必须消费 TESTDOCK_WEB_HOST"
    assert "assertLoopback" in vite_config, "vite 配置必须做回环校验"
    for host in ("127.0.0.1", "localhost", "::1"):
        assert host in vite_config

    dev_up = (REPO_ROOT / "scripts" / "dev_up.ps1").read_text(encoding="utf-8")
    assert "TESTDOCK_WEB_HOST" in dev_up and "TESTDOCK_HOST" in dev_up
    assert "回环地址" in dev_up, "dev_up.ps1 必须有回环快速失败"

    config_py = Path(__file__).resolve().parent.parent / "app" / "config.py"
    text = config_py.read_text(encoding="utf-8")
    assert "LOOPBACK_HOSTS" in text and "ensure_loopback_host" in text
