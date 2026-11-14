"""Read root .env for PowerShell without evaluating shell commands."""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 先把「本脚本所在部署根」的 .env 灌进进程环境，再导入 app.config：
# pip install -e 的 editable finder 按模块名劫持 'app'（meta_path 先于 sys.path
# 扫描），导入到的 config 可能属于另一个安装根（2026-11-14 CI 实测：隔离根的
# .env 被绕过，TESTDOCK_PORT 从输出里消失）。override=False 保证调用方显式
# 设置的环境变量优先，不被这里覆盖。
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

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
