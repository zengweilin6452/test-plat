# 2026-11-09 验收修复

- 基线 b3622f6，修改均在工作区，未提交或推送。
- toast 根因：dialog.show() 不进入 top layer，原注释错误。改为 manual popover/showPopover，并去除 toast 自身继承的模态背景模糊。保留非阻断、三槽位与自动消失行为。
- Windows ego 浏览器使用真实 ToastProvider 与正式 CSS 的独立组件页面：旧代码 toast 非 popover 且位于模态外；修复后成功/失败同时进入顶层，模态保持，提示计时清理通过。已人工查看 toast-fixed.png，提示清晰、未被遮挡。此证据是组件浏览器回归，不冒充业务提交端到端验收。
- 前端类型、90/90 测试与生产构建通过。浏览器回归入口为 web 的 toast-browser 测试页面及配套脚本，先在 5188 启动 Vite 再运行脚本；仅测试页面，无数据库写入。
- restore 根因：按 UPDATE 后的 archived_at 判断 already，恒为 true。改为行锁下读取更新前状态。项目与应用新增接口回归在旧代码均失败，修复后正式化测试通过，父项目归档限制继续有效。
- 后端默认测试启动缺 createdb.exe（便携 PG 不带该二进制）。2026-11-14 复核确认：`server/tests/conftest.py`
  工作区未改动（建库仍走 createdb 子进程路径），当时的一次性规避未保留代码改动，测试基础设施保持原样。
  复跑改经 `TESTDOCK_TEST_DATABASE_URL` 指向 dev PG 55432 隔离库完成，未访问正式库。
- 实际 Windows DPI/高对比度仍待现场验证，未更改用户系统设置；当前业务服务未运行，不以组件回归代替整站验收。相关状态索引和 07/09 记录已纠正。
- 远程 CI 本次查询仍是旧提交失败记录，最终代码未推送，不能声称当前远程 CI 已通过。修复授权不自动包含提交、推送或发布。

## 2026-11-14 复核追记（推送前实测）

- 后端：`test_formalization.py` **21 项 exit 0**（`TESTDOCK_TEST_DATABASE_URL` → dev PG 55432
  隔离库 `testdock_docsync1114`，alembic 升至 0011）。
- ruff（CI 口径 `cd server && python -m ruff check .`，tests/ 依 `extend-exclude` 不纳入）：All checks passed。
- 前端：`tsc --noEmit` 通过；`npm test` **90/90**；`npm run build` 通过（426.10 kB JS）。
- `toast-browser.mjs` 为 ego-browser 运行时脚本，本次未复跑；组件验证证据沿用 2026-11-09 的
  `toast-fixed.png`（已人工查看：success/error 堆叠于底层、模态保持）。
