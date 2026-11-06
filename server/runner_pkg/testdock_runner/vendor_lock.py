"""vendor 本地设备锁的**跨进程**兜底（runner 侧；只在没有 vendor 时自足）。

为什么不直接用 vendor DeviceLease 就够
-------------------------------------
vendor 的 DeviceLease 在 Windows 上用 msvcrt 字节区锁，而 Windows 的字节区锁
是**按进程**的：同一个进程里第二次 acquire 同一把锁不会失败。API 重启后旧进程
残留的 holder.json 也挡不住新进程（文件锁随进程消亡）。所以 runner 侧还需要一个
纯文件协议的锁：O_CREAT|O_EXCL 建锁文件并写入 pid，acquire 时若锁文件存在则检查
持有进程是否还活着（stale 自动回收）。

状态机（与 vendor 的语义对齐）：
  锁不存在           -> acquire 成功
  锁存在 + pid 活着   -> DeviceBusy（runner 退出码 3，reason=local_lease_busy）
  锁存在 + pid 已死   -> 判定 stale，删掉后重试一次
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


class DeviceBusy(RuntimeError):
    """设备被另一个活进程持有。"""

    def __init__(self, serial: str, holder_pid: int | None) -> None:
        super().__init__(
            "device %s is held by pid=%s" % (serial, holder_pid)
        )
        self.serial = serial
        self.holder_pid = holder_pid


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # type: ignore[attr-defined]
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            return True
        except Exception:  # noqa: BLE001
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


@dataclass
class LocalDeviceLock:
    """一个进程级设备锁（幂等 release）。"""

    serial: str
    lock_dir: Path
    pid: int
    acquired: bool = False

    @property
    def path(self) -> Path:
        digest = hashlib.sha256(self.serial.encode("utf-8")).hexdigest()[:24]
        return self.lock_dir / (digest + ".lock")

    def acquire(self) -> bool:
        """非阻塞抢锁。已被活进程持有抛 DeviceBusy。"""
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        path = self.path
        for _attempt in range(2):
            try:
                handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                holder = self._read_holder()
                if holder is not None and _pid_alive(holder):
                    raise DeviceBusy(self.serial, holder) from None
                # 残留锁（holder 进程已死）：清掉再试一次
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            try:
                os.write(handle, str(self.pid).encode("utf-8"))
            finally:
                os.close(handle)
            self.acquired = True
            return True
        raise DeviceBusy(self.serial, self._read_holder())

    def release(self) -> bool:
        """释放锁（幂等；不是自己建的也删，因为 holder 只会是 stale 才会走到这里）。"""
        if not self.acquired:
            return False
        self.acquired = False
        try:
            self.path.unlink()
            return True
        except OSError:
            return False

    def _read_holder(self) -> int | None:
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
            return int(raw.split()[0]) if raw else None
        except (OSError, ValueError):
            return None

    def __enter__(self) -> LocalDeviceLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


__all__ = ["DeviceBusy", "LocalDeviceLock"]
