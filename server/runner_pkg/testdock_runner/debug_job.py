"""debug / perf 作业：CLI 形状稳定，行为最小可用。

P5 起调试会话有真实行为：
  - debug：在子进程里启动 vendor viewer（uvicorn，127.0.0.1 随机空闲口），
    然后把端口回报给 API（POST /internal/debug-sessions/{id}/ready {port}），
    之后占住设备直到收到取消。vendor / 设备不可用时退回"占位"行为并以
    exit 3（infra）+ reason=viewer_unavailable 收尾。
  - perf：复用 ui 的 pytest 通道（性能用例在同一套 evidence 插件下跑）。
两者都不改变释放顺序（停设备 -> 放 vendor 锁 -> 放本地锁）。
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from .env import RunnerContext, fake_enabled, has_vendor
from .protocol import emit_stage, emit_text
from .ui_job import UiJobOptions, UiJobResult, run_ui_job

#: fake 模式下回报给 API 的固定端口（不起真 viewer）。
FAKE_VIEWER_PORT = 58000


def _free_port() -> int:
    """向操作系统要一个 127.0.0.1 上的空闲 TCP 端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _report_ready(base_url: str, token: str, session_id: str, port: int) -> None:
    """POST /internal/debug-sessions/{id}/ready。

    ControlClient 只会拼 /internal/runs/{id}/... 前缀，调试会话的 ready 端点
    路径不同，这里直接用 urllib 发请求。失败抛 ControlError 语义外的异常由
    调用方转成 viewer_unavailable。
    """
    url = f"{base_url.rstrip('/')}/internal/debug-sessions/{session_id}/ready"
    data = json.dumps({"port": port}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Control-Token": token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8") or "{}")
    if not body.get("ok"):
        raise RuntimeError(f"ready 上报被拒绝：{body}")


def _start_viewer(options: UiJobOptions) -> int:
    """启动 vendor viewer 并返回其监听端口。

    vendor 按依赖隔离契约走 PYTHONPATH（env.ensure_vendor_on_path），import 只能
    发生在本函数内部 —— runner 子进程不受 app 的静态 vendor import 约束，但保持
    同样的延迟导入风格。
    """
    from .env import ensure_vendor_on_path

    ensure_vendor_on_path()
    import uvicorn  # noqa: PLC0415 - vendor 侧依赖，函数内导入
    from mobile_auto.viewer.app import create_app  # noqa: PLC0415

    app = create_app(session=None, store=None)
    port = _free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    # 不阻塞主线程：serve 在后台线程跑，主线程负责取消循环
    import threading  # noqa: PLC0415

    thread = threading.Thread(target=server.run, name="debug-viewer", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15.0
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("viewer 启动超时（15s 未监听）")
        if thread.is_alive() is False:
            raise RuntimeError("viewer 线程提前退出")
        time.sleep(0.1)
    return port


def run_debug_job(options: UiJobOptions, context: RunnerContext) -> UiJobResult:
    """交互式调试：起 viewer -> 回报端口 -> 占住设备直到取消。"""
    artifacts_dir = Path(options.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    context.set_stage("debug", 10, stage=2)
    emit_stage("debug", 10, serial=options.serial)

    viewer_port: int | None = None
    if fake_enabled(options.fake) or options.serial.startswith("fake"):
        # 假执行：不起真 viewer，直接回报固定端口让 API 转 active
        viewer_port = FAKE_VIEWER_PORT
        emit_text(f"fake debug viewer port={viewer_port}")
    else:
        if not has_vendor():
            emit_text("vendor 不可用，debug 会话退化为占位")
            return UiJobResult(exit_code=3, reason="viewer_unavailable")
        try:
            viewer_port = _start_viewer(options)
            emit_text(f"viewer started on 127.0.0.1:{viewer_port}")
        except Exception as exc:  # noqa: BLE001 - viewer 起不来按 infra 收敛
            emit_text(f"viewer 启动失败：{exc}")
            return UiJobResult(exit_code=3, reason="viewer_unavailable")

    # 回报端口（__main__.main 已先 ack，此时会话行 state=opening）
    try:
        _report_ready(
            context.control.base_url,
            context.control.token,
            options.run_id,
            viewer_port,
        )
    except Exception as exc:  # noqa: BLE001
        emit_text(f"ready 上报失败：{exc}")
        return UiJobResult(exit_code=3, reason="viewer_unavailable")

    context.set_stage("debug", 50, stage=2)
    emit_stage("debug", 50, serial=options.serial)
    deadline = time.monotonic() + float(options.timeout or 0)
    while not context.cancelled():
        if not context.check_fence():
            return UiJobResult(exit_code=5, reason="fence_mismatch", fence_lost=True)
        if options.timeout and time.monotonic() > deadline:
            return UiJobResult(exit_code=3, reason="timeout")
        time.sleep(1.0)
    emit_text("debug cancelled")
    return UiJobResult(exit_code=4, reason="cancelled", cancelled=True)


def run_perf_job(options: UiJobOptions, context: RunnerContext) -> UiJobResult:
    """性能作业：当前复用 UI 通道（同一 artifacts_dir 契约）。"""
    emit_text("perf job delegating to ui pipeline")
    return run_ui_job(options, context)


__all__ = ["run_debug_job", "run_perf_job"]
