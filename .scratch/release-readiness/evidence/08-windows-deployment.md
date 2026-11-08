# 08: Windows 部署、升级与恢复 — 验收证据

- 执行时间：2026-11-08 21:58–22:20（本机时间）
- 部署目录（含空格）：`D:\workspace\claudecode-test\testdock deploy test`
- 代码来源：master @ `596306e`（含本轮部署修复）；部署实例构建身份 `.env` 显式绑定 `TESTDOCK_BUILD_COMMIT=16f1771`
- 隔离条件：独立 venv（`.venv`）、独立便携 PG 实例（端口 55434，`-Port` 参数）、独立 `data/` 产物目录；
  开发环境（:8000/:5173/55432）全程未动

## 本轮发现并修复的范围内缺陷（commit 596306e）

| 缺陷（含空格目录实证） | 修复 | 复验 |
| --- | --- | --- |
| `Start-Process -ArgumentList '-D', $PgData` 不加引号：postgres 把路径按空格拆词，报 `invalid argument: "deploy"` 拒启 | `-ArgumentList ('"{0}"' -f $PgData)` 显式内嵌引号 | 修复后 start 成功、55434 LISTENING |
| Windows PowerShell 5.1 `Set-Content -Encoding UTF8` 写出**带 BOM** 的 postgresql.conf，postgres 报 `syntax error in file ... line 1` 拒启（开发环境当时用 PS7 语义初始化故未暴露） | 改 `[System.IO.File]::WriteAllText`（恒 UTF-8 无 BOM） | 重新 init 后 conf 首字节 `# --`（无 BOM）、start 成功 |

## 验收项逐条（measured）

| AC | 结果 | 证据 |
| --- | --- | --- |
| 另一含空格目录正式初始化与完整启停 | ✅ | robocopy 复制 server/scripts/web/vendor → venv `pip install -e "server[dev]"` → `pg_portable_setup.ps1 -Port 55434 init/start` → alembic head（0011）→ `dev_up.ps1`：`/health` `{"status":"ok","commit":"16f1771","db":"ok",...}`、Web :5175 200；`projects` 为空（0 项，无演示数据） |
| 健康检查识别本平台 | ✅ | `/api/v1/health` 返回 TestDock 结构（status/version/commit/db/vendor）；dev_up 的就绪探测只认该结构 |
| 端口冲突明确失败 | ✅ | 8011 被外部进程占用时 `dev_up` 明确报错：「端口 8011 已被其他服务占用，且不是 TestDock API；请更换 TESTDOCK_API_PORT 或停止该进程。」 |
| 停止只作用本实例 | ✅ | `dev_down.ps1` 后 8010/5175 停止；:8000 / :5173 / :55432（开发环境）全部仍在监听 |
| 隔离旧库升级，历史保留，不改写历史迁移 | ✅ | `testdock_old`（55434）迁移到 **0008** → 种入历史链（项目/应用/构建/套件版本/资源档案/执行节点/已验证修订/completed+passed 运行）→ 部署代码 `alembic upgrade head`（0008→0009→0010→0011）→ 升级前后逐行对比一致（`upgrade-before.txt` / `upgrade-after.txt`，仅 alembic_version 0008→0011 差异）；迁移文件未改写（只追加） |
| 备份并实际恢复隔离库与产物，完整性核对 | ✅ | `pg_dump testdock_rr02`（本收口轮全部真机验收数据：runs=10 / evidence=124 / projects=3）→ 恢复到 `testdock_rr02_restore`：计数逐行一致（COUNTS-IDENTICAL）、运行结论 completed/failed 保留、证据行 logical_key/availability/byte_size 一致（junit.xml 1502B 与磁盘文件 sha256 `806419b0…` 前后一致）；产物目录整体复制到 `backup-drill/data/artifacts/` 并哈希核对 |
| 失败路径保留故障信息并用隔离备份恢复 | ✅ | 重复恢复（对象已存在）→ 明确 ERROR（`relation "alembic_version" already exists` 等，全文留档）→ DROP/重建 → 从备份干净恢复（0 错误） |
| 部署/升级/恢复说明可按实测执行 | ✅ | 全程按 README「正式初始化/启动/停止/升级备份恢复」章节逐步执行；两处偏差即上述脚本缺陷，已修复并回归；无缺依赖（Python 3.12 venv + Node 构建均走通；web 构建本轮复用 CI 证据，未在部署目录执行 npm ci——部署验收口径为启停与健康，前端构建证据见 CI web 作业） |

## 环境与版本

- OS：Windows 10.0.26300.9711 x64；Python 3.12（venv）；PostgreSQL 17.6 便携版（55434）
- 数据库版本记录：部署库 alembic `0011`；升级演练库 0008→0011；恢复库 0011
- 部署实例构建身份：`TESTDOCK_BUILD_COMMIT=16f1771`（.env 显式绑定；无 git 目录时按 README「留空不猜」）

## 边界

- 部署目录的 web 未执行 `npm ci` 构建（验收口径为平台启停与健康检查；前端构建/测试证据由 CI web 作业与本轮 `tsc`/`npm test` 覆盖）。
- 备份恢复演练的对象是本轮隔离验收库 rr02 与其产物（非用户业务数据）；共享库 `testdock` 未触碰。
- 部署 PG 实例（55434）演练后保留运行，供后续抽查；可用 `pg_portable_setup.ps1 stop` 停止。
