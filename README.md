# TestDock 平台

移动端 UI 自动化与性能测试平台：任务编排、设备租约、运行生命周期、证据归档与三态性能门禁。
后端 FastAPI + PostgreSQL（便携版 17.6），前端 React + Vite，runner 以独立子进程复用
`vendor/` 里的 mobile-auto / mobile-perf 能力（`app/` 不直接 import vendor）。

正式安装默认获得**干净的可使用环境**：不灌演示项目、伪设备或假运行结果。首次打开页面
按真实数据引导建立工作空间名称、项目、Android 应用并同步设备；显式演示安装另见最后一节。

## 前置条件

- Windows 10/11（脚本均按 PowerShell 编写）
- Python 3.12（通过 `TESTDOCK_PYTHON` 或 PATH 指定；路径可以含空格）
- Node.js 20+（含 npm；前端构建用）
- 无需管理员权限：PostgreSQL 为 EDB 便携版，落在安装目录 `.runtime/` 内

## 目录结构

```
server/        FastAPI 后端（app/ 领域与路由、alembic/ 迁移、tests/ 测试）
web/           React + Vite 前端（src/pages 与设置 / 引导 / 帮助入口）
vendor/        只读源仓库快照（禁止手工修改；正常启动直接使用）
scripts/       构建 / 环境脚本（PG 起停、演示导入、schema 文档生成、dev 一键启停）
docs/          设计文档、契约基线与原型
data/          运行产物（artifacts、control.token 等，不入库）
.runtime/      便携 PG 17.6 与临时文件
```

## 配置（不含秘密）

复制 `.env.example` 为安装根目录的 `.env`。后端、演示导入、启停脚本和 Vite 均读取该文件；进程环境变量优先。数据库、产物目录、运行时目录、Python、ADB 与可信来源
沿用现有 `TESTDOCK_*` 配置机制；路径从配置或安装目录解析，不依赖开发者个人目录。
公开前端不会拿到连接串、令牌或宿主敏感路径。

启动、前端代理、健康检查和停止共用同一组端口设置：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `TESTDOCK_HOST` / `TESTDOCK_PORT` | `127.0.0.1` / `8000` | API 绑定与健康检查（Vite 代理也读它） |
| `TESTDOCK_API_PORT` | 同 `TESTDOCK_PORT` | 兼容别名；同时设置时 `TESTDOCK_PORT` 优先 |
| `TESTDOCK_WEB_HOST` / `TESTDOCK_WEB_PORT` | `127.0.0.1` / `5173` | Vite 绑定与代理目标端口 |
| `TESTDOCK_PYTHON` | `python` | 后端解释器（可含空格路径） |
| `TESTDOCK_DATA_DIR` / `TESTDOCK_RUNTIME_DIR` | 安装目录下 `data/` / `.runtime/` | 产物与运行时目录 |
| `TESTDOCK_SUITE_SOURCES` | 空 | 可信套件来源 JSON（宿主编排，浏览器不能任意指定宿主路径） |
| `TESTDOCK_MOBILE_AUTO_SOURCE` / `TESTDOCK_MOBILE_PERF_SOURCE` | 空 | **仅**开发者 vendor 同步需要的显式只读源目录 |
| `TESTDOCK_BUILD_COMMIT` | 空（`dev_up.ps1` 自动取 `git rev-parse --short HEAD`） | `/health` 与 `/capabilities` 报出的构建提交，便于核对运行实例代码 |

端口占用时明确失败；健康检查只认本平台 `/api/v1/health` 的响应结构，不把其他服务
返回 200 当作就绪。含空格的安装目录与解释器路径均可使用。

## 正式初始化（默认路径，不运行 seed）

### 1. 便携 PostgreSQL

```powershell
powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 init
powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 start
powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 status
```

数据目录 `.runtime/pg17/data`，端口 **55432**，用户 **testdock**（trust 认证，仅回环），库名 **testdock**。

### 2. 依赖与迁移（只建立必要系统设置）

```powershell
& $env:TESTDOCK_PYTHON -m pip install -e "server[dev]"
cd server
& $env:TESTDOCK_PYTHON -m alembic upgrade head
cd ..
& $env:TESTDOCK_PYTHON scripts/gen_schema_doc.py
```

若省略 `TESTDOCK_PYTHON`，直接用 PATH 里的 `python`。迁移 `0009` 建立单行工作空间设置
（默认名称「默认工作空间」）与以后显式演示导入用的来源标记；**不创建任何业务演示数据**。
只追加迁移，不改写历史迁移；重复执行 `alembic upgrade head` 不会灌 seed 或改旧身份。

### 3. 启动服务

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1
# 停止只作用于本次实例（PID 文件）：
powershell -ExecutionPolicy Bypass -File scripts/dev_down.ps1
```

或分别启动：

```powershell
cd server
python -m app.main     # http://127.0.0.1:8000，健康检查 /api/v1/health
```

```powershell
cd web
npm ci
npx vite              # http://127.0.0.1:5173（生产构建用 npm run build）
```

### 4. 首次使用（无需改源码或直接操作数据库）

1. 打开 `#/onboarding`，按真实数据计算待办；引导可跳过，之后仍可返回。
2. 在设置页修改工作空间名称 → 在「项目与应用」创建项目及登记 Android 应用。
3. 连接 Android 设备后，在「执行资源」页同步真实设备。
4. 配置可信来源 `TESTDOCK_SUITE_SOURCES`，登记构建并核对身份、选择套件或性能场景。
5. 创建任务并发起运行，在报告中心查看结论与证据。

正式启动若检测到 `TESTDOCK_FAKE_RUNNER=1` 会拒绝启动并提示纠正；假执行只允许测试
（pytest）或显式演示环境使用，不能生成看似真实的通过结果。

## 升级、备份与恢复

1. 停止平台；**先备份数据库**：`pg_dump -h 127.0.0.1 -p 55432 -U testdock testdock > backup.sql`，
   并复制 `data/`（产物与哈希）与 `.env`。
2. 替换安装目录中的程序文件（保留 `data/`、`.runtime/`、`.env`）。
3. 执行 `alembic upgrade head`；迁移只追加，不改旧身份、不丢失历史。
4. 用 `python -m app.main` / `dev_up.ps1` 启动，健康检查通过后验证旧运行、报告与证据。
5. 恢复时先还原备份库与 `data/`，再用同一版本的迁移把 schema 升到 head。

旧演示数据不要按名称批量删除：使用 `#/legacy-review` 预览固定身份与关联关系，
逐项确认保留、改名或归档；执行前重新校验占用。设备 / 节点等没有安全归档语义的记录
只保留并说明。处理共享真实库前必须有用户确认的具体清单。

## 测试

```powershell
# 后端：不设 TESTDOCK_TEST_DATABASE_URL 时自动起独立临时 PG，不接触正式库
cd server
python -m pytest tests -q

# 前端类型检查、单元测试与构建
cd web
npm run typecheck
npm test
npm run build

# OpenAPI 契约基线（API 变更后重新导出并比较）
python scripts/export_openapi.py
cd server && python -m pytest tests/test_contract_openapi.py -q
```

## 领域规则（不可妥协）

- 三态门禁不压二态：warn 只展示告警，不自动变 failed；门禁判定与测试结论分离
- 缺失指标不写 0：`metric_summaries.value` 为 NULL 并带 `missing_reason`
- 资源租约互斥不靠约定：部分唯一索引 + fencing token 强制
- 非 completed 运行 `outcome` 必须 NULL（completed + failed 属于测试断言失败，不是执行错误）
- 项目编码、应用所属项目 / 目标端 / 标识创建后固定；改名只影响显示名，历史运行按稳定 ID 与原始快照追溯
- 归档对象仍可只读查看历史；新业务写入由服务端统一拒绝，不能只靠页面按钮隐藏
- `app/` 禁止 import `vendor/`（AST 级测试 `test_no_vendor_import.py` 把关），
  vendor 能力主通道是 `server/runner_pkg/testdock_runner` 子进程

## 显式演示安装（与正式环境隔离）

演示数据**不会**自动写入正式库。仅当确实需要演示时：

1. 另起独立 PostgreSQL 实例 / 数据库（例如端口 `55433`、库名 `testdock_demo`），
   设置 `TESTDOCK_DATABASE_URL` 指向该库；设置 `TESTDOCK_DATA_DIR` 指向独立产物目录。
2. 设置 `TESTDOCK_DEMO_MODE=1`；如需假执行再设置 `TESTDOCK_FAKE_RUNNER=1`。
   页面会持续显示「演示环境」；能力响应不暴露数据库连接串。
3. 对演示库执行 `alembic upgrade head`，再显式执行：

```powershell
python scripts/seed_demo.py --demo --database-url "postgresql+psycopg://testdock@127.0.0.1:55433/testdock_demo"
```

脚本按主机、端口和库名识别并拒绝写入正式默认库（连接参数或用户名变化不能绕过）；演示启动也会检查独立数据库与产物目录。只给新导入的项目 / 应用打来源标记，不倒填旧数据。
正式安装与升级路径**不需要**也不会调用 `seed_demo.py`。
