# mobile_perf 能力接入与 E2E 验收记录

- 日期：2026-11-08
- 分支：`feature/ui-ux-polish`（延续 UI/UX 批次；本轮改动见文末清单）
- 背景：2026-11-08 能力盘点确认 vendor mobile_perf 有 6 块能力平台未接、3 处部分接入。本轮全部接入并做真机 E2E。

## 一、接入内容

| 能力 | 接入方式 | 关键改动 |
| --- | --- | --- |
| 启动耗时（cold/warm） | 场景字段 `start_mode` → runner 透传 `kit.collect(start_mode=…)` | `schemas.py`、`domain/suite.py`、`runner perf_config.py`（两端镜像校验）、`debug_job.py`、`joint_job.py` |
| HAR 抓包 | 场景字段 `capture_har` → vendor 自动起 mitmproxy 代理；产物 `.har` → `artifacts.kind='har'` | 同上 + `domain/artifacts.py::classify/mime_for` + 迁移 0011 |
| 网络剖面/弱网 | 场景字段 `net_profile/net_tier/net_port/net_overrides`（档位 none/4g/3g/weak/custom） | 同上；mitmdump 缺失时 vendor 如实降级 not_tested+hint |
| 接口级指标（api_req_* 4 项） | 随代理通道产出；报告块 `api` 透传；映射层按块推导期望 key | `integrations/mobile_perf.py::_expected_keys/CHANNEL_BLOCK_KEYS` |
| 整页耗时 | 场景字段 `page_marks`（{page, at_s}）→ 采集窗口内 `scope.mark_page()`；perf-only 主循环调度、joint 后台线程调度 | `debug_job.py`、`joint_job.py` |
| 泄漏趋势 | 平台侧按 vendor leak 同口径实现（同应用+同档案 mem_pss_mb median 序列 OLS → MB/天，置信三态 insufficient/low/ok）；`/analyses` 返回 `leakTrend` | `routers/analyses.py` |
| p90 统计位 | 迁移 0011：`metric_summaries.statistic` 枚举加 `p90`（同迁移给 `artifacts.kind` 加 `har`）；映射层 `DB_STATISTICS` 加 p90 | `alembic/versions/0011_perf_capability_enums.py` |
| joint 报告丢失修复 | `_write_joint_report` 透传 startup/pages/network/api/jank/frames/series 等块（此前只留 metricsSummary/thresholds）；runner 调用从 SessionSpec 升级为 kwargs 形态以支持新参数 | `joint_job.py` |
| 缺失如实呈现 | FPS 组补卡顿分级 3 key、GPU 组补显存、新增 Temperature 组；报告出现能力块时即使 notTested 也落「有指标没值」行 | `integrations/mobile_perf.py` |
| 前端呈现 | PerfPage 指标卡中文名全表 + 泄漏趋势卡（明确不参与门禁判定）；ReportDrawer 新增「能力详情（启动/整页/网络）」节；登记表单新增高级能力字段（渐进式披露，缺省收起不启用） | `PerfPage.tsx`、`ReportDrawer.tsx`、`api/types.ts`、`InputRegistration.tsx` |
| 附带修复 | GPU 卡片死键（gpu_usage_pct→gpu_util_pct）；joint 缺省 items 由 metric key 修正为 SoloPi 分组名（CPU/Memory/FPS，vendor 不做 key 归一化） | `PerfPage.tsx`、`joint_job.py` |

设计纪律：`net_mitmdump` 是宿主可执行路径，**浏览器不传**（spec §9.2），运维经 `MOBILE_PERF_MITMDUMP` 环境变量提供；`vendor/**` 零改动（全部经 runner_pkg 适配层）；场景白名单外字段一律拒绝（两端一致）；缺失/未判定不伪造（HAR 解密不可用即 not_tested + 原因）。

## 二、E2E 真链路验收（真机 749622c9，android-14）

链路：发布能力场景 → 建任务 → validate → 发起运行 → 真机采集 → 报告/分析/产物验证。

1. **发布**：`POST /suites/fc368843/versions` v3（scenario: duration 90s + CPU/Memory/FPS + `start_mode=cold` + `capture_har` + `frame_poll` + `page_marks=[{home@15}]`）→ 201 `cce4f177`（新 schema/校验通过）
2. **任务/运行**：任务 `410d9892` validate → validated（revision `4e18e5ea`）→ `POST /runs` → **RUN-1032**，100s 内 completed（真机 90s 采集窗 + 冷启动编排）
3. **真机结果**（`data/artifacts/7bf11471…/report.json`）：
   - `app_cold_start_ms=438ms`（TotalTime 口径，launchState=COLD，force-stop 后拉起）
   - `page_load_ms` home 页 **3338.9ms**（15s 打标生效，402 帧，末帧稳定口径，status=ok）
   - 逐帧 P50/P90/P99（9.3/13.1/21.8ms）+ 卡顿分级（轻微 2 / 重度 0）
   - GPU 利用率/显存、电池温度 34.6°C（补采通道）
   - `metricsSummary` 共 **27 个指标 key**，全部含 p90
4. **平台验证**：
   - `/runs/{id}/report`：startup/pages/network/api 块透传 ✓（修复 `_report_json_payload` 丢块后）
   - `/runs/{id}/metrics`：mem_pss_mb 五统计位 min/median/mean/max/**p90**（235.54）✓
   - `/analyses`：27 指标 median + `leakTrend`（**77.53 MB/天**，3 次历史运行自动参与，21.87h 跨度 → 置信 low 如实标注）✓
   - artifacts：24 个产物登记；无 har 行——vendor 语义「零有效条目不建空文件」，如实
5. **UI 走查**（截图 `docs/plan/ui-shots/disclosure/after/e2e-*.png`）：PerfPage 新指标卡 + 泄漏趋势卡（含「不参与判定」纪律说明）；报告抽屉「能力详情」节完整呈现启动/整页/网络/HAR 三态

## 三、如实降级与边界（非缺陷）

| 现象 | 原因 | 证据 |
| --- | --- | --- |
| HAR status=not_tested（entries=0） | mitmproxy 代理**成功启动**，但被测 App HTTPS 不信任代理 CA 且无明文 HTTP；vendor 不伪造、不建空文件 | report.json `network.har.notTestedReason`；README 边界说明 |
| api_* 4 指标 not_tested | 同上（解密档不可用） | 指标卡展示完整原因文本 |
| 泄漏趋势置信=low | 跨度 21.87h < 24h（vendor 同口径） | `leakTrend.confidenceReason` |
| 解密全链路（HAR complete） | 需设备信任 mitmproxy CA（Android≥7 用户证书对 App 不生效，需 root 装系统证书或目标 App 配置网络安全策略）——环境边界，留待有 root 设备/可控被测 App 时补测 | vendor README HAR 覆盖边界 |

## 四、验证证据

- 后端：`python -m pytest tests -q`（全新 scratch 库，exit=0；新增 `tests/test_perf_capability.py` 19 项 + `test_perf_gate_api.py` 2 项 DB 枚举测试；joint 链路 3 处测试替身同步 kwargs 约定）
- 契约：`python scripts/export_openapi.py` 重生成 + `test_contract_openapi.py` 通过
- 前端：`npm run typecheck` / `npm test`（85/85）/ `npm run build` 全绿
- 迁移：0011 在 scratch 与 dev 两库 `alembic upgrade head` 成功
- 真机：RUN-1032 完整跑通（证据见 §二）

## 五、未做项

- `jank_thresholds_ms`（卡顿阈值覆盖）与 `capture_options`（HAR 脱敏选项）未暴露到场景字段——vendor 支持但当前默认值即验收口径，避免配置面过度膨胀；需要时按同模式扩展
- HAR **完整解密**的端到端受设备 CA 信任边界限制（见 §三）；链路本身已验证
- `custom` 网络档位未做 UI（API/场景可用），UI 只列 none/4g/3g/weak
