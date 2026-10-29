"""OpenAPI 契约投影（工单 01）。

为什么不直接提交整份 `app.openapi()`：FastAPI / pydantic 的小版本升级会改变
docstring、operationId、示例等非契约字段，导致基线测试对依赖升级过敏。
这里只保留真正的对外契约：

- 每个路径 + 方法的参数（name / in / required）；
- 请求体与各状态响应的 JSON schema（$ref 或 type/properties）；
- components.schemas（响应模型字段与必填性）。

`scripts/export_openapi.py` 写出的基线与
`server/tests/test_contract_openapi.py` 比较的都是这个投影。
"""

from __future__ import annotations

from typing import Any

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def _json_schema(container: Any) -> Any:
    """取 container["content"]["application/json"]["schema"]，没有则 None。"""
    if not isinstance(container, dict):
        return None
    content = container.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        return None
    return media.get("schema")


def _parameters(operation: dict[str, Any]) -> list[dict[str, Any]]:
    params = []
    for param in operation.get("parameters", []) or []:
        if not isinstance(param, dict):
            continue
        params.append(
            {
                "name": param.get("name"),
                "in": param.get("in"),
                "required": bool(param.get("required")),
            }
        )
    return params


def project_openapi(schema: dict[str, Any]) -> dict[str, Any]:
    """把 FastAPI 生成的 OpenAPI 压成稳定契约投影。"""
    paths: dict[str, Any] = {}
    for path, operations in sorted((schema.get("paths") or {}).items()):
        if not isinstance(operations, dict):
            continue
        methods: dict[str, Any] = {}
        for method, operation in sorted(operations.items()):
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            responses = {}
            for status, response in sorted((operation.get("responses") or {}).items()):
                responses[str(status)] = _json_schema(response)
            methods[method.lower()] = {
                "parameters": _parameters(operation),
                "request": _json_schema(operation.get("requestBody")),
                "responses": responses,
            }
        paths[path] = methods

    schemas = (schema.get("components") or {}).get("schemas") or {}
    return {"paths": paths, "schemas": schemas}
