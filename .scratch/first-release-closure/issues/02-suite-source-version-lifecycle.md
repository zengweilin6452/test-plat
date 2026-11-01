# 02: 可信套件来源、登记与不可变版本

**What to build:** 核对并补齐「来源为空 → 明确提示 → 宿主预配置 → 登记套件 → 发现用例 → 固定版本」这条链；来源只能由宿主配置，浏览器不能指定任意宿主路径；每次发现生成不可变版本，来源后续变化不影响既有版本。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

## 现状指针

- 来源解析/复制/发现：`server/app/integrations/discover.py`（`TESTDOCK_SUITE_SOURCES` / `TESTDOCK_TRUSTED_SUITE_ROOTS` / `TESTDOCK_CODE_COPIES_DIR`）。
- 服务层：`server/app/services/suites.py`（`create_suite` / `discover_version` / `publish_version`）。
- 路由：`server/app/routers/suites.py`。
- 现行 API 实测：`GET /api/v1/suite-sources` 返回 `{"items":[],"total":0}`，与 spec 描述一致。
- 既有测试：`server/tests/test_issue05_suite_sources.py`、`test_03_code_copy.py`、`test_p2_suites_api.py`。

## 实现要点

1. 核实来源列表端点在「空来源」时的响应与页面提示：UI 必须说明「需要宿主配置来源」，不给出可绕过的自由路径输入。
2. 核实浏览器只能传 `source_id`；任何宿主绝对路径字段被拒绝（400/422，错误里不回显宿主路径）。
3. 核实发现流程：先复制固定副本，再在副本上 `--collect-only`；失败时保留副本但不发布版本。
4. 核实 `suite_versions` 不可变：重新发现只追加新版本；旧版本 manifest 的 `code_copy` 摘要不变。
5. 核实 UI 套件 V1 必须带 `code_copy`；旧版本无副本时明确要求重新发现。
6. 发现缺陷就修，先写失败测试再改。

## 验收标准

- [ ] 空来源时 API 与页面都明确「未配置」，不出现可输入任意路径的入口。
- [ ] 预配置来源（测试里用受控夹具目录）能登记套件并发布带 `code_copy` 的 V1。
- [ ] 同一套件再次发现追加 V2，V1 的 manifest/摘要保持不变。
- [ ] 来源内容改变后，V1 仍指向原副本；执行准备读 V1 得到原内容。
- [ ] 越界/链接逃逸/来源缺失分别被拒绝，错误不含宿主绝对路径。
- [ ] 页面「用例」页签展示所选版本的真实 manifest.cases；空清单如实说明。

## 验证命令（建议）

```powershell
cd server
$env:TESTDOCK_TEST_DATABASE_URL="postgresql+psycopg://testdock@127.0.0.1:55432/<ticket02_db>"
D:\python312\python.exe -m pytest tests/test_issue05_suite_sources.py tests/test_03_code_copy.py tests/test_p2_suites_api.py -q
```

## 约束

- 不新增真实来源配置；测试只用 `TESTDOCK_SUITE_SOURCES` + 临时夹具目录。
- 不修改 `vendor/`、不安装依赖、不 push。
- 真机与真实来源的验收由本工单记录为「待用户提供来源」，不得伪造。

## Comments
