# 工单状态索引（与实际情况对齐）

> 2026-11-09 更正优先：release-readiness 07 为 ready-for-human，实际 Windows DPI/高对比度待验，25–26 用户故事不能标为完整通过；09 保持有缺口。下方 2026-11-08 的“32/32 通过、仅剩 CI”是已撤回的历史结论。toast 与恢复 already 缺陷已于 2026-11-14 提交（`d02212a` / `a50df4a`，验证证据见 `evidence/acceptance-fixes-2026-11-09.md`）。

> 2026-11-08 收口轮校正（release-readiness 九票执行完毕）。本文件仍是状态权威；
> 上一版校准（2026-11-07）中被本轮事实取代的描述已更新。
> 2026-11-14 同步：`git push origin master` 已执行（4 个修复提交 + 文档同步并入 origin/master）；
> 推送/远端 CI 相关陈旧描述按当前事实更新，已被取代的重复缺口段删除。
> 2026-11-14 CI 转绿：远端 CI 自建立以来首次三作业全绿（run `43557510582`：vendor 1m58s /
> 前端 37s / 后端 10m44s）；过程中暴露并修复 CI 从未真正跑过的七层问题（逐层 dated 记录见
> PROGRESS.md 与 evidence/09 §8）。远程 CI 复核缺口自此解除。

## 总览

| effort | 票数 | 实际状态 | 证据 |
| --- | --- | --- | --- |
| `release-readiness` | 9 | **01–06/08 resolved；07 复核改 ready-for-human（Windows 实际 DPI/高对比度待现场验收）；09 有缺口（唯一剩余=07 现场复验）；远程 CI 已转绿（2026-11-14 run `43557510582`）** | `.scratch/release-readiness/evidence/02..08`、`evidence/acceptance-fixes-2026-11-09.md`、`baseline/01-evidence-baseline.md`、`evidence/09-delivery-baseline.md` |
| `prototype-alignment` | 25 | 19 票 resolved；3 票已实现但验收项未勾；3 票有明确未闭环项 | 已并入 HEAD；`acceptance.md`、`handoff-2026-10-29.md`、`server/tests/` |
| `first-release-closure` | 10 | 10 票 resolved；真机/来源/像素证据齐（2026-11-01 §8–§10） | `acceptance.md` |
| `product-formalization` | 12 | 7 票 resolved；5 票待验项已由 release-readiness 承接并关闭（03→06、08→02、10→07、11→08、12→09） | `implementation-report.md` + release-readiness 证据 |
| `debug-direct-control` | 2 | 2 票 resolved | `acceptance.md` §11–§12 |

## release-readiness 收口结论（2026-11-08）

- **~~32/32 用户故事已通过~~**（2026-11-09 更正：撤回 25–26，实际 30/32 通过、2 条待 Windows 现场复验；
  含 3 条「本轮实测+自动化复用」口径）；验收暴露并修复 5 个范围内缺陷：
  `3eff530`（CI ruff 死导入 + vendor charmap 编码）、`d3c2124`（运行 started_at/耗时 0s）、
  `16f1771`（joint 版本发布缺 ui_timeout_s）、`596306e`（便携 PG 含空格路径 ×2：ArgumentList 引号 + UTF-8 BOM）。
- 真机验收：RUN-0001~0010（UI/性能/联动/取消/互斥/调试），设备串行全程租约干净。
- 后端 665 项（0 失败/1 跳过）+ 定向 47 项；前端 90/90 + tsc + build。
- **未闭合必需项（2026-11-14 更新后）**：仅剩 ① 07 的 Windows 实际 125% DPI / 高对比度现场复验。
  ② 远程 CI 复核已解除：推送执行后远端逐层暴露 CI 建立以来从未跑过的问题并全部修复，
  run `43557510582` 三作业全绿（2026-11-14）。①解除前交付结论维持「有缺口」。

## 现存验证缺口（跨 effort，2026-11-08 更新）

| 缺口 | 影响 | 解除条件 |
| --- | --- | --- |
| ~~本轮 4 个修复提交未推送~~ | 已解除：2026-11-14 推送执行完毕 | 已授权并执行（2026-11-14） |
| ~~远程 CI 复核~~ | 已解除：run `43557510582` 三作业全绿（2026-11-14）；CI 从未跑过的七层问题已修（见 PROGRESS.md CI 转绿轮） | 已解除（2026-11-14） |
| 07 现场 DPI/高对比度复验 | 用户故事 25–26 不标完整通过（2026-11-09 更正） | 真实 Windows 显示设置下现场验收 |
| 无版本 tag | 构建身份靠 `TESTDOCK_BUILD_COMMIT`（可核对），tag 缺失不影响身份识别 | 打标签需独立授权 |
| 历史 runner 消失根因 | 观察项（本轮 10 次真机运行未复现） | 复现后按规格决策 11 限口径调查 |
| 多 worker 凭证共享 / 保留期 expired 态 | out-of-scope 维持 | 按首版边界 |


## prototype-alignment（已并入 `integration/first-release-closure`）

- **已 resolved（2026-11-07 校正，19 票）**：04–16、18–21、24、25。判据：工单验收项全部勾选，
  实现已并入 HEAD。
- **已实现但验收项从未勾选（3 票）**：`01-contract-baseline`、`02-readiness-lease-spike`、
  `03-copy-and-finalize-spike`。证据：`server/tests/test_contract_openapi.py`、租约/设备只读用例、
  `test_03_finalize_atomic.py`；`export_openapi.py --check` 通过。状态保持 `ready-for-human`，
  需人工确认后勾选，不代勾。
- **有未闭环项（3 票）**：
  - `17-debug-image-templates`：未勾「模板库跨会话 + 执行锁定 version 与 sha256」——
    后者由 25 号票落地（`server/tests/test_template_library_read.py`），需复核后勾选。
  - `22-database-dictionary`：未勾「生成过程不修改业务库；空结果不残留无关表详情」——
    需复核 `scripts/gen_schema_doc.py` 的只读性后勾选。
  - `23-visual-closeout`：未勾「加载/失败/空态/部分缺失/过期分别呈现」与「视觉验收记录原型内容摘要」——
    **视觉验收仍未执行**，这是真实的剩余缺口。

## first-release-closure

- 10 票全 resolved；`acceptance.md` 是验收正本，§16–§18 记录了复审 P2 与后续修复。
- 仍成立的口径：§2 的 8 条 US 标「已实现待验」（真机条件不满足）；US1「可信套件来源」在
  **当前运行环境仍受阻**（`GET /api/v1/suite-sources` → 0 条，需宿主配置
  `TESTDOCK_SUITE_SOURCES`）。客户套件的真机验证走的是 `beta-academy-suite/` 副本，见
  `PROVENANCE.md`。

## product-formalization

- **已 resolved（2026-11-07 校正，7 票）**：01、02、04、05、06、07、09。判据：对应 AC 在
  隔离库/静态验收中通过（见 `implementation-report.md` §5）。
- **保持 `ready-for-human`（5 票）**：
  - `03-shared-context`：AC-08 的浏览器跨页交互未实际执行。
  - `08-first-real-run`：AC-15 受阻（无可用真机 + 无可信来源）。
  - `10-navigation-copy-closeout`：AC-14 的 100%/125% 缩放与高对比度键盘焦点未实测。
  - `11-portable-windows-deployment`：AC-13 未在真实另一含空格目录执行完整启停。
  - `12-integrated-acceptance`：整体验收未完成，不得仅凭自动化测试关闭。

> 原 2026-11-07 版「现存验证缺口（跨 effort）」表（无 git 远端、真机闭环、浏览器视觉验收、
> 换目录启停等）已被 2026-11-08 收口轮事实全部取代（远端已配置、CI 已实跑、真机/桌面交互/含空格
> 部署均实测通过），现行缺口以本文「release-readiness 收口结论」后的缺口表为准。
