"""runner 入口：python -m testdock_runner <ui|perf|debug> [options]（§10.1）。

退出码约定（与 app/integrations/mobile_auto.py 的 EXIT_MAPPING 一一对应）：
  0 成功（含用例失败——失败已在 complete(outcome=failed) 里上报）
  2 用例失败且未能上报 complete
  3 基础设施错误（本地锁占用、设备不可用、超时、内部异常）
  4 被取消
  5 fence 不匹配（DB 租约已属于别人，结果必须丢弃）

为什么"成功也要分 0 和 2"
----------------------
0 = 这条链路本身没问题（pytest 正常跑完，结果已提交）；2 = 同样的用例失败，
但没有成功提交。API 侧用退出码只能做兜底，权威结果是 complete/fail 上报。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

from .artifacts import collect_layout
from .env import RunnerContext, fake_enabled, utcnow_iso
from .protocol import ControlClient, ControlError, emit_result, emit_stage, emit_text

EXIT_OK = 0
EXIT_CASE_FAILURE = 2
EXIT_INFRA_ERROR = 3
EXIT_CANCELLED = 4
EXIT_FENCE_MISMATCH = 5

SUBCOMMANDS = ("ui", "perf", "debug")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="testdock_runner")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in SUBCOMMANDS:
        job = sub.add_parser(name)
        job.add_argument("--run-id", required=True)
        job.add_argument("--artifacts-dir", required=True)
        job.add_argument("--serial", default="")
        job.add_argument("--revision", default=None)
        job.add_argument("--task-id", default=None)
        job.add_argument("--control-url", default="")
        job.add_argument("--control-token", default="")
        job.add_argument("--fencing-token", type=int, default=0)
        job.add_argument("--timeout", type=float, default=1800.0)
        job.add_argument("--test-path", action="append", default=[])
        job.add_argument("--fake", action="store_true")
        job.add_argument("--skip-vendor-check", action="store_true")
    return parser


def _control_client(args: argparse.Namespace) -> ControlClient | None:
    if not args.control_url or not args.control_token:
        emit_text("control_disabled")
        return None
    return ControlClient(args.control_url, args.control_token, args.run_id)


def _job_options(args: argparse.Namespace):
    from .ui_job import UiJobOptions

    return UiJobOptions(
        run_id=str(args.run_id),
        artifacts_dir=Path(args.artifacts_dir),
        serial=args.serial or "",
        revision_id=args.revision,
        task_id=args.task_id,
        timeout=float(args.timeout or 0),
        test_paths=list(args.test_path or []),
        fake=bool(args.fake),
    )


def _report_complete(
    control: ControlClient | None,
    args: argparse.Namespace,
    result,
) -> None:
    if control is None:
        return
    junit = result.junit or {}
    if junit.get("failed"):
        outcome = "failed"
    elif junit.get("tests"):
        outcome = "passed"
    else:
        outcome = "not_tested"
    try:
        control.complete(
            outcome=outcome,
            fencing_token=int(args.fencing_token or 0),
            components=[{"kind": "ui", "state": "completed", "outcome": outcome}],
            cases=result.cases or [],
            junit=junit,
            metrics={"artifacts": len((result.layout or {}).get("files", []))},
        )
    except ControlError as exc:
        emit_text("complete_failed", detail=str(exc)[:500])


def _report_fail(
    control: ControlClient | None,
    args: argparse.Namespace,
    error_code: str,
    message: str,
    stage: str,
) -> None:
    if control is None:
        return
    try:
        control.fail(
            error_code=error_code,
            message=message[:2000],
            stage=stage,
            fencing_token=int(args.fencing_token or 0),
        )
    except ControlError as exc:
        emit_text("fail_report_failed", detail=str(exc)[:500])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    control = _control_client(args)
    context = RunnerContext(
        run_id=str(args.run_id),
        fencing_token=int(args.fencing_token or 0),
        artifacts_dir=Path(args.artifacts_dir),
        control=control,
    )
    if control is not None:
        try:
            control.ack(
                pid=os.getpid(),
                started_at=utcnow_iso(),
                fencing_token=int(args.fencing_token or 0),
            )
        except ControlError as exc:
            emit_text("ack_failed", detail=str(exc)[:300])
            if exc.fence_mismatch:
                return EXIT_FENCE_MISMATCH
    context.start_heartbeat()
    options = _job_options(args)
    exit_code = EXIT_INFRA_ERROR
    try:
        if args.command == "debug":
            from .debug_job import run_debug_job

            result = run_debug_job(options, context)
        elif args.command == "perf":
            from .debug_job import run_perf_job

            result = run_perf_job(options, context)
        else:
            from .ui_job import run_ui_job

            result = run_ui_job(options, context)
        exit_code = result.exit_code
        emit_stage("finalize", 100, stage=3)
        layout = result.layout or collect_layout(Path(args.artifacts_dir))
        emit_result(
            outcome=(result.junit or {}).get("failed") and "failed" or "passed",
            reason=result.reason,
            junit=result.junit,
            files=len(layout.get("files", [])),
            fake=fake_enabled(args.fake),
        )
        if result.fence_lost:
            return EXIT_FENCE_MISMATCH
        if result.cancelled:
            _report_fail(control, args, "cancelled", "runner cancelled", "cancelled")
            return EXIT_CANCELLED
        if exit_code in (EXIT_OK, EXIT_CASE_FAILURE):
            _report_complete(control, args, result)
            return exit_code
        _report_fail(control, args, result.reason or "runner_error", result.message, result.reason)
        return exit_code if exit_code in (EXIT_OK, EXIT_CASE_FAILURE, EXIT_INFRA_ERROR) else EXIT_INFRA_ERROR
    except ControlError as exc:
        if exc.fence_mismatch:
            print(json_line("fence_mismatch"), flush=True)
            return EXIT_FENCE_MISMATCH
        traceback.print_exc()
        return EXIT_INFRA_ERROR
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _report_fail(control, args, "runner_exception", str(exc), context.stage)
        return EXIT_INFRA_ERROR
    finally:
        context.stop_heartbeat()


def json_line(name: str) -> str:
    import json

    return json.dumps({"t": "text", "name": name})


if __name__ == "__main__":
    sys.exit(main())
