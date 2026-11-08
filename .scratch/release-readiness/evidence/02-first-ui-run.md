# 02: 首次使用到 UI 运行与报告 — 验收证据

- 执行时间：2026-11-08 19:55–20:50（本机时间）
- 版本：master @ `d3c2124`（后端 `/health` 与设置页「提交标识」均实测一致）
- 环境：隔离正式初始化库 `testdock_rr02`（55432 便携 PG，alembic 0011，无演示数据）；
  产物目录 `.runtime/rr-verify/data`；Web :5173；真机 `749622c9`（Xiaomi 2206123SC / Android 14 / 1080x2400）
- 可信来源：`TESTDOCK_SUITE_SOURCES` 宿主预配置 2 项（calc-smoke 受控验收套件 + beta-academy 客户套件副本），
  页面下拉只显示 id/name，未回显宿主路径

## 验收项逐条（measured）

| AC | 结果 | 证据 |
| --- | --- | --- |
| 正式初始化不产生演示业务数据 | ✅ | 引导页待办 5 项全部「当前 0 项」；项目/应用/设备空态文案均明确「不会自动建立演示数据」 |
| 页面设置工作空间/建项目/登记应用 | ✅ | 设置页改名「交付验收工作空间」成功反馈「名称已保存」；项目 `delivery-acceptance` 使用中；应用 com.miui.calculator 标识固定、支持执行 |
| 登记可追溯构建 + 可信套件版本，修订配置就绪 | ✅ | 构建 15.0.14（315000014）登记后真机身份核对（dumpsys 只读）：versionName match、versionCode 观测 315000014；显式「确认以上身份并固定基准」；套件 v1 发布 4 用例、固定副本 `86f5595fc981…`（4 文件）；任务 TASK-68791794 修订 r1→验证后 readiness=validated（revision 629f6c29） |
| 真机成功用例 + 故意断言失败用例，区分状态/结论/错误 | ✅ | RUN-0002：state=completed、outcome=failed（断言失败，非执行错误）、junit 4 用例 3 passed / 1 failure（失败消息=「预期内的故意失败」可从 junit.xml 下载核实）；RUN-0001 同结论；执行错误 0 |
| 报告定位修订/构建/套件/资源/证据 | ✅ | 报告抽屉「追溯」段：应用当前名称、项目当前名称、套件版本 v1·calc-smoke·local、固定副本 86f5595fc981·4 文件、构建 v15.0.14·315000014、任务修订 validated·ui、资源档案指纹 57482cde2c88；证据链 4 产物全部 available（actions.jsonl 553B / junit.xml 1.5KB / mobile-config.toml 271B / runs/main.json 143B），download_url 实测可下载且含故意失败断言消息 |
| 在线报告可读 | ✅ | 「在线查看」沙箱渲染：横幅「报告由后端渲染，页面只做展示，不参与判定」，与平台源隔离说明可见 |
| 缺前置条件给真实原因 | ✅ | 构建未选时「验证（readiness=validated）必须绑定构建」；套件版本未选时给出原因；来源为空提示由既有自动化钉住（复用） |

## 本轮发现并修复的范围内缺陷

| 缺陷 | 修复 | 复验 |
| --- | --- | --- |
| 运行耗时恒为 0s：`started_at` 留空到收敛，finalize 单事务连跳 DISPATCHING→COMPLETED 并回填事务时间戳，`started_at == ended_at`（RUN-0001 实证，报告「耗时 0s」） | `d3c2124`：dispatcher 在 QUEUED→DISPATCHING（lease_acquired）extras 写入真实 `started_at`；runtime 的 IS NULL 回填保留为遗留兜底 | 回归测试先失败后通过（`test_dispatch_records_started_at_and_finalize_keeps_started_before_ended`）；RUN-0002 真机复核：started 20:46:01.7 < ended 20:46:22.7，报告 `durationS=20`；定向回归 47 项通过（issue24/04/03/import_and_finalize 36 + perf 派发 7 + 租约 4） |

## 观察项（非阻塞）

- 任务向导在打开状态下若套件/版本列表刷新，可能出现选择被重置、向导回退的现象（本轮两次遇到，
  重选后可完成；初步指向 reset effect 依赖 `initialSuite` 派生值在 refetch 瞬间变化）。归入 07 的弹层/抽屉行为验收复核；如复现稳定则按范围内缺陷修复。
- 任务确认页「应用版本 / 套件」显示的是可选自由文本字段（渐进式披露的次级项），所选 build_id/suite_version_id
  在第 2 步与提交载荷中真实生效（任务详情「当前绑定」可见），不构成追溯缺口。

## 复用说明

- 首期验收（2026-11-01）的执行副本/身份核对/生命周期/报告追溯自动化结论继续有效（路径未变）；
  本轮页面级流程在其上重走一遍并落真机证据。
