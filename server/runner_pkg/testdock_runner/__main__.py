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

SUBCOMMANDS = ("ui", "perf", "debug", "joint")


def _json_object(value: str) -> dict:
    import json
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("配置必须是 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("配置必须是 JSON 对象")
    return parsed


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
        job.add_argument("--ui-timeout", type=float, default=0.0)
        job.add_argument("--test-path", action="append", default=[])
        # 固定代码副本（dispatcher 复验后写入 spawn 配置）：pytest 的 cwd 与
        # 目标解析边界都来自它；缺失即阻断，不退回 server/ 或来源目录。
        job.add_argument("--suite-root", default="")
        job.add_argument("--suite-version", default="")
        job.add_argument("--suite-sha256", default="")
        job.add_argument("--app-package", default="")
        job.add_argument("--app-activity", default="")
        job.add_argument("--perf-config", type=_json_object, default={})
        job.add_argument("--fake", action="store_true")
        job.add_argument("--skip-vendor-check", action="store_true")
    return parser


def _control_client(args: argparse.Namespace) -> ControlClient | None:
    # token 优先取环境变量（spawn 侧不把它放进 argv，避免进程列表泄露）；
    # --control-token 参数保留给手工调试。
    token = args.control_token or os.environ.get("TESTDOCK_CONTROL_TOKEN", "")
    if not args.control_url or not token:
        emit_text("control_disabled")
        return None
    from .protocol import DebugControlClient
    client_type = DebugControlClient if args.command == "debug" else ControlClient
    return client_type(args.control_url, token, args.run_id)


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
        app_package=args.app_package,
        app_activity=args.app_activity,
        perf=args.perf_config,
        suite_root=Path(args.suite_root) if args.suite_root else None,
        suite_version_id=args.suite_version or None,
        suite_sha256=args.suite_sha256 or None,
    )


def _result_outcome(result) -> str:
    if result.exit_code not in (0, 2):
        return "not_tested"
    if result.outcome:
        return result.outcome
    junit = result.junit or {}
    if junit.get("failed"):
        return "failed"
    if int(junit.get("tests") or 0) > int(junit.get("skipped") or 0):
        return "passed"
    return "not_tested"


def _report_complete(
    control: ControlClient | None,
    args: argparse.Namespace,
    result,
) -> None:
    if control is None:
        return
    junit = result.junit or {}
    outcome = _result_outcome(result)
    try:
        control.complete(
            outcome=outcome,
            fencing_token=int(args.fencing_token or 0),
            components=result.components or [{"kind": "ui", "state": "completed", "outcome": outcome,
                                              "reason_code": result.reason if outcome == "not_tested" else None}],
            artifacts_dir=str(Path(args.artifacts_dir).resolve()),
            reason=result.reason,
            cases=result.cases or [],
            junit=junit,
            metrics={"artifacts": len((result.layout or {}).get("files", []))},
        )
    except ControlError:
        emit_text("complete_failed")
        raise


def _report_fail(
    control: ControlClient | None,
    args: argparse.Namespace,
    error_code: str,
    message: str,
    stage: str,
    result=None,
) -> None:
    if control is None:
        return
    # joint 的组件事实随 fail 一并上报（如"采集启动失败、UI 未执行"），
    # 平台据此落组件行，而不是让 errored 运行没有任何组件记录。
    components = getattr(result, "components", None)
    try:
        control.fail(
            error_code=error_code,
            message=message[:2000],
            stage=stage,
            fencing_token=int(args.fencing_token or 0),
            components=components,
            # 失败前可能已经产出（joint 超时收口的 report.json 就是唯一采集窗口
            # 证据）；登记后 /report 才看得到，而不是让证据只留在磁盘上。
            artifacts_dir=str(Path(args.artifacts_dir).resolve()),
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
    result = None  # 作业失败发生在赋值前时，fail 上报仍能安全引用
    try:
        if args.command == "debug":
            from .debug_job import run_debug_job

            result = run_debug_job(options, context)
        elif args.command == "perf":
            from .debug_job import run_perf_job

            result = run_perf_job(options, context)
        elif args.command == "joint":
            from .joint_job import run_joint_job

            # 执行窗上限走 UiJobOptions 的显式字段：joint_job 与 ui_job 读同一个
            # 值（真实 pytest deadline），不再只放在 perf 描述里。
            options.ui_timeout_s = int(args.ui_timeout) if args.ui_timeout else None
            result = run_joint_job(options, context)
        else:
            from .ui_job import run_ui_job

            result = run_ui_job(options, context)
        exit_code = result.exit_code
        if args.command == "debug":
            if control is not None:
                try:
                    control.close(reason=result.reason, fencing_token=context.fencing_token)
                except ControlError as exc:
                    # 控制面瞬时不可达时不让回报失败拖垮退出码：调试会话由平台侧
                    # 租约超时兜底回收，这里只留下可观测的失败标记。
                    emit_text("close_report_failed", detail=str(exc)[:300])
            return exit_code
        emit_stage("finalize", 100, stage=3)
        layout = result.layout or collect_layout(Path(args.artifacts_dir))
        emit_result(
            outcome=_result_outcome(result),
            reason=result.reason,
            junit=result.junit,
            files=len(layout.get("files", [])),
            fake=fake_enabled(args.fake),
        )
        if result.fence_lost:
            return EXIT_FENCE_MISMATCH
        if result.cancelled:
            _report_fail(control, args, "cancelled", "runner cancelled", "cancelled", result)
            return EXIT_CANCELLED
        if exit_code in (EXIT_OK, EXIT_CASE_FAILURE):
            _report_complete(control, args, result)
            return exit_code
        _report_fail(control, args, result.reason or "runner_error", result.message, result.reason, result)
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
