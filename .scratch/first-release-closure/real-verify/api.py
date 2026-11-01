"""真机验收的 HTTP 小工具（隔离后端 8010）。"""

from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8010/api/v1"
HEADERS = {"X-TestDock-Client": "web"}

PROJECT_ID = "a6f21ff4-0278-58bd-9fc6-dd145792350f"
APP_ID = "7715ad9c-71f1-52da-a9fc-ad7cb0896bcd"
BUILD_ID = "a342d799-f8ce-487f-8f39-df8766c37042"
RESOURCE_ID = "3eac0cec-c005-4a30-a76b-b1950fc3ee52"
SERIAL = "749622c9"


def call(method: str, path: str, body: dict | None = None, *, timeout: float = 120.0) -> dict:
    url = BASE + path
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(method, url, json=body, headers=HEADERS)
    try:
        data = resp.json()
    except ValueError:
        data = {"text": resp.text}
    if resp.status_code >= 400:
        print(f"HTTP {resp.status_code} {method} {path}", file=sys.stderr)
        print(json.dumps(data, ensure_ascii=False, indent=1), file=sys.stderr)
        raise SystemExit(1)
    return data


def show(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=1))
