# 08: 真机调试——只读、冻结、框选验证与模板库

**What to build:** 核对调试会话只读、显示真实设备与实时画面；冻结后节点树与画面同源；框选必须用新画面做真实匹配，验证成功才允许登记模板；刷新或恢复预览清除临时选择/验证/颜色框；模板库跨会话可查并能被任务修订固定版本。

**Blocked by:** 04

**Status:** ready-for-agent

## 现状指针

- 后端：`server/app/routers/debug.py`、`debug_runtime.py`、`server/app/domain/templates.py`、`server/runner_pkg/testdock_runner/crop_match.py`、`debug_job.py`。
- 前端：`web/src/components/DebugDrawer.tsx`、`web/src/components/TemplateLibrary.tsx`、`web/src/pages/UiPage.tsx`。
- 既有测试：`test_issue17_debug_templates.py`、`test_issue25_template_library.py`、`test_crop_validation.py`、`test_template_library_read.py`、`test_p5_debug_api.py`。
- 历史真机记录：`.scratch/prototype-alignment/real-device-debug-acceptance.md`（2026-10-31）。

## 实现要点

1. 核实会话创建/关闭：只读预览、WS 连接状态、关闭后租约释放；同一设备不能双开。
2. 核实冻结快照：节点树与图像来自同一采集时刻；后续实时画面变化不改快照含义。
3. 核实节点拾取与定位候选（resource-id 优先）；无可定位标识时如实显示空候选。
4. 核实框选验证：必须基于**当前新画面**验证；框选、阈值、快照或会话变化后验证结果失效，必须重新验证；验证失败不得登记模板。
5. 核实登记：只有验证通过后从当前框选登记；生成不可变模板版本（sha256）。
6. 核实刷新/恢复预览：清除临时选择、验证结果、颜色框，但**不删除**已登记模板。
7. 核实模板库跨会话可查；任务修订锁定模板 version+sha256，执行时按锁定版本核对（与 25 一致）。
8. 修复缺陷并补测试。

## 验收标准

- [ ] 会话显示实际设备 serial、实时画面与连接状态；关闭后设备释放。
- [ ] 冻结快照的节点树与图像对应同一次采集。
- [ ] 框选验证用新画面真实匹配；验证前/失败时不能登记模板。
- [ ] 框选/阈值/快照/会话改变后旧验证结果不可复用。
- [ ] 刷新或恢复预览清除临时状态，已登记模板仍在。
- [ ] 模板库跨会话可见；修订固定版本后执行按固定版本核对。
- [ ] 在目标 Windows 视口检查必要尺寸与键鼠操作；真机证据记录设备与版本。

## 验证命令（建议）

```powershell
cd server
$env:TESTDOCK_TEST_DATABASE_URL="postgresql+psycopg://testdock@127.0.0.1:55432/<ticket08_db>"
D:\python312\python.exe -m pytest tests/test_issue17_debug_templates.py tests/test_issue25_template_library.py tests/test_crop_validation.py tests/test_template_library_read.py tests/test_p5_debug_api.py -q
cd ../web
npx tsc -p tsconfig.json --noEmit
npm test
```

## 已核实缺陷（探索笔记）

- 服务端 `POST /templates`（`server/app/routers/debug.py:583-587`）直接转发，不校验「刚刚用新画面验证通过」；唯一防线是前端按钮 disabled（`DebugDrawer.tsx:685/1254`）。服务端必须可独立拒绝未验证登记。
- `validate_crop` 确实新捕获画面（`debug.py:629-632`），但返回的新 `snapshot_id` 前端只展示（`DebugDrawer.tsx:1245`），后续登记仍可能用旧快照。
- 模板存储位置两处注释矛盾：`debug.py:549-563`（按会话隔离）vs `domain/templates.py:3-6`（共享 `server/assets`）；跨会话共享需以真实行为核实并统一说明。
- 详细笔记：`C:\Users\williamzeng\AppData\Local\Temp\testdock-frc-notes\08-debug.md`

## 约束

- 调试只读，不做触控/安装/设置修改。
- 真机 749622c9 可用；用完必须关闭会话。
- 不修改 `vendor/`、不安装依赖、不 push。

## Comments
