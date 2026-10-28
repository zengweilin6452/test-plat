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


# --------------------------------------------------------------------------- #
# 进程内令牌：spawn 侧与校验侧的唯一真源
# --------------------------------------------------------------------------- #
# 为什么不能只靠 app.state：`python -m app.main` 启动时服务跑在 `__main__` 模块里，
# 而任何 `from ..main import app` 的代码会把 `app.main` **再导入一次**，拿到另一个
# app 对象（lifespan 没跑过，state 为空），于是回落去读磁盘文件。文件一旦被别的
# 进程轮换过，spawn 出去的 runner 拿到的令牌就和 /internal/* 校验用的不一致 ——
# 会话直接 401（runner_exit）。令牌放在本模块（全进程唯一单例）里，两侧都从这里取。
_CURRENT_TOKEN: str | None = None


def set_current_token(token: str | None) -> None:
    """lifespan 启动时登记本进程的令牌（与 app.state.control_token 同值）。"""
    global _CURRENT_TOKEN
    _CURRENT_TOKEN = token or None


def current_token() -> str | None:
    """本进程登记过的令牌；未跑过 lifespan（CLI / 纯单测）时为 None。"""
    return _CURRENT_TOKEN


def resolve_token(state_token: str | None, path: Path | str) -> str:
    """令牌解析的唯一入口：进程内值 > app.state > 磁盘文件。

    spawn 侧（交给 runner）与校验侧（/internal/*）必须走同一个入口，否则会出现
    "发出去的令牌没人认"。
    """
    return current_token() or state_token or (read_token(path) or "")


__all__ = [
    "ENV_CONTROL_TOKEN",
    "TOKEN_BYTES",
    "current_token",
    "ensure_token",
    "generate_token",
    "read_token",
    "resolve_token",
    "set_current_token",
    "token_path",
    "tokens_match",
    "write_token",
]
