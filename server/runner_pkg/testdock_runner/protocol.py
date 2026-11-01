"""runner 与 API 的内部协议客户端（§8.3）+ 事件输出约定（§10.1）。

为什么 runner 不用 SDK / 不连库
--------------------------------
runner 跑在可能失败的环境里（设备掉线、pytest 崩、被 taskkill）。它唯一需要做
的两件事是：把进度告诉 API、把终态告诉 API。用一个极小的 HTTP 客户端最稳：
没有连接池、没有 ORM、每次调用 5s 超时 + 最多 2 次重试；全部失败也只记日志，
绝不因为"上报失败"而让设备操作半途而废。

stdout 约定（§10.1）：每行一个 JSON 对象，字段 `t` 是类型：
  {"t":"stage","name":"ready","progress":20}
  {"t":"text","name":"pytest: ...."}
  {"t":"result","outcome":"failed","junit":{"tests":12,"failed":1}}
API 侧逐行读并转发成 run_events + WS 帧。非 JSON 行也必须能容忍。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

CONTROL_TOKEN_HEADER = "X-Control-Token"
REQUEST_TIMEOUT = 5.0
MAX_RETRIES = 2


@dataclass
class ControlError(RuntimeError):
    """内部协议调用失败。status=409 且 code=fence_mismatch 时 fence_mismatch=True。"""

    status: int
    code: str
    body: str

    @property
    def fence_mismatch(self) -> bool:
        return self.status == 409 and "fence_mismatch" in (self.body or "")


class ControlClient:
    """`http://host:port/internal/runs/{id}/...` 的最小客户端。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        run_id: str,
        *,
        timeout: float = REQUEST_TIMEOUT,
        retries: int = MAX_RETRIES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.run_id = str(run_id)
        self.timeout = timeout
        self.retries = retries

    # -- 基础 ------------------------------------------------------------- #
    def _url(self, suffix: str) -> str:
        return "%s/internal/runs/%s/%s" % (self.base_url, self.run_id, suffix.lstrip("/"))

    def _request(
        self, method: str, suffix: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        data = None
        headers = {CONTROL_TOKEN_HEADER: self.token}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            self._url(suffix), data=data, headers=headers, method=method
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                # 4xx 不重试：重试也只会得到同样的拒绝（fence/状态冲突）
                if 400 <= exc.code < 500:
                    code = _code_of(body)
                    raise ControlError(exc.code, code, body) from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(0.5 * (attempt + 1))
        raise ControlError(0, "network_error", str(last_error))

    # -- 协议方法 --------------------------------------------------------- #
    def ack(self, *, pid: int, started_at: str, fencing_token: int) -> dict[str, Any]:
        return self._request(
            "POST",
            "ack",
            {"pid": pid, "started_at": started_at, "fencing_token": fencing_token},
        )

    def heartbeat(
        self, *, pid: int, progress: int, stage: int, fencing_token: int
    ) -> dict[str, Any]:
        """返回 {cancel, fence_ok, state}；网络失败由调用方决定是否忽略。"""
        return self._request(
            "POST",
            "heartbeat",
            {
                "pid": pid,
                "progress": progress,
                "stage": stage,
                "fencing_token": fencing_token,
            },
        )

    def check_fence(self, fencing_token: int) -> dict[str, Any]:
        return self._request("GET", "fence?token=%d" % int(fencing_token))

    def events(self, events: list[Mapping[str, Any]]) -> dict[str, Any]:
        return self._request("POST", "events", {"events": list(events)})

    def complete(
        self,
        *,
        outcome: str,
        fencing_token: int,
        components: list[Mapping[str, Any]] | None = None,
        cases: list[Mapping[str, Any]] | None = None,
        metrics: Mapping[str, Any] | None = None,
        junit: Mapping[str, Any] | None = None,
        artifacts_dir: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "complete",
            {
                "outcome": outcome,
                "fencing_token": fencing_token,
                "components": list(components or []),
                "cases": list(cases or []),
                "metrics": dict(metrics or {}),
                "junit": dict(junit or {}),
                "artifacts_dir": artifacts_dir,
                "reason": reason,
            },
        )

    def fail(
        self,
        *,
        error_code: str,
        message: str,
        stage: str,
        fencing_token: int,
        components: list[Mapping[str, Any]] | None = None,
        artifacts_dir: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "fail",
            {
                "error_code": error_code,
                "message": message[:4000],
                "stage": stage,
                "fencing_token": fencing_token,
                "components": list(components or []),
                # 失败也可能已有产物（如 joint 超时前写下的 report.json/采集窗口），
                # 交给平台登记，报告才能说明采集确实发生过。
                "artifacts_dir": artifacts_dir,
            },
        )


class DebugControlClient(ControlClient):
    """调试会话有自己的租约和状态，不能使用 test_runs 协议。"""

    def _url(self, suffix: str) -> str:
        return "%s/internal/debug-sessions/%s/%s" % (self.base_url, self.run_id, suffix.lstrip("/"))

    def ready(self, *, port: int, fencing_token: int) -> dict[str, Any]:
        return self._request("POST", "ready", {"port": port, "fencing_token": fencing_token})

    def close(self, *, reason: str, fencing_token: int) -> dict[str, Any]:
        return self._request("POST", "close", {"reason": reason, "fencing_token": fencing_token})


def _code_of(body: str) -> str:
    try:
        parsed = json.loads(body)
    except ValueError:
        return "error"
    if isinstance(parsed, Mapping):
        detail = parsed.get("detail")
        if isinstance(detail, Mapping) and detail.get("code"):
            return str(detail["code"])
        if parsed.get("code"):
            return str(parsed["code"])
    return "error"


# --------------------------------------------------------------------------- #
# stdout 事件（§10.1：每行一个 JSON）
# --------------------------------------------------------------------------- #


def emit(event: Mapping[str, Any]) -> None:
    """写一行 JSON 到 stdout 并立即 flush（API 逐行读，行缓冲会丢现场）。"""
    try:
        sys.stdout.write(json.dumps(dict(event), ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 - stdout 坏了不能拖垮设备收尾
        pass


def emit_stage(name: str, progress: int, **extra: Any) -> None:
    payload = {"t": "stage", "name": name, "progress": int(progress)}
    payload.update(extra)
    emit(payload)


def emit_text(name: str, **extra: Any) -> None:
    payload = {"t": "text", "name": name}
    payload.update(extra)
    emit(payload)


def emit_result(**payload: Any) -> None:
    emit({"t": "result", **payload})


__all__ = [
    "CONTROL_TOKEN_HEADER",
    "ControlClient",
    "ControlError",
    "emit",
    "emit_result",
    "emit_stage",
    "emit_text",
]
