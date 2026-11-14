# 06: 项目上下文与归档恢复 — 验收证据

> 2026-11-09：下方 already 观察项已在本次工作区修复，更新前读取原归档状态；首次恢复 false，重复恢复 true。新增项目/应用接口回归，旧代码均失败，修复后正式化测试通过。未提交，具体测试环境限制见修复记录。

- 执行时间：2026-11-08 21:28–21:35（本机时间）
- 版本：master @ `16f1771`；环境同前（隔离库 testdock_rr02、浏览器实驱动 + 接口探针）
- 测试对象：项目 A「交付验收项目」(540f2fa1) 与项目 B「context-project-b」(5000b728)；
  同名应用：A 应用（a9feb4f2，7 次历史运行）与 B 应用（4a9b66e3，无运行），均显示名「计算器」、标识 com.miui.calculator

## 验收项逐条（measured）

| AC | 结果 | 证据 |
| --- | --- | --- |
| 项目切换/跨页导航/刷新/深链接范围一致 | ✅ | 工作区锚定 A 应用后：跨页（apps→tasks→ui）任务/套件清单均为 A 范围；浏览器刷新后范围保持（任务列表仍只有 A 的任务）；hash 深链直达页面渲染同一范围；无旧项目数据串显 |
| 切换后清理不兼容的表单选择 | ✅ | 任务向导应用下拉仅含锚定项目内应用（B 应用不出现，结构性防混）；代码层 `TaskWizard.tsx:654` 应用切换即清 `resourceId/buildId/suiteId/suiteVersionId`；锚定切换（进入工作区）整体重挂载 |
| 双项目同名应用明确区分 | ✅ | 两行「计算器 · com.miui.calculator」并列展示，归属项目/关联任务数（3 vs 0）可辨；页面提示「同名应用可在不同项目 / 目标端分别登记」 |
| 项目编码/应用所属固定；改名只动显示 | ✅ | 应用改名（com.miui.calculator → 计算器）后：标识列不变、历史报告 `applicationId` 不变、`currentNames.application=计算器` + `nameSource=current_display_name`（当前名与稳定 ID 分轨）；项目编码 context-b 全程不变 |
| 归档阻止新业务；接口不能绕过守卫 | ✅ | 应用归档后 POST /runs → 404（归档对象退出新业务查找）；项目归档后 POST /runs → **409**（明确冲突）；UI 侧「显示归档对象」开关控制可见性 |
| 归档占用时拒绝 | ✅（复用） | 归档前占用校验由 `test_issue04_run_lifecycle`（活动租约）与 `identity_mod.assert_scope_active` 守卫自动化覆盖；本轮所有归档操作均在无活动占用时执行 |
| 恢复用原身份；父项目恢复不复活单独归档的应用 | ✅ | 组合序列（21:34:08 实测）：归档应用 B → 归档项目 B → 恢复项目 B（archived_at→NULL，同一 id/code）→ **应用 B 仍处归档态（SQL 实证 still_archived=t）** → 恢复应用 B（同一 id）→ 全部回到使用中 |
| 历史运行/报告仍可访问 | ✅（复用+本轮） | A 应用 7 次运行在改名/项目操作后报告全部可读（本轮回读 RUN-0001 报告核对 currentNames）；归档对象只读历史由 `test_issue05_report_traceability` 自动化钉住 |

## 观察项（非阻塞，P3）

- `POST /applications/{id}/restore` 与项目 restore 响应的 `already` 旗标语义有误：任何成功恢复都返回
  `already: true`（实现按「更新后 archived_at IS NULL」判定，见 `identity.py:401`），字面含义应为「调用前已处于
  活动态」。UI 不消费该旗标（仅 types.ts 声明），无用户可见影响——按范围纪律仅记录不改码。
- 通过 curl 内联中文 JSON 会被 Git Bash 编码损坏（"error parsing the body"）；改用 `--data-binary @file` 正常。
  属测试工具链现象，非平台缺陷。

## 接口直连证据清单

- `POST /applications/{id}/archive|restore`（应用）与 `POST /projects/{id}/archive|restore`（项目）返回体均含
  固定 id 与归档时间，身份不变。
- 归档后 `POST /runs`（application_id 指向归档应用）→ 404；项目归档 → 409（identity 守卫 `assert_scope_active`）。
