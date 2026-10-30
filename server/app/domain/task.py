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

from dataclasses import dataclass, field
from typing import Any

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
    if suite_version_id is None:
        missing.append("suite_version_id")
    elif suite_version is None:
        invalid.append("suite_version_id: 该套件版本不存在")
    elif case_total <= 0:
        invalid.append("suite_version_id: 该套件版本没有收集到任何用例")
    else:
        test_type = str(revision.get("test_type") or "")
        manifest = suite_version.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        if test_type in ("ui", "joint") and not isinstance(manifest.get("code_copy"), dict):
            invalid.append("suite_version_id: 该套件版本未保留固定代码副本，请重新发现并创建新版本")

    if not revision.get("build_id"):
        missing.append("build_id")

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
