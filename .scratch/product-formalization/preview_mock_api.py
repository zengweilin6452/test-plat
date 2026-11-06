"""浏览器验收辅助：只服务前端展示用的隔离 mock API。

不连接数据库、不写任何文件、不接触用户已有服务；仅用于 Browser 面板检查
工作空间长名称、能力摘要、统一上下文、归档标识与错误状态等前端行为。
真实服务端行为由 server/tests/test_formalization.py 在独立 PG 上验证。

用法：python .scratch/product-formalization/preview_mock_api.py
监听 127.0.0.1:8010，配合 web/vite.verify.config.ts（5174 → 8010）使用。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
APP_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
APP_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

WORKSPACE_NAME = "超长中文工作空间名称验收示例——用于检查省略与窄窗口布局"
WORKSPACE = {
    "name": WORKSPACE_NAME,
    "customized_at": "2026-11-04T10:00:00+00:00",
    "updated_at": "2026-11-04T10:00:00+00:00",
    "demo_mode": False,
}
CAPABILITIES = {
    "version": "0.1.0",
    "commit": None,
    "demo_mode": False,
    "fake_runner_enabled": False,
    "platforms": [
        {"platform": "android", "supported": True},
        {"platform": "ios", "supported": False},
        {"platform": "web", "supported": False},
    ],
}
PROJECTS = {
    "items": [
        {"id": PROJECT_A, "code": "mobile-regression", "name": "移动端回归项目", "archived_at": None},
        {"id": PROJECT_B, "code": "payment-core", "name": "支付核心项目（已归档）", "archived_at": "2026-11-03T10:00:00+00:00"},
    ],
    "total": 2,
}
APPLICATIONS = {
    "items": [
        {"id": APP_A, "project_id": PROJECT_A, "platform": "android", "name": "同名应用", "identifier": "com.example.app", "task_count": 3, "archived_at": None},
        {"id": APP_B, "project_id": PROJECT_B, "platform": "android", "name": "同名应用", "identifier": "com.example.app", "task_count": 1, "archived_at": None},
    ],
    "total": 2,
    "by_platform": {"android": 2},
}
ONBOARDING = {
    "complete": False,
    "steps": [
        {"key": "workspace", "title": "设置工作空间名称", "description": "在设置页给本机工作空间起一个名字", "done": True, "target": "/settings", "count": 1},
        {"key": "project", "title": "建立项目", "description": "在项目与应用页创建第一个项目", "done": True, "target": "/apps", "count": 2},
        {"key": "application", "title": "登记 Android 应用", "description": "在项目下登记被测应用的包名标识", "done": True, "target": "/apps", "count": 2},
        {"key": "device", "title": "同步执行设备", "description": "连接 Android 设备后，在执行资源页同步真实设备", "done": False, "target": "/devices", "count": 0},
        {"key": "run", "title": "完成第一次运行", "description": "登记构建与套件输入，创建任务并发起运行", "done": False, "target": "/ui", "count": 0},
    ],
}
LEGACY = {
    "items": [
        {
            "id": "33333333-3333-4333-8333-333333333333",
            "entity": "project",
            "name": "星河 Demo",
            "current_name": "星河 Demo",
            "match_basis": ["固定 ID 与 seeds 命名空间一致", "原始名称字段一致"],
            "confidence": "confirmed",
            "related_counts": {"applications": 3, "test_runs": 2, "test_tasks": 1},
            "has_real_runs": True,
            "active_occupancy": False,
            "real_run_count": 2,
            "allowed_actions": ["keep", "rename", "archive"],
            "note": "已承载真实运行：建议保留并改名，不重建或迁移历史记录。",
        }
    ],
    "total": 1,
    "preview_token": "mock-preview-token",
}

ROUTES = {
    "/api/v1/workspace": WORKSPACE,
    "/api/v1/capabilities": CAPABILITIES,
    "/api/v1/onboarding/status": ONBOARDING,
    "/api/v1/projects": PROJECTS,
    "/api/v1/applications": APPLICATIONS,
    "/api/v1/legacy-review": LEGACY,
    "/api/v1/overview": {
        "application_total": 2, "resource_total": 0, "resource_ready": 0,
        "run_total": 0, "run_running": 0, "passed": 0, "failed": 0,
        "not_tested": 0, "pass_rate": None, "needs_attention": 0,
    },
    "/api/v1/resources": {"items": [], "total": 0},
    "/api/v1/runs": {"items": [], "total": 0, "next_cursor": None},
    "/api/v1/tasks": {"items": [], "total": 0},
    "/api/v1/suites": {"items": [], "total": 0},
    "/api/v1/builds": {"items": [], "total": 0},
    "/api/v1/reports": {"items": [], "total": 0},
    "/api/v1/health": {"status": "ok", "version": "0.1.0", "db": "ok", "vendor": {}, "runners": {"active": None}},
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ROUTES:
            self._send(200, ROUTES[path])
            return
        if path.startswith("/api/v1/applications/"):
            app = next(item for item in APPLICATIONS["items"] if item["id"] in path)
            self._send(200, app)
            return
        self._send(404, {"code": "not_found", "message": "mock API 未提供该端点", "request_id": "mock", "details": {}})

    def do_PATCH(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.startswith("/api/v1/workspace"):
            name = str(body.get("name") or "").strip()
            if not (1 <= len(name) <= 60):
                self._send(400, {"code": "validation_error", "message": "名称需为 1-60 个字符", "request_id": "mock", "details": {}})
                return
            WORKSPACE["name"] = name
            self._send(200, WORKSPACE)
            return
        self._send(404, {"code": "not_found", "message": "mock API 未提供该端点", "request_id": "mock", "details": {}})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8010), Handler).serve_forever()
