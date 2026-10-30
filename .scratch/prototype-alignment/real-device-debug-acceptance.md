# 真机调试验收记录（2026-10-31）

设备：小米 2206123SC（mayfly），serial `749622c9`，USB 已授权（adb state=device）。
链路：平台 API（127.0.0.1:8000，dev 库迁移 head 0007）→ runner 子进程（非 fake）→ vendor viewer（127.0.0.1:13444）→ 真机。

| 步骤 | 操作 | 结果 |
| --- | --- | --- |
| 1 设备同步 | POST /resources/sync | 749622c9 状态 ready，updated=1 |
| 2 建会话 | POST /debug-sessions {serial, purpose} | 201 opening → 3s 内 active，viewer http://127.0.0.1:13444 |
| 3 真实截屏 | POST /debug-sessions/{id}/snapshots | 1080x2400 PNG（1.1MB，`real-device-snapshot.png`），consistent=true |
| 4 控件树 | 带 with_tree 采集 | 91 个带 resource-id 的节点（48 个唯一），含 com.miui.home / systemui |
| 5 resource-id 验证 | /locators/validate {by: resource_id, value: com.miui.home:id/drag_layer} | **唯一匹配，验证通过**，bounds 0,0,1080,2400 |
| 6 图像模板登记 | POST /templates {snapshot_id, region:[581,1048,173,173]} | logical `real-device/icon_icon.png`，version c85ab83c…，sha256 34c4ffd5…，173x173 |
| 7 图像匹配 | /templates/validate {by: image, confidence: 0.8} | **唯一匹配，验证通过，score 1.0**，命中坐标 581,1048,173,173 与裁剪区域完全一致 |
| 8 共享库 | server/assets/manifest.json | 真机登记的模板出现在共享库（与工单 25 的执行锁定同源） |
| 9 收口 | DELETE /debug-sessions/{id} | state=closed，设备释放，无活动租约 |

过程发现（均为使用方式，不是缺陷）：
- 平台模板代理是 `/templates?session_id=…`（query 传会话），`/debug-sessions/{id}/templates` 不存在（404）。
- vendor 的 validate 会**重新采集**当前屏幕再做匹配；屏幕内容变化会导致上一次的资源 id 匹配为 0——验证前先看当前前台（此时是 MIUI launcher）。
- vendor 快照缓存有淘汰：裁剪模板要用**刚采集**的 snapshot_id（过期 404"快照不存在或已过期"）。
- 首次截图未带 UI 树：需要 `{"with_tree": true}`。

对应工单：17（AC-DBG-01～05 的真机部分）、25（共享库）。证据：本目录 `real-device-snapshot.png`。
