"""vendor 契约的**元数据**投影（只读，不 import vendor）。

为什么只放常量而不 import
------------------------
development-plan.md §3.3 规定：只有 `testdock_runner`（跑在独立子进程里）可以
import mobile_auto / mobile_perf。API 进程一旦 import vendor，它就会和 vendor 的
可选依赖（cv2 / numpy / fastapi 等）绑死，部署面被无谓扩大，而且 vendor 的任何
导入期副作用都会污染 API 进程。所以这里只用**纯数据**描述契约：
  - exit code 语义（runner 子进程 -> API 的错误映射）
  - 运行目录布局（evidence/<16hex>/、run-manifest.jsonl、junit.xml）
  - 阶段权重
真正操作设备的能力全部通过 `testdock_runner` 子进程暴露。
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 退出码（development-plan.md §10.1）
# --------------------------------------------------------------------------- #
EXIT_OK = 0
EXIT_CASE_FAILURE = 2
EXIT_INFRA_ERROR = 3
EXIT_CANCELLED = 4
EXIT_FENCE_MISMATCH = 5


@dataclass(frozen=True)
class ExitMapping:
    """退出码 -> (run 状态, outcome, reason_code)。

    关键点：**只有 exit 0 才是 completed**。exit 2（有用例失败）表示"跑完了且有
    红"，同样属于 completed，但 outcome=failed；3/4/5 都是"没跑出结论"，
    outcome 必须 NULL（DB CHECK 兜底）。
    """

    state: str
    outcome: str | None
    reason_code: str
    failed: bool


EXIT_MAPPING: dict[int, ExitMapping] = {
    EXIT_OK: ExitMapping("completed", "passed", "ok", False),
    EXIT_CASE_FAILURE: ExitMapping("completed", "failed", "case_failure", False),
    EXIT_INFRA_ERROR: ExitMapping("errored", None, "infra_error", True),
    EXIT_CANCELLED: ExitMapping("cancelled", None, "cancelled", False),
    EXIT_FENCE_MISMATCH: ExitMapping("errored", None, "fence_mismatch", True),
}


def map_exit_code(code: int | None, *, timeout: bool = False) -> ExitMapping:
    """未知退出码（含被外部 kill 的负数）一律按基础设施错误处理。"""
    if timeout:
        return ExitMapping("errored", None, "timeout", True)
    if code is None:
        return ExitMapping("errored", None, "runner_lost", True)
    mapped = EXIT_MAPPING.get(int(code))
    if mapped is not None:
        return mapped
    # Windows 被 TerminateProcess 杀掉时 Python 返回 1（被包装）或负数；一律 infra
    return ExitMapping("errored", None, "runner_exit_%d" % int(code), True)


# --------------------------------------------------------------------------- #
# 目录布局（vendor mobile_auto/evidence/collector.py 的落盘约定）
# --------------------------------------------------------------------------- #
EVIDENCE_DIR = "evidence"
JUNIT_XML = "junit.xml"
RUN_MANIFEST = "run-manifest.jsonl"
REPORT_JSON = "report.json"
FAILURE_FRAME = "failure-frame.png"
UI_TREE = "ui-tree.xml"
EVIDENCE_META = "meta.json"

#: ui 任务的默认超时（development-plan.md §10.1）
UI_TIMEOUT_SECONDS = 1800
#: 取消后等待 runner 自行退出的宽限，超时即 taskkill /T /F（§10.1）
CANCEL_GRACE_SECONDS = 10
#: 心跳间隔（§7.1）
HEARTBEAT_SECONDS = 10
#: reconciler 判定掉线的阈值（§7.1）；Settings.stale_run_seconds 默认 60
STALE_SECONDS = 60


__all__ = [
    "CANCEL_GRACE_SECONDS",
    "EVIDENCE_DIR",
    "EVIDENCE_META",
    "EXIT_CANCELLED",
    "EXIT_CASE_FAILURE",
    "EXIT_FENCE_MISMATCH",
    "EXIT_INFRA_ERROR",
    "EXIT_MAPPING",
    "EXIT_OK",
    "ExitMapping",
    "FAILURE_FRAME",
    "HEARTBEAT_SECONDS",
    "JUNIT_XML",
    "REPORT_JSON",
    "RUN_MANIFEST",
    "STALE_SECONDS",
    "UI_TIMEOUT_SECONDS",
    "UI_TREE",
    "map_exit_code",
]
