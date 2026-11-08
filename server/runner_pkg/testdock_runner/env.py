"""runner 运行环境探测 + 取消/心跳协作状态（§10.1）。"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def fake_enabled(argv_fake: bool = False) -> bool:
    """TESTDOCK_FAKE_RUNNER=1 -> 走 fake runner（无真机也能跑完整流程）。"""
    if argv_fake:
        return True
    return os.environ.get("TESTDOCK_FAKE_RUNNER", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def vendor_paths(vendor_dir: Path | None = None) -> list[Path]:
    """vendor 两个 src 目录（顺序固定：mobile_auto 先于 mobile_perf）。"""
    if vendor_dir is None:
        env_dir = os.environ.get("TESTDOCK_VENDOR_DIR")
        if env_dir:
            vendor_dir = Path(env_dir)
        else:
            vendor_dir = Path(__file__).resolve().parents[3] / "vendor"
    return [vendor_dir / "mobile_auto" / "src", vendor_dir / "mobile_perf" / "src"]


def ensure_vendor_on_path(vendor_dir: Path | None = None) -> list[str]:
    """把 vendor src 插到 sys.path 最前（runner 是唯一允许这么做的进程）。"""
    added: list[str] = []
    for path in reversed(vendor_paths(vendor_dir)):
        text = str(path)
        if path.is_dir() and text not in sys.path:
            sys.path.insert(0, text)
            added.append(text)
    return added


def has_vendor(vendor_dir: Path | None = None) -> bool:
    paths = vendor_paths(vendor_dir)
    return all(p.is_dir() for p in paths)


@dataclass
class RunnerContext:
    """runner 进程的协作状态：心跳线程读它，主流程读它。"""

    run_id: str
    fencing_token: int
    artifacts_dir: Path
    control: object | None = None
    pid: int = field(default_factory=os.getpid)
    cancel_requested: bool = False
    fence_lost: bool = False
    progress: int = 0
    stage: str = "start"
    stage_number: int = 1
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def set_stage(self, name: str, progress: int, stage: int | None = None) -> None:
        with self._lock:
            self.stage = name
            self.progress = max(0, min(100, int(progress)))
            if stage is not None:
                self.stage_number = int(stage)

    def snapshot(self) -> tuple[int, int, str]:
        with self._lock:
            return self.progress, self.stage_number, self.stage

    # -- 心跳线程 --------------------------------------------------------- #
    def start_heartbeat(self, interval: float = 10.0) -> None:
        if self.control is None or self._thread is not None:
            return

        def _loop() -> None:
            while not self._stop.wait(interval):
                progress, stage, _name = self.snapshot()
                try:
                    reply = self.control.heartbeat(  # type: ignore[attr-defined]
                        pid=self.pid,
                        progress=progress,
                        stage=stage,
                        fencing_token=self.fencing_token,
                    )
                except Exception as exc:  # noqa: BLE001
                    if getattr(exc, "fence_mismatch", False):
                        with self._lock:
                            self.fence_lost = True
                    # 401/403 = 平台已不认这个 runner（API 重启换 token）：不是
                    # 抖动，续租永远不可达，标记 fence 丢失让主流程尽快退出。
                    if getattr(exc, "auth_lost", False):
                        with self._lock:
                            self.fence_lost = True
                    continue
                if isinstance(reply, dict):
                    if reply.get("cancel"):
                        with self._lock:
                            self.cancel_requested = True
                    if reply.get("fence_ok") is False:
                        with self._lock:
                            self.fence_lost = True

        self._thread = threading.Thread(target=_loop, name="testdock-heartbeat", daemon=True)
        self._thread.start()

    def stop_heartbeat(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._thread = None

    def cancelled(self) -> bool:
        with self._lock:
            return self.cancel_requested

    def fence_lost_now(self) -> bool:
        with self._lock:
            return self.fence_lost

    def check_fence(self) -> bool:
        """fence 边界检查（§7.1 四个边界之一）。返回 True 表示仍然持有租约。"""
        if self.control is None:
            return True
        try:
            reply = self.control.check_fence(self.fencing_token)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "fence_mismatch", False) or getattr(exc, "auth_lost", False):
                with self._lock:
                    self.fence_lost = True
                return False
            # 网络抖动不等于丢租约：靠心跳/对账兜底
            return not self.fence_lost_now()
        if isinstance(reply, dict):
            ok = reply.get("ok", True)
            if ok is False:
                with self._lock:
                    self.fence_lost = True
            return bool(ok)
        return True


class Deadline:
    """简单超时器（ui 默认 1800s）。"""

    def __init__(self, seconds: float) -> None:
        self.seconds = float(seconds)
        self.started = time.monotonic()

    @property
    def expired(self) -> bool:
        return self.seconds > 0 and (time.monotonic() - self.started) > self.seconds

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - (time.monotonic() - self.started))


__all__ = [
    "Deadline",
    "RunnerContext",
    "ensure_vendor_on_path",
    "fake_enabled",
    "has_vendor",
    "utcnow_iso",
    "vendor_paths",
]
