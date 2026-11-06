# 21: 接入页真实示例与能力探测

**What to build:** 接入说明中的路由、请求模型、错误码和表名与实际 OpenAPI 一致；存活与能力探测分开呈现三态。

**Blocked by:** 01

**Status:** resolved

- [x] AC-INT-01：逐条验证示例与实际接口，不公开内部协议为普通接入 API
- [x] AC-INT-02：DB 不可达、vendor 缺失、runner 未知分别反映
- [x] ok=null 不渲染成失败；存活 200 不冒充全能力健康
- [x] 探测不启动运行或占用设备，无凭据输出

## Comments

- 实现提交 `083e0c1`（`feat(issue21): 接入页真实契约与三态能力探测`）。
- AC-INT-01：接入页能力卡改为真实端点（tasks/builds/suites/runs/events/report/gate-evaluations），错误码表改为实际枚举（validation_error 400、readiness_incomplete 422、not_found 404、state_conflict 409、stale_version 409、device_busy 409）；明确 runner 内部协议 /internal/*（X-Control-Token）不作为普通接入 API。
- AC-INT-02/03：/api/v1/health 重写——db 实测 SELECT 1（ok/fail）、vendor 两目录 present/missing、runner 恒 null（未知 ≠ 失败）；status 仅反映存活。前端核查项三态 badge（green/red/gray），ok=null 渲染灰色"未知"。
- 不泄露：/health 不再输出 database_target（原实现把 DB 主机:库名拼进响应）。
- AC 探测只读：调用前后 test_runs 与活动租约数不变（测试覆盖）。
- 验收（定向）：`test_issue21_integration_probe.py` 3 例；web `tsc --noEmit` 通过；OpenAPI `--check` 通过。

## Answer

2026-11-07 状态校正：验收项已全部勾选，实现已并入 `integration/first-release-closure`（证据见 `.scratch/first-release-closure/acceptance.md` 与 `server/tests/`、`web/tests/` 对应用例）。原 `Status: ready-for-human` 是未校正的历史值，以本文件为准。
