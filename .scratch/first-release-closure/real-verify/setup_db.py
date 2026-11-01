"""准备真机验收用的隔离环境（幂等）。

- 新建/复用 testdock_real（不碰共享库 testdock）
- alembic upgrade head
- seed_demo（项目/节点/档案）
- 登记被测应用（com.miui.calculator）与一个 environment

只做本地准备，不访问设备。
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[3]
DB_NAME = "testdock_real"
API_URL = f"postgresql+psycopg://testdock@127.0.0.1:55432/{DB_NAME}"
SYNC_URL = f"postgresql://testdock@127.0.0.1:55432/{DB_NAME}"
ADMIN_URL = "postgresql://testdock@127.0.0.1:55432/postgres"
PY = r"D:\python312\python.exe"

APP_ID = str(uuid.uuid5(uuid.UUID("6f1b2c34-0000-4000-8000-000000000000"), "application:real-calculator"))
ENV_ID = str(uuid.uuid5(uuid.UUID("6f1b2c34-0000-4000-8000-000000000000"), "environment:real-verify"))


def main() -> int:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{DB_NAME}"')
            print(f"created database {DB_NAME}")
        else:
            print(f"database {DB_NAME} exists")

    env = dict(os.environ, TESTDOCK_DATABASE_URL=API_URL)
    subprocess.run([PY, "-m", "alembic", "upgrade", "head"], cwd=REPO / "server", env=env, check=True)
    subprocess.run([PY, str(REPO / "scripts" / "seed_demo.py"), "--database-url", API_URL], check=True)

    with psycopg.connect(SYNC_URL) as conn:
        project_id = conn.execute(
            "SELECT id FROM projects WHERE code = %s", ("testdock-demo",)
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO applications (id, project_id, platform, name, identifier)
            VALUES (%s, %s, 'android', %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (APP_ID, project_id, "计算器（真机验收）", "com.miui.calculator"),
        )
        conn.execute(
            """
            INSERT INTO environments (id, project_id, name, config)
            VALUES (%s, %s, 'real-verify', '{}'::jsonb)
            ON CONFLICT DO NOTHING
            """,
            (ENV_ID, project_id),
        )
        node = conn.execute(
            "SELECT id, name, status FROM execution_nodes WHERE project_id = %s ORDER BY created_at LIMIT 1",
            (project_id,),
        ).fetchone()
        conn.commit()
        print("project_id", project_id)
        print("application_id", APP_ID)
        print("environment_id", ENV_ID)
        print("node", node)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
