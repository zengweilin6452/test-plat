"""工单 25：跨会话模板库与执行锁定（定向测试）。

覆盖：

- 共享根：runner 不覆盖 MobileConfig.assets_dir，所有调试会话的
  TemplateStore 落在同一个资产根 → 新会话能引用其他会话登记的模板
  （用 vendor TemplateStore 在同一根上做"两个会话"的读写证据）；
- 执行锁定：修订 config.image_templates 的 logical/version_id/sha256 与
  共享库 manifest 逐条核对；缺失 / 版本不符 / 摘要不符 → 派发阻断
  （errored template_pin_mismatch），租约释放；全部命中 → 正常 spawn。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.domain.templates import pinned_templates, verify_template_pins
from app.scheduler import dispatcher
from tests._p3_common import TEST_DB, reset_db_engine, requires_db
from tests._p3_common import api_client as client  # noqa: F401
from tests._p3_common import make_run as make_run  # noqa: F401
from tests._p3_common import p3_project as project  # noqa: F401
from tests._p3_common import sync_engine as sync_engine  # noqa: F401

pytestmark = requires_db

VENDOR_SRC = Path(__file__).resolve().parents[2] / "vendor" / "mobile_auto" / "src"


def _write_template(root: Path, logical: str, version_id: str, sha256: str) -> None:
    """按 vendor TemplateStore 的布局写一份模板（清单 + 版本目录）。"""
    (root / "versions" / version_id).mkdir(parents=True, exist_ok=True)
    (root / "versions" / version_id / "image.png").write_bytes(b"\x89PNG fake")
    (root / "versions" / version_id / "meta.json").write_text(
        json.dumps({"schema_version": 2, "image_sha256": sha256}), encoding="utf-8"
    )
    manifest_path = root / "manifest.json"
    manifest = {"schema_version": 2, "templates": {}}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["templates"][logical] = {"version_id": version_id, "image_sha256": sha256}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_shared_store_is_visible_from_another_session(tmp_path, monkeypatch):
    """同一资产根上的两个 TemplateStore 实例共享清单（跨会话引用的证据）。"""
    monkeypatch.syspath_prepend(str(VENDOR_SRC))
    from mobile_auto.imaging import store as store_mod
    from mobile_auto.imaging.store import TemplateStore

    # decode_rgb 需要真 PNG；用 numpy 伪造解码结果即可（store 只校验尺寸/摘要一致）
    import numpy as np

    monkeypatch.setattr(
        store_mod, "decode_rgb", lambda data, what="": np.zeros((4, 4, 3), dtype="uint8")
    )
    png = b"\x89PNG-fake"
    root = tmp_path / "assets"
    store_a = TemplateStore(root)  # 会话 A 登记
    created = store_a.create(
        "ui/login-button.png", png, source_width=1080, source_height=2400
    )
    store_b = TemplateStore(root)  # 会话 B（新调试会话）读同一根
    listed = store_b.list_templates()
    assert "ui/login-button.png" in listed, "新会话必须能看到其他会话登记的模板"
    assert listed["ui/login-button.png"]["version_id"] == created.version_id
    assert listed["ui/login-button.png"]["image_sha256"] == created.sha256


def test_pins_missing_template_blocks_dispatch(client, project, make_run, sync_engine, monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    monkeypatch.setenv("TESTDOCK_TEMPLATE_ASSETS_DIR", str(assets))
    reset_db_engine(TEST_DB)

    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        config_snapshot={"image_templates": [{"logical": "login", "version_id": "v1", "sha256": "a" * 64}]},
    )
    outcome = asyncio.run(dispatcher.dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "template_pin_mismatch"
    with sync_engine.connect() as conn:
        state = conn.execute(
            text("SELECT state FROM test_runs WHERE id = CAST(:id AS uuid)"), {"id": run_id}
        ).scalar_one()
    assert state == "errored"
    with sync_engine.connect() as conn:
        live = conn.execute(
            text("SELECT count(*) FROM resource_leases WHERE released_at IS NULL")
        ).scalar_one()
    assert live == 0, "阻断后租约必须释放"


def test_pins_version_mismatch_blocks_dispatch(client, project, make_run, sync_engine, monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    _write_template(assets, "login", "current-version", "b" * 64)
    monkeypatch.setenv("TESTDOCK_TEMPLATE_ASSETS_DIR", str(assets))
    reset_db_engine(TEST_DB)

    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        config_snapshot={"image_templates": [{"logical": "login", "version_id": "pinned-old", "sha256": "b" * 64}]},
    )
    outcome = asyncio.run(dispatcher.dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "template_pin_mismatch", "版本被更新后不得静默改用新版本"


def test_pins_all_matched_spawn_normally(client, project, make_run, sync_engine, monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    _write_template(assets, "login", "ver-ok", "b" * 64)
    monkeypatch.setenv("TESTDOCK_TEMPLATE_ASSETS_DIR", str(assets))
    reset_db_engine(TEST_DB)

    from app.runner import dispatch_runner

    calls = []

    async def spawn(**kwargs):
        calls.append(kwargs)
        return 1

    monkeypatch.setattr(dispatch_runner, "_spawner", spawn)
    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        config_snapshot={"image_templates": [{"logical": "login", "version_id": "ver-ok", "sha256": "b" * 64}]},
    )
    outcome = asyncio.run(dispatcher.dispatch_one(run_id=run_id))
    assert outcome.ok is True, outcome.reason
    assert calls, "锁定命中必须正常派发"


def test_pins_undeclared_is_skipped(client, project, make_run, sync_engine, monkeypatch, tmp_path):
    monkeypatch.setenv("TESTDOCK_TEMPLATE_ASSETS_DIR", str(tmp_path / "assets"))
    assert pinned_templates({}) == []
    assert verify_template_pins([], assets_root=tmp_path / "assets")["verdict"] == "skipped"
