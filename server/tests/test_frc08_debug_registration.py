"""工单 08（首期收口）：模板登记必须有「刚用新画面验证通过」的服务端证明。

验收对应：
- 框选验证用新画面真实匹配；验证前/失败时不能登记模板 → 无凭证登记 409。
- 框选/阈值/快照/会话改变后旧验证结果不可复用 → 凭证绑定 session+snapshot+region+threshold。
- 凭证一次性、有有效期 → 复用/过期 409。

只走公共接口：validate_crop / create_template / update_template 的请求-响应，
不依赖前端 disabled，也不查库。
"""

from __future__ import annotations

import json

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.errors import ApiError
from app.routers import debug


def _request(payload: dict) -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body}

    return Request({"type": "http"}, receive)


def _capture_response(snapshot_id: str = "fresh") -> Response:
    return Response(
        json.dumps({"snapshot_id": snapshot_id, "width": 1080, "height": 2400}),
        media_type="application/json",
    )


def _patch_forward(monkeypatch, *, forwarded: list, count: int = 1):
    """vendor 代理替身：记录转发并给 validate-crop 一个确定匹配结果。"""

    async def session(*args):
        return "session"

    async def forward(sid, method, path, **kwargs):
        forwarded.append((method, path, kwargs.get("json_body")))
        if path == "/api/v1/snapshots":
            return _capture_response()
        if path.startswith("/api/v1/snapshots/"):
            return Response(b"pixels")
        return Response(json.dumps({"logical": "buttons/ok.png"}), media_type="application/json")

    async def match(source, current, region, threshold):
        if count == 1:
            return {
                "count": 1,
                "matches": [{"x": region[0], "y": region[1], "width": region[2], "height": region[3]}],
                "scores": [1.0],
            }
        return {"count": count, "matches": [], "scores": []}

    monkeypatch.setattr(debug, "_template_session", session)
    monkeypatch.setattr(debug, "_forward", forward)
    monkeypatch.setattr(debug, "_match_crop", match)


async def _verified_token(region=(581, 1048, 173, 173), threshold=0.8) -> dict:
    response = await debug.validate_crop(
        _request({"snapshot_id": "frozen", "region": list(region), "threshold": threshold}),
        "session",
        None,
    )
    return json.loads(response.body)


def _register_body(token: str | None, **overrides) -> dict:
    body = {
        "snapshot_id": "fresh",
        "region": [581, 1048, 173, 173],
        "logical": "buttons/ok.png",
        "threshold": 0.8,
    }
    if token is not None:
        body["verification"] = token
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_registration_without_verification_is_rejected(monkeypatch):
    """服务端必须独立拒绝未验证登记：不是靠前端 disabled。"""
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded)

    with pytest.raises(ApiError) as excinfo:
        await debug.create_template(_request(_register_body(None)), "session", None)

    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "crop_not_verified"
    assert forwarded == [], "未验证的登记不得触达 vendor"


@pytest.mark.asyncio
async def test_verification_is_bound_to_the_fresh_capture_and_matched_box(monkeypatch):
    """验证返回的新快照 + 新画面里的命中框就是登记依据。"""
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded)

    verified = await _verified_token()
    assert verified["count"] == 1
    assert verified["snapshot_id"] == "fresh"
    assert verified["source_snapshot_id"] == "frozen"
    assert verified["region"] == [581, 1048, 173, 173]
    assert verified["verification"]

    forwarded.clear()
    await debug.create_template(
        _request(_register_body(verified["verification"])), "session", None
    )
    assert forwarded == [
        (
            "POST",
            "/api/v1/templates",
            {"snapshot_id": "fresh", "region": [581, 1048, 173, 173], "logical": "buttons/ok.png"},
        )
    ], "登记必须用验证时的新快照与命中框，且不外泄验证凭证"


@pytest.mark.asyncio
async def test_failed_match_issues_no_verification_and_blocks_registration(monkeypatch):
    """零匹配不得登记；凭证缺失时登记被拒。"""
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded, count=0)

    verified = await _verified_token()
    assert verified["count"] == 0
    assert verified.get("verification") in (None, "")

    with pytest.raises(ApiError) as excinfo:
        await debug.create_template(_request(_register_body(None)), "session", None)
    assert excinfo.value.code == "crop_not_verified"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"region": [581, 1000, 173, 173]},   # 框选变了
        {"snapshot_id": "other"},            # 快照变了
        {"threshold": 0.95},                 # 阈值变了
    ],
)
async def test_verification_is_invalidated_by_region_snapshot_or_threshold(monkeypatch, overrides):
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded)
    token = (await _verified_token())["verification"]

    forwarded.clear()
    with pytest.raises(ApiError) as excinfo:
        await debug.create_template(_request(_register_body(token, **overrides)), "session", None)
    assert excinfo.value.code == "crop_not_verified"
    assert forwarded == []


@pytest.mark.asyncio
async def test_verification_is_single_use(monkeypatch):
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded)
    token = (await _verified_token())["verification"]

    await debug.create_template(_request(_register_body(token)), "session", None)
    with pytest.raises(ApiError) as excinfo:
        await debug.create_template(_request(_register_body(token)), "session", None)
    assert excinfo.value.code == "crop_not_verified"


@pytest.mark.asyncio
async def test_verification_expires(monkeypatch):
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded)
    monkeypatch.setattr(debug, "CROP_VERIFICATION_TTL_SECONDS", -1.0)
    token = (await _verified_token())["verification"]

    with pytest.raises(ApiError) as excinfo:
        await debug.create_template(_request(_register_body(token)), "session", None)
    assert excinfo.value.code == "crop_not_verified"


@pytest.mark.asyncio
async def test_verification_from_another_session_is_rejected(monkeypatch):
    """会话改变（或凭证来自别的会话）后旧验证不可复用。"""
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded)
    token = (await _verified_token())["verification"]

    async def other_session(*args):
        return "other-session"

    monkeypatch.setattr(debug, "_template_session", other_session)
    with pytest.raises(ApiError) as excinfo:
        await debug.create_template(_request(_register_body(token)), "other-session", None)
    assert excinfo.value.code == "crop_not_verified"


@pytest.mark.asyncio
async def test_registration_shape_is_validated_before_vendor(monkeypatch):
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded)
    token = (await _verified_token())["verification"]

    forwarded.clear()
    with pytest.raises(ApiError) as excinfo:
        await debug.create_template(_request(_register_body(token, region=[1, 2, 3])), "session", None)
    assert excinfo.value.code == "validation_error"
    assert forwarded == []
