"""工单 08（首期收口）：模板库存储事实与执行锁定回归。

- 存储事实（统一注释与实现）：debug runner 的 cwd 固定为 server/，vendor
  MobileConfig 不覆盖 assets_dir 且默认相对 "assets" —— 每个调试会话的
  TemplateStore 都落在同一个 server/assets，也就是 domain.templates.
  template_assets_root()。这是「模板跨会话可查、不随会话关闭消失」的实现依据。
- 执行锁定：修订固定 logical + version_id + sha256，派发前按锁定版本核对，
  摘要不符同样阻断（与工单 25 同口径）。
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.domain.templates import TEMPLATE_ASSETS_ENV, template_assets_root
from app.runner import spawn as spawn_mod
from app.scheduler import dispatcher
from tests._p3_common import TEST_DB, reset_db_engine, requires_db
from tests._p3_common import api_client as client  # noqa: F401
from tests._p3_common import make_run as make_run  # noqa: F401
from tests._p3_common import p3_project as project  # noqa: F401
from tests._p3_common import sync_engine as sync_engine  # noqa: F401

VENDOR_SRC = Path(__file__).resolve().parents[2] / "vendor" / "mobile_auto" / "src"


def _debug_spawn_spec() -> spawn_mod.SpawnSpec:
    return spawn_mod.build_spec(
        run_id=str(uuid.uuid4()),
        config={"module": "debug", "serial": "SERIAL-FOR-TEST"},
        lease={"fencing_token": 1, "serial": "SERIAL-FOR-TEST"},
    )


def test_debug_viewer_template_store_lands_in_the_shared_library(tmp_path, monkeypatch):
    """调试会话的模板根 == 平台共享库根（不是按会话隔离的目录）。"""
    # vendor imaging 链路顶层导入 cv2（engine.py），缺图像依赖时跳过
    # （与 test_crop_validation.py 同口径），CI server 作业会安装。
    pytest.importorskip("cv2")
    pytest.importorskip("numpy")
    monkeypatch.delenv(TEMPLATE_ASSETS_ENV, raising=False)
    monkeypatch.syspath_prepend(str(VENDOR_SRC))
    from mobile_auto.config import MobileConfig
    from mobile_auto.imaging.store import TemplateStore

    spec = _debug_spawn_spec()
    monkeypatch.chdir(spec.cwd)
    # 与 testdock_runner.debug_job._start_viewer 同参数：不传 assets_dir
    config = MobileConfig(artifacts_dir=tmp_path)

    assert TemplateStore(config.assets_dir).root == template_assets_root(), (
        "调试会话登记的模板必须落在平台共享库根，跨会话可见"
    )
    assert template_assets_root() == (Path(spec.cwd) / "assets").resolve()


def test_library_root_is_absolute_and_device_independent(monkeypatch):
    """共享库根不依赖 cwd/设备，且 GET /template-library 与执行锁定读同一根。"""
    monkeypatch.delenv(TEMPLATE_ASSETS_ENV, raising=False)
    root = template_assets_root()
    assert root.is_absolute()
    assert root.name == "assets"
    assert root.parent.name == "server"


def test_registered_template_survives_new_session_and_reload(tmp_path, monkeypatch):
    """刷新/恢复预览/新会话都不会删掉已登记模板：模板在共享根，不在前端状态里。"""
    # 同上：vendor imaging 链路需要 cv2/numpy，缺依赖时跳过。
    pytest.importorskip("cv2")
    pytest.importorskip("numpy")
    monkeypatch.syspath_prepend(str(VENDOR_SRC))
    import numpy as np

    from app.domain.templates import list_template_library
    from mobile_auto.imaging import store as store_mod
    from mobile_auto.imaging.store import TemplateStore

    # store 只校验尺寸/摘要；真 PNG 解码用替身，避免引入图像依赖
    monkeypatch.setattr(
        store_mod, "decode_rgb", lambda data, what="": np.zeros((4, 4, 3), dtype="uint8")
    )
    root = tmp_path / "assets"
    created = TemplateStore(root).create(
        "ui/login.png", b"\x89PNG-fake", source_width=1080, source_height=2400
    )

    # 新会话（新的 store 实例 == 新的 viewer）与平台共享库读到同一个版本
    reloaded = TemplateStore(root).list_templates()
    assert reloaded["ui/login.png"]["version_id"] == created.version_id
    assert reloaded["ui/login.png"]["image_sha256"] == created.sha256
    library = list_template_library(assets_root=root)
    assert [row["version_id"] for row in library if row["logical"] == "ui/login.png"] == [
        created.version_id
    ]


def _write_template(root: Path, logical: str, version_id: str, sha256: str) -> None:
    """按 vendor TemplateStore 的布局写一份模板（清单 + 版本目录）。"""
    import json

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


@requires_db
def test_pins_sha256_mismatch_blocks_dispatch(
    client, project, make_run, sync_engine, monkeypatch, tmp_path
):
    """版本号相同但摘要不同（模板内容被替换）也必须阻断执行。"""
    assets = tmp_path / "assets"
    _write_template(assets, "login", "ver-same", "c" * 64)
    monkeypatch.setenv(TEMPLATE_ASSETS_ENV, str(assets))
    reset_db_engine(TEST_DB)

    run_id = make_run(
        state="queued",
        request_key=str(uuid.uuid4()),
        config_snapshot={
            "image_templates": [
                {"logical": "login", "version_id": "ver-same", "sha256": "d" * 64}
            ]
        },
    )
    outcome = asyncio.run(dispatcher.dispatch_one(run_id=run_id))
    assert outcome.ok is False
    assert outcome.reason == "template_pin_mismatch"
    with sync_engine.connect() as conn:
        run_state = conn.execute(
            text("SELECT state, reason_code FROM test_runs WHERE id = CAST(:id AS uuid)"),
            {"id": run_id},
        ).mappings().one()
    assert run_state["state"] == "errored"
    assert run_state["reason_code"] == "template_pin_mismatch"
