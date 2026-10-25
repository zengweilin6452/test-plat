"""套件与套件版本：列表 / 版本 / 发现用例（P2）。

设计约束（来自 0001 真源，不是偏好）
------------------------------------
- test_suites **没有配置列**：套件目录只能由 discover 请求体传 suite_root。
- schema 里**没有 cases 表**：用例清单存在 suite_versions.manifest 的 jsonb 里
  （该列注释原文是"用例 key、入口、场景及 schemaVersion"）。
- suite_versions 不可变：每次 discover 追加一个新版本，不覆盖历史版本。

discover 跑在宿主子进程里（app/integrations/discover.py），只做 pytest --collect-only，
不 import 被测代码到 API 进程，也不碰 vendor/**。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..domain import suite as suite_domain
from ..errors import discover_failed, not_found, validation_error
from ..integrations import discover as discover_integration
from ..schemas import SuiteDiscoverIn
from ..services import suites as suite_service
from .tasks import require_client_header

router = APIRouter(tags=["suites"])


@router.get("/suites")
async def list_suites(
    test_type: Annotated[str | None, Query(description="ui / performance / joint")] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """套件列表，可按 test_type 过滤（枚举值来自 DB CHECK）。"""
    if test_type and test_type not in suite_domain.TEST_TYPES:
        raise validation_error(
            [f"test_type 只支持 {' / '.join(suite_domain.TEST_TYPES)}，收到 {test_type!r}"]
        )
    return await suite_service.list_suites(session, test_type=test_type)


@router.get("/suites/{suite_id}/versions")
async def list_suite_versions(
    suite_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """套件版本列表（version 倒序），每个版本带 case_count。"""
    return await suite_service.list_versions(session, suite_id)


@router.post("/suites/{suite_id}/discover", status_code=201)
async def discover_suite(
    suite_id: str,
    body: SuiteDiscoverIn,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """在宿主上跑 pytest --collect-only，把用例清单写成新的 suite_version。

    失败语义（都是 422，业务能处理）：
      - suite 不存在           -> 404 not_found
      - suite_root 不存在/不是目录 -> 422 discover_failed
      - pytest 返回非 0        -> 422 discover_failed，带 stderr 末 200 行
      - 超时（默认 120s）      -> 422 discover_failed，error=timeout
      - 收集到 0 条用例        -> 422 discover_failed，error=no_tests
        （写一个空版本会让绑定它的任务永远 validate 不过，而且掩盖了"目录配错了"）
    """
    suite_row = await suite_service.get_suite(session, suite_id)

    root = discover_integration.resolve_suite_root(body.suite_root)
    result = discover_integration.collect_suite(root)

    if not result.ok:
        kind = result.error
        if kind == discover_integration.DiscoverErrorKind.ROOT_MISSING:
            raise discover_failed(
                f"suite_root 不存在：{root}",
                result.stderr_tail,
                result.returncode,
            )
        if kind == discover_integration.DiscoverErrorKind.ROOT_NOT_DIR:
            raise discover_failed(
                f"suite_root 不是目录：{root}",
                result.stderr_tail,
                result.returncode,
            )
        if kind == discover_integration.DiscoverErrorKind.TIMEOUT:
            raise discover_failed(
                f"用例收集超时（{discover_integration.DISCOVER_TIMEOUT_S}s）：{root}",
                result.stderr_tail,
                result.returncode,
            )
        if kind == discover_integration.DiscoverErrorKind.NO_TESTS:
            raise discover_failed(
                f"未收集到任何用例：{root}",
                result.stderr_tail,
                result.returncode,
            )
        if kind == discover_integration.DiscoverErrorKind.PYTEST_MISSING:
            raise discover_failed(
                "宿主解释器缺少 pytest，无法收集用例",
                result.stderr_tail,
                result.returncode,
            )
        raise discover_failed(
            f"pytest --collect-only 失败（退出码 {result.returncode}）：{root}",
            result.stderr_tail,
            result.returncode,
        )

    version = await suite_service.create_version(
        session,
        suite_row=suite_row,
        node_ids=result.node_ids,
        source_ref=body.source_ref,
        source_commit=body.source_commit,
        extra={"suite_root": str(root)},
    )
    return version
