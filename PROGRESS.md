# PROGRESS — 调试工作区 UI 审查问题修复（F1–F7）

Goal: 按 2026-11-14 审查报告修复设备调试工作区 F1–F7，基点 master 0c25c95。

## Done（全部完成，2026-11-14）
- F1+F4：`stageViewBadge` 状态机 + 终态禁用恢复 + 单条主提示（重建内置 + details）；冻结「已暂停预览」。
- F2+F3：聚焦投屏（UiPage debugFocus）+ 上下文条提前折行；1366/2560 聚焦实测无滚动无裁切。
- F5：选中节点蓝框 + 树受控展开/roving tabindex/aria；字号 10→12px。
- F6/F7：文案统一（模板库/图像框选/冻结并检查/恢复实时/返回/主页/已断开）+ forced-colors 系统色与 ✓ 标识。
- 防御修正：手势 WS `ended`/idle 是 vendor 设计内生命周期，静默收尾不退出操控；仅手势进行中断连提示并自动重连。初版误报已修（真机复验：两次点击+idle 路径零提示）。
- H.264 帧停被动提示（不自动处置）。
- 验证：typecheck ✓ / 100 tests ✓ / build ✓；真机三视口 + 冻结拾取键盘 + 平台关会话终态 + 重建恢复 全链路实测。
- 证据与文件清单：REPAIR-REPORT.md「UI/UX 审查修复」节。

## Next
- 提交分支 fix/debug-ux-audit-f1-f7 并推送；按需开 PR（分支 push 不触发 CI）。

## Open questions
- Windows 原生高对比主题复验（F7）、第二台真机的跨设备/物理断线场景——与审查遗留一致。
- H.264 持续断流自动处置待可控复现后再决策。

## Key facts
- 写端点需 `X-TestDock-Client: web`（P1-04 加固），fetch 调试 DELETE 必须带头。
- 聚焦垂直预算：main pb 8 / workspace pb 6 / body gap 12 / 行距 10 / footer 8+8 / canvas clamp(240, 100vh-470, 1100)。
- 树导航纯函数在 debugModel（treeNavAction/visibleTreeRows/initialOpenTreeSet），组件只渲染。
