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
from tests._p3_common import CLIENT_HEADERS, requires_db
from tests._p3_common import api_client as api_client  # noqa: F401 - 夹具注册
from tests._p3_common import p3_project as p3_project  # noqa: F401 - 夹具注册
from tests._p3_common import sync_engine as sync_engine  # noqa: F401 - 夹具注册

#: vendor viewer 的快照 id 是 `uuid4().hex[:16]`（vendor/mobile_auto/src/
#: mobile_auto/viewer/store.py:43），不是带连字符的 UUID。平台把它拼进上游
#: path 前按这个 id 空间校验，所以测试也只用这种形态的 id。
_SOURCE = "0011223344556677"   # 框选来源的冻结快照
_FRESH = "8899aabbccddeeff"    # 验证时重新捕获的新快照
_OTHER = "ffeeddccbbaa9988"    # 另一个快照（用于"快照变了"分支）
_SNAPSHOT = "0123456789abcdef"


def _request(payload: dict) -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body}

    return Request({"type": "http"}, receive)


def _capture_response(snapshot_id: str = _FRESH) -> Response:
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
        _request({"snapshot_id": _SOURCE, "region": list(region), "threshold": threshold}),
        "session",
        None,
    )
    return json.loads(response.body)


def _register_body(token: str | None, **overrides) -> dict:
    body = {
        "snapshot_id": _FRESH,
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
    assert verified["snapshot_id"] == _FRESH
    assert verified["source_snapshot_id"] == _SOURCE
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
            {"snapshot_id": _FRESH, "region": [581, 1048, 173, 173], "logical": "buttons/ok.png"},
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
        {"snapshot_id": _OTHER},            # 快照变了
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


# --------------------------------------------------------------------------- #
# 客户端 snapshot_id 只允许 vendor 真实 id 空间（uuid4().hex[:16]）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "0123456789abcde",          # 15 位
        "0123456789abcdef0",        # 17 位
        "0123456789ABCDEF",         # 大写不在 id 空间
        "../../etc/passwd",         # 路径穿越
        "0123456789abcdef/../../x",
        "0123456789abcdef?x=1",     # 查询串注入
        "fresh",                    # 任意字符串
        "0123456789abcdeg",         # 非十六进制
        "3f2a1b4c-5d6e-4f70-8a1b-2c3d4e5f6071",  # RFC UUID 也不是上游 id
    ],
)
async def test_validate_crop_rejects_snapshot_id_outside_vendor_id_space(monkeypatch, bad):
    """非法快照 id 必须 400，且绝不把它拼进上游 URL。"""
    forwarded: list = []
    _patch_forward(monkeypatch, forwarded=forwarded)

    with pytest.raises(ApiError) as excinfo:
        await debug.validate_crop(
            _request({"snapshot_id": bad, "region": [1, 2, 3, 4], "threshold": 0.8}),
            "session",
            None,
        )

    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "validation_error"
    assert forwarded == [], "非法 snapshot_id 不得触达 vendor"


@pytest.mark.asyncio
async def test_proxy_snapshot_id_endpoints_reject_illegal_snapshot_id(monkeypatch):
    """image/tree 代理同样不得把客户端字符串直接拼进上游 path。"""
    forwarded: list = []

    async def active_row(*args):
        return {"id": "session"}

    async def forward(sid, method, path, **kwargs):
        forwarded.append((method, path))
        return Response(b"pixels")

    monkeypatch.setattr(debug, "_active_row", active_row)
    monkeypatch.setattr(debug, "_forward", forward)

    for call in (
        lambda: debug.proxy_snapshot_image("session", "../secrets/image", None),
        lambda: debug.proxy_snapshot_tree("session", "0123456789abcdef/x", None),
    ):
        with pytest.raises(ApiError) as excinfo:
            await call()
        assert excinfo.value.status_code == 400
        assert excinfo.value.code == "validation_error"

    assert forwarded == [], "非法 snapshot_id 不得触达 vendor"

    # 合法 id 正常转发（证明校验只挡非法形态）
    await debug.proxy_snapshot_image("session", _SNAPSHOT, None)
    assert forwarded == [("GET", f"/api/v1/snapshots/{_SNAPSHOT}/image")]


# --------------------------------------------------------------------------- #
# 会话关闭：调试验证凭证随之作废
# --------------------------------------------------------------------------- #
def _insert_active_debug_session(sync_engine, project: dict, session_id: str) -> None:
    from sqlalchemy import text

    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO debug_sessions (id, project_id, resource_id, actor_ref,"
                "                           state, expires_at)"
                " VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:rid AS uuid),"
                "         'pytest', 'active', now() + interval '10 minutes')"
            ),
            {
                "id": session_id,
                "pid": project["project_id"],
                "rid": project["resource_id"],
            },
        )


@requires_db
def test_closing_debug_session_drops_its_crop_verifications(
    api_client, p3_project, sync_engine
):
    """会话关闭后旧凭证必须失效：否则另一个会话能拿它去登记模板。"""
    import uuid as uuid_mod

    session_id = str(uuid_mod.uuid4())
    other_session_id = str(uuid_mod.uuid4())
    _insert_active_debug_session(sync_engine, p3_project, session_id)
    token = debug._issue_crop_verification(
        session_id=session_id, snapshot_id=_SNAPSHOT, region=[1, 2, 3, 4], threshold=0.8
    )
    other_token = debug._issue_crop_verification(
        session_id=other_session_id, snapshot_id=_SNAPSHOT, region=[1, 2, 3, 4], threshold=0.8
    )
    try:
        assert token in debug._CROP_VERIFICATIONS
        response = api_client.delete(
            f"/api/v1/debug-sessions/{session_id}", headers=CLIENT_HEADERS
        )
        assert response.status_code == 200, response.text
        assert token not in debug._CROP_VERIFICATIONS, "会话关闭后旧凭证必须作废"
        assert other_token in debug._CROP_VERIFICATIONS, "别的会话的凭证不受影响"
    finally:
        debug._CROP_VERIFICATIONS.pop(token, None)
        debug._CROP_VERIFICATIONS.pop(other_token, None)
        # 清理关闭后的会话行由 project 夹具的项目级删除覆盖（drop_project 含 debug_sessions）


@requires_db
def test_closing_session_via_runner_exit_also_drops_verifications(
    p3_project, sync_engine
):
    """非 DELETE 的关闭路径（runner 退出兜底 _close_session）同样要清理。"""
    import asyncio
    import uuid as uuid_mod

    session_id = str(uuid_mod.uuid4())
    _insert_active_debug_session(sync_engine, p3_project, session_id)
    token = debug._issue_crop_verification(
        session_id=session_id, snapshot_id=_SNAPSHOT, region=[1, 2, 3, 4], threshold=0.8
    )
    try:
        asyncio.run(debug._close_session(session_id, reason="runner_exit"))
        assert token not in debug._CROP_VERIFICATIONS
    finally:
        debug._CROP_VERIFICATIONS.pop(token, None)
