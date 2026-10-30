# 17: 调试图像模板

**What to build:** 调试工作区支持原生节点与图像模板定位，冻结后可框选并保存模板版本，重新匹配显示真实结果，模板库跨会话共享，任务执行锁定版本。

**Blocked by:** 01、02

**Status:** ready-for-human

- [x] AC-DBG-01：冻结视图、节点、裁剪和结果对应同一快照
- [x] AC-DBG-02：会话失效或快照淘汰时不提交旧坐标，不留下活动占用
- [x] AC-DBG-03：resource-id 优先，表达式可复制且结果与图像一致
- [x] AC-DBG-04：未冻结或忙设备禁止框选；4×4、越界、非整数拒绝；预览与覆盖层同映射；尺寸不兼容清除选区
- [x] AC-DBG-05（部分）：同名未确认冲突，确认后追加版本；阈值 0.10–1.00；匹配失败不伪造
- [ ] AC-DBG-05（余项）：模板库跨会话；执行锁定 version 与 sha256

## Comments

- 实现提交 `984a454`（`feat(issue17): 图像模板阈值契约与调试抽屉阈值输入`）。
- 本工单大部分行为在 P5 调试工作区已交付并有测试/实现支撑：冻结视图/节点/裁剪/结果同源（DebugDrawer 只从服务端保留的快照裁剪建档，vendor 不收浏览器图片）；busy 设备新建会话 409 且无活动会话不可框选（`test_p5_debug_api` 覆盖 busy 冲突、4404/4403）；resource-id 优先与表达式验证走 `/locators/validate`，图像走 `/templates/validate`；同名模板 409 + expected_old_sha256 确认覆盖（TemplatesPanel 乐观锁流程）；匹配结果带 scores，零匹配如实提示。
- 本工单新增：`/templates/validate` 的阈值契约（0.10-1.00 之外 422，不透传 vendor，有参数化测试）；DebugDrawer 增加阈值输入（by=image 时显示并随验证提交，越界前端拦截）。
- 余项单列工单 25：模板库跨会话共享（vendor TemplateStore 绑定会话 assets_dir，需要平台侧共享存储设计）与任务执行锁定模板 version/sha256（任务清单扩展）。
- 验收（定向）：`test_issue17_debug_templates.py` 2 例 + `test_p5_debug_api.py` 回归全过；web `tsc --noEmit` 通过。真实设备上的框选/匹配留待设备授权后的实机走查（spec §"真实验证"清单）。

## Comments（2026-10-31 真机验收补记）

- 真机调试链路验收通过：小米 2206123SC（serial 749622c9）经平台 API 建会话（3s active，vendor viewer 13444）→ 真实截屏 1080x2400 → 控件树 91 个 resource-id 节点 → resource-id 定位验证唯一匹配 → 从真机屏幕裁剪登记模板（sha256 34c4ffd5…）→ 图像匹配唯一命中（score 1.0，坐标与裁剪区域一致）→ 模板进入共享库（与工单 25 执行锁定同源）→ 会话关闭设备释放。
- 过程记录与使用要点见 `.scratch/prototype-alignment/real-device-debug-acceptance.md`；证据 `real-device-snapshot.png`。
