"""统一错误契约：错误码注册表、request_id 可追溯、敏感值不回显。

这些用例全部是静态/进程内测试，不连接数据库：
- 错误码注册表用 AST 扫描 app/ 源码，保证没有“文档里没有的码”。
- 错误信封用 FastAPI TestClient 请求不存在的路径（框架 404），
  以及 POST /tasks 的请求体校验失败（pydantic 422），都不会触发 SQL。
- 脱敏直接测 errors.redact_sensitive，并用真实配置的 database_url 作为已知敏感值。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVER_DIR = Path(__file__).resolve().parents[1]
APP_DIR = SERVER_DIR / "app"


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _literal_codes_in_app() -> set[str]:
    """收集 app/ 里所有 ApiError / conflict 调用的字面量错误码。

    两种写法：
      - ApiError(status, "code", ...)        第 2 个位置参数
      - conflict("code", ...)                第 1 个位置参数
      - ApiError(..., code="code")           关键字参数
    """
    codes: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "ApiError" and len(node.args) >= 2:
                arg = node.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    codes.add(arg.value)
            if name == "conflict" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    codes.add(arg.value)
            for kw in node.keywords:
                if kw.arg == "code" and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str):
                        codes.add(kw.value.value)
    return codes


def test_every_error_code_is_registered() -> None:
    """app/ 里出现的错误码必须都在统一注册表里（防止文档外的码漂移）。"""
    from app.errors import ERROR_CODES

    used = _literal_codes_in_app()
    missing = used - set(ERROR_CODES)
    assert not missing, f"未登记的错误码: {sorted(missing)}"
    assert used, "没有扫描到任何错误码，扫描逻辑失效"


def test_registered_codes_are_snake_case() -> None:
    from app.errors import ERROR_CODES

    bad = [c for c in ERROR_CODES if not c.replace("_", "").isalnum() or c.lower() != c]
    assert not bad, f"错误码必须是 snake_case: {bad}"


def test_error_envelope_shape_and_request_id_header(client: TestClient) -> None:
    """任何错误都是 {code,message,request_id,details}，且响应头回带同一个 request_id。"""
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert set(body) == {"code", "message", "request_id", "details"}
    assert body["code"] == "not_found"
    assert body["request_id"]
    assert resp.headers.get("X-Request-Id") == body["request_id"]


def test_client_supplied_request_id_is_traced(client: TestClient) -> None:
    """客户端带 X-Request-Id 时必须原样贯穿到响应头与信封。"""
    rid = "contract-trace-0001"
    resp = client.get("/api/v1/does-not-exist", headers={"X-Request-Id": rid})
    assert resp.headers.get("X-Request-Id") == rid
    assert resp.json()["request_id"] == rid


def test_validation_error_uses_envelope(client: TestClient) -> None:
    """请求体校验失败也走统一信封，而不是 FastAPI 默认的 {"detail": ...}。"""
    resp = client.post(
        "/api/v1/tasks",
        json={"name": ""},
        headers={"X-TestDock-Client": "web"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert body["request_id"] == resp.headers.get("X-Request-Id")


def test_sensitive_details_are_redacted() -> None:
    """错误 details 中的密码/token/数据库连接串不得回显。"""
    from app.config import settings
    from app.errors import redact_sensitive

    secret_url = settings.database_url
    redacted = redact_sensitive(
        {
            "password": "super-secret",
            "api_token": "tok_live_123",
            "nested": {"control_token": "abc", "note": "keep me"},
            "database_url": secret_url,
            "message": f"failed to connect: {secret_url}",
            "items": [{"secret": "s1"}, "plain"],
            # 资源标识不是凭据，不能被误脱敏（否则错误信封失去可追溯性）
            "session_id": "sess-0001",
        }
    )

    dumped = repr(redacted)
    assert "super-secret" not in dumped
    assert "tok_live_123" not in dumped
    assert "abc" not in dumped
    assert secret_url not in dumped
    assert "keep me" in dumped
    assert "plain" in dumped
    assert redacted["password"] == "***"
    assert redacted["session_id"] == "sess-0001"


def test_health_does_not_echo_credentials(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "@" not in body["database_target"]
