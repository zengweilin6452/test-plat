"""vendor 适配层：只读 import，不改 vendor 源文件。"""

# P2 追加：套件用例发现（宿主子进程跑 pytest --collect-only，不 import vendor）
from . import discover

__all__ = ["discover"]
