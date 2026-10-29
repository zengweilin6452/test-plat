"""冻结 0001 迁移的 sha256（工单 01）。

用法（仓库根目录）：
    D:/python312/python.exe scripts/freeze_migration_baseline.py

输出：docs/contracts/migration-baseline.json
server/tests/test_migration_append_only.py 会校验 0001 未被修改。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "server" / "alembic" / "versions" / "0001_initial.py"
OUTPUT = REPO_ROOT / "docs" / "contracts" / "migration-baseline.json"


def main() -> None:
    digest = hashlib.sha256(TARGET.read_bytes()).hexdigest()
    payload = {
        TARGET.name: {
            "sha256": digest,
            "note": "0001 是冻结原件；结构变更必须追加 0002+ 迁移。",
        }
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"已写入 {OUTPUT}（{TARGET.name} sha256={digest}）")


if __name__ == "__main__":
    main()
