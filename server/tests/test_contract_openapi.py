"""OpenAPI 契约基线（无需数据库）。

三件事：
1. `app.openapi()` 必须与 `docs/contracts/openapi.json` 完全一致；
   接口形状变化时测试失败，必须显式重新导出基线，避免静默漂移。
2. 对外 OpenAPI 只包含 `/api/v1`；runner 的 `/internal/*` 不进公开契约。
3. 被前端消费的响应模型必须显式声明 extra 策略（allow/forbid），
   不允许 pydantic 默认的 ignore —— 那会在响应序列化时静默丢字段。

重新生成基线：
    D:/python312/python.exe scripts/export_openapi.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "docs" / "contracts" / "openapi.json"

#: 现有只读/列表端点必须使用具名响应模型（不能返回无 schema 的裸 dict）。
EXPECTED_RESPONSE_MODELS = {
    "/api/v1/overview": "OverviewOut",
    "/api/v1/applications": "ApplicationsOut",
    "/api/v1/resources": "ResourcesOut",
    "/api/v1/projects": "ProjectsOut",
    "/api/v1/runs": "RunsOut",
    "/api/v1/tasks": "TasksOut",
    "/api/v1/tasks/{task_id}/revisions": "TaskRevisionListOut",
}

#: 前端类型检查会用到的 schema，必须出现在 components.schemas。
REQUIRED_SCHEMAS = {
    "OverviewOut",
    "ApplicationRecordOut",
    "ApplicationsOut",
    "ResourceProfileOut",
    "ResourceRecordOut",
    "ResourcesOut",
    "ProjectRecordOut",
    "ProjectsOut",
    "RunRecordOut",
    "RunsOut",
    "TaskRecordOut",
    "TasksOut",
    "TaskRevisionRecord",
    "TaskRevisionListOut",
    "ErrorEnvelope",
}


def _live_openapi() -> dict:
    """与导出脚本使用同一个稳定投影（见 app/contract.py）。"""
    from app.contract import project_openapi
    from app.main import app

    return project_openapi(app.openapi())


def test_baseline_file_exists() -> None:
    assert BASELINE.is_file(), (
        f"缺少 OpenAPI 基线 {BASELINE}；运行 scripts/export_openapi.py 生成"
    )


def test_openapi_matches_committed_baseline() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    live = _live_openapi()
    assert live == baseline, (
        "OpenAPI 与基线不一致。确认契约变更后运行 "
        "`D:/python312/python.exe scripts/export_openapi.py` 重新生成基线。"
    )


def test_public_openapi_excludes_internal_protocol() -> None:
    paths = _live_openapi()["paths"]
    internal = [p for p in paths if p.startswith("/internal")]
    assert not internal, f"/internal 不应出现在公开 OpenAPI: {internal}"
    non_v1 = [p for p in paths if not p.startswith("/api/v1")]
    assert not non_v1, f"公开路径必须以 /api/v1 开头: {non_v1}"


def _response_ref(operation: dict, status_prefix: str = "2") -> str:
    """取一个 operation 的 2xx 响应 $ref（无具名模型时为空串）。

    契约投影（app/contract.py）把每个响应压成 schema 本体：{"200": {"$ref": ...}}。
    """
    for status, response in sorted(operation.get("responses", {}).items()):
        if not status.startswith(status_prefix):
            continue
        ref = response.get("$ref", "") if isinstance(response, dict) else ""
        if ref:
            return ref
    return ""


def test_expected_endpoints_use_named_response_models() -> None:
    """具名响应模型以公开 OpenAPI 投影的 2xx $ref 为准。

    不再走 `APIRoute.response_model` 路由属性：fastapi>=0.16 起该属性不再
    承载具名模型（内部行为漂移），而契约的真实载体是 openapi 文档本身。
    """
    paths = _live_openapi()["paths"]
    for path, model_name in EXPECTED_RESPONSE_MODELS.items():
        operation = paths.get(path, {}).get("get")
        assert operation is not None, f"GET {path} 不在公开 OpenAPI 中"
        ref = _response_ref(operation)
        actual = ref.rsplit("/", 1)[-1] if ref else None
        assert actual == model_name, (
            f"GET {path} 期望响应模型 {model_name}，实际 {actual!r}"
        )


def test_response_models_declare_explicit_extra_policy() -> None:
    """响应模型不能沿用 pydantic 默认 extra=ignore（会静默丢字段）。

    只检查 pydantic BaseModel 响应模型；返回注解是 `dict[...]` 的端点不在此列
    （它们不经过模型序列化，也就不会因 extra 策略丢字段）。模型从公开 OpenAPI
    的 2xx $ref 解析（同上，路由属性跨 fastapi 版本不可靠），再回 app.schemas
    取类检查 model_config。
    """
    import app.schemas as app_schemas
    from pydantic import BaseModel

    offenders: list[str] = []
    seen: set[str] = set()
    for path, methods in _live_openapi()["paths"].items():
        for method, operation in methods.items():
            ref = _response_ref(operation)
            if not ref:
                continue
            name = ref.rsplit("/", 1)[-1]
            if name in seen:
                continue
            seen.add(name)
            model = getattr(app_schemas, name, None)
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                continue
            extra = model.model_config.get("extra")
            if extra not in ("allow", "forbid"):
                offenders.append(name)
    assert not offenders, f"响应模型未声明 extra 策略: {sorted(set(offenders))}"


def test_required_schemas_present() -> None:
    schemas = _live_openapi().get("schemas", {})
    missing = REQUIRED_SCHEMAS - set(schemas)
    assert not missing, f"OpenAPI 缺少 schema: {sorted(missing)}"


def test_error_envelope_schema_documents_fields() -> None:
    schemas = _live_openapi()["schemas"]
    assert "ErrorEnvelope" in schemas
    props = schemas["ErrorEnvelope"]["properties"]
    assert set(props) >= {"code", "message", "request_id", "details"}
