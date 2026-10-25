"""TestDock runner：**唯一**允许 import vendor（mobile_auto / mobile_perf）的包。

架构约束（development-plan.md §3.3）：
  - API 进程（app/**）不得 import vendor：vendor 的可选依赖（cv2/numpy/fastapi/
    adb 等）会把 API 的部署面撑大，导入期副作用也会污染 API 进程。
  - 所有设备能力都在本包里，通过 `python -m testdock_runner <ui|perf|debug>`
    在独立子进程中执行。子进程与 API 只通过 HTTP（/internal/runs/...）和
    stdout 的 JSON 行事件通信。

这个边界由 server/tests/test_no_vendor_import.py 用 AST 扫描守住：任何
app/ 下的模块出现 `import mobile_auto` / `import mobile_perf` 都会让测试失败。
"""

from __future__ import annotations

__version__ = "0.3.0"

#: 退出码（与 app/integrations/mobile_auto.py 的映射保持一致）
EXIT_OK = 0
EXIT_CASE_FAILURE = 2
EXIT_INFRA_ERROR = 3
EXIT_CANCELLED = 4
EXIT_FENCE_MISMATCH = 5

__all__ = [
    "EXIT_CANCELLED",
    "EXIT_CASE_FAILURE",
    "EXIT_FENCE_MISMATCH",
    "EXIT_INFRA_ERROR",
    "EXIT_OK",
    "__version__",
]
