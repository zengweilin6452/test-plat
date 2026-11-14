# PROGRESS — release-readiness 收口执行

## 2026-11-09 复核更正（优先于历史 Done）

- 07 改回 ready-for-human：实际 Windows DPI/高对比度待验，历史模拟不代替现场设置。
- toast 遮挡实际缺陷已改为手动 popover，Windows 浏览器独立组件验证成功/失败堆叠，前端 90 项、类型和构建通过。
- 09 保持有缺口；“只剩远程 CI”不再成立。推送与发布不在本次修复授权内。

## Goal
按 spec.md 与 9 张工单完成首个可交付版本收口：真实运行、Windows 交互、部署升级恢复验收
+ 范围内缺陷修复 + 交付基线，直至真机验收完成。

## Done（2026-11-08 收口轮完成）
- 01–08 工单 resolved、09 ready-for-human（汇总完成，结论=有条件通过）。
- 真机验收 RUN-0001~0010：UI 成功/故意失败、性能 15 指标、联动窗口包围 UI、取消收敛、
  互斥双向 409/排队、调试冻结/定位/恢复、设备复用全程租约干净。
- 5 个范围内缺陷修复并复验：3eff530（CI ruff+编码）、d3c2124（started_at/耗时 0s）、
  16f1771（joint ui_timeout_s）、596306e（PG 空格路径×2）。
- 后端 665 项 0 失败；前端 90/90 + tsc + build；部署/升级/恢复实测通过。
- 证据：evidence/02..08 + baseline/01 + evidence/09；STATUS.md 已更新为收口轮校准。
- 文档提交 b3622f6（含证据与脚本，Edge profile 已排除；b216a2f 为 amend 前的悬空对象，不再引用）。

## Done（2026-11-14 CI 转绿轮）

推送后远端 CI 逐层暴露自 CI 建立以来从未真正跑过的问题，七轮修复后 **run `43557510582` 三作业首次全绿**
（vendor 1m58s / 前端 37s / 后端 10m44s，后端 668 passed）：

| 轮 / run | 暴露问题 | 修复（提交） |
| --- | --- | --- |
| R1 `43544761040` | 契约测试依赖 `APIRoute.response_model`（fastapi 0.162 不再承载）；vendor 作业缺 `[image]/[viewer]` extras 与 tests 包 PYTHONPATH | 契约改读 OpenAPI 投影 + CI 装配修复（`cfdeb4e`） |
| R2 `43548956983` | 0.162 全量预演 4 失败：模板库测试无 cv2 环境、p2_static 路由内省 | server 作业装成像依赖、补 `importorskip` 护栏、p2_static 改投影（`4e6b176`） |
| R3 `43549984837` | vendor 逐字节校验在 CI 从未通过（runner autocrlf 转 CRLF；pwsh 多命令步骤吞退出码） | `.gitattributes * -text`、check 步骤改 bash（`221c77d`） |
| R4 `43552215992` | 索引内容被规范化为 LF，与锁文件（原始字节）行尾不一致；PG 直启 ExitCode=1 双日志皆空 | `git add --renormalize vendor` + 启动自诊断（`c8a7438`） |
| R5 `43553021774` | PG `start` 直启路径在 runner 不可依赖 | `pg_ctl -w start` 为主、直启降级沙箱兜底（`874729c`） |
| R6 `43555987953` | symlink 用例 CI 首次真跑暴露 `resolve_source` 不扫树内链接；报告导出与快照时间戳格式随版本分叉（'Z' vs '+00:00'） | 解析期树内链接拒绝 + `_report_view` 出口统一 jsonable_encoder（`2a88b56`）；全量 0.162 预演 667 passed |
| R7 `43557510582` | `deployment_env.py` 被 editable finder 劫持 app 模块，隔离根 .env 被绕过 | 先灌部署根 .env + 探针按文件路径加载（`cdb88b7`） |

每轮均为「先本地复现失败、修复后双版本/双环境验证通过」再推送；网络间歇故障（github.com:443 重置）
由后台重试循环消化（最长一次第 10 次重试成功）。

## Next（2026-11-14 更新）
- 推送已执行（2026-11-14，用户已授权）：网络恢复（fetch / gh API 实测可达）后 `git push origin master` 完成，
  收口修复、11-09 的 toast/restore 修复（`d02212a`/`a50df4a`）与文档同步并入 origin/master。
- 远程 CI 复核已解除（同日 run `43557510582` 三作业全绿）；仅剩 07 的 Windows 实际 DPI/高对比度现场复验
  （2026-11-09 更正），解除后 09 与 STATUS.md 升级为整体通过（dated 追记，不改写原文）。
- 可选：打 tag（独立授权）；停部署实例 PG（55434）。

## Open questions
- 无（观察项见 evidence/09 §3）。

## Key facts
- 真机 749622c9；隔离库 rr01（测试）/rr02（验收主库，后被恢复演练复制）；部署实例 PG 55434。
- dev 环境 :8000/:5173 未动；55432 于 2026-11-14 为复跑定向测试启动（隔离库 testdock_docsync1114）。
