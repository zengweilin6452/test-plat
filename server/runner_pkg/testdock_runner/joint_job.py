"""joint 作业：一次资源独占内，性能采集窗口包围同一次 UI 执行（D8/D11）。

矩阵语义（spec §6.7，测试在 server/tests/test_issue16_joint_lifecycle.py）：

- 采集启动失败：不启动 UI，直接 fail(perf_collect_start_failed)；组件事实由
  runner 一并上报（UI=cancelled"前置采集失败未执行"，性能=errored），平台终态
  errored / outcome=NULL；
- UI 正常结束立即停止采集：不补采、不等样本；采集窗口取真实时间戳写入
  report.json，UI 核心活动窗另记边界；
- UI 达到 ui_timeout_s 上限：停止 UI 并收口，fail(ui_timeout) → 平台 errored；
  ui_timeout 独立于总 deadline（AC-CONTRACT-06），spawn 侧给总超时留缓冲；
- 用例断言失败是 completed/failed，不是 runner 故障。

fake 模式走同一条代码路径：TESTDOCK_FAKE_OUTCOME 控制用例结论，
TESTDOCK_FAKE_PERF=collect_start_failed / TESTDOCK_FAKE_UI_TIMEOUT=1 模拟矩阵异常行。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import collect_layout, write_report_json
from .env import RunnerContext, ensure_vendor_on_path, fake_enabled
from .protocol import emit_stage, emit_text
from . import EXIT_INFRA_ERROR
from .ui_job import (
    SuiteCopyError,
    UiJobOptions,
    require_suite_copy_targets,
    run_ui_job,
)

#: D11：UI 执行上限默认 600 秒，允许 10–3600 秒，由任务修订固定
DEFAULT_UI_TIMEOUT_S = 600
MIN_UI_TIMEOUT_S = 10
MAX_UI_TIMEOUT_S = 3600

UI_CANCELLED_BEFORE_START = "collect_start_failed_ui_not_started"
PERF_COLLECT_START_FAILED = "perf_collect_start_failed"
UI_TIMEOUT = "ui_timeout"


def clamp_ui_timeout(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_UI_TIMEOUT_S
    return max(MIN_UI_TIMEOUT_S, min(MAX_UI_TIMEOUT_S, seconds))


@dataclass
class JointJobResult:
    exit_code: int
    reason: str
    message: str = ""
    junit: dict[str, Any] = field(default_factory=dict)
    cases: list[dict[str, Any]] = field(default_factory=list)
    layout: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    fence_lost: bool = False
    timed_out: bool = False
    outcome: str | None = None
    components: list[dict[str, Any]] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _start_perf_collect(options: UiJobOptions):
    """真实路径：打开 vendor PerfKit 交互式采集窗口（设计方案 §6.2）。

    返回 CollectScope：with 语义由调用方手动 finalize——性能采集窗口必须
    包围同一次 UI 执行（D8），UI 一返回就 finalize 停采。
    采集项来自 perf 配置 items，缺省 PSS / 进程 CPU / FPS 三项。
    """
    ensure_vendor_on_path(options.vendor_dir)
    from mobile_perf.kit import PerfKit
    from mobile_perf.session import SessionSpec

    perf = options.perf or {}
    items = [str(item) for item in (perf.get("items") or ["mem_pss_mb", "cpu_process_pct", "fps_frame"])]
    if not options.app_package:
        raise ValueError("joint 运行缺少 app_package：采集需要目标前台应用")
    runs_dir = options.artifacts_dir / "perf-runs"
    kit = PerfKit(serial=options.serial or None, runs_dir=str(runs_dir))
    spec = SessionSpec(
        target=str(options.app_package),
        items=items,
        host_run_id=str(options.run_id),
        runs_dir=str(runs_dir),
    )
    return kit.collect(spec)


def run_joint_job(options: UiJobOptions, context: RunnerContext) -> JointJobResult:
    """采集包围 UI：先开采集，再跑一次 UI，UI 一返回立刻停采并归档。"""
    fake = fake_enabled(options.fake)
    # 固定副本与目标边界先于采集校验：副本不可用/目标越界时不该先占设备与采集。
    # 与 UI 作业共用同一套解析（require_suite_copy_targets），不出现第二套口径。
    if not fake:
        try:
            require_suite_copy_targets(options)
        except SuiteCopyError as exc:
            emit_text(exc.code, detail=exc.message)
            return JointJobResult(
                exit_code=EXIT_INFRA_ERROR,
                reason=exc.code,
                message=exc.message,
                components=[
                    {"kind": "ui", "state": "errored", "reason_code": exc.code},
                    {
                        "kind": "performance",
                        "state": "cancelled",
                        "reason_code": "ui_not_started",
                    },
                ],
            )
    emit_stage("perf_collect_start", 10, stage=1)
    collect_started_at = _now()

    scope = None
    if not fake:
        try:
            scope = _start_perf_collect(options)
        except Exception as exc:  # noqa: BLE001 - 采集启动失败按矩阵收敛为 errored
            emit_text("perf_collect_start_failed", detail=str(exc)[:300])
            return JointJobResult(
                exit_code=EXIT_INFRA_ERROR,
                reason=PERF_COLLECT_START_FAILED,
                message="性能采集启动失败，UI 未执行：" + str(exc)[:200],
                components=[
                    {"kind": "ui", "state": "cancelled", "reason_code": UI_CANCELLED_BEFORE_START},
                    {"kind": "performance", "state": "errored", "reason_code": PERF_COLLECT_START_FAILED},
                ],
            )

    if os.environ.get("TESTDOCK_FAKE_PERF", "").strip() == "collect_start_failed":
        # 采集启动失败：UI 根本不开始。组件事实随 fail 一并上报，平台按矩阵
        # 收敛为 errored / outcome=NULL，不产生任何"部分通过"的假象。
        emit_text("perf_collect_start_failed", detail="fake 采集启动失败")
        return JointJobResult(
            exit_code=EXIT_INFRA_ERROR,
            reason=PERF_COLLECT_START_FAILED,
            message="性能采集启动失败，UI 未执行",
            components=[
                {"kind": "ui", "state": "cancelled", "reason_code": UI_CANCELLED_BEFORE_START},
                {"kind": "performance", "state": "errored", "reason_code": PERF_COLLECT_START_FAILED},
            ],
        )

    # UI 阶段：直接复用 ui_job（同一 runner 进程已持有平台租约与本地锁语义，
    # ponytail: 真机模式复用 run_ui_job，若 vendor 锁不可重入再拆内部函数）。
    ui_started_at = _now()
    if os.environ.get("TESTDOCK_FAKE_UI_TIMEOUT", "").strip() == "1":
        # fake 模拟 UI 达到 ui_timeout_s：runner 在窗口边界停 UI 并收口
        return JointJobResult(
            exit_code=EXIT_INFRA_ERROR,
            reason=UI_TIMEOUT,
            message="UI 执行达到 ui_timeout_s 上限，已停止采集并收口",
            components=[
                {"kind": "ui", "state": "errored", "reason_code": UI_TIMEOUT},
                {"kind": "performance", "state": "cancelled",
                 "reason_code": "collect_stopped_at_ui_timeout"},
            ],
        )
    ui_result = run_ui_job(options, context)
    ui_window = {
        "started_at": ui_started_at,
        "ended_at": _now(),
        "timeout_s": clamp_ui_timeout(
            (options.perf or {}).get("ui_timeout_s") or DEFAULT_UI_TIMEOUT_S
        ),
    }

    if ui_result.timed_out:
        # UI 达到上限：停止采集并收口，记超时错误（不是用例失败）
        emit_stage("perf_collect_stop", 90, stage=2)
        return JointJobResult(
            exit_code=EXIT_INFRA_ERROR,
            reason=UI_TIMEOUT,
            message="UI 执行达到 ui_timeout_s 上限，已停止采集并收口",
            junit=ui_result.junit,
            cases=ui_result.cases,
            components=[
                {"kind": "ui", "state": "errored", "reason_code": UI_TIMEOUT},
                {"kind": "performance", "state": "cancelled", "reason_code": "collect_stopped_at_ui_timeout"},
            ],
        )

    # UI 一返回立即停采：不等待最小样本数、不补空闲样本（D11）。
    # 真实路径 finalize 走 vendor 归档/入库/报告全链路，报告含真实指标。
    vendor_report = None
    if scope is not None:
        try:
            vendor_report = scope.finalize()
        except Exception as exc:  # noqa: BLE001 - 停采失败不吞 UI 结果，指标按缺失呈现
            emit_text("perf_collect_stop_failed", detail=str(exc)[:300])
    collect_stopped_at = _now()
    emit_stage("perf_collect_stop", 90, stage=2)

    window = {
        "collect_started_at": collect_started_at,
        "collect_stopped_at": collect_stopped_at,
        "ui": ui_window,
    }
    metrics_summary = {}
    if fake:
        _write_fake_perf_report(options.artifacts_dir, window)
        metrics_summary = {"mem_pss_mb": {"unit": "MB", "median": 268.0, "sampleCount": 12}}
    elif isinstance(vendor_report, dict):
        # vendor 报告字段映射到平台 report.json 契约（runtime._report_json_payload 消费）
        report_data = {
            "runId": str(options.run_id),
            "mode": "original",
            "metricsSummary": vendor_report.get("metricsSummary") or {},
            "thresholdsAtRun": vendor_report.get("thresholdsAtRun") or {},
            "collectWindow": window,
            "prototype": False,
        }
        write_report_json(options.artifacts_dir, report_data)
        metrics_summary = report_data["metricsSummary"]

    components = list(ui_result.components or [])
    if not components:
        components = [
            {
                "kind": "ui",
                "state": "completed",
                "outcome": ui_result.outcome,
                "reason_code": ui_result.reason if ui_result.outcome == "not_tested" else None,
            }
        ]
    components.append({"kind": "performance", "state": "completed"})

    layout = ui_result.layout or collect_layout(options.artifacts_dir)
    return JointJobResult(
        exit_code=ui_result.exit_code,
        reason=ui_result.reason,
        message=ui_result.message,
        junit=ui_result.junit,
        cases=ui_result.cases,
        layout=layout,
        cancelled=ui_result.cancelled,
        fence_lost=ui_result.fence_lost,
        outcome=ui_result.outcome,
        components=components,
    )


def _write_fake_perf_report(artifacts_dir: Path, window: dict[str, Any]) -> None:
    """fake 采集的真实数据窗口（时间戳是真实的，指标是桩）。"""
    report = {
        "runId": artifacts_dir.name,
        "mode": "original",
        "metricsSummary": {"mem_pss_mb": {"unit": "MB", "median": 268.0, "sampleCount": 12}},
        "collectWindow": window,
        "prototype": False,
    }
    write_report_json(artifacts_dir, report)


__all__ = [
    "DEFAULT_UI_TIMEOUT_S",
    "JointJobResult",
    "MAX_UI_TIMEOUT_S",
    "MIN_UI_TIMEOUT_S",
    "clamp_ui_timeout",
    "run_joint_job",
]
