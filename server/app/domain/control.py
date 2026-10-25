"""内部协议令牌：X-Control-Token 的生成/校验（development-plan.md §8.3）。

为什么用文件而不是配置项
------------------------
runner 是被 spawn 出来的**独立进程**，它需要和 API 共享一个秘密来证明
"我是这次 run 的合法执行者"。这个秘密不能写进 .env（重启即失效且容易泄漏到
版本库），也不该让 runner 读数据库。折中方案：API 启动时生成随机 token，
写入 data/control.token（权限 0600），spawn 时通过 --control-token 参数注入；
API 重启 -> 重新生成 -> 旧 runner 的下一次上报立刻 401，正好符合"重启后一切
在途执行作废"的语义。

文件里只放 token 本身（不带换行标记以外的东西），方便运维 curl 时直接读。
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

#: 环境变量：测试或外部部署可以显式指定，避免依赖 data/ 目录可写
ENV_CONTROL_TOKEN = "TESTDOCK_CONTROL_TOKEN"

TOKEN_BYTES = 32


def token_path(control_token_path: Path | str) -> Path:
    return Path(control_token_path)


def generate_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


def write_token(path: Path | str, token: str) -> Path:
    """原子写 + 0600。先写临时文件再 replace，避免 runner 读到半截 token。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        # Windows 上 chmod 只影响只读位，做不到 POSIX 0600；不视为失败
        pass
    os.replace(tmp, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def read_token(path: Path | str) -> str | None:
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def ensure_token(path: Path | str, *, explicit: str | None = None) -> str:
    """启动时调用：显式给值就用它，否则生成新 token 并落盘。"""
    token = explicit or os.environ.get(ENV_CONTROL_TOKEN) or generate_token()
    write_token(path, token)
    return token


def tokens_match(expected: str | None, provided: str | None) -> bool:
    """常量时间比较，避免 token 前缀被时序侧信道猜出。"""
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


__all__ = [
    "ENV_CONTROL_TOKEN",
    "TOKEN_BYTES",
    "ensure_token",
    "generate_token",
    "read_token",
    "token_path",
    "tokens_match",
    "write_token",
]
