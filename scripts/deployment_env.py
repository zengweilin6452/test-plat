"""Read root .env for PowerShell without evaluating shell commands."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from app.config import settings, demo_isolation_error

if "--validate-demo" in sys.argv:
    if settings.demo_mode:
        error = demo_isolation_error(settings.database_url, settings.data_dir)
        if error:
            print(error, file=sys.stderr)
            raise SystemExit(2)
else:
    print(json.dumps({key: value for key, value in os.environ.items() if key.startswith("TESTDOCK_")}))
