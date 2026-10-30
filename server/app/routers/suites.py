"""套件与套件版本：来源 / 登记 / 版本 / 发现用例。

设计约束（来自 0001 真源与 spec §9.2）
--------------------------------------
- test_suites **没有配置列**：套件来源只能按服务端预配置的 source_id 解析，
  浏览器不能传任意宿主路径。
- schema 里**没有 cases 表**：用例清单存在 suite_versions.manifest 的 jsonb 里。
- suite_versions 不可变：每次 discover 追加一个新版本，不覆盖历史版本。
- 发现跑在宿主子进程里（app/integrations/discover.py），只做 pytest --collect-only，
  不 import 被测代码到 API 进程，也不碰 vendor/**；发现读的是固定副本，
  不是可变来源目录。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..domain import suite as suite_domain
from ..errors import validation_error
from ..integrations import discover as discover_integration
from ..schemas import SuiteCreateIn, SuiteDiscoverIn, SuiteSourcesOut
from ..services import suites as suite_service
from .tasks import require_client_header

router = APIRouter(tags=["suites"])


@router.get("/suite-sources", response_model=SuiteSourcesOut)
async def list_suite_sources() -> dict[str, Any]:
    """预配置套件来源：只返回 source_id、显示名与适用类型，不含宿主目录。"""
    items = discover_integration.list_suite_sources()
    return {"items": items, "total": len(items)}


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


@router.post("/suites", status_code=201)
async def create_suite(
    body: SuiteCreateIn,
    _client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """从预配置来源登记套件并发布 V1（来源 -> 固定副本 -> 发现）。

    失败语义：
      - 应用不存在           -> 404 not_found
      - source_id 未配置/不适用 -> 400 validation_error（details.reason）
      - 来源越界/链接逃逸     -> 422 discover_failed（details.reason）
      - 来源缺失/不是目录     -> 422 discover_failed
      - 复制期间来源变化      -> 422 discover_failed（reason=source_changed）
      - 磁盘不足             -> 422 discover_failed（reason=disk_full，不淘汰旧副本）
      - pytest 失败/0 用例    -> 422 discover_failed（带 stderr 尾巴）
      - 同名套件已存在        -> 409 state_conflict
    """
    return await suite_service.create_suite(
        session,
        application_id=body.application_id,
        name=body.name,
        test_type=body.test_type,
        source_id=body.source_id,
        source_ref=body.source_ref,
        source_commit=body.source_commit,
    )


@router.get("/suites/{suite_id}/versions")
async def list_suite_versions(
    suite_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """套件版本列表（version 倒序），每个版本带 case_count 与是否保留固定代码。"""
    return await suite_service.list_versions(session, suite_id)


@router.post("/suites/{suite_id}/discover", status_code=201)
async def discover_suite(
    suite_id: str,
    body: SuiteDiscoverIn,
    client: str = Depends(require_client_header),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """按预配置 source_id 复制固定副本并在副本上发现，追加一个新版本。

    失败语义与 POST /suites 相同；失败不发布半成品版本，诊断留在副本目录。
    """
    suite_row = await suite_service.get_suite(session, suite_id)
    return await suite_service.discover_version(
        session,
        suite_row=suite_row,
        source_id=body.source_id,
        source_ref=body.source_ref,
        source_commit=body.source_commit,
    )
