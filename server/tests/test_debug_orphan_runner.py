"""调试会话关闭路径的孤儿 runner 兜底（无需数据库）。

背景（2026-11-08 真机排障）：API 重启后 spawn._PROCESSES 内存表丢失，DELETE
关闭调试会话时杀不到重启前 spawn 的 runner —— 孤儿持有本地设备锁
（.runtime/device-locks/<sha256(serial)>.lock），之后该设备每个新调试会话都在
~200ms 内 DeviceBusy（reason=local_lease_busy）关闭，前端表现为「重新连接
连不上」。关闭路径因此增加按命令行（testdock_runner --run-id <id>）的兜底扫描。
"""

from __future__ import annotations

import uuid

from app.routers import debug as debug_mod


def test_terminate_falls_back_to_command_line_scan(monkeypatch):
    """进程表没有该 run_id（API 重启过）时，按命令行扫描兜底杀 runner。"""
    from app.runner import spawn

    spawn._PROCESSES.pop("orphan-run", None)
    seen: list[list[str]] = []
    monkeypatch.setattr(
        debug_mod,
        "_find_runner_pid_by_run_id",
        lambda run_id: 4242 if run_id == "orphan-run" else None,
    )
    monkeypatch.setattr(debug_mod.subprocess, "run", lambda args, **kwargs: seen.append(list(args)))

    debug_mod._terminate_runner_blocking("orphan-run")
    assert seen, "兜底路径必须发起 taskkill/kill"
    assert "4242" in seen[0]
    assert spawn._PROCESSES.get("orphan-run") is None


def test_terminate_uses_process_table_when_present(monkeypatch):
    """进程表里有活进程就不扫描：表内 pid 是最直接的证据。"""
    from app.runner import spawn

    class FakeProc:
        pid = 111

    spawn._PROCESSES["live-run"] = FakeProc()  # type: ignore[assignment]
    seen: list[list[str]] = []
    scanned: list[str] = []

    def _scan(run_id: str) -> int | None:
        scanned.append(run_id)
        return None

    monkeypatch.setattr(debug_mod, "_find_runner_pid_by_run_id", _scan)
    monkeypatch.setattr(debug_mod.subprocess, "run", lambda args, **kwargs: seen.append(list(args)))
    try:
        debug_mod._terminate_runner_blocking("live-run")
    finally:
        spawn._PROCESSES.pop("live-run", None)
    assert seen and "111" in seen[0]
    assert scanned == [], "进程表命中时不应扫描"
    assert spawn._PROCESSES.get("live-run") is None


def test_scan_returns_none_without_runner():
    """没有 runner 进程时扫描必须返回 None，不误伤无关进程。

    run_id 是随机 uuid，命令行里不会有进程携带它；真实执行一次
    （Windows 走 PowerShell，POSIX 走 pgrep）验证管道本身可用。
    """
    assert debug_mod._find_runner_pid_by_run_id(str(uuid.uuid4())) is None
