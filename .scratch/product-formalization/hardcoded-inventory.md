# 正式化改造：硬编码处理清单

基线：`7511fc0` / `integration/first-release-closure`。本清单按类别记录实际用途、目标来源、处理方式和验收编号；搜索命中区分注释、帮助示例、默认值与真实执行路径。测试夹具、历史验收与原型参考保留示例，不作为正式数据回退来源。

## 1. 产品外壳与虚构身份

| 位置 | 原用途 | 目标来源 | 处理 | AC |
| --- | --- | --- | --- | --- |
| `web/src/components/layout/Sidebar.tsx` | 写死「星河工作空间」「内部测试平台」「测试工程组」「P1 骨架阶段」 | `GET /api/v1/workspace`、`BRAND` 统一定义 | 改为真实名称、本机模式；加载/失败状态与演示标识可见 | AC-02/14 |
| `web/src/components/layout/Topbar.tsx` | 面包屑写死「星河工作空间」、P6 阶段标签 | 同上 + `/capabilities` 真实版本 | 删除虚构身份与阶段标签；提供关于入口 | AC-02/14 |
| `web/src/components/PageBits.tsx` | 上下文条写死「星河」，过时的 P1 骨架说明 | `EffectiveContextProvider` | 真实项目/应用或明确「全部项目」「未选择应用」；加载/空/失败分离 | AC-08/14 |
| `web/index.html` | 浏览器标题 TestDock | `BRAND.name` | 保持统一品牌，不新增编辑界面 | AC-02 |
| `web/src/store/platform.tsx` | 新增 | 服务端 `/workspace`、`/capabilities` | 统一品牌定义、模式、演示标识与版本来源 | AC-02/07/11 |

## 2. 上下文与业务默认值

| 位置 | 原用途 | 目标来源 | 处理 | AC |
| --- | --- | --- | --- | --- |
| `web/src/store/project.ts` / `app.ts` | 各自缓存项目/应用，设备页自动取第一个项目 | `store/effectiveContext.tsx` | URL 优先、服务端对象校验、显式全部、仅 app 解析项目、冲突拒绝；设备/Ui/Perf/任务/报告/向导统一接入 | AC-07/08 |
| `web/src/constants.ts` | `TARGET_CATALOG.capability` 写「已有组件基础」「规划中」 | `GET /api/v1/capabilities` | 常量只保留展示名与过渡说明；能力由服务端提供，读取失败不显示可执行 | AC-12/14 |
| `web/src/constants.ts` | `DEFAULT_BUILD_LABEL='3.8.0-rc.2'` | 无（示例常量） | 改名 `BUILD_LABEL_EXAMPLE`，仅帮助示例使用 | AC-14 |
| `web/src/components/TaskWizard.tsx` | 版本 placeholder、包名/设备示例 | 选择与输入 | 示例标「例如 …（不会自动提交）」；表单版本初值保持空；删除 P2 阶段说明；查询带项目范围 | AC-07/14 |
| `web/src/components/layout/navItems.ts` | 「24 张表」、9 项顺序不可改的研发注释 | `/schema` 实际数据 | 改为正式导航；表数量由 `DatabasePage` 动态读取 `/schema`；保留旧路径兼容 | AC-14 |

## 3. 初始化与演示隔离

| 位置 | 原用途 | 目标来源 | 处理 | AC |
| --- | --- | --- | --- | --- |
| `server/alembic/versions/0009_formalization_workspace.py` | 新增 | 系统设置表 | 只追加：单行默认工作空间 + 以后显式导入用的 origin 标记；不灌业务数据 | AC-01/16 |
| `scripts/seed_demo.py` | 默认既可被 README 引导写入正式库 | 显式演示库 | 要求 `--demo` 与独立 `--database-url`；拒绝正式默认库；新导入项目/应用标 `demo_seed`，不倒填旧数据 | AC-01/11/16 |
| `README.md` | 默认安装要求运行 seed | 正式初始化流程 | 默认路径只迁移；演示安装单独章节；备份恢复与升级说明 | AC-01/11/16 |
| `server/app/config.py` / `main.py` | 假执行默认可被正式启动接受 | 配置守卫 | `formal_start_blocker()`：测试/显式演示除外，正式启动拒绝 `TESTDOCK_FAKE_RUNNER=1` | AC-11 |

## 4. 部署与个人路径

| 位置 | 原用途 | 目标来源 | 处理 | AC |
| --- | --- | --- | --- | --- |
| `scripts/vendor_sync.py` | 源仓库写死 `D:\workspace\claudecode-test\...` | `TESTDOCK_MOBILE_AUTO_SOURCE` / `TESTDOCK_MOBILE_PERF_SOURCE` | 正常运行用既有 vendor 快照；只有显式 sync 才要求配置源 | AC-13 |
| `scripts/dev_up.ps1` / `dev_down.ps1` | 固定 8000/5173、按进程名全局杀进程、200 即认为就绪 | 统一 `TESTDOCK_*` 端口与 PID 文件 | 端口可覆盖、含空格路径可配、平台健康检查识别自身、停止只作用于本次实例 | AC-13 |
| `web/vite.config.ts` | 固定代理 8000 / 5173 | `TESTDOCK_API_PORT` / `TESTDOCK_WEB_PORT` / HOST | 与启停脚本共用配置，`strictPort` 占用即失败 | AC-13 |
| `README.md` / `.env.example` | `D:\python312\python.exe` 个人路径 | `TESTDOCK_PYTHON` / PATH | 无秘密配置示例与 Windows 说明；公开前端不暴露连接串/令牌 | AC-13 |

## 5. 保留项及理由（不按缺陷处理）

- 协议枚举、状态映射、设计令牌、DB CHECK 取值：有明确依据的协议/设计常量，改成配置反而会破坏契约。
- `docs/platform-prototype/`、历史验收文档、`web/tests/*` 夹具中的「星河 / Demo」：原型参考与测试夹具，不是运行时正式数据回退来源。
- `scripts/seed_demo.py` 中的演示名称与固定 ID：显式演示导入与旧数据识别依据，仅演示库可用。
- `server/tests/*` 中的 `P3_PROJECT_PREFIX`、历史 issue 编号：测试夹具与历史追溯，不在运行时页面展示。
- `web/src/api/endpoints.ts` 注释里的 P1/P2/P6：代码注释中的历史阶段标记，不是运行时文案；后续逐步清理不列入本轮验收阻塞。

## 6. 动态描述

- 数据设计页表数量、分组与字段字典来自 `GET /api/v1/schema`，`scripts/gen_schema_doc.py` 已随 0009 追加迁移把 `workspace_settings` 纳入分组；读取失败如实呈现。
- 首用引导完成状态来自 `GET /api/v1/onboarding/status` 的真实项目、应用、设备、运行计数，不写引导进度状态。
- 能力标签来自 `GET /api/v1/capabilities`；设备就绪仍来自资源状态与租约，二者分别展示。
