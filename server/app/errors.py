"""统一错误信封与业务异常（api-design.md §1.2）。

为什么不用 HTTPException(detail=...)：FastAPI 默认把 detail 序列化成 {"detail": ...}，
而平台契约要求 {code, message, request_id, details}（与 vendor viewer 信封一致）。
这里用一个继承 HTTPException 的 ApiError 类：既能被 FastAPI 的异常体系识别
（handlers / OpenAPI 都照常工作），又由 main.py 里注册的处理器渲染成信封。

status / code 的对应关系见 api-design.md §1.2 的表格；本模块只登记 P2 实际用到的
几个码，避免出现"文档里没有的错误码"。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

# web 写操作必须携带的客户端标识头（development-plan.md §8.1：防跨站表单）
CLIENT_HEADER = "X-TestDock-Client"
CLIENT_HEADER_VALUE = "web"


class ApiError(HTTPException):
    """带错误码与结构化 details 的业务异常。

    detail 里放 {"code", "message", "details"}，由 main.api_error_handler 展开成
    完整信封（request_id 在处理器里统一补）。
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.extra_details = details if details is not None else {}


# --------------------------------------------------------------------------- #
# 便捷构造器：路由层只表达"这件事不允许"，不关心 JSON 形状
# --------------------------------------------------------------------------- #
def client_header_required() -> ApiError:
    return ApiError(
        428,
        "client_header_required",
        f"写操作必须携带请求头 {CLIENT_HEADER}: {CLIENT_HEADER_VALUE}",
        {"header": CLIENT_HEADER, "expected": CLIENT_HEADER_VALUE},
    )


def not_found(entity: str, entity_id: str) -> ApiError:
    return ApiError(404, "not_found", f"{entity} {entity_id} 不存在", {"entity": entity, "id": entity_id})


def stale_version(latest: Any) -> ApiError:
    """lock_version CAS 失败：details 必须带最新对象，前端据此刷新（api-design.md §1.3）。"""
    return ApiError(409, "stale_version", "任务已被他人更新，请刷新后重试", {"latest": latest})


def conflict(code: str, message: str, details: Any | None = None) -> ApiError:
    """通用 409：唯一约束冲突等"当前状态不允许这么做"但不在错误码表细分里的情况。"""
    return ApiError(409, code, message, details or {})


def illegal_transition(current: str, target: str, reason: str) -> ApiError:
    return ApiError(
        409,
        "illegal_transition",
        reason,
        {"current": current, "target": target},
    )


def bad_request(message: str, details: Any | None = None) -> ApiError:
    return ApiError(400, "validation_error", message, details or {})


def validation_error(messages: list[str]) -> ApiError:
    return ApiError(400, "validation_error", "；".join(messages) or "请求校验失败", {"errors": messages})


def task_not_ready(*, missing: list[str], invalid: list[str]) -> ApiError:
    """readiness 必要条件不满足（任务书的 P2 validate 契约）。"""
    return ApiError(
        422,
        "task_not_ready",
        "任务尚未满足可运行条件：" + "；".join(missing + invalid),
        {"missing": missing, "invalid": invalid},
    )


def readiness_incomplete(missing: list[str]) -> ApiError:
    """api-design.md §1.2 里的 422 readiness_incomplete（运行前置）。"""
    return ApiError(422, "readiness_incomplete", "修订未就绪：" + "；".join(missing), {"missing": missing})


def discover_failed(message: str, stderr_tail: list[str], returncode: int | None = None) -> ApiError:
    return ApiError(
        422,
        "discover_failed",
        message,
        {"stderr_tail": stderr_tail, "returncode": returncode, "lines": len(stderr_tail)},
    )


# --------------------------------------------------------------------------- #
# P3：运行生命周期 / 租约 / runner 内部协议
# --------------------------------------------------------------------------- #
def state_conflict(run_id: str, current: str, expect: str) -> ApiError:
    """expect_state 与当前状态不符（api-design.md §1.2 state_conflict）。"""
    return ApiError(
        409,
        "state_conflict",
        f"运行 {run_id} 当前状态为 {current!r}，不是期望的 {expect!r}",
        {"run_id": run_id, "current": current, "expect": expect},
    )


def illegal_run_transition(run_id: str, current: str, target: str, detail: str) -> ApiError:
    """状态机不允许的迁移（api-design.md §1.2 illegal_transition）。"""
    return ApiError(
        409,
        "illegal_transition",
        f"运行 {run_id} 不能从 {current!r} 迁移到 {target!r}：{detail}",
        {"run_id": run_id, "current": current, "target": target},
    )


def terminal_run_immutable(run_id: str, current: str) -> ApiError:
    """终态不可再改（development-plan.md §7.2）。"""
    return ApiError(
        409,
        "illegal_transition",
        f"运行 {run_id} 已处于终态 {current!r}，不允许再次迁移（重跑请新建 run）",
        {"run_id": run_id, "current": current, "terminal": True},
    )


def lease_conflict(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(409, "lease_conflict", message, details or {})


def fence_mismatch(run_id: str, expected: int | None, provided: int | None) -> ApiError:
    """runner 的 fencing token 与 DB 租约不一致（api-design.md §1.2）。"""
    return ApiError(
        409,
        "fence_mismatch",
        f"运行 {run_id} 的 fencing token 失配，执行身份已失效",
        {"run_id": run_id, "expected": expected, "provided": provided},
    )


def device_not_ready(resource_id: str, status: str) -> ApiError:
    return ApiError(
        424,
        "device_not_ready",
        f"设备 {resource_id} 当前状态为 {status!r}，不可执行",
        {"resource_id": resource_id, "status": status},
    )


def runner_spawn_failed(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(503, "runner_spawn_failed", message, details or {})


def control_token_invalid() -> ApiError:
    return ApiError(401, "control_token_invalid", "缺少或错误的 X-Control-Token")
