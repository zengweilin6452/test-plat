# 03: 构建登记与设备安装身份基准

**What to build:** 核对「选择应用与构建 → 只读读取设备已安装身份 → 用户确认后固定基准 → 运行前复核」；不可读/不一致要给出原因并阻断，不把版本信息核对说成 APK 字节摘要验证。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

## 现状指针

- 服务/路由：`server/app/services/builds.py`、`server/app/routers/builds.py`。
- 运行前复核：`server/app/scheduler/dispatcher.py:125-183`（`_verify_build_identity`）。
- 只读 adb：`server/app/integrations/devices.py`（`resolve_adb_path` / `_run`）。
- 既有测试：`server/tests/test_issue04_builds.py`、`test_issue24_execution_wiring.py`。
- 环境：真机 `749622c9` 在线，adb 在 `vendor/mobile_auto/tools/adb/adb.exe`。

## 实现要点

1. 核实构建登记与身份学习：`app_builds.metadata.identity` 的 `pending → confirmed` 只在用户明确确认后发生；同名/同 key 冲突拒绝确认。
2. 核实只读：读取身份只用 `dumpsys package` 等白名单命令，不含 install/tcpip/connect/push/reboot。
3. 核实三类结论：`confirmed` 冲突 → 阻断；不可读 → 阻断并显示原因；pending → 不阻断但明确「无从复核」。
4. 核实界面文案不把 `versionName` 核对表述为 APK 哈希校验；`sha256` 字段若展示，来源与含义要准确。
5. 缺测试的补测试；发现缺陷先写失败测试再修。

## 验收标准

- [ ] 构建登记后身份为 pending；确认后固定 baseline（package/versionName）。
- [ ] 设备上 versionName 与基准不一致 → 运行 errored(identity_mismatch)，租约释放。
- [ ] dumpsys 不可读/无 versionName → 运行阻断且原因可读，不冒充通过。
- [ ] pending 身份 → 派发继续，但报告/事件明确「未复核」，不写成已验证。
- [ ] 复核命令白名单测试通过（无写操作）。
- [ ] 页面能展示身份不可读/不一致的原因，用户可修正后重试。

## 验证命令（建议）

```powershell
cd server
$env:TESTDOCK_TEST_DATABASE_URL="postgresql+psycopg://testdock@127.0.0.1:55432/<ticket03_db>"
D:\python312\python.exe -m pytest tests/test_issue04_builds.py tests/test_issue24_execution_wiring.py -q
```

## 约束

- 真机只读；不安装应用、不修改设备设置。
- 不修改 `vendor/`、不安装依赖、不 push。

## Comments
