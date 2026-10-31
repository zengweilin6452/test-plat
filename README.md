# TestDock 平台

移动端 UI 自动化与性能测试平台：任务编排、设备租约、运行生命周期、证据归档与三态性能门禁。
后端 FastAPI + PostgreSQL（便携版 17.6），前端 React + Vite，runner 以独立子进程复用
`vendor/` 里的 mobile-auto / mobile-perf 能力（`app/` 不直接 import vendor）。

## 前置条件

- Windows 10/11（脚本均按 PowerShell 编写）
- Python 3.12（本仓库开发机使用 `D:\python312\python.exe`，任意 3.12 均可）
- Node.js 20+（含 npm；前端构建用）
- 无需管理员权限：PostgreSQL 为 EDB 便携版，落在仓库 `.runtime/` 内

## 目录结构

```
server/        FastAPI 后端（app/ 领域与路由、alembic/ 迁移、tests/ 测试）
web/           React + Vite 前端（src/pages 与原型一一对应）
vendor/        只读源仓库（mobile-auto / mobile-xn 等，禁止修改，app/ 禁止 import）
scripts/       构建 / 环境脚本（PG 起停、seed、schema 文档生成、dev 一键启停）
docs/          设计文档与原型（platform-prototype/ 为产品原型）
data/          运行产物（artifacts、control.token 等，不入库）
.runtime/      便携 PG 17.6（pgsql/ 与 data/）与临时文件
```

## 从零起环境（目标 ≤30 分钟）

### 1. 便携 PostgreSQL（约 10 分钟，含下载）

```powershell
# 首次：下载 zip + 解压 + initdb + 建库（幂等，可重复执行）
powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 init
# 启动 / 停止 / 状态
powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 start
powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/pg_portable_setup.ps1 stop
```

- 数据目录：`.runtime/pg17/data`，端口 **55432**，用户 **testdock**（trust 认证，仅回环），库名 **testdock**
- 连接串：`postgresql+psycopg://testdock@127.0.0.1:55432/testdock`
- 注意：沙箱 / 受限环境下 `pg_ctl` 不可用，脚本已改用 `Start-Process postgres.exe` 直接启动，
  停止读取 `postmaster.pid` 首行 PID，先 `taskkill`（不带 /F）优雅停机，超时再强制结束

### 2. 建表 + 演示数据（约 2 分钟）

```powershell
cd server
D:\python312\python.exe -m pip install -e ".[dev]"   # 后端依赖
D:\python312\python.exe -m alembic upgrade head       # 建全部 24 张表
cd ..
D:\python312\python.exe scripts/seed_demo.py           # 幂等演示数据
```

### 3. 启动服务（2 条命令）

后端（在 `server/` 下；Windows 事件循环问题已在 `app/main.py` 内处理，
**必须用 `python -m app.main` 或 `uvicorn app.main:app`，入口会装 SelectorEventLoop**）：

```powershell
cd server
D:\python312\python.exe -m app.main     # http://127.0.0.1:8000，健康检查 /api/v1/health
```

前端（在 `web/` 下）：

```powershell
cd web
npm ci
npx vite dev    # http://127.0.0.1:5173（开发）；生产构建用 npm run build
```

或者一键（后台起后端 + 前端，并探测 `/health` 就绪）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1   # 幂等：已在运行的进程跳过
# 停止：
powershell -ExecutionPolicy Bypass -File scripts/dev_down.ps1
```

### 4. 生成数据设计页静态文档（仅表结构变更后需要）

```powershell
D:\python312\python.exe scripts/gen_schema_doc.py
# 产出 server/app/static_data/schema_doc.json（构建期产物，随包入库；运行期 API 只读）
```

## 测试

```powershell
# 后端全量（不设 TESTDOCK_TEST_DATABASE_URL 时，conftest 自动起独立临时 PG 实例；
# 勿把该变量指回 55432 共享开发库——dev server 的调度器会认领测试排队的 run）
cd server
D:\python312\python.exe -m pytest tests -q

# 前端类型检查与构建
cd web
npx tsc -p tsconfig.json --noEmit
npm run build
```

## 领域规则（不可妥协）

- 三态门禁不压二态：warn 只展示告警，不自动变 failed；门禁判定与测试结论分离
- 缺失指标不写 0：`metric_summaries.value` 为 NULL 并带 `missing_reason`
- 资源租约互斥不靠约定：部分唯一索引 + fencing token 强制
- 非 completed 运行 `outcome` 必须 NULL（completed + failed 属于测试断言失败，不是执行错误）
- `app/` 禁止 import `vendor/`（AST 级测试 `test_no_vendor_import.py` 把关：模块顶层一律禁止，
  函数内只读 import 仅白名单 `app/integrations/mobile_perf.py` 一处），
  vendor 能力主通道是 `server/runner_pkg/testdock_runner` 子进程
