# 18: 工作台 scope 与告警入口

**What to build:** 工作台的 scope 同时约束统计、告警、最近运行和资源；新建、模块卡和告警都能定位到正确目标。

**Blocked by:** 08、10

**Status:** ready-for-human

- [x] AC-OV-01：切换 scope 后统计、告警、列表和资源一致
- [x] AC-OV-02：新建、模块卡、告警均可定位正确目标
- [x] 无判定样本时通过率为空，不显示伪造的 0%
- [x] 无告警、无资源、接口失败分别呈现

## Comments

- 实现提交 `1410f6d`（`feat(issue18): 工作台 scope 聚合与告警入口`）。
- AC-OV-01：`GET /overview` 新增 `scope` 参数（android/ios/web，未知 422），应用/资源/运行/需要关注全部按平台过滤；OverviewPage 的概览查询带当前 targetScope（queryKey 含 scope，切换即重取）。最近运行与资源本就按 scope 拉（工单 08/10 的 /runs 与 /resources）。
- AC-OV-02：新建与模块卡沿用原型入口（TargetCardGrid 选中即切 scope）；"需要关注"卡新增"查看报告 ›"链接到 #/reports（报告中心即 completed 过滤 + 搜索，工单 10）。
- 无判定样本：`pass_rate` 分母为 0 时 null（既有语义），测试在全新 scope（ios）上验证 null 而非 0%。
- 无告警/无资源/接口失败：needs_attention=0 正常显示 0；无资源计数为 0；接口失败走既有红色 Notice（含 request_id）。
- 验收（定向）：`test_issue18_overview_scope.py` 3 例；web `tsc --noEmit` 通过；OpenAPI `--check` 通过。浏览器端 scope 切换的端到端走查未做（按指示不跑全量/浏览器 QA）。
