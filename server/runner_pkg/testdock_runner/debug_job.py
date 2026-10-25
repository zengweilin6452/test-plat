"""debug / perf 作业：CLI 形状稳定，行为最小可用。

P3 交付的是 UI 真跑；debug（交互式调试会话）与 perf（性能采集）已在
development-plan §10.1 定好入口参数，这里给出结构正确的实现：
  - debug：占住设备直到收到取消，正常收尾（无产物）；
  - perf：复用 ui 的 pytest 通道（性能用例在同一套 evidence 插件下跑）。
两者都不改变释放顺序（停设备 -> 放 vendor 锁 -> 放本地锁）。
"""

from __future__ import annotations

import time
from pathlib import Path

from .env import RunnerContext
from .protocol import emit_stage, emit_text
from .ui_job import UiJobOptions, UiJobResult, run_ui_job


def run_debug_job(options: UiJobOptions, context: RunnerContext) -> UiJobResult:
    """交互式调试：占住设备直到取消。"""
    artifacts_dir = Path(options.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
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
