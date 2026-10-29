"""导出 OpenAPI 基线（工单 01）。

用法（仓库根目录）：
    D:/python312/python.exe scripts/export_openapi.py          # 重新生成基线
    D:/python312/python.exe scripts/export_openapi.py --check  # 只校验，不写文件

基线文件：docs/contracts/openapi.json
契约测试 server/tests/test_contract_openapi.py 会逐字节比较 app.openapi() 与基线。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "server"
BASELINE = REPO_ROOT / "docs" / "contracts" / "openapi.json"

#: 让 `from app.main import app` 在仓库根目录执行时也可用。
sys.path.insert(0, str(SERVER_DIR))


def render(schema: dict) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出/校验 TestDock OpenAPI 基线")
    parser.add_argument("--check", action="store_true", help="只比较，不写文件")
    args = parser.parse_args()

    from app.contract import project_openapi  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415 - 延迟导入，--help 不加载应用

    rendered = render(project_openapi(app.openapi()))

    if args.check:
        if not BASELINE.is_file():
            print(f"缺少基线: {BASELINE}", file=sys.stderr)
            return 1
        current = BASELINE.read_text(encoding="utf-8")
        if current != rendered:
            print(
                "OpenAPI 与基线不一致；确认契约变更后重新运行 "
                "scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print(f"OpenAPI 基线一致: {BASELINE}")
        return 0

    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"已写入 {BASELINE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
