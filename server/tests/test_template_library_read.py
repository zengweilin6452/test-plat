import json

import pytest

from app.domain.templates import list_template_library


def test_library_survives_sessions_and_keeps_history(tmp_path):
    logical = "buttons/ok.png"
    for version in ("a" * 32, "b" * 32):
        directory = tmp_path / "versions" / version
        directory.mkdir(parents=True)
        (directory / "meta.json").write_text(json.dumps({
            "logical": logical, "image_sha256": version * 2, "width": 4, "height": 5,
        }), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"templates": {
        logical: {"version_id": "b" * 32, "image_sha256": "b" * 64},
    }}), encoding="utf-8")
    first = list_template_library(assets_root=tmp_path)
    assert first == list_template_library(assets_root=tmp_path)
    assert len(first) == 2
    assert [v["version_id"] for v in first if v["current"]] == ["b" * 32]
    (tmp_path / "versions" / ("b" * 32) / "meta.json").unlink()
    with pytest.raises(OSError):
        list_template_library(assets_root=tmp_path)


def test_missing_library_is_empty_but_corruption_is_not(tmp_path):
    assert list_template_library(assets_root=tmp_path) == []
    (tmp_path / "manifest.json").write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError):
        list_template_library(assets_root=tmp_path)


def test_library_endpoint_needs_no_device_session_and_reports_corruption(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("TESTDOCK_TEMPLATE_ASSETS_DIR", str(tmp_path))
    client = TestClient(app)
    response = client.get("/api/v1/template-library")
    assert response.status_code == 200
    assert response.json() == {"templates": []}
    (tmp_path / "manifest.json").write_text("broken", encoding="utf-8")
    response = client.get("/api/v1/template-library")
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
