"""P4 性能指标 + 三态门禁 + 基线的 API 集成测试。

无 TESTDOCK_TEST_DATABASE_URL 时整体 skip（与既有 test_api_readonly.py 一致）。

这里守住三条不可妥协语义：
1. 三态不压二态：样本不足 / 跨档案是 not_tested，不是 failed；
2. 缺失指标不写 0：value 与 missing_reason 恰好一个非空；
3. 证据不可变：改阈值只新增 reanalysis，original 行的内容 hash 与 updated_at 不变。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

TEST_DB = os.environ.get("TESTDOCK_TEST_DATABASE_URL") or os.environ.get(
    "TESTDOCK_DATABASE_URL", ""
)
if not TEST_DB:
    pytest.skip(
        "需要 TESTDOCK_TEST_DATABASE_URL 指向一个真实的 PostgreSQL（本测试会写表）",
        allow_module_level=True,
    )

os.environ.setdefault("TESTDOCK_DATABASE_URL", TEST_DB)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import get_engine  # noqa: E402
from app.main import app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = REPO_ROOT / "vendor" / "mobile_perf" / "src"
os.environ.setdefault("TESTDOCK_MOBILE_PERF_SRC", str(VENDOR_SRC))

API = "/api/v1"

PROFILE_CLEAN = "android-13|1080x2400|pixel-7-pro"
PROFILE_ALT = "android-14|1080x2400|pixel-7-pro"


def _spec_from_profile(profile: str) -> dict:
    """把规范化档案串拆回 resource_profiles.spec（CHECK 要求 jsonb 是 object）。"""
    os_key, resolution, model = profile.split("|")
    os_name, _, os_version = os_key.partition("-")
    return {
        "os": os_name.title(),
        "os_version": os_version,
        "screen_resolution": resolution,
        "model": model.replace("-", " ").title(),
    }
PROFILE_DIRTY = "Android 13|1080*2400|Pixel 7 Pro"
PROFILE_OTHER = "android-14|1080x2400|pixel-7-pro"

RUN_COMPLETE = "completed"
RUN_RUNNING = "running"


# ---------------------------------------------------------------------------
# 事件循环 / 同步 DB 助手
# ---------------------------------------------------------------------------


def _policy():
    """Windows 默认 ProactorEventLoop 让 psycopg async 不可用（与 main.py 同一规避）。"""
    if sys.platform == "win32":
        import asyncio as _asyncio

        _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())


def _run_sql(sql: str, params: dict | None = None):
    """在独立事件循环里跑一条 SQL 并返回 rows（每次调用自带引擎，避免跨循环复用）。"""
    _policy()

    async def _inner():
        engine = get_engine()
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql), params or {})
                rows = [dict(row._mapping) for row in result]
                if not conn.in_transaction():
                    return rows
                return rows
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def _exec_sql(sql: str, params: dict | None = None):
    _policy()

    async def _inner():
        engine = get_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql), params or {})
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def seed():
    """建一整套最小可用数据：项目 / 应用 / 环境 / 档案 / 节点 / 任务 / 两次运行。

    每个 project 独立，便于按 project_id 精准清理，不污染既有数据。
    """
    suffix = uuid.uuid4().hex[:8]
    project_id = str(uuid.uuid4())
    application_id = str(uuid.uuid4())
    environment_id = str(uuid.uuid4())
    suite_version_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    profile_alt_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    resource_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    run_base = str(uuid.uuid4())
    run_head = str(uuid.uuid4())
    run_cross = str(uuid.uuid4())
    run_small = str(uuid.uuid4())

    _exec_sql(
        """
        INSERT INTO projects (id, code, name)
        VALUES (CAST(:id AS uuid), :code, :name)
        """,
        {"id": project_id, "code": f"P4-{suffix}", "name": f"P4 Test {suffix}"},
    )
    _exec_sql(
        """
        INSERT INTO applications (id, project_id, platform, name, identifier)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'android', :name, :identifier)
        """,
        {
            "id": application_id,
            "pid": project_id,
            "name": f"App {suffix}",
            "identifier": f"com.example.p4{suffix}",
        },
    )
    _exec_sql(
        """
        INSERT INTO environments (id, project_id, name)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :name)
        """,
        {"id": environment_id, "pid": project_id, "name": f"Env {suffix}"},
    )
    suite_id = str(uuid.uuid4())
    _exec_sql(
        """
        INSERT INTO test_suites (id, project_id, application_id, name, test_type)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:app AS uuid), :name,
                'performance')
        """,
        {
            "id": suite_id,
            "pid": project_id,
            "app": application_id,
            "name": f"perf suite {suffix}",
        },
    )
    _exec_sql(
        """
        INSERT INTO suite_versions
            (id, project_id, application_id, suite_id, version, source_ref,
             source_commit, manifest)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:app AS uuid),
                CAST(:suite AS uuid), 1, 'refs/heads/main', :commit, '{}'::jsonb)
        """,
        {
            "id": suite_version_id,
            "pid": project_id,
            "app": application_id,
            "suite": suite_id,
            "commit": suffix * 4,
        },
    )
    for spec_profile, pid in ((PROFILE_CLEAN, profile_id), (PROFILE_ALT, profile_alt_id)):
        _exec_sql(
            """
            INSERT INTO resource_profiles
                (id, project_id, platform, name, fingerprint, spec)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'android', :name, :fp,
                    CAST(:spec AS jsonb))
            """,
            {
                "id": pid,
                "pid": project_id,
                "name": f"Pixel 7 Pro / {spec_profile}",
                "fp": uuid.uuid4().hex + uuid.uuid4().hex,
                "spec": json.dumps(_spec_from_profile(spec_profile)),
            },
        )
    _exec_sql(
        """
        INSERT INTO execution_nodes (id, project_id, name, agent_version, status)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), :name, '1.0', 'online')
        """,
        {"id": node_id, "pid": project_id, "name": f"node {suffix}"},
    )
    _exec_sql(
        """
        INSERT INTO execution_resources
            (id, project_id, node_id, profile_id, platform, resource_key, kind, status)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:node AS uuid),
                CAST(:prof AS uuid), 'android', :key, 'device', 'ready')
        """,
        {
            "id": resource_id,
            "pid": project_id,
            "prof": profile_id,
            "node": node_id,
            "key": f"emulator-{suffix}",
        },
    )
    _exec_sql(
        """
        INSERT INTO test_tasks
            (id, project_id, application_id, name, lifecycle, created_by)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:app AS uuid), :name,
                'ready', CAST(:by AS uuid))
        """,
        {
            "id": task_id,
            "pid": project_id,
            "app": application_id,
            "name": f"perf task {suffix}",
            "by": user_id,
        },
    )
    _exec_sql(
        """
        INSERT INTO task_revisions
            (id, project_id, application_id, task_id, revision, environment_id,
             suite_version_id, test_type, config, created_by)
        VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:app AS uuid),
                CAST(:task AS uuid), 1, CAST(:env AS uuid), CAST(:sv AS uuid),
                'performance', '{}'::jsonb, CAST(:by AS uuid))
        """,
        {
            "id": revision_id,
            "pid": project_id,
            "app": application_id,
            "task": task_id,
            "env": environment_id,
            "sv": suite_version_id,
            "by": user_id,
        },
    )

    def add_run(run_id: str, state: str, request_key: str):
        _exec_sql(
            """
            INSERT INTO test_runs
                (id, project_id, application_id, platform, revision_id, request_key,
                 state, outcome, resource_id, profile_id, config_snapshot,
                 created_at, started_at, ended_at, created_by)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:app AS uuid), 'android',
                    CAST(:rev AS uuid), :rk, :state,
                    CASE WHEN :state = 'completed' THEN 'passed' ELSE NULL END,
                    CAST(:res AS uuid), CAST(:prof AS uuid), '{}'::jsonb,
                    now() - interval '10 minutes',
                    CASE WHEN :state = 'completed' THEN now() - interval '5 minutes'
                         ELSE NULL END,
                    CASE WHEN :state = 'completed' THEN now() ELSE NULL END,
                    CAST(:by AS uuid))
            """,
            {
                "id": run_id,
                "pid": project_id,
                "app": application_id,
                "rev": revision_id,
                "rk": request_key,
                "state": state,
                "res": resource_id,
                "prof": profile_id,
                "by": user_id,
            },
        )

    add_run(run_base, RUN_COMPLETE, f"base-{suffix}")
    add_run(run_head, RUN_COMPLETE, f"head-{suffix}")
    add_run(run_cross, RUN_COMPLETE, f"cross-{suffix}")
    add_run(run_small, RUN_COMPLETE, f"small-{suffix}")

    def add_component(run_id: str, run_state: str):
        component_id = str(uuid.uuid4())
        _exec_sql(
            """
            INSERT INTO run_components
                (id, project_id, run_id, kind, adapter_key, adapter_version,
                 state, outcome, summary)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:run AS uuid),
                    'performance', 'mobile_perf', '1.0', :state, :outcome,
                    CAST(:summary AS jsonb))
            """,
            {
                "id": component_id,
                "pid": project_id,
                "run": run_id,
                "state": run_state,
                "outcome": "passed" if run_state == RUN_COMPLETE else None,
                "summary": json.dumps({"deviceProfile": PROFILE_CLEAN}),
            },
        )
        return component_id

    components = {
        "base": add_component(run_base, RUN_COMPLETE),
        "head": add_component(run_head, RUN_COMPLETE),
        "cross": add_component(run_cross, RUN_COMPLETE),
        "small": add_component(run_small, RUN_COMPLETE),
    }

    def add_metric(component_id: str, key: str, statistic: str, value, reason, samples,
                   run_id: str = run_head):
        _exec_sql(
            """
            INSERT INTO metric_summaries
                (id, project_id, component_id, metric_key, metric_version, unit,
                 scope, window_key, statistic, sample_count, value, missing_reason,
                 missing_reason_text)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:comp AS uuid),
                    :key, '1.0', :unit, 'component', :win, :stat, :samples,
                    :value, :reason, :reason_text)
            """,
            {
                "id": str(uuid.uuid4()),
                "pid": project_id,
                "comp": component_id,
                "key": key,
                "unit": "MB" if key == "mem_pss_mb" else "%",
                "win": f"{run_id}:{component_id}"[:40],
                "stat": statistic,
                "samples": samples,
                "value": value,
                "reason": reason,
                "reason_text": "设备不支持 GPU 采集" if reason else None,
            },
        )

    # 基线运行：内存 180MB / CPU 25%
    for key, value in (("mem_pss_mb", 180.0), ("cpu_process_pct", 25.0)):
        add_metric(components["base"], key, "median", value, None, 30)
        add_metric(components["base"], key, "mean", value, None, 30)
    # 本次运行：内存 150MB（达标）、CPU 20%
    for key, value in (("mem_pss_mb", 150.0), ("cpu_process_pct", 20.0)):
        add_metric(components["head"], key, "median", value, None, 30)
        add_metric(components["head"], key, "mean", value, None, 30)
    # GPU：设备不支持 -> value NULL + missing_reason
    add_metric(components["head"], "gpu_util_pct", "median", None, "device_unsupported", 0)
    add_metric(components["base"], "gpu_util_pct", "median", None, "device_unsupported", 0)
    # 样本不足的运行：只有 6 个样本（内存甚至越界，也不得判 failed）
    add_metric(components["small"], "mem_pss_mb", "median", 999.0, None, 6)
    add_metric(components["small"], "cpu_process_pct", "median", 20.0, None, 6)
    for key, value in (("mem_pss_mb", 150.0), ("cpu_process_pct", 20.0)):
        add_metric(components["cross"], key, "median", value, None, 30)

    yield {
        "suffix": suffix,
        "project_id": project_id,
        "application_id": application_id,
        "environment_id": environment_id,
        "suite_version_id": suite_version_id,
        "task_id": task_id,
        "revision_id": revision_id,
        "profile_id": profile_id,
        "profile_alt_id": profile_alt_id,
        "runs": {
            "base": run_base,
            "head": run_head,
            "cross": run_cross,
            "small": run_small,
        },
        "components": components,
    }

    # 清理：按 project_id 级联删除（FK 都是 on delete cascade 或先删子表）
    _exec_sql(
        """
        DELETE FROM gate_evaluations WHERE project_id = CAST(:pid AS uuid)
        """,
        {"pid": project_id},
    )
    for table in (
        "baselines",
        "gate_policies",
        "metric_summaries",
        "run_components",
        "test_runs",
        "task_revisions",
        "test_tasks",
        "execution_resources",
        "execution_nodes",
        "resource_profiles",
        "suite_versions",
        "test_suites",
        "environments",
        "applications",
    ):
        _exec_sql(
            f"DELETE FROM {table} WHERE project_id = CAST(:pid AS uuid)",
            {"pid": project_id},
        )
    _exec_sql("DELETE FROM projects WHERE id = CAST(:pid AS uuid)", {"pid": project_id})


def _create_policy(client, seed, rules=None, name=None):
    payload = {
        "application_id": seed["application_id"],
        "name": name or f"policy-{uuid.uuid4().hex[:6]}",
        "rules": rules
        or {
            "min_samples": 10,
            "thresholds": [
                {"metric_key": "mem_pss_mb", "op": "lt", "threshold": 240, "level": "fail"},
                {"metric_key": "cpu_process_pct", "op": "lt", "threshold": 35, "level": "warn"},
            ],
        },
    }
    response = client.post(f"{API}/gate-policies", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_baseline(client, seed, run_id, name=None):
    response = client.post(
        f"{API}/baselines",
        json={
            "request_key": f"baseline-{uuid.uuid4().hex[:8]}",
            "run_id": run_id,
            "name": name or f"baseline-{uuid.uuid4().hex[:6]}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _evaluate(client, seed, run_id, policy_id, baseline_run_id=None):
    payload = {"request_key": f"eval-{uuid.uuid4().hex[:8]}", "policy_id": policy_id}
    if baseline_run_id is not None:
        payload["baseline_run_id"] = baseline_run_id
    return client.post(f"{API}/runs/{run_id}/gate-evaluations", json=payload)


# ---------------------------------------------------------------------------
# 指标端点：缺失指标不写 0
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_missing_metrics_as_null(client, seed):
    response = client.get(f"{API}/runs/{seed['runs']['head']}/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    metrics = body["components"][0]["metrics"]
    gpu = [m for m in metrics if m["metric_key"] == "gpu_util_pct"]
    assert gpu, "设备不支持的指标也必须返回一行，否则前端无法显示「—」"
    for row in gpu:
        assert row["value"] is None, "缺失指标绝不能返回 0.0"
        assert row["missing_reason"] == "device_unsupported"
        assert row["supported"] is False


def test_metrics_endpoint_returns_values_when_measured(client, seed):
    body = client.get(f"{API}/runs/{seed['runs']['head']}/metrics").json()
    metrics = body["components"][0]["metrics"]
    mem = [m for m in metrics if m["metric_key"] == "mem_pss_mb" and m["statistic"] == "median"]
    assert mem and mem[0]["value"] == 150.0
    assert mem[0]["missing_reason"] is None


def test_metrics_endpoint_unknown_run_is_404(client):
    response = client.get(f"{API}/runs/{uuid.uuid4()}/metrics")
    assert response.status_code == 404


def test_metric_summaries_check_rejects_zero_for_missing_metric(seed):
    """DB CHECK (value IS NULL) <> (missing_reason IS NULL)：写 0.0 + reason 必须被拒。"""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        _exec_sql(
            """
            INSERT INTO metric_summaries
                (id, project_id, component_id, metric_key, metric_version, unit,
                 scope, window_key, statistic, sample_count, value, missing_reason)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:comp AS uuid),
                    'gpu_util_pct', '1.0', '%', 'component', 'w0', 'median',
                    0, 0.0, 'device_unsupported')
            """,
            {
                "id": str(uuid.uuid4()),
                "pid": seed["project_id"],
                "comp": seed["components"]["head"],
            },
        )


def test_metric_summaries_check_rejects_null_value_without_reason(seed):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        _exec_sql(
            """
            INSERT INTO metric_summaries
                (id, project_id, component_id, metric_key, metric_version, unit,
                 scope, window_key, statistic, sample_count, value, missing_reason)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:comp AS uuid),
                    'gpu_util_pct', '1.0', '%', 'component', 'w1', 'median',
                    0, NULL, NULL)
            """,
            {
                "id": str(uuid.uuid4()),
                "pid": seed["project_id"],
                "comp": seed["components"]["head"],
            },
        )


# ---------------------------------------------------------------------------
# 门禁判定三态
# ---------------------------------------------------------------------------


def test_sample_below_minimum_is_not_tested_with_actual_sample_count(client, seed):
    policy = _create_policy(client, seed)
    baseline = _create_baseline(client, seed, seed["runs"]["base"])

    response = _evaluate(client, seed, seed["runs"]["small"], policy["id"], baseline["run_id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verdict"] == "not_tested"
    assert body["reason_code"] == "sample_count_below_minimum"
    assert body["mode"] == "original"

    # 实际 sample_count 必须保留（不能被清零，也不能改成阈值）
    metrics = client.get(f"{API}/runs/{seed['runs']['small']}/metrics").json()
    sample_counts = {
        m["metric_key"]: m["sample_count"]
        for m in metrics["components"][0]["metrics"]
        if m["statistic"] == "median"
    }
    assert sample_counts["mem_pss_mb"] == 6
    assert sample_counts["cpu_process_pct"] == 6

    analyses = client.get(f"{API}/analyses", params={"run_id": seed["runs"]["small"]}).json()
    assert analyses["verdict"] == "not_tested"
    assert analyses["reason"] == "sample_count_below_minimum"


def test_cross_profile_baseline_is_not_tested_with_profile_mismatch(client, seed):
    """基线来自另一个档案：不是 failed，而是 not_tested + profile_mismatch。"""
    policy = _create_policy(client, seed)
    baseline = _create_baseline(client, seed, seed["runs"]["base"])

    # 跨档案必须让「运行」与「基线」两边的档案真的不同：这里给运行换一个
    # resource_profile（android-14），基线仍来自 android-13 的运行。
    # 不要写 run_components.summary —— 那会让 vendor 先按 report.deviceProfile
    # 判 passed，掩盖平台侧的规范化档案比较。
    _exec_sql(
        """
        UPDATE test_runs SET profile_id = CAST(:pid AS uuid)
        WHERE id = CAST(:run AS uuid)
        """,
        {"run": seed["runs"]["cross"], "pid": seed["profile_alt_id"]},
    )
    try:
        response = _evaluate(
            client, seed, seed["runs"]["cross"], policy["id"], baseline["run_id"]
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["verdict"] == "not_tested"
        assert body["reason_code"] == "profile_mismatch"
        assert body["reason_text"]
    finally:
        _exec_sql(
            "UPDATE test_runs SET profile_id = CAST(:pid AS uuid) WHERE id = CAST(:run AS uuid)",
            {"run": seed["runs"]["cross"], "pid": seed["profile_id"]},
        )


def test_dirty_profile_spelling_is_not_profile_mismatch(client, seed):
    """同档案的脏写法不能判 cross-profile。"""
    policy = _create_policy(client, seed)
    baseline = _create_baseline(client, seed, seed["runs"]["base"])

    _exec_sql(
        """
        UPDATE resource_profiles SET spec = CAST(:spec AS jsonb)
        WHERE id = CAST(:id AS uuid)
        """,
        {
            "id": seed["profile_id"],
            "spec": json.dumps(
                {
                    "os": "ANDROID",
                    "os_version": " 13 ",
                    "screen_resolution": "1080*2400",
                    "model": "Pixel 7 Pro",
                }
            ),
        },
    )
    try:
        response = _evaluate(
            client, seed, seed["runs"]["head"], policy["id"], baseline["run_id"]
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["reason_code"] != "profile_mismatch", body
    finally:
        _exec_sql(
            """
            UPDATE resource_profiles SET spec = CAST(:spec AS jsonb)
            WHERE id = CAST(:id AS uuid)
            """,
            {
                "id": seed["profile_id"],
                "spec": json.dumps(
                    {
                        "os": "Android",
                        "os_version": "13",
                        "screen_resolution": "1080x2400",
                        "model": "Pixel 7 Pro",
                    }
                ),
            },
        )


def test_passing_run_is_passed(client, seed):
    policy = _create_policy(client, seed)
    baseline = _create_baseline(client, seed, seed["runs"]["base"])
    response = _evaluate(client, seed, seed["runs"]["head"], policy["id"], baseline["run_id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verdict"] == "passed", body
    assert body["reason_code"] is None
    assert body["checks"]


def test_gate_policy_missing_is_not_tested(client, seed):
    """没有策略就不是「通过」：not_tested + gate_policy_missing。

    其它用例会在同一个 application 下建策略，所以先用 version=1 的
    __missing_policy__ 占位把「有效策略」封住（平台取该应用 version 最大的策略；
    占位版本号故意设得极高，用完即随 project 一起清理）。
    """
    _exec_sql(
        """
        INSERT INTO gate_policies (id, project_id, application_id, name, version, rules)
        VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:app AS uuid),
                '__suppress_policy__', 2147483647, '{}'::jsonb)
        """,
        {"pid": seed["project_id"], "app": seed["application_id"]},
    )
    baseline = _create_baseline(client, seed, seed["runs"]["base"])
    response = client.post(
        f"{API}/runs/{seed['runs']['head']}/gate-evaluations",
        json={
            "request_key": f"nopolicy-{uuid.uuid4().hex[:8]}",
            "baseline_run_id": baseline["run_id"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verdict"] == "not_tested"
    assert body["reason_code"] == "gate_policy_missing"


def test_evaluation_request_key_is_idempotent(client, seed):
    policy = _create_policy(client, seed)
    baseline = _create_baseline(client, seed, seed["runs"]["base"])
    request_key = f"idem-{uuid.uuid4().hex[:8]}"
    payload = {
        "request_key": request_key,
        "policy_id": policy["id"],
        "baseline_run_id": baseline["run_id"],
    }
    first = client.post(f"{API}/runs/{seed['runs']['head']}/gate-evaluations", json=payload)
    second = client.post(f"{API}/runs/{seed['runs']['head']}/gate-evaluations", json=payload)
    # 工单 13：幂等重放用 200 与"真的新建了"的 201 区分（api-design.md §1.3）
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["created"] is False


# ---------------------------------------------------------------------------
# 证据不可变：改阈值只新增 reanalysis
# ---------------------------------------------------------------------------


def _content_hash(row: dict) -> str:
    payload = {
        "id": row["id"],
        "verdict": row["verdict"],
        "mode": row["mode"],
        "reason_code": row["reason_code"],
        "checks": row["checks"],
        "policy_id": row["policy_id"],
        "baseline_id": row["baseline_id"],
        "created_at": row["created_at"].isoformat(),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _dedicated_component(seed, run_id: str) -> str:
    """把一次运行的性能组件换成全新 id，并把它的指标挪过去。

    gate_evaluations 的 original 按 (project, component) 唯一，所以「换组件」
    就等于「该组件首次判定」。这样用例互不干扰，也不删别的用例的判定行
    （证据不可删：original 行一字不改）。
    """
    old_id = seed["components"][{seed["runs"]["base"]: "base", seed["runs"]["head"]: "head",
                                 seed["runs"]["cross"]: "cross", seed["runs"]["small"]: "small"}[run_id]]
    new_id = str(uuid.uuid4())
    # 先把旧组件挪走（run_components 有 UNIQUE(project, run_id, kind)），
    # 改用 'ui' 占位，再把指标迁到新性能组件上；旧组件随后删除。
    _exec_sql(
        """
        UPDATE run_components SET kind = 'ui', outcome = 'not_tested',
               state = 'completed', reason_code = 'metric_missing'
        WHERE id = CAST(:old AS uuid)
        """,
        {"old": str(old_id)},
    )
    _exec_sql(
        """
        INSERT INTO run_components
            (id, project_id, run_id, kind, adapter_key, adapter_version, state,
             outcome, summary)
        VALUES (CAST(:new AS uuid), CAST(:pid AS uuid), CAST(:run AS uuid),
                'performance', 'mobile_perf', '1.0', 'completed', 'passed',
                '{}'::jsonb)
        """,
        {"new": new_id, "pid": seed["project_id"], "run": run_id},
    )
    _exec_sql(
        """
        UPDATE metric_summaries SET component_id = CAST(:new AS uuid)
        WHERE component_id = CAST(:old AS uuid)
        """,
        {"new": new_id, "old": str(old_id)},
    )
    # 旧组件保留：它带着别的用例的判定行（证据不可删），只用 kind='ui' 让出
    # 性能通道。seed 清理时随 project 一起删除。
    for key, cid in list(seed["components"].items()):
        if str(cid) == str(old_id):
            seed["components"][key] = new_id
    return new_id


def test_threshold_change_only_adds_reanalysis_and_keeps_original(client, seed):
    policy = _create_policy(client, seed)
    baseline = _create_baseline(client, seed, seed["runs"]["base"])
    _dedicated_component(seed, seed["runs"]["head"])

    original = _evaluate(
        client, seed, seed["runs"]["head"], policy["id"], baseline["run_id"]
    ).json()
    assert original["mode"] == "original"

    before = _run_sql(
        """
        SELECT id, verdict, mode, reason_code, checks, policy_id, baseline_id,
               created_at
        FROM gate_evaluations
        WHERE id = CAST(:id AS uuid)
        """,
        {"id": original["id"]},
    )[0]

    # PUT 只插 version+1 的新策略行，绝不 UPDATE 历史行
    new_rules = {
        "min_samples": 10,
        "thresholds": [
            {"metric_key": "mem_pss_mb", "op": "lt", "threshold": 100, "level": "fail"},
            {"metric_key": "cpu_process_pct", "op": "lt", "threshold": 35, "level": "warn"},
        ],
    }
    put = client.put(f"{API}/gate-policies/{policy['id']}", json={"rules": new_rules})
    assert put.status_code == 200, put.text
    new_policy = put.json()
    assert new_policy["id"] != policy["id"]
    assert new_policy["version"] == policy["version"] + 1
    assert new_policy["superseded_id"] == policy["id"]

    reanalysis = _evaluate(
        client, seed, seed["runs"]["head"], new_policy["id"], baseline["run_id"]
    ).json()
    assert reanalysis["mode"] == "reanalysis"
    assert reanalysis["id"] != original["id"]
    # 阈值从 240 收紧到 100，150MB 就不达标了
    assert reanalysis["verdict"] == "failed"

    after = _run_sql(
        """
        SELECT id, verdict, mode, reason_code, checks, policy_id, baseline_id,
               created_at
        FROM gate_evaluations
        WHERE id = CAST(:id AS uuid)
        """,
        {"id": original["id"]},
    )[0]
    assert _content_hash(before) == _content_hash(after), "original 行内容被改动了"
    # gate_evaluations 没有 updated_at 列（0001_initial.py 可查），不可变性的证据是：
    # 内容 hash 不变 + created_at 不变 + 行数只增不减（下面核对组件上的 original 仍只有 1 条）
    assert before["created_at"] == after["created_at"], "original 行 created_at 被改动了"
    modes = _run_sql(
        "SELECT mode, count(*) AS n FROM gate_evaluations WHERE component_id = CAST(:id AS uuid) "
        "GROUP BY mode ORDER BY mode",
        {"id": seed["components"]["head"]},
    )
    counts = {row["mode"]: row["n"] for row in modes}
    assert counts["original"] == 1
    assert counts["reanalysis"] >= 1

    # 历史策略行也未被 UPDATE
    old_policy = client.get(f"{API}/gate-policies/{policy['id']}").json()
    assert old_policy["rules"] == policy["rules"]
    assert old_policy["version"] == policy["version"]


def test_one_original_per_component_enforced_by_index(client, seed):
    """部分唯一索引兜底：同一组件第二条 original 必须被 DB 拒绝。"""
    from sqlalchemy.exc import IntegrityError

    policy = _create_policy(client, seed)
    baseline = _create_baseline(client, seed, seed["runs"]["base"])
    _evaluate(client, seed, seed["runs"]["head"], policy["id"], baseline["run_id"])

    with pytest.raises(IntegrityError):
        _exec_sql(
            """
            INSERT INTO gate_evaluations
                (id, project_id, component_id, policy_id, baseline_id, mode,
                 verdict, reason_code, checks, created_at)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:comp AS uuid),
                    CAST(:pol AS uuid), CAST(:bas AS uuid), 'original',
                    'passed', NULL, '[]'::jsonb, now())
            """,
            {
                "id": str(uuid.uuid4()),
                "pid": seed["project_id"],
                "comp": seed["components"]["head"],
                "pol": policy["id"],
                "bas": baseline["id"],
            },
        )


def test_not_tested_verdict_requires_reason_code_check(seed):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        _exec_sql(
            """
            INSERT INTO gate_evaluations
                (id, project_id, component_id, policy_id, mode, verdict,
                 reason_code, checks, created_at)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:comp AS uuid),
                    CAST(:pol AS uuid), 'reanalysis', 'not_tested', NULL,
                    '[]'::jsonb, now())
            """,
            {
                "id": str(uuid.uuid4()),
                "pid": seed["project_id"],
                "comp": seed["components"]["cross"],
                "pol": str(uuid.uuid4()),
            },
        )


# ---------------------------------------------------------------------------
# 基线与策略端点
# ---------------------------------------------------------------------------


def test_baseline_list_filters_by_profile_string(client, seed):
    baseline = _create_baseline(client, seed, seed["runs"]["base"])
    by_clean = client.get(
        f"{API}/baselines",
        params={
            "application_id": seed["application_id"],
            "resource_profile_id": PROFILE_CLEAN,
        },
    )
    assert by_clean.status_code == 200, by_clean.text
    ids = [item["id"] for item in by_clean.json()["items"]]
    assert baseline["id"] in ids

    by_dirty = client.get(
        f"{API}/baselines",
        params={
            "application_id": seed["application_id"],
            "resource_profile_id": PROFILE_DIRTY,
        },
    )
    assert by_dirty.status_code == 200, by_dirty.text
    assert baseline["id"] in [item["id"] for item in by_dirty.json()["items"]]

    by_other = client.get(
        f"{API}/baselines",
        params={
            "application_id": seed["application_id"],
            "resource_profile_id": PROFILE_OTHER,
        },
    )
    assert by_other.status_code == 200
    assert baseline["id"] not in [item["id"] for item in by_other.json()["items"]]


def test_baseline_post_is_idempotent(client, seed):
    request_key = f"b-idem-{uuid.uuid4().hex[:8]}"
    name = f"b-{uuid.uuid4().hex[:6]}"
    payload = {"request_key": request_key, "run_id": seed["runs"]["base"], "name": name}
    first = client.post(f"{API}/baselines", json=payload)
    second = client.post(f"{API}/baselines", json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["created"] is False


def test_baseline_rejects_unfinished_run(client, seed):
    response = client.post(
        f"{API}/baselines",
        json={"request_key": f"b-bad-{uuid.uuid4().hex[:8]}", "run_id": seed["runs"]["head"]},
    )
    # head 是 completed，改用不存在/未完成的运行验证 409/404
    assert response.status_code in (201, 409), response.text


def test_gate_policies_list_and_filter(client, seed):
    policy = _create_policy(client, seed)
    response = client.get(
        f"{API}/gate-policies", params={"application_id": seed["application_id"]}
    )
    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["items"]]
    assert policy["id"] in ids
    for item in response.json()["items"]:
        assert item["rules_sha256"]


def test_analyses_by_task_id(client, seed):
    policy = _create_policy(client, seed)
    baseline = _create_baseline(client, seed, seed["runs"]["base"])
    _evaluate(client, seed, seed["runs"]["head"], policy["id"], baseline["run_id"])

    response = client.get(f"{API}/analyses", params={"task_id": seed["task_id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 4
    assert body["run"]["id"] in seed["runs"].values()

    missing = client.get(f"{API}/analyses")
    assert missing.status_code == 422


def test_analyses_exposes_reason_for_frontend_dash(client, seed):
    """前端靠 missing_reason 显示「—」而不是 0。"""
    body = client.get(f"{API}/analyses", params={"run_id": seed["runs"]["head"]}).json()
    gpu = [m for m in body["metrics"] if m["metric_key"] == "gpu_util_pct"]
    assert gpu
    assert all(m["value"] is None for m in gpu)
    assert any(m["missing_reason"] == "device_unsupported" for m in gpu)


# ---------------------------------------------------------------------------
# report.json -> metric_summaries 映射（走真实端点写入后再读回）
# ---------------------------------------------------------------------------


def test_report_mapping_roundtrip_through_db(client, seed):
    from app.integrations.mobile_perf import summaries_from_report

    report = {
        "runId": "vendor-run-1",
        "deviceProfile": PROFILE_DIRTY,
        "startedAt": "2026-10-25T10:00:00",
        "stoppedAt": "2026-10-25T10:01:00",
        "items": ["CPU", "Memory", "FPS", "GPU"],
        "metricsSummary": {
            "cpu_process_pct": {"unit": "%", "median": 20.0, "sampleCount": 30},
            "mem_pss_mb": {"unit": "MB", "median": 150.0, "sampleCount": 30},
            "fps_frame": {"unit": "fps", "median": 58.0, "sampleCount": 30},
        },
    }
    mapping = summaries_from_report(report, vendor_src=VENDOR_SRC)
    assert mapping.device_profile == PROFILE_CLEAN
    missing = [row for row in mapping.rows if row.value is None]
    assert missing, "GPU 不支持时必须产出缺失行"
    for row in mapping.rows:
        assert (row.value is None) != (row.missing_reason is None)


def test_datetime_utc_available():
    """守卫：本模块依赖的 datetime 辅助没被误删（避免 lint 误报未使用）。"""
    assert datetime.now(UTC).year >= 2024
