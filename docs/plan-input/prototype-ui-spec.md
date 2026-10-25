# 平台原型 UI 规格（证据版）

> 用途：为「平台开发方案」提供可核对的接入面、验收依据与缺口清单。
> 取证对象：`docs/platform-prototype/index.html`（168,894 B / 332 行，单 <script> 位于 L63–L330，无外部依赖）、`docs/platform-prototype/database-design.md`（237 行）、`docs/platform-prototype/schema.sql`（730 行，PostgreSQL 17 语法）、`docs/platform-prototype/research.md`（136 行）、`docs/platform-prototype/verify-design.cjs`（58 行）。
> 行号口径：`index.html:N` 指该文件第 N 行（该文件行极长，一个函数常整段占一行，故"行号+函数名"才唯一）；`schema.sql:N`、`database-design.md:N` 同理。
> 标注：**已演示**＝原型可交互且产生可见状态变化，可直接转验收用例；**规划态**＝只有文案/占位/草稿，不得当已实现；`未核实`＝本轮未取证。
> 本轮只读：未在浏览器实际操作、未执行 SQL、未运行两个被分析项目、未修改任何原型文件。

## 0. 结论速览（供方案直接引用）

1. 原型是纯前端单文件：全部状态存 `localStorage['testdock.prototype.v1']`（index.html:103、L116），"运行"由按钮手动推进（index.html:250 mutateTask），无后端、无真实设备/脚本调用。
2. 平台层已演示：9 个导航页 + hash 路由（index.html:139–142）+ 目标端 context 条（index.html:122）+ 任务/报告/设备/性能门禁/数据设计五套页面骨架。
3. 目标端隔离只做到"过滤 + 降级"：Web/iOS 的 UI 与性能页降级为 plannedCapabilityPage（index.html:141、L148），向导降级为 plannedWizard（L152–L157），任务只能存草稿（L159）。
4. 性能门禁语义最完整：median + 绝对阈值 + 有效样本下限 + 基线档案可比性 → passed/failed/not_tested 三态（index.html:203 perfVerdict），且"试算不改历史结论"（index.html:206）。
5. 数据库是 24 表 / 231 字段 / 56 外键的 SQL 草案（schema.sql:1–7、L730），未建库、未迁移，原型与 DB 之间没有任何代码级连接。
6. 关键缺口不在页面而在语义实现：设备租约与 fencing、状态机由后端强制、证据不可变与对账、实时性能推送，原型均只有文案（详见 §2.8、§8）。

## 1. 全局外壳

### 1.1 骨架与 DOM 分区（index.html:49–62）

| 区域 | 元素 | 说明 | 证据 |
| --- | --- | --- | --- |
| 侧栏 | `aside#sidebar` → 品牌 `#overview`、工作空间块、`nav#navigation`、`sidebar-foot` | 工作空间固定文案"产品质量空间 / Web / Android / iOS"；底部固定"多端平台 · 交互原型 / 所有数据均为演示"与演示账号 William | L49–L54 |
| 顶栏 | `.topbar` → `#menu-toggle`、`.breadcrumb`（`#breadcrumb` 由 render 写入当前页标题）、固定日期"2026 年 10 月 25 日"、`.prototype-tag`"交互原型 / 演示数据"、`?` 帮助按钮 | 面包屑只有"工作空间 / <页面名>"两级 | L56、L141 |
| 主区 | `main#main` | render() 每次整块重写 `innerHTML`，无框架、无局部 diff | L57、L141 |
| 浮层 | `dialog#modal`、`dialog#drawer`（抽屉）、`#toast`（role=status、aria-live=polite）、`noscript` | 原生 `<dialog>`，无自定义焦点陷阱库 | L59–L62 |

### 1.2 组件原语（全部为字符串模板函数）

| 原语 | 签名（index.html 行） | 行为/约束 |
| --- | --- | --- |
| `heading(title,desc,actions)` | L119 | 页头 h1 + 说明 + 右侧动作区 |
| `tabs(items,active,action)` | L120 | 每项 `data-action=action`、`data-value=id`、`aria-pressed` |
| `empty(title,description)` | L121 | 统一空态（搜索图标 + 标题 + 说明） |
| `badge(status)` | L71 | 查 statusMap L70 得「文案 + 色」；未知状态回落灰 |
| `icon(name)` | L69 + `paths` L68 | 内联 SVG 路径表 |
| `btn(label,action,id,cls)` | L118 | 统一按钮生成器 |
| `toast(msg)` | L117 | 写 `#toast` 文本并加 `show` 类，定时移除（未核实毫秒数） |
| `openModal/closeModal/closeDrawer/simpleModal` | L222–L225 | 原生 dialog `showModal()` |
| `taskTable(rows,withFilterFooter)` | L186 | 任务表；编号规则见 §2.6 |

### 1.3 导航（index.html:139–140）

9 项，顺序、图标与分组标签如下（分组由索引硬编码插入：i===2 / i===4 / i===7）：

| # | 路由 id | 图标名 | 标题 | 前置分组标签 |
| --- | --- | --- | --- | --- |
| 0 | overview | grid | 工作台 | — |
| 1 | apps | layers | 项目与应用 | — |
| 2 | ui | phone | UI 自动化 | 测试能力 |
| 3 | perf | pulse | 性能测试 | — |
| 4 | devices | devices | 执行资源 | 共享资源 |
| 5 | tasks | tasks | 任务中心 | — |
| 6 | reports | report | 报告中心 | — |
| 7 | integration | plug | 接入说明 | 设计依据 |
| 8 | database | layers | 数据设计 | — |

- 导航即 `<a href="#id">`，不拦截点击（index.html:140）；当前项加 `active` 与 `aria-current="page"`。
- 任务中心项在 `count('running')>0` 时显示 `nav-count` 角标（L140），是全局唯一"运行中任务数"指示。
- 侧栏响应式：`#menu-toggle` 切 `.open`；render() 结束即关闭侧栏与遮罩（L141）。

### 1.4 路由（index.html:141–142、L328）

- `render()`：`route = navItems.some(n=>n[0]===location.hash.slice(1)) ? location.hash.slice(1) : 'overview'` —— 未知 hash 静默回落工作台，不报错、不改 URL。
- 页面分派：`#main = context() + 页面函数`；其中 ui/perf 在 `targetScope` 属于 [web, ios] 时改渲染 `plannedCapabilityPage('ui'|'perf')`。
- `document.title = 页面名 + ' · TestDock'`；渲染后关闭侧栏。
- `go(page)`（L142）：目标与当前 `route` 相同则直接 `render()`，否则改 `location.hash` → 触发 `hashchange`（L328：`render()` + `scrollTo(0,0)`）。
- 结论：浏览器前进/后退可用；同页重复点击靠 `go` 的等值判断避免无变化的 hash 事件。

### 1.5 context 条与 targetScope 语义（index.html:122；写入口 L310）

- 变量 `targetScope`（L79）默认 `'all'`，取值 all/android/ios/web；仅由 `#target-scope` 下拉（change 委托 L310）、目标端卡片 `target-scope` 动作（L262）或 `open-target` 动作（L261）修改。
- context 条内容：品牌"星河产品" + 目标端下拉（"全部目标端" + 三端 label）+ 右端说明：`all` 时显示"统一项目 / 三个应用目标"，否则显示 `targetCatalog[scope].application` + " · 测试环境"。
- 数据过滤只有一条规则：`inScope(t) = targetScope==='all' || platformOf(t)===targetScope`（L81），`platformOf(t)=t.platform||'android'`（L80，历史任务无 platform 视为 Android）；`scopedTasks()`（L82）供工作台、任务中心、报告中心使用。
- 资源文案：`resourceLabel(t)`（L83）Android 返回设备名，其他端返回 `t.resourceLabel||'执行环境待接入'`。

**targetScope 对页面与数据的影响（逐页核对）**

| 页面 | all | android | ios | web | 证据 |
| --- | --- | --- | --- | --- | --- |
| 工作台 | 全量统计 + 最近任务取 scopedTasks 前 6 | 同左，仅 Android 任务 | 渲染 plannedOverview（规划概览） | 同 ios | L164–165、L147 |
| 可用执行资源卡 | 统计全部设备 | 统计全部设备（设备池本就是 Android） | 0 台 + "执行资源待接入" | 同 ios | L174 |
| 项目与应用 | 三张目标端卡 + 三行应用表 | 单端卡 + 单行 | 单端（规划能力） | 单端（规划能力） | L145–146 |
| UI 自动化 | uiPage（套件/调试/模板） | uiPage | plannedCapabilityPage('ui') | 同 ios | L141、L148 |
| 性能测试 | perfPage | perfPage | plannedCapabilityPage('perf') | 同 ios | L141 |
| 执行资源 | targetOverview + androidDevicesPage | androidDevicesPage | 规划设备模板（iPhone/iPad/模拟器） | Chromium/Firefox/WebKit 模板 | L149 |
| 任务中心 | scopedTasks 过滤 | 仅 Android | 空/草稿 + 底部提示"当前端仅支持配置草稿" | 同 ios | L187–188 |
| 报告中心 | scopedTasks ∩ isFinished | 仅 Android | 通常为空态 | 同 ios | L213–214 |
| 接入说明/数据设计 | 不随 scope 变化 | 同左 | 同左 | 同左 | L215、L128 |

- 需注意：`'all'` 下任务中心显示全部端任务，但 Android 专有页面（设备调试、设备池）仍展示 Android 设备，二者语义不同（列表"全部"，资源页"仅 Android"）。
- 未核实：`targetScope` 未做 URL 持久化，刷新后回到 `'all'`（状态变量初始化 L108，未见读 hash 的部分）。

## 2. 逐页规格

页面格式统一为：区域 → 组件 → 字段 → 按钮/动作 → 校验 → 状态与空态。

### 2.1 工作台（overviewPage，index.html:164；plannedOverview L147）

**区域一：页头** — 标题/说明 + 主按钮"新建测试任务"。已演示。

**区域二：统计卡（4 张，L170–L174）**

| 卡片 | 主值算法 | 脚注 | 证据 |
| --- | --- | --- | --- |
| 演示运行记录 | 排除 draft 后的任务数 | running / queued / draft 三个数 | L170 |
| 已判定任务通过率 | round(passed / (passed+failed) × 100) | passed 数 + 已判定数 | L171 |
| 需要关注 | failed + not_tested 计数 | 分别列 failed 与 not_tested | L172 |
| 可用执行资源 | idle 设备数 / 设备总数 | busy 台数；非 all/android 时显示 0 + "执行资源待接入" | L174 |

- 通过率口径与 database-design.md §4.1 一致：不含 not_tested / errored / cancelled / 草稿。

**区域三：模块入口（2 卡，L177–L178）** — UI 自动化 / 性能测试，点击进入对应页（`nav` 动作）；`moduleVisual`（L163）生成缩略示意。

**区域四：最近测试任务（L180）** — `taskTable(scopedTasks().slice(0,6), false)` + 两列脚注"任务结果、运行状态与未判定项分开统计 / 演示数据"；下方蓝 notice"统一运行，独立判定"（L181）。

**区域五：右栏待处理事项（L182）** — 2 条静态告警：
1. "首页滑动内存超阈值：PSS 中位数 268 MB，门槛 < 240 MB" → `open-perf` + `data-id=1047`；
2. "搜索场景缺少有效样本：6 个低于 10 个下限" → `open-perf` + `data-id=1044`。
- 已演示：点击会切 scope→android、把 `selectedRun` 设为该 id、`perfTab='analysis'`、复位基线/样本状态后跳性能页（L254–L304 的 `open-perf` 分支）。
- 规划态：告警是硬编码两条，非由指标计算产生，**不能当作告警引擎已实现**。

**区域六：执行资源（L183）** — 前 3 台设备行 + `tiny-bar` 占用条 + 文案"4 台已授权在线 / 6 台设备"。

**页脚（L184）** — "统一项目、目标端与执行任务 · Android 组件先接入，Web / iOS 逐步扩展"。

**plannedOverview（L147，仅 ios/web scope）** — 规划态概览：目标端能力清单 + "执行能力待接入"，无统计卡。

**空态** — 工作台无独立空态；任务为空时表格显示 `empty('没有匹配的任务')`（来自 taskTable）。

### 2.2 项目与应用（appsPage，index.html:146；targetOverview L145）

- **页头**：标题"项目与应用"，说明"一个产品项目下分别管理 Web、Android 和 iOS 应用，共用任务与报告入口。"
- **区域一：目标端卡（targetOverview，L145）** — 三张可点卡（android 徽章"已有组件基础"，ios/web 徽章"规划中"），卡内两行 `application / resource`，底部小字：android"UI 与性能交互可体验"，其他"可配置草稿，执行服务待接入"。点击 = 切 `targetScope` 并整页 render（L262）。
- **区域二：应用表（L146）** — 表头：目标端 / 应用 / 目标标识 / 执行能力 / 操作。
  - 行按 scope 过滤（`targetScope==='all' || scope===k`）。
  - 字段来自 `targetCatalog`（L74–78）：Android `星河 Android / com.example.xinghe / 已有组件，平台未连接`；iOS `星河 iOS / com.example.xinghe.ios / 规划中`；Web `星河 Web / https://staging.example.test / 规划中`。
  - 操作"进入应用工作区"= `open-target`：设 scope 后 `go('ui')`（L261）。
- **区域三：蓝 notice** — "应用标识按目标端区分：Android 包名、iOS Bundle ID、Web 站点地址。任务绑定明确的应用与环境，跨端只汇总共同结果，不混用性能基线。"
- **状态/空态**：无空态（固定 3 行）；scope=android 时只剩 1 行。
- **规划态**：多项目、成员与权限、真实构建上传均未出现（仅"未来可按项目隔离应用、配置与执行权限"文案）。

### 2.3 UI 自动化（uiPage，index.html:190；tabs 三视图）

**页头** — 标题"UI 自动化"，说明"当前工作区：Android · 复用 pytest 用例、设备调试与失败证据"，主按钮"新建 UI 任务"，tabs：测试套件 / 设备调试 / 图像模板（`uiTab` 默认 `'suites'`，L108）。

**视图 A：测试套件（uiTab='suites'）**
- 蓝 notice："用例继续由 Python / pytest 维护 … 接入后由宿主同步用例元数据"。
- 套件表（`suites` L189）：4 行示例 — 核心链路回归（12 例 / passed / 启动、首页、搜索、商品详情）、登录与账号（6 / passed）、下单链路（8 / failed）、个人中心（5 / passed），合计 31 示例用例。
- 两卡跳转："在冻结快照中定位元素"（→ 设备调试）、"查看失败现场"（→ report 1042）。
- 套件弹窗（click 分支 L289）：展示 pytest 用例与 MobileAdapter 代码示意；"运行套件"（L290）→ `newTask('ui', 套件名)` 打开向导。
- 校验：无（只读列表）；**空态**：无（恒定 4 行）。

**视图 B：设备调试（inspectorPage，index.html:192）**
- 工具栏：设备下拉（仅列 idle/busy 设备）、状态 badge、"直接控制（演示）"复选框（非 idle 或 frozen 时 disabled）、"采集检查 / 恢复预览"按钮。
- 约束：非 idle 时 notice"设备正在执行任务，当前仅可观察示意画面；采集与控制受到设备租约限制"；`freeze` 动作在非 idle 时 toast"设备被占用，仅可观察，不能采集检查。"（L254–L304）。
- 三栏：
  1. 手机示意（`phoneMarkup` L191）— 含 `phone-top`、`phone-app`、去结算按钮、底部导航；frozen 时显示 badge"冻结快照" + `SNAP-DEMO-01` + 分辨率；"返回 / 主屏"仅 `directControl` 为真可用。
  2. UI 层级树 — 3 个示例节点（FrameLayout / LinearLayout + title / product / checkout 可点节点）；未 frozen 时整棵禁点（disabled）。
  3. 元素与定位描述（`nodeDetails` L198）— 选中后显示 text / class / clickable、定位候选（resource-id 优先，text 标注"文案变动会失效"）、表达式 `Target(Locator.RESOURCE_ID, "com.example.xinghe:id/<name>")`、"验证定位""复制表达式"按钮 + `#locator-result`。
- 校验行为："验证定位"固定返回"✓ 演示匹配：1 个节点，匹配唯一。来源：冻结快照 SNAP-DEMO-01；非真机校验。"（L287，硬编码，**不调用真实定位**）；复制走 `navigator.clipboard`，失败则选中文本（L288）。
- 拾取交互：未 frozen 且无直接控制时 toast"先点击「采集检查」，在冻结快照中拾取。"；frozen 后点节点切换选中并重渲染（L254–L304）。
- **空态**：未拾取时第三栏 `empty('等待拾取')`。
- **规划态**：预览与层级均为 CSS/静态示意；未见 WS 预览流、ADB 通道、真实 uiautomator dump。

**视图 C：图像模板（templatesPage，index.html:199）**
- 蓝 notice："复用现有不可变模板版本机制。原型只保存模板元数据，图片区域使用示意占位。"
- 表列：逻辑名 / 模板版本 / 匹配阈值 / 来源（演示冻结快照）/ 操作。
- 新建弹窗（L301）：`name`（pattern `[a-zA-Z0-9_/-]+`）、`confidence`（0.01–1）。
- 提交（submit 委托 L323）：同名则版本号 +1 追加（旧版本不变），`save()` 后 toast"已保存模板元数据 vN；原有版本保持不变"。
- 查看定位描述（L302）：输出 `Target(Locator.IMAGE, "name", confidence=x)`。
- **空态**：无；**规划态**：模板图片、截图裁剪、真实匹配算法均未实现。

### 2.4 性能测试（perfPage index.html:204；baselinePage L212；metricData L109；metricForRun L202；perfVerdict L203）

**页头** — 标题"性能测试" + 说明 + "新建采集任务" + tabs：运行分析 / 基线与门禁（`perfTab` 默认 `'analysis'`）。

**指标口径（metricData，L109）**

| key | 名称 | SQL 指标键 | 单位 | 演示 median | 演示 baseline | 范围 |
| --- | --- | --- | --- | --- | --- | --- |
| memory | PSS 内存 | mem_pss_mb | MB | 268 | 221 | 160–340 |
| cpu | 应用进程 CPU | cpu_process_pct | % | 24.6 | 22.8 | 0–50 |
| fps | 帧率 | fps_frame | fps | 58.2 | 59.1 | 30–65 |
| gpu | GPU 占用 | gpu_util_pct | % | null | null | 0–100，null=当前设备不支持 |

- `metricForRun`（L202）：非 1047 且 passed 的运行把 median 改为 218 / 22 / 59（制造"另一条通过运行"）。

**视图 A：运行分析**
- 工具栏：运行下拉 `#perf-run`（仅 `taskHasPerf(t) && isFinished(t)` 的任务）、设备档案 badge、"导出报告 JSON"（L205，调 `exportReport`）。
- 结论 notice（L206）：显示**原始运行结论**原文 + "切换基线或规则只影响分析，不改写历史报告"。
- 指标卡 ×4（L207）：median + 单位 + 较基线百分比；median 为 null 显示"— / 当前设备不支持"；跨档案显示"跨档案，不作对比"；fps 下降标 amber，其余上升标 amber。
- 趋势卡（L208 + chartMarkup L211）：手绘 SVG `polyline` + 基线虚线；正常 31 点、样本不足 6 点；gpu 显示"当前设备不支持 GPU 占用采集…不以 0 代替未采集值"；图注区分"采集结束后的归档曲线（演示）"与"180 个演示样本 / 判定使用 median"。
- 运行上下文卡（L209）：应用版本 / 场景 / 设备档案 / 窗口 / 统计口径（median）/ 采集来源（SoloPi / 补采）+ 两个下拉：**对比基线**（`baselineProfile`：same / 其他档案）、**样本状态**（`sampleMode`：normal / low）。
- 质量门禁试算表（L210）：列 指标 / 中位数 / 绝对阈值 / 级别 / 样本数 / 检查结果；未判定时用 `empty`。

**门禁判定算法（perfVerdict，L203，接入必须照此实现语义）**
1. `baselineProfile !== 'same'` → not_tested，文案"基线设备档案不匹配…"，`checks=[]`（不可比 ⇒ 不判定）。
2. `sampleMode==='low'` 或任务已是 not_tested → not_tested，"有效样本数为 6，低于默认下限 10"。
3. 否则逐指标生成 check：memory（`< 240`，fail）、cpu（`< 35`，level 取 `rules.cpuLevel`，默认 warn）、fps（`≥ 50`，fail），`sampleCount:180`。
4. 任一 fail 级不满足 → failed；只有 warn 级不满足 → passed 且 reason 说明"告警不改结论"；全部满足 → passed。

**视图 B：基线与门禁（baselinePage L212）**
- 蓝 notice："基线按设备档案隔离；阈值由平台传入 … 不自动把版本回退百分比当成门禁"。
- 基线卡：来源运行 `BASE-DEMO-379`、设备档案、PSS 221 MB、CPU 22.8%、FPS 59.1、样本下限 10。
- 阈值表单 `#rules-form`：memory `<` 阻断；cpu `<` 级别可选告警/阻断；fps `≥` 阻断；含 min/max。提交（submit 委托 L322）保存 `rules` → 切回 ·analysis· → toast"演示规则已保存…历史结果不变"。
- 校验：依赖控件原生 min/max/step，未见自定义 JS 校验（未核实）；**空态**：无。

### 2.5 执行资源

**devicesPage（index.html:149）分派**：scope=android → androidDevicesPage；all → `targetOverview() + androidDevicesPage()`；ios/web → 规划模板（ios：iPhone 真机 / iPad 真机 / iOS 模拟器；web：Chromium / Firefox / WebKit），徽章"待接入"，可用实例 0，"创建配置草稿"按钮 + "WebKit 不等于 Safari、模拟器不等于真机"说明。

**androidDevicesPage（index.html:200）**
- 页头："Android 设备池 · 管理设备档案、就绪状态与占用"；筛选 `#device-filter`（全部设备（6）+ 4 个状态）。
- 设备卡：名称 + 状态 badge、设备示意（idle 可调试 / busy 只读预览 / 未连接）、档案行 系统 / 分辨率 / 设备编号 / 当前任务、操作按钮 + "设备档案"。
  - 当前任务：busy → RUN 链接；unauthorized → "等待 USB 调试授权"；offline → "检查连接与设备状态"；否则"无占用"。
  - 操作：busy → "只读预览"；否则"打开调试"；offline / unauthorized 时 disabled。
- 三态语义（`deviceState` L112 + 种子 `devices` L85–L92）：`idle`（无占用）/ `busy`（有 running 任务占用，动态推导、不落库）/ `offline` / `unauthorized`；种子 4 idle + 1 unauthorized + 1 offline，页脚"4 台已授权在线 / 6 台设备"。
- 底部 notice："设备占用状态与 UI、性能任务共用 … 接入时由宿主协调设备租约和短事务准入；原型不执行连接、安装或授权操作。"
- **空态**：`empty('当前没有此状态的设备')`。
- **规划态**：租约、fencing token、心跳、draining 未在 UI 出现（schema.sql:172 有 `draining`，原型无此状态，见 §8）。

### 2.6 任务中心（tasksPage L187；filteredTasks L188；taskTable L186）

**列表视图**
- 工具栏：`#task-search`（占位"搜索任务名称或编号"）、`#task-module`（全部模块 + UI 自动化 / 性能测试 / UI + 性能）、`#task-status`（全部状态 + 7 状态：draft / running / queued / passed / failed / not_tested / cancelled）、右侧提示"演示任务会在当前浏览器保存"。
- 过滤逻辑（L188）：`scopedTasks() ∩ module ∩ status ∩ (name + 'RUN-'|'TASK-' + id).toLowerCase().includes(query)`；底部"共 N 条任务"+ 端范围提示（web/ios 时"当前端仅支持配置草稿，执行服务待接入"）。
- 表格（taskTable L186）：表头 任务名称/编号、目标端/类型、状态、执行资源、创建时间、操作。
  - 编号规则：draft → `TASK-<id>`，其余 `RUN-<id>`；应用版本缺省 `3.8.0-rc.2`。
  - running 行内嵌进度条（`progress` 0–100）。
  - 操作列：`isFinished` → "查看报告"；draft → "查看配置"；否则"查看执行"。
- **空态**：`empty('没有匹配的任务')`。

**新建向导（newTask L240；readDraft L241；wizardRender L242–L247；wizardNext L248；createDemoTask L249）**

3 步，步骤标签"基本信息 / 设备与配置 / 确认任务"；底部"上一步或取消" + "下一步 / 创建演示任务"，`foot-hint`"仅创建本地演示记录"，错误区 `#wizard-error role=alert`。

| 步骤 | 字段 | 控件 / 校验 |
| --- | --- | --- |
| 1 | 目标端 | targetPicker（L144）；编辑态禁用其他端 |
| 1 | 测试模块 | 3 卡：UI 自动化 / 性能测试 / UI + 性能（联动标注"联动设计 / 待接入"，选中时 notice"真实运行需要宿主注入设备准入协议并实现步骤打标"） |
| 1 | 任务名称* | maxlength 60，必填（空 → "请填写任务名称、应用包名和版本。"） |
| 1 | 应用包名* | maxlength 120，必填 + 正则 `/^[a-zA-Z]\w*(\.[a-zA-Z]\w*)+$/`（失败 → "请使用合法的应用包名"） |
| 1 | 应用版本* | maxlength 40，必填 |
| 1 | 测试套件 / 场景 | select：ui 取 suites 名；perf 取 首页滑动场景 / 商品详情 / 搜索场景；提示"示例目录；实际用例与应用版本需要宿主同步" |
| 2 | 执行设备* | 单选列表，每台 name + OS + 状态 badge；offline / unauthorized disabled；"可选择占用中的设备排队；离线或未授权设备不可选"；校验 → "请选择已授权在线的设备。" |
| 2 | 采集时长（非 ui） | number min 10 max 3600 step 1；校验整数且 10–3600（→ "采集时长需要是 10–3600 之间的整数秒。"） |
| 2 | 采集指标（perf） | CPU / Memory / FPS 禁用且必选；Network（全局网络）/ Battery（电流·功率）可选 |
| 2 | 基线与门禁摘要（perf） | 只读"同档案稳定版 / 标准门禁 PSS < 240 / CPU < 35 / FPS ≥ 50" |
| 3 | 确认 | 蓝 notice"创建后进入本地演示队列，不会触发真实测试" + 汇总 dl（任务名称 / 模块 / 应用 / 版本 / 套件或场景 / 执行设备；perf 另有采集时长 / 采集指标 / 门禁"同档案基线 + 标准门禁 / median / 样本 ≥ 10"） |

- 创建结果（L249）：`id` = max+1、`status='queued'`、`platform='android'`、`projectId='xinghe'`、`applicationId='xinghe-android'`；unshift → `save()` → 关弹窗 → `targetScope='android'` → 清筛选 → 跳任务中心并打开详情 → toast"演示任务已创建，可点击「开始演示」"。
- **规划态**：无真实提交 API、无 request_key 幂等键、无 revision / readiness 概念（DB 侧有，见 §3）。

**运行详情（taskDetail L226；draft 转 plannedTaskDetail L160）**
- 抽屉结构：badge + 平台/模块 + 描述列表（应用版本、设备/系统、用例或场景、采集窗口（ui 显示"不采集性能"）、创建时间"2026-10-25 <time>（演示）"、重跑时"重新运行自 RUN-x"）。
- 4 步 timeline（`labels` L228）：设备准入与环境检查 → 执行 pytest 用例 / 启动采集会话 → 断言与失败证据 / UI 步骤与采集关联（待接入设计）/ 采集时间窗 → 归档与结果判定；`stage` 由 progress 推导（<40→1，<85→2，=100→3，终态→4），failed 时第 4 步变 error 样式。
- 按钮与状态转换见 §3.4；notice"演示模式：使用下方按钮推进状态。不会运行脚本…"。
- **空态**：无（id 必存在）。

### 2.7 报告中心（reportsPage L213；reportCards L214；reportDetail L231；exportReport L252）

**列表** — 搜索 `#report-search`、模块筛选 `#report-filter`、提示"重跑创建新记录，不覆盖历史证据"；仅 `isFinished` 的任务出现（passed / failed / not_tested；draft / running / queued / cancelled 不出现）。
- 卡片字段：模块 pill（平台 / 模块）、状态 badge、名称、`RUN-<id> / <执行资源>`、一句话结论、时间 + "查看报告"。
- 一句话结论映射（L214）：not_tested → "样本不足，未产生门禁结论"；ui failed → "断言未满足，已保留失败现场"；ui passed → "用例断言通过，执行过程可追溯"；perf failed → "性能阈值未满足，查看指标与基线"；perf passed → "性能门禁通过，指标与基线可比"。
- **空态**：`empty('没有匹配的报告','已完成且有判定结果的任务会出现在这里。')`。

**详情（reportDetail，L231）**
- 头部：`RUN-<id> · 测试报告` + 结论圆点 + 状态标题 + 一句话。
- 汇总 dl：设备档案 / 应用版本 / 测试模块 / 证据归属 `RUN-<id>（演示产物）`。
- 性能分支：notice 三态文案（not_tested "6 个有效样本，低于 10 个下限。缺失不是通过。"；failed "PSS median 268 MB / 门槛 < 240 MB / 180 个样本。"；passed "PSS median 218 MB…"）+ "归档内容"3 条（指标汇总与时序曲线（演示）/ 采集窗口设备档案与基线引用 / 原始门禁结论与后续试算分开保留）；joint 额外蓝 notice"UI 结果：通过… 组合编排属于待接入设计"。
- UI failed 分支：失败截图示意 + `pre` 失败证据（AssertionError: 确认页关键元素未出现 / wait_for: order_confirm / timeout: 10 s / run: RUN-id / evidence: 演示证据）+ 截图 / UI 树 / 异常属性 + "查看 UI 树示意"（L292 弹窗输出 hierarchy XML 与"预期的 order_confirm 节点未出现。"）。
- UI passed 分支：绿 notice"所有示例断言通过，无失败证据。" + 3 步 timeline。
- 底部动作：导出 JSON / 重新运行 / 打开性能分析（仅 perf）/ 关闭。

**JSON 导出（exportReport，L252）** — 字段：`prototype:true`、`notice`（"演示数据，未执行真实测试；平台导出示意，不是组件原始接口响应"）、`runId` / `hostRunId`（同值 `'RUN-'+id`）、`name`、`projectId`（缺省 xinghe）、`applicationId`（缺省 xinghe-android）、`platform`、`environmentId`（缺省 staging）、`resourceId`、`module`、`status`、`target`（缺省包名）、`deviceProfile`、`durationS`、`metricsSummary`（perf 时 memory / cpu / fps 三项 {median, unit, sampleCount: not_tested?6:180, source:'synthetic_demo'}）、`verdict`（=status）、`thresholdsAtRun`（`mem_pss_mb: ['lt',240,'fail']`、`cpu_process_pct: ['lt',35,'warn']`、`fps_frame: ['ge',50,'fail']`）、`reason`（not_tested → `'sample_count_below_minimum'`）。
- 下载：Blob + 文件名 `TestDock-RUN-<id>-DEMO.json`；toast"已导出演示报告 JSON。"；research.md 自述"未捕获下载完成事件"。
- 差异：这是**平台侧汇总格式**，与 mobile_perf report.py 原生字段（schemaVersion / deviceProfile / marks / metricsSummary / series / events / integrity）不同，接入时必须映射（database-design.md §9）。

### 2.8 接入说明（integrationPage，index.html:215；architectureNote L150）

- **架构 note**：平台通用模型 flow + "配置草稿未执行，不计入运行通过率，也不等同于 not_tested"。
- **页头**：标题"接入说明" + 链接 research.md。
- **蓝 notice**："原型尚未连接后端"。
- **flow 图**：Web 工作台 → 宿主编排 / 适配层（待开发）→ mobile_auto / mobile_perf 两个组件。
- **本地能力核查（5 行）**：UI 自动化组件 passed"已查代码"；性能测试组件 passed；平台任务 / 用例目录 amber"待接入"；UI + 性能联动 amber"待接入"；远程访问 / iOS gray"首期未实现"。
- **开源参考（6 条）**：Sonic（服务端已归档）、STF、SoloX、Maestro、SoloPi、Allure。
- **"接入时必须保留的语义"（5 条，本页最重要原文）**：
  1. 设备占用：同一实例同一时刻只允许一个运行或调试持有租约；
  2. 采样缺失：缺指标写 NULL + 原因，不以 0 代替；
  3. 三态门禁：passed / failed / not_tested 不得压成二态；
  4. 原始报告：保留组件原始结论，平台汇总可追加不可覆盖；
  5. 性能时序：当前没有已核实的平台实时性能推送接口（曲线是采集结束后的归档）。
- **规划态**：该页是"接入契约"的文字声明，没有任何代码 / 接口实现。

### 2.9 数据设计（databasePage L128；databaseOverview L129–L134；databaseDictionaryPage L135 / databaseDictionary L136；databaseFlowPage L137；databaseFlows L125）

- **页头**："多端共用的数据模型 · 设计草案 v1 / PostgreSQL" + 链接 database-design.md + "下载 schema.sql"（`download` 属性，纯静态文件）+ 蓝 notice"当前原型仍使用浏览器本地存储，未连接数据库；SQL 尚未经过真实建库验证"。
- **3 个 tab**（`dbTab`）：关系总览 / 字段字典 / 写入流程。任务要求的"四视图"实际为：总览、字典、字典内检索、写入流程（检索不是独立 tab）。

**视图 1：关系总览（databaseOverview）**
- 24 张设计表徽章（数量取 `databaseTables.length`）。
- 4 条业务泳道：
  - 从配置到运行：projects / applications / test_tasks / task_revisions
  - 一次运行的可追溯结果：test_runs / run_components / case_results / artifacts
  - 共用资源保留各端差异：resource_profiles / execution_resources / debug_sessions / resource_leases
  - 性能口径与历史判定：metric_summaries / baselines / gate_policies / gate_evaluations
- 双卡："关系库存结构与摘要 / 文件存储保留完整现场" + 文案"建表不等于接入完成…"。

**视图 2：字段字典（databaseDictionaryPage + databaseDictionary）**
- 工具栏：`#db-search`（输入即局部重渲染，input 委托 L305）+ `#db-group`（全部领域 + 7 组：基础资产 / 执行资源 / 测试定义 / 任务运行 / 结果证据 / 性能质量 / 治理追溯）+ 说明"列、键与 schema.sql 对应"。
- 左栏：表清单（分组过滤 + 关键词匹配表名 / 中文名 / 字段名，显示匹配数，选中项 `aria-pressed`）。
- 右栏详情：表名 + 中文名 + 分组、`purpose`（业务职责原文）、引用 / 被引用外键链接（`dbLink` L127，点击跳到关联表并清空筛选）、字段表（字段 / SQL 定义 / 说明）、表级约束列表、`notes` notice（如"角色必须由后端检查""终态只追加"）。
- **空态**：`empty('没有匹配的数据表')`。
- 检索边界：纯前端字符串匹配，无全文索引、无模糊纠错（是否大小写不敏感未核实，按 includes 推断）。

**视图 3：写入流程（databaseFlowPage）**
4 个流程（`#db-flow`），每流程 4 步（标题 + 说明 + 涉及表按钮），底部 notice"本页描述事务与数据去向，不能代替真实并发测试"：
1. `save` 保存配置与重跑 — test_tasks / task_revisions（lock_version CAS）→ test_runs（request_key 幂等）。
2. `lease` 资源分配与人工调试 — execution_resources / resource_leases / debug_sessions / fence_counter。
3. `report` 结果与证据归档 — run_components / case_results / artifacts（临时键 → 校验 → 提交元数据）。
4. `gate` 基线与规则试算 — gate_policies / baselines / gate_evaluations（original 与 reanalysis 分离）。

## 3. 状态枚举与转换（原型 ↔ SQL 对照）

### 3.1 五组核心枚举（以 schema.sql 为准，原型为演示子集）

| 字段 | 枚举值（SQL CHECK） | 证据 | 原型对应 |
| --- | --- | --- | --- |
| `test_tasks.lifecycle` | draft / ready / archived | schema.sql:251 | 无此字段；原型用 `status='draft'` 混合表达"草稿" |
| `task_revisions.readiness` | draft / validated | schema.sql:282 | 无；原型草稿即"未验证配置" |
| `test_runs.state` | queued / dispatching / running / finalizing / completed / errored / cancelled | schema.sql:320 | 原型 `status`：queued / running / passed / failed / not_tested / cancelled（缺 dispatching、finalizing、errored；多了业务结论） |
| `test_runs.outcome` | passed / failed / not_tested（仅 completed 非空） | schema.sql:321、L341 | 原型的 passed / failed / not_tested 即 outcome，但与 state 挤在同一 `status` 字段 |
| `gate_evaluations.mode` | original / reanalysis | schema.sql:631 | 无；原型只演示"试算不改历史"文案，未建两条记录 |
| `artifacts.availability` | available / missing / expired | schema.sql:505 | 无；原型只有"证据归属 RUN-id（演示产物）"文案 |

补充枚举（同样只有 SQL 强制，原型未体现）：`run_components.state` pending / running / completed / errored / cancelled 与 `outcome` 三态（schema.sql:439–440、L448）；`debug_sessions.state` opening / active / closing / closed / lost（L375）；`execution_resources.status` ready / offline / unauthorized / draining（L172，原型无 draining）；`case_results.outcome` passed / failed / skipped / errored（L470）；`metric_summaries.statistic` median / p95 / mean / min / max（L540）。

### 3.2 关键约束（DB 层强制，原型无）

- 结论与状态互锁：`(state='completed' AND outcome IS NOT NULL) OR (state<>'completed' AND outcome IS NULL)`（schema.sql:341）；`(state IN ('completed','errored','cancelled')) = (ended_at IS NOT NULL)`（L342）；running / finalizing / completed 必须有 `resource_id` 与 `started_at`（L343）。
- 配置可运行性：`readiness='draft' OR (build_id IS NOT NULL AND suite_version_id IS NOT NULL)`（L294）— "字段完整不代表可运行"。
- 租约互斥：`(run_id IS NOT NULL) <> (debug_session_id IS NOT NULL)`（L415）+ 部分唯一索引 `leases_one_live_resource`（L721）、`leases_one_live_run`（L722）、`leases_one_live_debug`（L728）。
- 指标缺失语义：`(value IS NULL AND missing_reason IS NOT NULL) OR (value IS NOT NULL AND missing_reason IS NULL)`（L548）— 禁止用 0 冒充缺失。
- 门禁可解释性：`verdict <> 'not_tested' OR reason_code IS NOT NULL`（L643）；每组件最多一条 original 判定（`gate_one_original` L724）。
- 幂等：`UNIQUE(project_id, request_key)` 用于 test_runs（L334）与 gate_evaluations（L638）；事件 `UNIQUE(project_id, run_id, source_key, source_event_id)`（L672）。

### 3.3 状态转换（database-design.md §4.2–4.3 原意）

| 转换 | 触发 | 强制点 |
| --- | --- | --- |
| 草稿保存 | 新增 task_revision（`revision+1`）+ `test_tasks.lock_version+1` | 应用事务 |
| 草稿 → 已验证 | 另存一条 `readiness='validated'` 修订，不同步改写草稿 | 应用事务 + L294 CHECK |
| validated → 排队 | 校验成员权限 / 未归档 / 套件类型匹配 / 构建明确 / 环境完整 / 适配器支持 → 新增 `state='queued'` 运行 | 提交事务；原型 createDemoTask 仅 UI 侧 |
| queued → dispatching | 调度器短事务领取 + 绑定实例与档案 + 写租约（带 fence token） | 需 `FOR UPDATE SKIP LOCKED`（DDL 未提供） |
| dispatching → running | Agent 确认取到任务、设备就绪 | 后端 + 心跳 |
| running → finalizing | 执行结束，证据校验 / 归档中 | 后端 |
| finalizing → completed | 证据完整 + 判定完成（outcome 三选一） | 后端 |
| 任意执行态 → errored | 节点断连 / 宿主失败（outcome 必须 NULL） | 后端 |
| 任意非终态 → cancelled | 用户取消 | 后端；不计通过率 |
| 终态 → 任何态 | **禁止回退**；只能新建 run 或新 reanalysis | 后端写入边界 |
| 重跑 | 新 test_runs 行 + `parent_run_id`，默认复用原 revision | 后端；原型 rerun L251 仅复制前端对象 |

### 3.4 原型"模拟运行"如何推进状态（index.html:250 mutateTask）

- 仅 Android 可推进，入口在任务详情按钮组。
- `start-task`：任务 `queued` 且其设备 `deviceState` 为 idle → `running` + `progress=20`；否则 toast"设备仍被其他演示任务占用"（原型对"租约冲突"的唯一演示）。
- `advance-task`：running 且 progress<40 → 55；<85 → 90；否则 100 且 `status='passed'`。
- `fail-task`：running → progress 100 + `failed`。
- `cancel-task`：queued / running → `cancelled`。
- 影响：`deviceState`（L112）在被 running 任务占用时返回 `busy`，于是设备页禁用"打开调试"、inspector 只能只读——这是原型唯一真实的"跨页联动约束"。
- 通过率 / 统计 / 导航角标 / 报告列表都随之实时变化。

## 4. 24 张表清单与业务职责（database-design.md §3；与 index.html:124 字典一致，231 字段 / 56 外键，verify-design.cjs 已核对）

| # | 表 | 中文 | 业务职责（按文档原意，不改写含义） |
| --- | --- | --- | --- |
| 1 | projects | 项目 | 产品级隔离单元，Android、iOS、Web 应用归属于同一项目。 |
| 2 | project_members | 项目成员 | 复用身份提供方，以项目角色授权，不在业务库保存登录口令。 |
| 3 | applications | 应用 | 目标端属于应用，不为每种端复制一套任务和报告表。 |
| 4 | app_builds | 应用构建 | 固定待测构建；移动包与 Web 部署均采用同一版本记录。 |
| 5 | environments | 测试环境 | 保存各环境的非敏感配置，实际站点地址可随环境区分。 |
| 6 | execution_nodes | 执行节点 | 宿主 Agent 与可用适配器，初期按项目独占。 |
| 7 | resource_profiles | 资源档案 | 不可变的可比性档案：系统、设备或浏览器、采集器、分辨率、指标版本。 |
| 8 | execution_resources | 执行实例 | 真机、模拟器或浏览器槽位。每个实例只承载一个活动运行。 |
| 9 | test_suites | 测试套件 | 登记代码维护的 UI 用例或性能场景，不把脚本正文塞进数据库。 |
| 10 | suite_versions | 套件版本 | 固定仓库、提交及选择器，旧运行可追溯到当时的用例。 |
| 11 | test_tasks | 测试任务 | 用户可编辑的逻辑任务；不存通过或失败结果。 |
| 12 | task_revisions | 任务配置版本 | 每次保存新增不可变修订；运行只引用已验证修订。 |
| 13 | test_runs | 测试运行 | 一次提交或重跑对应一行，保留执行状态、最终结论和当时配置。 |
| 14 | debug_sessions | 调试会话 | 人工设备控制使用短期调试会话，与自动运行竞争同一资源租约。 |
| 15 | resource_leases | 资源租约 | 保留运行或调试的独占历史，用 fencing token 拒绝过期执行者。 |
| 16 | run_components | 运行组件 | 一次运行下的 UI/性能子结果。联动共用运行和租约，分别保留结论。 |
| 17 | case_results | 用例结果 | 每个用例的执行尝试独立保存，可区分用例重试与整次重跑。 |
| 18 | artifacts | 证据文件 | 保存文件元数据和私有存储键，截图、日志、录像、曲线均通过此表归档。 |
| 19 | metric_summaries | 性能摘要 | 按指标、统计窗口和统计量保存查询所需的小体积摘要。 |
| 20 | baselines | 基线版本 | 不可变的对照版本；源运行和全部可比性信息一并保留。 |
| 21 | gate_policies | 门禁规则版本 | 平台持有门槛，适配器负责正确的测量与统计。 |
| 22 | gate_evaluations | 门禁判定 | 原始判定与后续试算分开保存；改规则不会覆盖历史结论。 |
| 23 | run_events | 运行事件 | 状态变化、步骤标记、接入事件按运行顺序追加，支持断线续看。 |
| 24 | audit_events | 审计事件 | 记录谁修改配置、发起运行或调整规则，不承载完整业务数据。 |

- 分组（字典 L124 的 `group` 字段，7 组）：基础资产 5 表 / 执行资源 5 表 / 测试定义 2 表 / 任务运行 3 表 / 结果证据 3 表 / 性能质量 4 表 / 治理追溯 2 表。
- 刻意没有独立 `reports` 主表：报告是查询视图，归档文件记为 `artifacts.logical_key`（database-design.md §3）。
- 联动模型：一条 `test_runs` + 同一租约 + 两个 `run_components`（ui / performance）；不建 `android_runs / ios_runs / web_runs`。
- 关键唯一键样例：`UNIQUE(project_id, id)` 全表通用；`UNIQUE(project_id, platform, identifier)` applications L53；`UNIQUE(project_id, request_key)` test_runs L334；`UNIQUE(project_id, run_id, logical_key)` artifacts L509；`UNIQUE(project_id, component_id, metric_key, metric_version, scope, window_key, statistic)` metric_summaries L546。

## 5. localStorage 与种子数据

### 5.1 存储键与读写

- 键：`'testdock.prototype.v1'`（index.html:103）。
- 写：`save()`（L116）序列化 `{tasks, templates, rules}`；失败 toast"浏览器未允许本地存储，本次演示仍可使用。"（降级为内存态）。
- 读：L105 启动时 `JSON.parse` + 逐条校验（statusMap 有该状态、moduleNames 有该模块、platform 属 targetCatalog、设备 id 存在），任一不合法整份回落 `structuredClone(seedTasks)`；`templates`（L106）与 `rules`（L107）失败时回落默认值。
- 结论：**无 schemaVersion、无迁移逻辑**，键名升级即整份重置。

### 5.2 种子任务形状（L93–L102，8 条）

固定字段（每行一个任务对象）：`id`（数字，展示时前缀 RUN-/TASK-）、`name`、`module`（ui / perf / joint）、`status`（passed / failed / not_tested / running / queued / draft / cancelled）、`device`（设备 id）、`suite`（套件或场景名）、`progress`（0–100）、`time`（HH:MM）、`duration`（秒）。

运行期新建 / 重跑对象额外带：`platform`、`projectId`、`applicationId`、`environmentId`、`identifier`、`resourceId`、`resourceLabel`、`browser`、`viewport`、`iosResource`、`build`、`pkg`、`items`（采集指标数组）、`parent`（重跑来源 id）— 见 L159 savePlannedTask、L249 createDemoTask、L251 rerun。

其他种子：`devices` 6 台（id / name / os / profile / serial / base / res / host，L85–L92）；`templates` 1 条 {name:'home/checkout', version:1, confidence:0.9}（L106）；`rules` {memory:240, cpu:35, fps:50, cpuLevel:'warn'}（L107）。

### 5.3 状态常量与 UI 状态

- `statusMap`（L70）：draft 配置草稿/amber、passed 已通过/green、failed 未通过/red、not_tested 未判定/amber、running 执行中/blue、queued 排队中/gray、cancelled 已取消/gray、idle 可用/green、busy 占用中/blue、offline 离线/gray、unauthorized 待授权/amber。
- `moduleNames`（L72）：ui / perf / joint → UI 自动化 / 性能测试 / UI + 性能。
- UI 状态变量（L108）：route、uiTab、perfTab、selectedMetric、selectedRun、baselineProfile、sampleMode、inspectorDevice、frozen、selectedNode、directControl、taskFilter、taskModule、taskQuery、deviceFilter、reportFilter、reportQuery、wizard、currentTask；DB 侧 dbTab / dbSelected / dbQuery / dbGroup / dbFlow 在 L126。全部是内存变量，不进 localStorage、不进 URL。

## 6. 结论 A：原型已演示（可直接作为验收用例）

1. 9 页导航 + hash 深链 + 前进后退 + 未知 hash 回落工作台（§1.3–1.4）。
2. 目标端切换驱动 5 处过滤与 2 处降级（§1.5 矩阵）；Web/iOS 进入 UI/性能页显示规划能力而非假数据。
3. 工作台 4 统计卡口径（通过率不含 not_tested）、待处理事项可跳转到指定运行。
4. 任务中心模块 / 状态 / 关键词组合过滤；草稿用 TASK- 前缀、运行用 RUN- 前缀。
5. 新建任务 3 步向导与全部校验文案（名称 / 包名 / 版本 / 设备 / 时长），含"离线或未授权设备不可选"。
6. 运行详情 4 步时间线 + 4 个手动动作（开始 / 推进 / 失败 / 取消）+ 设备占用冲突 toast。
7. 报告中心只列已判定运行，5 类一句话结论；UI 失败现场（AssertionError + UI 树）；性能三态结论；JSON 导出字段完整可下载。
8. 性能分析：4 指标卡、SVG 归档曲线、基线 / 样本切换即时改判定、试算表格、跨档案"不作对比"、GPU 缺失显示"不支持"而非 0。
9. 基线与门禁页：阈值可改并即时反映到试算，且明确"不改写历史报告"。
10. Android 设备池：4 状态展示与操作禁用规则；busy 由 running 任务动态推导。
11. 设备调试：冻结快照 → 拾取节点 → 定位候选与表达式 → 验证 / 复制，未冻结或无直接控制时有正确引导与拒绝。
12. 图像模板：不可变版本追加（同名 +1，旧版本保留）。
13. 数据设计：24 表总览泳道、字典检索与分组、外键互跳、4 条写入流程；schema.sql 可下载。

## 7. 结论 B：规划态（不得当已实现）

1. 任何真实执行：无后端、无 API 调用、无设备 / ADB / WS 连接，全部"运行"是手动推进（L250）。
2. Web / iOS 能力：只有 plannedOverview / plannedCapabilityPage / plannedWizard 三套文案页与"配置草稿"，无适配器、无指标口径、无门禁（L141、L148、L152–L159）。
3. UI + 性能联动（joint）：只有配置演示与"待接入设计"文案，无步骤打标、无两组件关联、无联合门禁。
4. 实时性能推送：不存在；曲线为"采集结束后的归档曲线（演示）"（L208 图注、接入说明第 5 条）。
5. 定位校验：固定返回"演示匹配 1 个节点"，未调用 mobile-auto 的 `/locators/validate`（L287）。
6. 图像模板匹配：只有元数据与阈值，无图片、无算法（L199 notice）。
7. 设备租约 / 准入 / fencing：UI 上只有 busy / idle；后端租房、fence_counter、心跳、draining 全未实现（schema.sql:172 有 draining，原型无）。
8. 数据库：仅 SQL 草案，未安装 PostgreSQL、未执行；verify-design.cjs 自述不是 PG 解析器（schema.sql:1–6）。
9. 身份与权限：侧栏写死用户 William；无登录、无 RBAC；权限矩阵只是文档建议。
10. 多项目：只有"星河产品"单项目演示数据；project_members / 多项目隔离未在 UI 出现。

## 8. 不一致、含糊与需决策点

| # | 问题 | 类型 | 证据 | 建议 |
| --- | --- | --- | --- | --- |
| 1 | PostgreSQL 依赖未落地：DDL 面向 PG17，但未装库、未跑迁移、无 DAO/ORM 设计 | 不一致（文档 vs 现实） | schema.sql:2–6、verify-design.cjs 自述 | 方案把"建库 + 迁移校验"列为第 0 里程碑 |
| 2 | 身份提供方未定：DDL 只有 `identity_issuer / identity_subject`，UI 无登录 | 决策点 | schema.sql:26–33、侧栏 L53 写死 William | 需选 OIDC/SSO 或明确演示期免登录边界 |
| 3 | Web/iOS 无适配器：任务只能 draft，但原型允许"创建配置草稿"且出现在任务中心 | 含糊 | L159、L187–188 | 验收需区分"草稿数"与"运行数"，草稿不进任何分母 |
| 4 | 实时性能推送缺失，趋势图易被误读为实时 | 缺口 | L208、接入说明第 5 条 | 方案注明"曲线 = 归档；实时通道未设计" |
| 5 | 原型 `status` 单字段混合 state 与 outcome，DB 拆成两列 | 不一致 | L70 vs schema.sql:320–321 | 适配层必须映射，禁止把原型 status 直写 test_runs.state |
| 6 | 原型无 dispatching / finalizing / errored，也无 lifecycle / readiness / mode / availability | 缺口 | §3.1 | 前端需补状态展示与文案，否则 DB 有值 UI 无处显示 |
| 7 | `execution_resources.draining` 与"重新建档须无活动租约"只在 SQL/文档 | 缺口 | schema.sql:172、字典 notes | 设备池需增维护 / draining 态 |
| 8 | 导出报告缺 mobile_perf 原生 series / events / integrity / marks 字段 | 不一致 | L252 vs research.md report.py | 组件原始报告作为证据文件，平台另出汇总，二者都存 artifacts |
| 9 | 导出的 `metricsSummary.sampleCount` 在 not_tested 时写 6，DB 要求 `value` 非空时 `sample_count>0` | 潜在冲突 | L252 vs schema.sql:541、L549 | 缺失指标应 `value=NULL + missing_reason`，另存实际采集数 |
| 10 | 原型"门禁试算"不落 gate_evaluations（无 original / reanalysis 两条） | 缺口 | L210 vs schema.sql:631 | 试算须插入 `mode='reanalysis'` 新行，不得改原行 |
| 11 | 原型设备 busy 由 running 任务推导，DB 由租约决定，可能不一致 | 语义差异 | L112 vs schema.sql:721–723 | UI 状态应以租约为准 |
| 12 | 数据设计页宣称"多端共用"，但 UI/性能页仍以 Android 为默认工作区 | 含糊 | L190 "当前工作区：Android" | 明确"共用模型 + 端侧适配器"的边界文案 |
| 13 | 时间时区：原型写死"2026-10-25（演示）"与固定顶栏日期，DB 用 `timestamptz` | 不一致 | L56、L231 | 前端需真实时区渲染规范 |
| 14 | 权限："项目角色必须由后端检查"是文档要求，DDL 未实现 RLS | 决策点 | database-design.md §8、字典 notes | 明确授权在应用层还是 DB 层 |
| 15 | 保留期 / 容量：文档多处"需用户确定" | 待决策 | database-design.md §7 | 给出 artifacts 保留期与对账周期默认值 |
| 16 | 首期"按项目独占执行节点"与远程访问 / 多节点目标冲突 | 决策点 | 字典 execution_nodes notes | 决定是否引入节点池与项目共享 |
| 17 | 原型未演示真实 UI 层级 dump 格式，报告里是手写 XML 片段 | 未核实 | L292、L231 | 以 mobile-auto `/evidence` 实际输出为准 |
| 18 | research.md 记录的本地项目（moblie-auto / feat/scrcpy-upstream 等）属外部依赖，不在本仓库 | 说明 | research.md "本次核查"表 | 方案需列外部组件版本基线 |

## 9. 附录：定位索引

- 文件清单：index.html（332 行）、database-design.md（237 行）、schema.sql（730 行）、research.md（136 行）、verify-design.cjs（58 行）、preview-overview.png、preview-performance.png。
- index.html 函数 → 行号（便于 Lead 复核）：导航 / 路由 L139–142；context L122；工作台 L164 / plannedOverview L147；项目与应用 L145–146；UI 套件 L189–L190；inspector L191–L198；模板 L199；设备池 L200；性能 L202–L211；基线 L212；报告 L213–L214；接入说明 L215 / L150；数据设计 L124–L137；向导 L144、L151–L159、L240–L249；详情 L226–L231；动作 L250–L252；事件委托 L254–L324；hashchange L328；首次 render L329。
- 状态 / 种子数据：statusMap L70、moduleNames L72、targetCatalog L74、devices L85、seedTasks L93、storageKey L103–L105、templates L106、rules L107、UI 状态 L108、metricData L109、databaseTables L124、databaseFlows L125。
- 建议复核命令（只读）：`node docs/platform-prototype/verify-design.cjs`（做 DDL 与字典一致性自检，不建库）。
- 未核实项汇总：toast 消失毫秒数、数据设计检索是否大小写不敏感、响应式断点具体像素、顶栏日期是否随系统日期变化（源码为固定字符串"2026 年 10 月 25 日"）。

