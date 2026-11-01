# 01: 调试页直接操控（Phase 1）

**Status:** resolved

## What to build
在 UI 自动化 → 设备调试工作区增加直接操控：点击、拖动、长按真机画面，并支持 Back/Home。复用 mobile-auto 的单操作者控制权（5s TTL）与 `/api/v1/input/gesture`；平台代持 token，浏览器不可见。默认关闭，启用前确认；冻结/图像模板模式/会话非 active 时不可用。

## 验收
- 控制权：领取/心跳/释放；他人持有 409 control-busy；TTL 后 control_expired；token 不离开服务端。
- 手势：平台 WS 代理 vendor，严格 Origin + token hello；每会话一条；坐标归一化。
- UI：按钮/确认/状态；pointer 映射；Back/Home；错误有原因；关闭/冻结释放。
- 真机：749622c9 点击「我的」切页、Home 回桌面、单操作者 409、关闭后租约 0。

## Comments
- 2026-11-01 交付：`feat/debug-direct-control`（`5aad752`）。后端全量 574 项（573 passed / 1 skipped / 0 failed）、新增 10 项控制测试、前端 52 项、`tsc`/build 通过；真机验收记录见 `acceptance.md §11`。
- 边界：浏览器后台标签页心跳被节流，超过 vendor 5s TTL 会如实失效并要求重新启用；H.264 预览按计划留作 Phase 2。
- 2026-11-01 延迟修复：UI 先设 `pointerStartRef` 再 `openGesture()`，后者经 `closeGestureSocket` 清空指针，导致 `end` 不发、vendor 2s 超时补 UP。已改为先 `openGesture()` 再记指针，并加源码顺序回归测试；真机 journal 由 `up seq:1 / 0.5–2s` 变为 `up seq:2 / 2ms`，点「我的」即时切页。
- 2026-11-01 调试页修复：原生节点模式拖拽不再生成/保留选择框（`cropSelectionEnabled` 门控 + 切回清空），图像模板模式框选保留；「返回键/Home」移到设备画面正下方居中（距 8px、DOM 在快照信息之前）。前端 61 passed、tsc/build 通过。
