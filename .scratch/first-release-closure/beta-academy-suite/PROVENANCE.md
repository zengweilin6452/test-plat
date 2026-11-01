# Beta Academy 客户套件副本（验收用）

- 来源：`D:/workspace/claudecode-test/moblie-auto/examples/beta_academy`（客户仓库 HEAD `f0d2ce0c37b6434f519b87ce7fc6c48e436753bc`）
- 复制日期：2026-11-01
- 逐字复制：conftest.py、flows.py、test_coldstart_landing.py、test_home_navigation.py、test_knowledge_base.py、test_platform_injection.py。
- 宿主新增：pytest.ini（`asyncio_mode = auto`；原配置在客户仓库 pyproject.toml）。
- 宿主适配（1 处）：test_settings_webview.py 在点击「问题反馈」后增加 `wait_for(WEBVIEW_NODE, timeout=10)`，再执行原有的 WebView 断言。原因：原用例点击后立即 `find_elements`，真机在 WebView 加载期间读到空列表（失败截图仍是 spinner）；等待不降低断言强度，客户仓库未改。
- 未复制 local.toml；设备/应用身份由 TestDock 生成的 mobile-config 注入。
- 文件哈希见 `FILES.sha256`（含上述适配后的版本）。
