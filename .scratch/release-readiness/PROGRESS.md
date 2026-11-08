# PROGRESS — release-readiness 收口执行

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
- 文档提交 b216a2f（含证据与脚本，Edge profile 已排除）。

## Next（待用户决策）
- 推送已获授权（22:30）；github.com:443 暂不可达（api.github.com 正常、SSH 无密钥）。
  网络恢复后执行 `git push origin master` → 远端 CI 复核转绿 → 09 升级为整体通过。
- 可选：打 tag（独立授权）；停部署实例 PG（55434）。

## Open questions
- 无（观察项见 evidence/09 §3）。

## Key facts
- 真机 749622c9；隔离库 rr01（测试）/rr02（验收主库，后被恢复演练复制）；部署实例 PG 55434。
- dev 环境 :8000/:5173/55432 未动。
