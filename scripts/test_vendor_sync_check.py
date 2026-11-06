"""vendor_sync.py check：缓存目录与运行时数据不得让只读校验变红。

真实场景：跑过 vendor 测试后 vendor/ 里会出现 __pycache__ / .pytest_cache /
mobile_perf/data/*.db；这些都不在锁文件与 include 清单里，但也不能算"改了 vendor"。
Run: python scripts/test_vendor_sync_check.py
"""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "vendor_sync_under_test", ROOT / "scripts" / "vendor_sync.py"
)
vendor_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vendor_sync)


def _write(path: Path, data: bytes = b"x") -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


class VendorCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.vendor = Path(self.temp.name) / "vendor"
        files = {
            "mobile_auto/src/mobile_auto/__init__.py": _write(
                self.vendor / "mobile_auto/src/mobile_auto/__init__.py"
            ),
            "mobile_perf/src/mobile_perf/__init__.py": _write(
                self.vendor / "mobile_perf/src/mobile_perf/__init__.py"
            ),
        }
        self.lock_path = self.vendor / "VENDOR.lock.json"
        self.lock_path.write_text(
            json.dumps(
                {"schema_version": 1, "files": files, "sources": {}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._original = (vendor_sync.VENDOR_DIR, vendor_sync.LOCK_PATH)
        vendor_sync.VENDOR_DIR = self.vendor
        vendor_sync.LOCK_PATH = self.lock_path

    def tearDown(self):
        vendor_sync.VENDOR_DIR, vendor_sync.LOCK_PATH = self._original
        self.temp.cleanup()

    def test_cache_dirs_and_runtime_data_do_not_fail_check(self):
        _write(self.vendor / "mobile_auto/src/mobile_auto/__pycache__/mod.pyc")
        _write(self.vendor / "mobile_auto/tools/adb/.pytest_cache/v/cache/nodeids")
        _write(self.vendor / "mobile_perf/data/mobile_perf.db")
        self.assertEqual(vendor_sync.cmd_check(), 0)

    def test_unregistered_real_file_still_fails_check(self):
        _write(self.vendor / "mobile_auto/src/mobile_auto/injected.py")
        self.assertEqual(vendor_sync.cmd_check(), 1)

    def test_modified_registered_file_still_fails_check(self):
        (self.vendor / "mobile_auto/src/mobile_auto/__init__.py").write_bytes(b"tampered")
        self.assertEqual(vendor_sync.cmd_check(), 1)


if __name__ == "__main__":
    unittest.main()
