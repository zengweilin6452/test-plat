"""套件用例发现：在宿主上跑 pytest --collect-only 拿到用例清单。

为什么用子进程而不是 import 测试文件：夹具（conftest）有副作用，任何 in-process
收集都会把被测项目的模块灌进本进程的 sys.modules / 全局状态，还可能污染
locale、logging、事件的全局钩子。子进程是唯一的隔离边界。

纪律：本模块**不 import 任何 vendor 包**，只按路径起子进程（development-plan.md §5.2
平台永不写 vendor/**；这里连读都不读）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: collect-only 的超时（秒）。套件很大时 collect 也可能慢，给足 120s。
DISCOVER_TIMEOUT_S = 120
#: 失败时回给前端的 stderr 尾巴行数（需求：末 200 行）
STDERR_TAIL_LINES = 200


class DiscoverErrorKind:
    """失败分类。路由层据此选 code，本模块不关心 HTTP。"""

    ROOT_MISSING = "root_missing"
    ROOT_NOT_DIR = "root_not_dir"
    TIMEOUT = "timeout"
    FAILED = "failed"
    NO_TESTS = "no_tests"
    PYTEST_MISSING = "pytest_missing"


@dataclass
class DiscoverResult:
    ok: bool
    node_ids: list[str] = field(default_factory=list)
    returncode: int | None = None
    stderr_tail: list[str] = field(default_factory=list)
    error: str | None = None
    command: list[str] = field(default_factory=list)

    def as_manifest_extra(self) -> dict[str, object]:
        return {"discover": {"command": self.command, "returncode": self.returncode}}


def resolve_suite_root(raw: str | None, *, vendor_dir: str | None = None) -> Path | None:
    """把配置里的 suite_root 解析成绝对目录。

    相对路径一律按仓库根解析（不是按 server/），因为套件目录通常放在仓库根的
    tests/ 或 e2e/ 下，跟 API 进程的 cwd 无关。

    返回 None 表示没配置；目录不存在由调用方判 422（这里不吞掉信息）。
    """
    if not raw or not raw.strip():
        return None
    candidate = Path(os.path.expanduser(raw.strip()))
    if not candidate.is_absolute():
        root = _repo_root()
        candidate = root / candidate
    return candidate.resolve()


def _repo_root() -> Path:
    # server/app/integrations/discover.py -> 上溯三级到仓库根
    return Path(__file__).resolve().parents[3]


def _python_for_discover() -> str:
    """用当前解释器：保证 pytest 版本与平台自己装的一致（避免 PATH 上的另一个 python）。"""
    return sys.executable or "python"


def _tail(lines: list[str], n: int = STDERR_TAIL_LINES) -> list[str]:
    return lines[-n:] if len(lines) > n else lines


def parse_collected_node_ids(stdout: str) -> list[str]:
    """从 pytest --collect-only -q 的输出里抽出 nodeid。

    输出形如：
        tests/test_a.py::test_one
        tests/test_b.py::TestK::test_m

        no tests ran in 0.01s
    只取含 "::" 的行，且跳过错误段（"ERROR ..."）与 summary 行。
    --collect-only -q 在收集报错时返回码非 0，这时调用方不会用它。
    """
    node_ids: list[str] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line or "::" not in line:
            continue
        # 收集错误会被打印成 "ERROR tests/x.py - ImportError..."，带 :: 时也不该算用例
        if line.startswith("ERROR ") or line.startswith("error "):
            continue
        if line.startswith("=") or line.startswith("!"):
            continue
        node_ids.append(line)
    return node_ids


def collect_suite(root: Path, *, timeout_s: int = DISCOVER_TIMEOUT_S) -> DiscoverResult:
    """在 root 上执行 pytest --collect-only -q，返回用例清单或失败分类。"""
    if not root.exists():
        return DiscoverResult(ok=False, error=DiscoverErrorKind.ROOT_MISSING)
    if not root.is_dir():
        return DiscoverResult(ok=False, error=DiscoverErrorKind.ROOT_NOT_DIR)

    command = [_python_for_discover(), "-m", "pytest", "--collect-only", "-q", str(root)]
    env = dict(os.environ)
    # 子进程里别再继承测试库连接串，避免被测套件的 conftest 顺手连上我们的库
    env.pop("TESTDOCK_TEST_DATABASE_URL", None)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    try:
        completed = subprocess.run(  # noqa: S603 - 参数是 list，不经 shell
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return DiscoverResult(
            ok=False,
            error=DiscoverErrorKind.TIMEOUT,
            command=command,
            stderr_tail=_tail([ln for ln in stderr.splitlines()]),
        )
    except OSError as exc:
        return DiscoverResult(ok=False, error=DiscoverErrorKind.FAILED, command=command,
                              stderr_tail=[f"{type(exc).__name__}: {exc}"])

    stderr_lines = (completed.stderr or "").splitlines()
    if completed.returncode != 0:
        kind = DiscoverErrorKind.FAILED
        if not (completed.stdout or "").strip() and "No module named pytest" in (completed.stderr or ""):
            kind = DiscoverErrorKind.PYTEST_MISSING
        return DiscoverResult(
            ok=False,
            error=kind,
            command=command,
            returncode=completed.returncode,
            stderr_tail=_tail(stderr_lines),
        )

    node_ids = parse_collected_node_ids(completed.stdout or "")
    if not node_ids:
        return DiscoverResult(
            ok=False,
            error=DiscoverErrorKind.NO_TESTS,
            command=command,
            returncode=completed.returncode,
            stderr_tail=_tail(stderr_lines),
        )
    return DiscoverResult(
        ok=True,
        node_ids=node_ids,
        command=command,
        returncode=completed.returncode,
    )
