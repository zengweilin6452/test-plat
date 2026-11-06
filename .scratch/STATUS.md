# 工单状态索引（与实际情况对齐）

> 2026-11-07 校正。起因：四份 effort 的 `Status:` 行与实际进度脱节，无法从 tracker 判断
> 「什么还开着」。**本文件是状态的权威**；各工单正文的 `Status:` 行保留历史值，冲突时以本文件为准。

## 总览

| effort | 票数 | 实际状态 | 证据 |
| --- | --- | --- | --- |
| `prototype-alignment` | 25 | 19 票 resolved；4 票已实现但验收项未勾；2 票有明确未闭环项 | 已并入 HEAD；`acceptance.md`、`handoff-2026-10-29.md`、`server/tests/` |
| `first-release-closure` | 10 | 10 票 resolved；8 条 US 为「已实现待验」，1 条受阻 | `acceptance.md` §2/§12/§16–§18 |
| `product-formalization` | 12 | 7 票 resolved；5 票待现场验收 | `implementation-report.md`、`fix-verification.md`、`server/tests/test_formalization.py` |
| `debug-direct-control` | 2 | 2 票 resolved | `acceptance.md` §11–§12 |

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

## 现存验证缺口（跨 effort）

| 缺口 | 影响 | 解除条件 |
| --- | --- | --- |
| 无 git 远端 | `ci.yml` 永不运行，一切「CI 绿」都是本地等价校验 | 提供远端 URL 并 push |
| 无版本 tag / 构建提交 | 运行实例身份只能靠进程启动时间推断 | 打 tag；`dev_up.ps1` 注入 `TESTDOCK_BUILD_COMMIT` |
| 真机闭环 | UI/性能/联动/调试的真机结论只到自动化与契约层 | 占用真机并配置可信套件来源 |
| 浏览器视觉验收 | 缩放、高对比度、长名称、焦点未实测 | 有桌面会话时补验 |
| 换目录启停 | 正式安装路径可迁移性未实测 | 在另一含空格目录跑 `dev_up.ps1` / `dev_down.ps1` |
