"""以隔离配置启动 HEAD 后端（8010 + testdock_real），不动 :8000 / :5173。

环境变量在 Python 里构造，避免 PowerShell 传中文 JSON 的编码问题。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RUNTIME = REPO / ".runtime" / "real-verify"
SUITE = REPO / ".scratch" / "first-release-closure" / "real-suite"

os.environ.update(
    {
        "TESTDOCK_DATABASE_URL": "postgresql+psycopg://testdock@127.0.0.1:55432/testdock_real",
        "TESTDOCK_HOST": "127.0.0.1",
        "TESTDOCK_PORT": "8010",
        "TESTDOCK_DATA_DIR": str(RUNTIME / "data"),
        "TESTDOCK_RUNTIME_DIR": str(RUNTIME / "runtime"),
        "TESTDOCK_RUNNER_PYTHON": r"D:\python312\python.exe",
        "TESTDOCK_SUITE_SOURCES": json.dumps(
            [
                {
                    "id": "calculator-smoke",
                    "name": "真机验收受控套件（计算器）",
                    "path": SUITE.as_posix(),
                    "test_types": ["ui", "joint"],
                }
            ],
            ensure_ascii=False,
        ),
        "TESTDOCK_SCHEDULER": "1",
    }
)

sys.path.insert(0, str(REPO / "server"))
from app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
