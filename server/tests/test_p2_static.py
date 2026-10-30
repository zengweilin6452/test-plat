"""P2 静态约束（不需要数据库）。

这些是架构纪律的回归网：结构被打破时应当立刻失败，而不是等到联调才发现。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = SERVER_ROOT / "app"


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


VENDOR_PACKAGES = {"mobile_auto", "mobile_perf"}


def test_app_never_imports_vendor_packages_at_module_level():
    """platform 不得在模块顶层 import vendor（只读纪律，development-plan.md §5.2）。

    只查模块级 import：vendor 的接入方式是"函数内延迟 import + 显式路径"，
    integrations/mobile_perf.py 就是这么写的（第 122/131/141 行），这是允许的；
    模块顶层 import 会把 vendor 变成 API 进程的硬依赖，那才是真正的违规。
    """
    offenders: list[str] = []
    for path in _python_files(APP_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # 只看模块顶层语句
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            for name in names:
                head = name.split(".")[0]
                if head in VENDOR_PACKAGES:
                    offenders.append(f"{path.relative_to(SERVER_ROOT)}: {name}")
    assert not offenders, "server/app 顶层 import 了 vendor 包：" + "; ".join(offenders)


def test_app_modules_import_without_vendor_on_sys_path():
    """平台自身的模块不依赖 vendor：单独起一个干净子进程验证。

    不能在本进程里直接断言 sys.modules —— server/pyproject.toml 的 pytest 配置
    会 autoload vendor 的 pytest_plugin，跑测试时 mobile_auto/mobile_perf 早就在
    sys.modules 里了，那是测试进程的事，不是 app 的事。所以开一个全新的解释器，
    PYTHONPATH 只给 server/，逐个 import app.* 并回读 sys.modules。
    """
    script = (
        "import importlib, json, pkgutil, sys\n"
        "import app as app_pkg\n"
        "bad = []\n"
        "for mod in pkgutil.walk_packages(app_pkg.__path__, prefix='app.'):\n"
        "    try:\n"
        "        importlib.import_module(mod.name)\n"
        "    except Exception as exc:\n"
        "        bad.append(mod.name + ': ' + type(exc).__name__ + ': ' + str(exc))\n"
        "vendor = sorted({m.split('.')[0] for m in sys.modules\n"
        "                 if m.split('.')[0] in ('mobile_auto', 'mobile_perf')})\n"
        "print(json.dumps({'failures': bad, 'vendor': vendor}))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SERVER_ROOT)
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(SERVER_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0, f"子进程导入失败：{completed.stderr}"
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    # app.scheduler.dispatcher 顶层 import 了 app.runner.spawn，而 app/runner/ 这个包
    # 在仓库里还不存在（P4/P5 的调度器那半尚未落地）。这是既有状态，不是 P2 引入的，
    # 因此只要"缺失的模块本身不存在"就放行；其他异常照旧失败。
    real_failures = [
        item
        for item in payload["failures"]
        if "No module named 'app.runner'" not in item
    ]
    assert not real_failures, "app 模块导入失败：" + "; ".join(real_failures)
    assert not payload["vendor"], f"app 导入期把 vendor 拉进 sys.modules：{payload['vendor']}"


def _clean_app_imports(**env_extra: str):
    """在干净子进程里 import 全部 app.* 模块，返回 CompletedProcess。"""
    script = (
        "import importlib, json, pkgutil, sys\n"
        "import app as app_pkg\n"
        "bad = []\n"
        "for mod in pkgutil.walk_packages(app_pkg.__path__, prefix='app.'):\n"
        "    try:\n"
        "        importlib.import_module(mod.name)\n"
        "    except Exception as exc:\n"
        "        bad.append(mod.name + ': ' + type(exc).__name__ + ': ' + str(exc))\n"
        "vendor = sorted({m.split('.')[0] for m in sys.modules\n"
        "                 if m.split('.')[0] in ('mobile_auto', 'mobile_perf')})\n"
        "print(json.dumps({'failures': bad, 'vendor': vendor}))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SERVER_ROOT)
    env["PYTHONUTF8"] = "1"
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(SERVER_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_domain_module_exposes_state_machine():
    from app.domain import suite, task

    assert task.LIFECYCLES == ("draft", "ready", "archived")
    assert task.READINESSES == ("draft", "validated")
    assert task.TEST_TYPES == ("ui", "performance", "joint")
    assert task.can_patch("draft") is True
    assert task.can_patch("archived") is False
    assert task.lifecycle_after_validate("draft") == "ready"
    assert task.lifecycle_after_validate("ready") == "ready"
    assert task.lifecycle_after_archive() == "archived"
    assert task.next_lock_version(1) == 2
    # 套件枚举与任务枚举共用一份，避免两处漂移
    assert suite.TEST_TYPES is task.TEST_TYPES


def test_readiness_checker_reports_missing_pieces():
    from app.domain.task import check_readiness

    report = check_readiness(
        revision={"build_id": None, "suite_version_id": None},
        platform="android",
        application_platform="android",
        suite_version=None,
        case_total=0,
    )
    assert report.ok is False
    details = report.as_details()
    assert "build_id" in details["missing"]
    assert "suite_version_id" in details["missing"]

    ok = check_readiness(
        revision={"build_id": "b", "suite_version_id": "sv"},
        platform="android",
        application_platform="android",
        suite_version={"id": "sv"},
        case_total=3,
    )
    assert ok.ok is True
    assert ok.as_details() == {"missing": [], "invalid": []}


def test_errors_are_renderable_by_the_envelope_handler():
    from app.errors import CLIENT_HEADER, client_header_required, stale_version, task_not_ready

    assert CLIENT_HEADER == "X-TestDock-Client"

    err = client_header_required()
    assert (err.status_code, err.code) == (428, "client_header_required")

    not_ready = task_not_ready(missing=["build_id"], invalid=[])
    assert (not_ready.status_code, not_ready.code) == (422, "task_not_ready")
    assert not_ready.extra_details["missing"] == ["build_id"]

    stale = stale_version({"id": "x", "lock_version": 7})
    assert (stale.status_code, stale.code) == (409, "stale_version")
    assert stale.extra_details["latest"]["lock_version"] == 7


def test_discover_parser_keeps_only_test_ids():
    from app.integrations.discover import parse_collected_node_ids

    stdout = (
        "no tests ran in 0.01s\n"
        "tests/test_a.py::test_one\n"
        "tests/test_a.py::TestX::test_two[param]\n"
        "ERROR tests/test_b.py - ImportError: boom\n"
        "============ 2 tests collected in 0.10s ============\n"
    )
    assert parse_collected_node_ids(stdout) == [
        "tests/test_a.py::test_one",
        "tests/test_a.py::TestX::test_two[param]",
    ]


def test_discover_manifest_round_trip():
    from app.domain.suite import build_manifest, case_keys, case_total

    manifest = build_manifest(
        ["tests/test_a.py::test_one", "tests/test_a.py::test_one", "tests/test_b.py::test_two"]
    )
    assert manifest["schema_version"] == 1
    assert manifest["case_count"] == 2  # 去重
    assert case_total(manifest) == 2
    assert case_keys(manifest) == [
        "tests/test_a.py::test_one",
        "tests/test_b.py::test_two",
    ]


def test_suites_router_is_mounted_under_api_prefix():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    for expected in (
        "/api/v1/tasks",
        "/api/v1/suites",
        "/api/v1/suites/{suite_id}/versions",
        "/api/v1/suites/{suite_id}/discover",
    ):
        assert expected in paths, f"缺少路由 {expected}"


# --------------------------------------------------------------------------- #
# 错误信封（api-design.md §1.2）不许回退
# --------------------------------------------------------------------------- #
_ENVELOPE_KEYS = {"code", "message", "request_id", "details"}


def _envelope_of(resp) -> dict:
    body = resp.json()
    assert isinstance(body, dict), body
    assert set(body) == _ENVELOPE_KEYS, f"信封字段集合变了：{sorted(body)}"
    assert isinstance(body["code"], str) and body["code"]
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["request_id"], str) and body["request_id"]
    return body


def test_error_envelope_survives_all_three_handlers():
    """三类异常都必须渲染成 {code,message,request_id,details}（不需要数据库）。

    这条是回归网：
      - ApiError            -> _api_error_handler（业务错误，details 可能带 datetime）
      - StarletteHTTPException -> _http_exception_handler（框架/旧路由抛的）
      - RequestValidationError -> _validation_error_handler（请求体校验失败）

    _api_error_handler 里有一层 jsonable_encoder：stale_version 的 details.latest
    会回填最新任务对象（带 created_at/updated_at 的 datetime），不编码就直接
    500（TypeError: Object of type datetime is not JSON serializable）。
    所以这里显式塞一个 datetime 进 details，确保编码那层没被谁顺手去掉。
    """
    import datetime as _dt

    from fastapi.testclient import TestClient
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from app.errors import stale_version
    from app.main import app as fastapi_app

    latest = {"id": "t-1", "lock_version": 7, "created_at": _dt.datetime(2024, 5, 6, 7, 8, 9)}

    @fastapi_app.get("/__p2_static__/api_error")
    async def _raise_api_error():  # pragma: no cover - 仅测试用临时路由
        raise stale_version(latest)

    @fastapi_app.get("/__p2_static__/http_error")
    async def _raise_http_error():  # pragma: no cover - 仅测试用临时路由
        raise StarletteHTTPException(status_code=405, detail="只读接口")

    @fastapi_app.get("/__p2_static__/http_error_detail")
    async def _raise_http_error_detail():  # pragma: no cover
        raise StarletteHTTPException(status_code=409, detail={"current": "draft"})

    @fastapi_app.get("/__p2_static__/validation_error")
    async def _raise_validation_error():  # pragma: no cover
        from fastapi.exceptions import RequestValidationError

        raise RequestValidationError(
            [{"type": "missing", "loc": ("body", "name"), "msg": "Field required", "input": {}}]
        )

    # 临时路由只挂在本进程的 app 对象上，用完后摘掉，不影响其它用例的路径集合。
    added = [
        route
        for route in fastapi_app.routes
        if getattr(route, "path", "").startswith("/__p2_static__/")
    ]
    try:
        with TestClient(fastapi_app, raise_server_exceptions=False) as client:
            resp = client.get("/__p2_static__/api_error")
            assert resp.status_code == 409, resp.text
            body = _envelope_of(resp)
            assert body["code"] == "stale_version"
            # datetime 必须被编码成字符串，而不是抛 500
            assert body["details"]["latest"]["created_at"] == "2024-05-06T07:08:09"
            assert body["details"]["latest"]["lock_version"] == 7

            resp = client.get("/__p2_static__/http_error")
            assert resp.status_code == 405, resp.text
            body = _envelope_of(resp)
            assert body["code"] == "method_not_allowed"
            assert body["message"] == "只读接口"

            resp = client.get("/__p2_static__/http_error_detail")
            assert resp.status_code == 409, resp.text
            body = _envelope_of(resp)
            assert body["code"] == "state_conflict"
            assert body["details"] == {"detail": {"current": "draft"}}

            resp = client.get("/__p2_static__/validation_error")
            assert resp.status_code == 422, resp.text
            body = _envelope_of(resp)
            assert body["code"] == "validation_error"
            assert body["details"]["errors"][0]["loc"] == ["body", "name"]
    finally:
        for route in added:
            fastapi_app.routes.remove(route)


# --------------------------------------------------------------------------- #
# 修订契约冻结（前端时间线直接按它渲染）
# --------------------------------------------------------------------------- #
def test_task_revision_record_is_frozen():
    """GET /tasks/{id}/revisions 的字段集合与可空性冻结，改动必须同步前端。"""
    from app.schemas import TaskRevisionListOut, TaskRevisionRecord

    fields = TaskRevisionRecord.model_fields
    assert set(fields) == {
        "id",
        "task_id",
        "revision",
        "test_type",
        "readiness",
        "build_id",
        "suite_version_id",
        "environment_id",
        "config",
        "created_by",
        "created_at",
    }
    # 可空但必填的四个：键必须出现（NULL 是合法值），前端才能无条件读取
    for name in ("build_id", "suite_version_id", "environment_id"):
        assert fields[name].is_required(), f"{name} 必须出现（允许为 null）"
        assert fields[name].annotation is not None
    for name in ("id", "task_id", "revision", "test_type", "readiness", "created_by", "created_at"):
        assert fields[name].is_required(), f"{name} 必填"
    assert TaskRevisionRecord.model_config.get("extra") == "forbid"
    assert set(TaskRevisionListOut.model_fields) == {"items", "total"}

    # 多给一个字段必须被判违约（契约收紧而不是静默放过）
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        TaskRevisionRecord.model_validate(
            {
                "id": "r1",
                "task_id": "t1",
                "revision": 1,
                "test_type": "ui",
                "readiness": "draft",
                "build_id": None,
                "suite_version_id": None,
                "environment_id": None,
                "config": {},
                "created_by": "web-client",
                "created_at": "2024-05-06T07:08:09",
                "surprise_field": 1,
            }
        )


def test_revisions_service_uses_the_frozen_record():
    """service 层必须经 TaskRevisionRecord 自检，而不是自己拼 dict。"""
    import inspect

    from app.services import tasks as task_service

    source = inspect.getsource(task_service.list_revisions)
    assert "TaskRevisionRecord.model_validate" in source
    assert "TaskRevisionListOut" in source


# --------------------------------------------------------------------------- #
# 同名任务判重（P2 验收项）
# --------------------------------------------------------------------------- #
def test_create_task_dedups_by_application_and_name():
    """service 层必须有按 (application_id, name) 查既有并比较内容的分支。

    工单 07 把判重从路由层移进 create_task：内容比较必须与建任务同一事务，
    否则"判定通过 → 另一个请求插入 → 再插入"会多出一条任务。
    """
    import inspect

    from app.routers import tasks as tasks_router
    from app.services import tasks as task_service

    create_source = inspect.getsource(task_service.create_task)
    assert "find_task_by_name" in create_source
    assert "create_content_diff" in create_source
    # 命中时用 200（既有）与 201（新建）区分
    assert "status_code=200" in inspect.getsource(tasks_router._reused)

    service_source = inspect.getsource(task_service.find_task_by_name)
    assert "application_id = :aid" in service_source
    assert "name = :name" in service_source
    # 归档过的同名任务要能重新创建，所以判重必须排除归档态
    assert "lifecycle <> :archived" in service_source
