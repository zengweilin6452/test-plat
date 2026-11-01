"""任务与修订的状态机（唯一入口）。

三列状态的取值真源是 DB CHECK（server/alembic/versions/0001_initial.py）：
  test_tasks.lifecycle      IN ('draft','ready','archived')
  test_tasks.lock_version   > 0
  task_revisions.readiness  IN ('draft','validated')
本模块只判断"给定当前状态与动作，是否允许、下一个状态是什么"，不发 SQL。

三条与业务强相关的硬规则：
1. 修订不可变：改任务只能**追加**一条 revision，永不 UPDATE 旧 revision。
   所以 PATCH 是"插入新行"，旧行的 readiness / config / build_id 保持原样。
2. 归档是终态：archived 之后不允许 PATCH / validate（409 illegal_transition），
   但 archive 本身幂等（再点一次仍 200 + 当前对象）。
3. readiness 只能通过 validate 动作从 draft 升到 validated；PATCH 会把它打回 draft，
   因为配置一变，之前"验过"的结论就失效了。

readiness 校验返回 missing / invalid 两组原因而不是单个布尔：前端需要把
"还缺什么"(missing) 与 "填错了什么"(invalid) 分别渲染到向导的对应步骤上。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

#: test_tasks.lifecycle 的合法值（与 CHECK 一致）
LIFECYCLES = ("draft", "ready", "archived")
#: task_revisions.readiness 的合法值（与 CHECK 一致）
READINESSES = ("draft", "validated")
#: task_revisions.test_type 的合法值（与 CHECK 一致）
TEST_TYPES = ("ui", "performance", "joint")

#: 已归档任务禁止的策略名（放进 details 方便前端提示）
ARCHIVED_PATCH_DENIED = "archived_task_immutable"


@dataclass(frozen=True)
class ReadinessReport:
    """readiness 校验结果。ok 为 False 时 missing / invalid 至少有一项非空。"""

    ok: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)

    def as_details(self) -> dict[str, Any]:
        return {"missing": list(self.missing), "invalid": list(self.invalid)}


def can_patch(lifecycle: str) -> bool:
    """归档后不可再改；draft / ready 都可改（ready 改完回 draft）。"""
    return lifecycle != "archived"


def can_validate(lifecycle: str) -> bool:
    return lifecycle != "archived"


def lifecycle_after_patch(lifecycle: str) -> str:
    """PATCH 成功后 lifecycle 归位：ready 被改回 draft（配置变了就不算 ready）。"""
    if lifecycle == "archived":  # pragma: no cover - 由 can_patch 拦住
        raise ValueError("archived 任务不可 PATCH")
    return "draft"


def lifecycle_after_validate(lifecycle: str) -> str:
    """validate 成功：draft -> ready；已经 ready 时保持 ready（幂等）。"""
    if lifecycle == "archived":
        raise ValueError("archived 任务不可 validate")
    return "ready"


def lifecycle_after_archive() -> str:
    return "archived"


def readiness_after_patch() -> str:
    """PATCH 产生的新修订总是 draft：必须重新 validate。"""
    return "draft"


def readiness_after_validate() -> str:
    return "validated"


def next_lock_version(current: int | None) -> int:
    """CAS 成功后的新 lock_version（每次写任务都 +1，单调递增）。"""
    return int(current or 1) + 1


def check_readiness(
    *,
    revision: dict[str, Any],
    platform: str,
    application_platform: str | None,
    suite_version: dict[str, Any] | None,
    case_total: int,
    suite_test_type: str | None = None,
) -> ReadinessReport:
    """校验修订是否满足"可运行"的必要条件。

    必要条件（对应任务书 P2 validate 契约）：
      1. suite_version_id 必须存在，且该版本已绑定 cases（case_total > 0）；
      2. 任务平台必须与应用的 platform 一致；
      3. DB 有一条跨列 CHECK「readiness='validated' 要求 build_id 与
         suite_version_id 都非空」(ck_task_revisions_readiness_requires_build_and_suite)。
         不在这里挡住，UPDATE 就会撞 500，所以缺 build 时明确报 missing；
      4. UI / joint 套件版本必须保留固定代码副本（spec §6.5）。旧版本只有
         local 标记或原目录时标“未保留固定代码”，新运行前须显式创建新版本，
         不追认旧运行使用了新代码。performance 声明式场景不需要代码副本。

    suite_version 为 None 表示"填了 id 但库里查不到"，属 invalid 而非 missing。
    """
    missing: list[str] = []
    invalid: list[str] = []

    suite_version_id = revision.get("suite_version_id")
    rev_test_type = str(revision.get("test_type") or "")
    effective_type = rev_test_type or suite_test_type or ""
    if suite_version_id is None:
        missing.append("suite_version_id")
    elif suite_version is None:
        invalid.append("suite_version_id: 该套件版本不存在")
    else:
        manifest = suite_version.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        if suite_test_type and rev_test_type and suite_test_type != rev_test_type:
            # 套件与修订的测试类型必须一致（spec §6.6 / AC-INPUT-03）
            invalid.append(
                f"suite_version_id: 套件类型 {suite_test_type!r} 与修订类型 {rev_test_type!r} 不一致"
            )
        elif isinstance(manifest.get("test_type"), str):
            # 新版本清单带类型标记：按 §6.6 的清单规则逐项校验
            from . import suite as suite_domain

            invalid.extend(
                f"suite_version_id: {problem}"
                for problem in suite_domain.validate_manifest(
                    manifest, test_type=effective_type or str(manifest["test_type"])
                )
            )
            if effective_type in ("ui", "joint") and not isinstance(
                manifest.get("code_copy"), dict
            ):
                invalid.append(
                    "suite_version_id: 该套件版本未保留固定代码副本，请重新发现并创建新版本"
                )
        else:
            # 旧版本清单没有类型标记：沿用旧口径，只要求 UI/joint 有用例与固定副本
            if effective_type in ("ui", "joint") and case_total <= 0:
                invalid.append("suite_version_id: 该套件版本没有收集到任何用例")
            if effective_type in ("ui", "joint") and not isinstance(
                manifest.get("code_copy"), dict
            ):
                invalid.append(
                    "suite_version_id: 该套件版本未保留固定代码副本，请重新发现并创建新版本"
                )

    if not revision.get("build_id"):
        missing.append("build_id")

    # 声明式性能场景（工单 06）：performance/joint 的执行时长与采集项必须在
    # 修订 readiness 就锁死在 10–3600 秒整数、items 非空——与套件发布口
    # （suite.validate_manifest）同一份规则，且与套件版本场景不一致时拒绝，
    # 而不是把非法场景留到 runner 才发现。
    # 套件版本尚不存在时不做场景判定：那时"还没有场景"是 suite_version_id
    # 缺失的后果，提前报 config.perf 会把向导指到错误的步骤。
    if effective_type in ("performance", "joint") and suite_version is not None:
        from . import suite as suite_domain

        manifest = (
            suite_version.get("manifest")
            if isinstance(suite_version, dict)
            and isinstance(suite_version.get("manifest"), dict)
            else {}
        )
        revision_config = revision.get("config") or {}
        revision_perf = revision_config.get("perf")
        scenario_problems_list: list[str] = []
        try:
            scenario, _source = suite_domain.resolve_scenario(
                test_type=effective_type, manifest=manifest, revision_perf=revision_perf
            )
        except suite_domain.PerfScenarioConflict as exc:
            scenario_problems_list.append(str(exc))
        else:
            scenario_problems_list.extend(suite_domain.scenario_problems(scenario))
            # 「写了 perf 键但内容空」也是一种声明：不能因为合并时被当成缺省而放过。
            if "perf" in revision_config:
                scenario_problems_list.extend(
                    problem
                    for problem in suite_domain.scenario_problems(revision_perf)
                    if problem not in scenario_problems_list
                )
        invalid.extend(
            f"config.perf: {problem}" for problem in scenario_problems_list
        )

    if application_platform is None:
        invalid.append("application_id: 应用不存在")
    elif platform != application_platform:
        invalid.append(f"platform: 任务平台 {platform!r} 与应用平台 {application_platform!r} 不一致")

    return ReadinessReport(ok=not missing and not invalid, missing=missing, invalid=invalid)


def config_merged(old: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    """修订 config 是整体快照：PATCH 给出则整份替换，未给出则沿用旧值。

    不做深合并 —— 深合并无法表达"删除某个键"（前端删掉整段配置时会静默保留）。
    """
    if patch is None:
        return dict(old or {})
    return dict(patch)


# --------------------------------------------------------------------------- #
# 创建身份：同名复用 / 幂等键的内容比较（spec §9.1）
# --------------------------------------------------------------------------- #
#: 决定"是不是同一个创建请求"的字段（应用与名称由查询条件保证相同，不重复比较）。
#: 键的顺序就是差异字段的输出顺序，前端按它渲染"哪几项不同"。
CREATE_IDENTITY_FIELDS = (
    "platform",
    "test_type",
    "build_id",
    "suite_version_id",
    "environment_id",
    "config",
)


def canonical_content(value: Any) -> str:
    """规范化 JSON：对象键顺序不产生新内容（spec §9.1）。

    sort_keys 递归生效，所以 config 里嵌套对象的键序也不影响比较；
    ensure_ascii=False 让中文按原文参与摘要，避免不同编码方式产生不同指纹。
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def create_content_fingerprint(content: Mapping[str, Any]) -> str:
    """创建内容的摘要：幂等键用它判断"同键是否同内容"。"""
    return hashlib.sha256(canonical_content(dict(content)).encode("utf-8")).hexdigest()


def create_content_diff(existing: Mapping[str, Any], requested: Mapping[str, Any]) -> list[str]:
    """同名任务与本次创建请求的差异字段名（空列表表示同内容，可复用）。

    只返回字段名，不回传字段值：错误 details 里不能出现配置内容（spec §9.1）。
    """
    return [
        name
        for name in CREATE_IDENTITY_FIELDS
        if canonical_content(existing.get(name)) != canonical_content(requested.get(name))
    ]
