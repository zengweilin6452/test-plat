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

import contextlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import EXIT_INFRA_ERROR
from .artifacts import collect_layout, write_report_json
from .env import RunnerContext, ensure_vendor_on_path, fake_enabled
from .perf_recovery import clear_stale_perf_recording
from .protocol import emit_stage, emit_text
from .ui_job import (
    SuiteCopyError,
    UiJobOptions,
    UiJobResult,
    require_suite_copy_targets,
    run_ui_job,
)

#: D11：UI 执行上限默认 600 秒，允许 10–3600 秒，由任务修订固定
DEFAULT_UI_TIMEOUT_S = 600
MIN_UI_TIMEOUT_S = 10
MAX_UI_TIMEOUT_S = 3600

UI_CANCELLED_BEFORE_START = "collect_start_failed_ui_not_started"
PERF_COLLECT_START_FAILED = "perf_collect_start_failed"
PERF_COLLECT_STOP_FAILED = "perf_collect_stop_failed"
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
    return datetime.now(UTC).isoformat()


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
    vendor_root = (
        Path(options.vendor_dir)
        if options.vendor_dir
        else Path(__file__).resolve().parents[3] / "vendor"
    )
    repo_root = vendor_root / "mobile_perf"
    # SQLite 必须落在本次运行产物目录：vendor 目录是只读固定副本，
    # 默认（<repo>/data/mobile_perf.db）会写穿 vendor。
    kit = PerfKit(
        serial=options.serial or None,
        repo_root=repo_root,
        runs_dir=str(runs_dir),
        db_path=str(options.artifacts_dir / "perf.sqlite3"),
    )
    # UI 开始前先清掉设备端残留录制，避免本作业 perf-start 撞 already active。
    kit_adb = getattr(kit, "adb_path", None)
    if kit_adb is not None and options.serial:
        clear_stale_perf_recording(
            serial=options.serial,
            adb_path=Path(kit_adb),
            repo_root=repo_root,
        )
    spec = SessionSpec(
        target=str(options.app_package),
        items=items,
        host_run_id=str(options.run_id),
        runs_dir=str(runs_dir),
    )
    # collect() 只构造作用域；真正的 perf-start 在 __enter__ 里发生。不进入就
    # 直接交给 finalize，会在 UI 跑完后报 "'NoneType' object has no attribute
    # 'stop'"——采集从未启动，报告却以为性能组件已执行（真机验收发现）。
    scope = kit.collect(spec)
    try:
        return scope.__enter__()
    except Exception:
        with contextlib.suppress(Exception):
            scope.finalize()
        raise


def _ui_window_timeout(options: UiJobOptions) -> int:
    """本次 UI 执行窗上限：派发固定的 ui_timeout_s 优先，兼容旧的 perf 字段。"""
    raw = options.ui_timeout_s
    if raw is None:
        raw = (options.perf or {}).get("ui_timeout_s")
    return clamp_ui_timeout(raw)


def _stop_collection(scope: Any) -> tuple[dict[str, Any] | None, str | None]:
    """UI 一返回（正常或超时）立即停采。

    finalize 失败不吞 UI 结果，但必须把失败作为性能组件事实返回：
    指标按缺失呈现，采集窗口仍要收口，不能把采集留到进程退出
    （工单 07 缺陷 2；复审缺陷 2）。
    """
    if scope is None:
        return None, None
    try:
        report = scope.finalize()
        return report if isinstance(report, dict) else None, None
    except Exception as exc:  # noqa: BLE001 - 停采失败不吞 UI 结果
        # str(exc) 可能是空串（bare Exception / TimeoutError）；空串是假值，
        # 调用方按真值判断会把停采失败当成成功，至少回落到异常类名。
        detail = (str(exc) or type(exc).__name__)[:300]
        emit_text(PERF_COLLECT_STOP_FAILED, detail=detail)
        return None, detail


def _write_joint_report(
    options: UiJobOptions,
    window: dict[str, Any],
    vendor_report: dict[str, Any] | None,
    *,
    fake: bool,
) -> None:
    """写 report.json：采集窗口是平台 /report 的唯一来源。

    真实路径即使 vendor 报告不可用也写：报告至少要能说明采集起止与 UI
    执行窗，而不是"什么都没有"。
    """
    if fake:
        _write_fake_perf_report(options.artifacts_dir, window)
        return
    report_data = {
        "runId": str(options.run_id),
        "mode": "original",
        "metricsSummary": {},
        "thresholdsAtRun": {},
        "collectWindow": window,
        "prototype": False,
    }
    if isinstance(vendor_report, dict):
        report_data["metricsSummary"] = vendor_report.get("metricsSummary") or {}
        report_data["thresholdsAtRun"] = vendor_report.get("thresholdsAtRun") or {}
    write_report_json(options.artifacts_dir, report_data)


def _ui_timeout_result(
    ui_result: Any, perf_stop_error: str | None = None
) -> JointJobResult:
    performance = (
        {
            "kind": "performance",
            "state": "errored",
            "reason_code": PERF_COLLECT_STOP_FAILED,
        }
        if perf_stop_error
        else {
            "kind": "performance",
            "state": "cancelled",
            "reason_code": "collect_stopped_at_ui_timeout",
        }
    )
    message = "UI 执行达到 ui_timeout_s 上限，已停止采集并收口"
    if perf_stop_error:
        message += "；性能采集停止失败：" + perf_stop_error[:200]
    return JointJobResult(
        exit_code=EXIT_INFRA_ERROR,
        reason=UI_TIMEOUT,
        message=message,
        junit=getattr(ui_result, "junit", {}) or {},
        cases=getattr(ui_result, "cases", []) or [],
        components=[
            {"kind": "ui", "state": "errored", "reason_code": UI_TIMEOUT},
            performance,
        ],
    )


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
    # UI 执行窗上限必须同时是真实 pytest deadline（工单 07 缺陷 1）：
    # 在这里固定成 UiJobOptions 的一部分，ui_job 与窗口描述读同一个值。
    window_timeout = _ui_window_timeout(options)
    options.ui_timeout_s = window_timeout

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
        # fake 模拟 UI 达到 ui_timeout_s：走与真实超时同一段收口逻辑
        ui_result = UiJobResult(
            exit_code=EXIT_INFRA_ERROR, reason=UI_TIMEOUT, timed_out=True
        )
    else:
        ui_result = run_ui_job(options, context)
    ui_window = {
        "started_at": ui_started_at,
        "ended_at": _now(),
        "timeout_s": window_timeout,
    }

    # UI 一返回立即停采：正常结束与超时都必须先收口（不补采、不等样本，D11）。
    vendor_report, perf_stop_error = _stop_collection(scope)
    collect_stopped_at = _now()
    emit_stage("perf_collect_stop", 90, stage=2)

    window = {
        "collect_started_at": collect_started_at,
        "collect_stopped_at": collect_stopped_at,
        "ui": ui_window,
    }
    _write_joint_report(options, window, vendor_report, fake=fake)

    if ui_result.timed_out:
        # UI 达到上限：停止采集并收口，记超时错误（不是用例失败）
        return _ui_timeout_result(ui_result, perf_stop_error)

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
    # 停采失败不得把性能组件写成 completed：UI 结果保留，性能如实报 errored
    components.append(
        {"kind": "performance", "state": "errored", "reason_code": PERF_COLLECT_STOP_FAILED}
        if perf_stop_error
        else {"kind": "performance", "state": "completed"}
    )

    layout = ui_result.layout or collect_layout(options.artifacts_dir)
    message = ui_result.message
    if perf_stop_error:
        message = (message + "；" if message else "") + "性能采集停止失败：" + perf_stop_error[:200]
    return JointJobResult(
        exit_code=ui_result.exit_code,
        reason=ui_result.reason,
        message=message,
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
