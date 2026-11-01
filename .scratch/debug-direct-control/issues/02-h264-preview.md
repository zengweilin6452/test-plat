# 02: 调试页 H.264 预览（Phase 2）

**Status:** resolved

## What to build
调试页优先使用 vendor H.264 直解；平台新增 `/api/v1/ws/debug/{id}/video` 代理（严格 Origin + proto hello、只下行、单会话一条）。前端用 WebCodecs 解码到现有 canvas，显示 fps；不可用/失败/超时回退 JPEG 并说明原因；冻结时暂停绘制，恢复后继续。

## 验收
- 平台代理：Origin/hello/二进制透传；会话非 active/未知 4403/4404；每会话一条。
- 前端：H.264 优先；WebCodecs 缺失/错误/8s 超时回退 JPEG；冻结/恢复；控制按钮仍可用。
- 真机：H.264 状态与 fps；回退原因可见；关闭会话后租约 0。

## Comments
- 2026-11-01 交付：`feat/debug-h264-preview`。后端视频代理 3 项 + 控制/契约 27 项通过；前端 57 项、`tsc`/build 通过。真机：H.264 · ~25fps（码流 486×1080），后端全量 577 项（576 passed / 1 skipped / 0 failed），冻结/恢复后继续，隐藏 `VideoDecoder` 时显示「浏览器不支持 WebCodecs，已回退 JPEG」。记录见 `acceptance.md §12`。
- 边界：不回退时并行；回退后本会话保持 JPEG；码流分辨率低于快照，精确拾取用快照。
