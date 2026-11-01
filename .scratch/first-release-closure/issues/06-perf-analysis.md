# 06: 独立性能与原始判定/试算分离

**What to build:** 核对独立性能运行使用固定场景而非伪装 UI 动作；原始判定与重分析分别保留；基线按应用与资源档案比较；缺失指标不补零，未判定给出真实原因。

**Blocked by:** 04

**Status:** resolved

## 现状指针

- 门禁与分析：`server/app/domain/gates.py`、`server/app/domain/profiles.py`、`server/app/domain/metrics_view.py`。
- 路由：`server/app/routers/analyses.py`、`baselines.py`、`gate_policies.py`。
- 运行收敛：`server/app/runtime.py`、`server/app/domain/runs.py`。
- 既有测试：`test_issue12_analysis_selection.py`、`test_issue13_original_freeze.py`、`test_issue14_historical_reanalysis.py`、`test_perf_gate_api.py`、`test_profiles.py`、`test_issue16_joint_lifecycle.py`。

## 实现要点

1. 核实 performance 版本是声明式场景（duration_s 10–3600、items 非空），不生成 pytest 用例。
2. 核实原始判定在 finalizing 内原子形成；completed 运行不出现缺 original。
3. 核实 `evaluation_id` 显式选择试算；默认展示 original；历史缺 original 的运行可追加 reanalysis，且缺失标记保留。
4. 核实基线只与应用 + 资源档案比较；不可比时说明原因。
5. 核实缺失指标为 NULL + `missing_reason`，不写 0；未判定展示原因。
6. 修复发现的缺陷并补测试。

## 验收标准

- [ ] 独立性能运行采集指定指标与时长；报告不声称执行了 UI 动作。
- [ ] original 不被 reanalysis 覆盖；两者都能按 id 查询。
- [ ] 基线不可比时给出具体原因（应用/档案不匹配）。
- [ ] 缺失指标为 NULL 且有原因；未判定不是通过。
- [ ] 历史运行缺 original 时，显式重分析可用且原缺失标记仍在。
- [ ] 既有报告检索/导出能力不受影响。

## 验证命令（建议）

```powershell
cd server
$env:TESTDOCK_TEST_DATABASE_URL="postgresql+psycopg://testdock@127.0.0.1:55432/<ticket06_db>"
D:\python312\python.exe -m pytest tests/test_issue12_analysis_selection.py tests/test_issue13_original_freeze.py tests/test_issue14_historical_reanalysis.py tests/test_perf_gate_api.py tests/test_profiles.py -q
```

## 已核实缺陷（探索笔记）

- `run_perf_job`（`server/runner_pkg/testdock_runner/debug_job.py:96-102`）只校验 `duration>0`，没有 10–3600 约束；任务修订 readiness（`server/app/domain/task.py:92-168`）也没有校验，与声明式清单规则不一致。
- 执行只读修订 `config_snapshot.perf`（`runs.py:441-508`、`dispatcher._resolve_config:84-105`），不合并 `suite_versions.manifest.scenario`；两处声明可能漂移。
- 成功采集返回 `not_tested/gate_policy_missing` 是「判定交给平台」的设计，不要改成 runner 直接出结论。
- 派发侧对所有运行统一要求 `code_copy`（`dispatcher._prepare_suite_copy`），而 performance 版本按设计没有代码副本，导致独立性能运行被误判为 `errored(execution_copy_missing)`。工单 06 需按 `test_type` 区分：performance 不要求副本；joint 仍必须有 UI 副本。
- 详细笔记：`C:\Users\williamzeng\AppData\Local\Temp\testdock-frc-notes\06-perf.md`

## 约束

- 不修改 `vendor/`、不安装依赖、不 push。
- 真机性能采集若不可用，记录为未执行，不伪造指标。

## Comments

- 2026-11-01 修复：`dispatcher._prepare_suite_copy` 按 `test_type` 区分——performance 返回 None（声明式场景无代码副本），不再误判 `errored(execution_copy_missing)`；ui/joint 缺副本照旧阻断。
- 场景口径统一：`domain.suite.scenario_problems` 公开并被套件发布、修订 readiness（`domain/task.check_readiness`）复用；runner 侧 `testdock_runner/perf_config.py` 是同口径镜像，`test_runner_window_matches_platform_rule` 双向锁死边界（10–3600 整数秒、items 非空），runner 不再默默夹紧或回落 60s 默认值。
- 两份声明合订：新增 `domain.suite.resolve_scenario`，提交时在 `runs._resolve_execution_scenario` 合订 `suite_versions.manifest.scenario/performance` 与修订 `config.perf`，一致用版本快照、仅一份用它、不一致 400 `validation_error`、写入 `config_snapshot.perf/perf_source` 冻结；派发不再二次解析。
- 提交：`d744aab`、`bb87079`（合并集成）、`aeb96a7`，合入 `a8733db`。
- 测试（`testdock_frc06`）：`test_issue06_perf_dispatch.py`、`test_issue06_perf_scenario.py` 等定向 64 passed；后端全量 `tests/` 退出码 0。
- 未执行：真机性能采集（留给 10 记录），不伪造指标。
