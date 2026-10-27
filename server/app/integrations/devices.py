"""adb 集成：设备发现与特征探测（device-registration.md D1/D3）。

只做 subprocess 直调 adb 二进制，**不 import 任何 vendor 包**——与
integrations/discover.py（pytest discover 子进程）完全一致的接入模式，
test_p2_static.test_app_never_imports_vendor_packages_at_module_level 继续绿。

不用 adbutils：它是 vendor 的可选依赖，server/pyproject.toml 未声明，
把 API 进程绑到 vendor 依赖树上违反 development-plan.md §5.2 的精神。

adb 路径解析（D1）：
    TESTDOCK_ADB 环境变量 > settings.adb_path（默认 vendor/mobile_auto/tools/adb/adb.exe）
路径不存在时**不静默降级、不猜 PATH**：静默回落会让「同一台机器不同 shell
看到不同设备」这类问题无法复现。调用方把 AdbUnavailableError 渲染成
503 adb_unavailable，details 带期望路径与 TESTDOCK_ADB 提示。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

#: adb devices -l 里可能出现的设备状态（其余行忽略，比如 daemon 提示）
_ADB_STATES = frozenset(
    {"device", "offline", "unauthorized", "recovery", "sideload", "bootloader", "rescue"}
)

#: 一次 shell 探测取齐全部特征（一次子进程，省 N 次 adb spawn）。
#: 顺序固定，解析按行号对位；wm size 可能同时给 Physical 和 Override 两行。
_PROBE_COMMAND = (
    "getprop ro.product.brand; "
    "getprop ro.product.manufacturer; "
    "getprop ro.product.model; "
    "getprop ro.build.version.release; "
    "getprop ro.build.version.sdk; "
    "wm size"
)

#: adb 子进程默认超时（秒）。真机 getprop 通常 <1s；留足冷启动余量。
ADB_TIMEOUT_S = 15.0


class AdbUnavailableError(RuntimeError):
    """adb 二进制缺失或不可执行（→ 503 adb_unavailable）。"""


class AdbProbeError(RuntimeError):
    """adb 执行失败或超时（→ 502 adb_probe_failed）。"""


@dataclass(frozen=True)
class AdbDevice:
    """adb devices -l 里的一行。state 是 adb 原始值，未经映射。"""

    serial: str
    state: str
    model: str | None = None  # devices -l 的 model:xxx；未授权设备可能没有


@dataclass(frozen=True)
class DeviceProbe:
    """一台已授权设备的特征（D3.1）。"""

    brand: str
    manufacturer: str
    model: str
    os_version: str
    sdk: str
    screen_resolution: str


def resolve_adb_path() -> Path:
    """adb 二进制路径：TESTDOCK_ADB 环境变量优先，其次 settings.adb_path。"""
    override = os.environ.get("TESTDOCK_ADB", "").strip()
    return Path(override) if override else settings.adb_path


def map_adb_state(state: str) -> str:
    """adb 状态 → execution_resources.status（D4 映射表）。

    其他状态（recovery/sideload 等）映射为 draining：不可调度，但不谎报离线——
    与 STF 的 unavailable 口径一致。
    """
    return {
        "device": "ready",
        "unauthorized": "unauthorized",
        "offline": "offline",
    }.get(state, "draining")


def _run(adb: Path, args: list[str], *, timeout_s: float) -> str:
    if not adb.is_file():
        raise AdbUnavailableError(str(adb))
    try:
        completed = subprocess.run(  # noqa: S603 - 参数固定，无用户可控 shell
            [str(adb), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbProbeError(f"adb 超时（>{timeout_s}s）: {' '.join(args)}") from exc
    except OSError as exc:
        # 权限/架构不对等执行层问题按「不可用」处理，而不是探测失败
        raise AdbUnavailableError(f"{adb}: {exc}") from exc
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-5:]
        raise AdbProbeError(
            f"adb 退出码 {completed.returncode}: {' '.join(args)}；stderr 尾部: {' | '.join(tail)}"
        )
    return completed.stdout


def list_devices(adb: Path, *, timeout_s: float = ADB_TIMEOUT_S) -> list[AdbDevice]:
    """解析 `adb devices -l`，返回设备清单（含未授权/离线设备）。"""
    stdout = _run(adb, ["devices", "-l"], timeout_s=timeout_s)

    devices: list[AdbDevice] = []
    header_seen = False
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        if not header_seen:
            if text.startswith("List of devices attached"):
                header_seen = True
            continue  # daemon 启动提示等都在表头之前
        if text.startswith("*"):
            continue
        parts = text.split()
        if len(parts) < 2 or parts[1] not in _ADB_STATES:
            continue
        model = next(
            (p[len("model:") :] for p in parts[2:] if p.startswith("model:")),
            None,
        )
        devices.append(AdbDevice(serial=parts[0], state=parts[1], model=model))
    return devices


def probe_device(adb: Path, serial: str, *, timeout_s: float = ADB_TIMEOUT_S) -> DeviceProbe:
    """读取一台已授权设备的特征（getprop + wm size，一次 shell 调用）。"""
    stdout = _run(adb, ["-s", serial, "shell", _PROBE_COMMAND], timeout_s=timeout_s)

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    # getprop 五行按命令顺序对位；wm size 的行取 Physical size
    def _prop(index: int) -> str:
        return lines[index] if len(lines) > index else ""

    physical = next(
        (ln[len("Physical size:") :].strip() for ln in lines if ln.startswith("Physical size:")),
        "",
    )
    probe = DeviceProbe(
        brand=_prop(0),
        manufacturer=_prop(1),
        model=_prop(2),
        os_version=_prop(3),
        sdk=_prop(4),
        screen_resolution=physical,
    )
    if not probe.model or not probe.os_version or not probe.screen_resolution:
        missing = [
            name
            for name, value in (
                ("model", probe.model),
                ("os_version", probe.os_version),
                ("screen_resolution", probe.screen_resolution),
            )
            if not value
        ]
        raise AdbProbeError(f"设备 {serial} 特征读取不完整，缺 {missing}；原始输出: {lines!r}")
    return probe
