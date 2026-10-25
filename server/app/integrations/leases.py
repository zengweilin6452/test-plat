"""vendor 本地租约的**进程级**兜底（不 import vendor）。

为什么需要第二道锁
------------------
DB 租约（domain/leases.py）解决了"跨进程/跨节点"的权威互斥，但 vendor 的
DeviceLease 仍会真实地锁住设备文件（adbd 侧的 uiautomator、scrcpy 端口等）。
两边角色不同：
  DB 租约   = 谁有权调度这台设备（权威、可恢复、带 fencing）
  vendor 锁 = 设备上真实资源的互斥（跨平台行为不一致，不能作权威）

本模块提供一个**纯本地**的进程锁（平台无关，O_CREAT|O_EXCL）作为最后一道
防线：DB 说"这台设备给你了"，但宿主上仍有一个活着的进程正拿着它时，spawn
应该直接失败并把 run 标记 errored（reason=local_lease_busy），而不是硬上。

为什么不直接用 vendor DeviceLease：
  Windows 上 vendor 用 msvcrt 字节区锁，**同一进程内重入不会失败**，而且
  它 import 了 msvcrt/平台分支，API 进程不该为了这一行逻辑去 import vendor。
  真正持有 vendor 锁的是 runner 子进程；API 只做探活。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

#: 默认锁目录（与 vendor 的 ~/.mobile-auto/leases 区分开，避免互相误删）
DEFAULT_LOCK_DIRNAME = "device-locks"


def lock_dir(base: Path | str) -> Path:
    return Path(base) / DEFAULT_LOCK_DIRNAME


def lock_path(serial: str, base: Path | str) -> Path:
    digest = hashlib.sha256(serial.encode("utf-8")).hexdigest()[:24]
    return lock_dir(base) / (digest + ".lock")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows 上 os.kill(pid, 0) 会抛，需要用 tasklist 之外的方式判活：
        # ctypes OpenProcess 最轻量，且不引入第三方依赖
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class LockState:
    """本地锁探活结果。"""

    held: bool
    holder_pid: int | None
    stale: bool
    path: Path


def probe(serial: str, base: Path | str) -> LockState:
    """只读探活：锁文件存在且持有进程还活着 => held=True。

    holder 进程已死（崩溃残留）=> stale=True，调用方可以清理后重试。
    """
    path = lock_path(serial, base)
    if not path.exists():
        return LockState(held=False, holder_pid=None, stale=False, path=path)
    pid: int | None = None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw.split()[0]) if raw else None
    except (OSError, ValueError):
        pid = None
    if pid is None:
        # 无法解析 pid 的残留文件按 stale 处理，避免永久卡死设备
        return LockState(held=False, holder_pid=None, stale=True, path=path)
    alive = _pid_alive(pid)
    return LockState(held=alive, holder_pid=pid, stale=not alive, path=path)


def acquire(serial: str, base: Path | str, *, pid: int | None = None) -> LockState:
    """抢占本地锁（O_EXCL 原子创建）；已被活进程持有则返回 held=True。"""
    path = lock_path(serial, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = probe(serial, base)
    if current.held:
        return current
    if current.stale and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    try:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return probe(serial, base)
    try:
        os.write(handle, str(pid or os.getpid()).encode("utf-8"))
    finally:
        os.close(handle)
    return LockState(held=True, holder_pid=pid or os.getpid(), stale=False, path=path)


def release(serial: str, base: Path | str) -> bool:
    """释放本地锁（幂等）。"""
    path = lock_path(serial, base)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


__all__ = [
    "DEFAULT_LOCK_DIRNAME",
    "LockState",
    "acquire",
    "lock_dir",
    "lock_path",
    "probe",
    "release",
]
