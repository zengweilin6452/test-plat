"""性能采集启动前的残留录制兜底。

SoloPi 的录制是设备端状态：上一个 runner 被强杀/崩溃后，``perf-start`` 会报
``A performance recording is already active``，下一次运行直接失败。
runner 已持有设备租约，此时设备上仍有 active 录制只可能是残留；启动前先查
``perf-status``，能停就停，停不掉则明确失败，绝不带着残留进入新采集。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .protocol import emit_text

STATUS_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 60.0
_ACTIVE_STATES = frozenset({"starting", "recording", "stopping"})


@dataclass(frozen=True)
class StaleRecording:
    session_id: str
    target_package: str | None = None
    duration_ms: int | None = None
    stopped: bool = True


def _data(result: Any) -> dict[str, Any]:
    payload = getattr(result, "data", None)
    return payload if isinstance(payload, dict) else {}


def clear_stale_perf_recording(
    *,
    serial: str,
    adb_path: Path,
    repo_root: Path,
) -> StaleRecording | None:
    """停掉设备上无主的 active 录制；返回本次清理的会话信息，无残留返回 None。

    ``perf-status`` 不可用时只记录事件并放行：这是诊断通道失败，不应凭空阻断
    一次可能正常的采集；真正的冲突仍会由后续 ``perf-start`` 如实报错。
    """
    from mobile_perf import solo

    common = {
        "adb_path": adb_path,
        "serial": serial,
        "repo_root": repo_root,
    }
    try:
        status = solo.run_harness(["perf-status"], timeout_s=STATUS_TIMEOUT_S, **common)
    except Exception as exc:  # noqa: BLE001 - 诊断失败不阻断启动
        emit_text("perf_status_failed", detail=str(exc)[:300])
        return None
    status_data = _data(status)
    if not getattr(status, "success", False):
        detail = str(status_data.get("error") or "perf-status 返回失败")[:300]
        emit_text("perf_status_failed", detail=detail)
        return None
    if not status_data.get("active"):
        return None

    session_id = status_data.get("sessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        raise RuntimeError("发现残留性能录制，但 SoloPi 未返回 sessionId，无法停止")

    try:
        stopped = solo.run_harness(
            [
                "perf-stop",
                "--session-id",
                session_id.strip(),
                "--stop-timeout",
                str(int(STOP_TIMEOUT_S)),
            ],
            timeout_s=STOP_TIMEOUT_S,
            **common,
        )
    except Exception as exc:  # noqa: BLE001 - 清理失败必须阻断
        raise RuntimeError(
            f"发现残留性能录制 {session_id}，perf-stop 失败：{exc}"
        ) from exc
    stopped_data = _data(stopped)
    if (
        not getattr(stopped, "success", False)
        or stopped_data.get("active") is True
        or stopped_data.get("state") not in ("stopped", "failed")
    ):
        detail = str(
            stopped_data.get("error")
            or f"state={stopped_data.get('state')!r}"
        )[:300]
        raise RuntimeError(
            f"发现残留性能录制 {session_id}，perf-stop 失败：{detail}"
        )

    target = status_data.get("targetPackage")
    duration = status_data.get("durationMs")
    recovered = StaleRecording(
        session_id=session_id.strip(),
        target_package=target if isinstance(target, str) else None,
        duration_ms=duration if isinstance(duration, int) else None,
    )
    emit_text(
        "perf_stale_recording_stopped",
        session_id=recovered.session_id,
        target=recovered.target_package or "",
        duration_ms=recovered.duration_ms or 0,
    )
    return recovered


__all__ = ["STATUS_TIMEOUT_S", "STOP_TIMEOUT_S", "StaleRecording", "clear_stale_perf_recording"]
