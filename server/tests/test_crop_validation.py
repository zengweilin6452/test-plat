"""Unregistered crops are matched against a fresh capture without asset writes."""
import json
from pathlib import Path

import pytest
from app.routers import debug
from starlette.requests import Request
from starlette.responses import Response


@pytest.mark.asyncio
async def test_crop_validation_captures_again_and_never_registers(monkeypatch):
    calls = []

    async def session(*args):
        return "session"

    async def forward(sid, method, path, **kwargs):
        calls.append((method, path))
        if method == "POST":
            return Response(json.dumps({"snapshot_id": "fresh"}))
        return Response(b"source" if "/old/" in path else b"current")

    async def match(source, current, region, threshold):
        assert (source, current, region, threshold) == (b"source", b"current", [1, 2, 3, 4], .8)
        return {"count": 0, "matches": [], "scores": []}

    monkeypatch.setattr(debug, "_template_session", session)
    monkeypatch.setattr(debug, "_forward", forward)
    monkeypatch.setattr(debug, "_match_crop", match)
    payload = json.dumps({"snapshot_id": "old", "region": [1, 2, 3, 4], "threshold": .8}).encode()

    async def receive():
        return {"type": "http.request", "body": payload}

    response = await debug.validate_crop(Request({"type": "http"}, receive), "session", None)
    assert json.loads(response.body) == {
        "count": 0, "matches": [], "scores": [],
        "snapshot_id": "fresh", "source_snapshot_id": "old",
    }
    assert calls == [("GET", "/api/v1/snapshots/old/image"),
                     ("POST", "/api/v1/snapshots"),
                     ("GET", "/api/v1/snapshots/fresh/image")]


def test_real_vendor_match_accepts_crop_and_rejects_absent_crop(monkeypatch):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "server" / "runner_pkg"))
    monkeypatch.syspath_prepend(str(root / "vendor" / "mobile_auto" / "src"))
    from testdock_runner.crop_match import match_crop

    rng = np.random.default_rng(12)
    image = rng.integers(0, 256, (100, 120, 3), dtype=np.uint8)
    def png(frame):
        return cv2.imencode(".png", frame)[1].tobytes()

    source = png(image)
    found = match_crop(source, source, [30, 40, 20, 20], .95)
    assert found["count"] == 1
    assert found["matches"] == [{"x": 30, "y": 40, "width": 20, "height": 20}]
    absent = match_crop(source, png(np.zeros_like(image)), [30, 40, 20, 20], .95)
    assert absent["count"] == 0
    with pytest.raises(ValueError, match="超出"):
        match_crop(source, source, [115, 90, 20, 20], .8)


@pytest.mark.asyncio
async def test_matching_runs_in_real_isolated_runner():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    image = np.random.default_rng(41).integers(0, 256, (80, 90, 3), dtype=np.uint8)
    encoded = cv2.imencode(".png", image)[1].tobytes()
    result = await debug._match_crop(encoded, encoded, [20, 30, 15, 15], .95)
    assert result["count"] == 1
    assert result["matches"][0] == {"x": 20, "y": 30, "width": 15, "height": 15}
