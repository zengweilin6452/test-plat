# 06: 独立性能与原始判定/试算分离

**What to build:** 核对独立性能运行使用固定场景而非伪装 UI 动作；原始判定与重分析分别保留；基线按应用与资源档案比较；缺失指标不补零，未判定给出真实原因。

**Blocked by:** 04

**Status:** ready-for-agent

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

## 约束

- 不修改 `vendor/`、不安装依赖、不 push。
- 真机性能采集若不可用，记录为未执行，不伪造指标。

## Comments
