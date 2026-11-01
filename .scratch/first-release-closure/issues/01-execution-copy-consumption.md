# 01: 执行侧真正消费固定代码副本

**What to build:** 让固定代码副本从「派发时写进 spawn 配置」走到「pytest 实际以副本为工作目录、在副本边界内解析用例」，UI 与联动共用同一条接线；副本不可用时不回退可变来源。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

## 现状（已核实，不是猜测）

- `server/app/scheduler/dispatcher.py:282-299` 已复验副本并写入 `config["suite_root"]`。
- `server/app/runner/spawn.py:161-218` 的 argv/env **完全没有读取** `suite_root`，runner 收到的只有 test_paths/app_package 等。
- `server/runner_pkg/testdock_runner/__main__.py` 没有 `--suite-root` 参数。
- `server/runner_pkg/testdock_runner/ui_job.py:329-339` 的 `subprocess.Popen` **没有 `cwd=`**，继承 spawn 的 `server/`；`resolve_test_paths()` 默认返回 `("tests",)`，实际会指向 `server/tests`。
- `joint_job.py:146` 直接复用 `run_ui_job(options, context)`，因此联动同样受影响。

## 实现要点

1. `spawn.build_spec`：把 `config["suite_root"]` 翻译成 `--suite-root`；同时把该套件版本的 `suite_version_id` 与 `code_copy.tree_sha256` 作为 `--suite-version` / `--suite-sha256` 传入（缺省可为空，但派发路径必须提供）。
2. `dispatcher.dispatch_one`：在 `_prepare_suite_copy` 成功后解析出 `suite_version_id` 与 `tree_sha256`（可让 `prepare_execution_copy` 返回结构化结果，避免二次查询；不要复制摘要计算逻辑）。
3. `testdock_runner.__main__`：新增参数并透传到 `UiJobOptions`。
4. `ui_job._run_pytest`：`Popen(..., cwd=suite_root)`。`artifacts_dir`、junit、env 全部用绝对路径，不受 cwd 影响。
5. `resolve_test_paths`：有 `suite_root` 时默认目标为副本根 `.`；显式 test_paths 必须是相对路径且 resolve 后仍在副本内，绝对路径、盘符、`..` 越界一律拒绝（exit 3 + 明确 reason，例如 `suite_path_out_of_bounds`）。无 `suite_root` 时保留 fake/vendor 兜底，但真实派发不应走到该分支。
6. 运行开始时发一条事件（如 `stage=suite` 或 `suite_copy`），记录 `suite_version_id` / `tree_sha256` / 相对目标，供事件与日志追溯。
7. runner 启动后若发现 `suite_root` 缺失/不是目录：立即 `fail(execution_copy_unavailable)`，**不得**退回 `server/` 或来源目录。

## 验收标准

- [ ] `suite_root` 出现在真实 spawn 的 argv 中；pytest 子进程 `cwd` 等于该副本。
- [ ] 固定副本内放标记文件与相对导入/本地模块/pytest.ini：用例能被执行，输出与 junit 指向该副本。
- [ ] 版本发布后修改原来源：再次执行仍跑原副本内容（用不同标记验证）。
- [ ] 副本缺失、摘要不符、路径越界、目标越界分别被阻断，运行落在 errored/not_tested，不回退来源目录。
- [ ] 联动运行走同一接线（同一 `UiJobOptions` 路径），不出现第二套目标解析。
- [ ] 事件/报告能追溯本次实际使用的套件版本与树摘要。
- [ ] 测试覆盖上述行为；测试使用专用数据库与临时副本目录，不写共享库、不占用真机。

## 验证命令（建议）

```powershell
cd server
$env:TESTDOCK_TEST_DATABASE_URL="postgresql+psycopg://testdock@127.0.0.1:55432/<ticket01_db>"
D:\python312\python.exe -m pytest tests/test_issue24_execution_wiring.py tests/test_runner_contracts.py -q
D:\python312\python.exe -m pytest tests -q
```

## 已核实副作用风险（必须处理）

- vendor `MobileConfig.assets_dir` / `artifacts_dir` 默认是相对路径（`vendor/mobile_auto/src/mobile_auto/config.py:79-80`），未显式传绝对路径时按 cwd 解析。
- vendor evidence 插件在 `pytest_sessionstart` 会往 `base.artifacts_dir/runs` 写运行状态（`vendor/mobile_auto/src/mobile_auto/evidence/pytest_plugin.py:142-170`）。若 cwd 改成固定副本，会**写进副本**，导致下次摘要校验失败。
- `assets_dir` 是模板库的存储根（`vendor/mobile_auto/src/mobile_auto/imaging/store.py`）；切 cwd 后若仍用默认值，模板库会指向副本内，破坏跨会话共享与执行锁定。
- 处理要求：pytest 子进程显式使用绝对 `assets_dir`（共享资产根）与绝对 `artifacts_dir`；并设置 `PYTHONDONTWRITEBYTECODE=1`，避免 `__pycache__` 写进副本。可为平台插件补一个 `--mobile-config` 选项，生成指向绝对目录的临时 TOML（不改 vendor）。
- 验收再加一条：执行前后固定副本的文件树摘要保持不变（平台自身不写副本）。

## 约束

- 不修改 `vendor/`；不安装/升级依赖；不新增外部来源。
- 不把 `TESTDOCK_TEST_DATABASE_URL` 指向共享库 `testdock`（8000 端口的调度器会认领 queued run 并占用真机 749622c9）。
- 本工单只改本地分支并合入 `integration/first-release-closure`，不 push。

## Comments
