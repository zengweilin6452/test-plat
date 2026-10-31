# 真机调试页 · 原型 UI 规格与当前实现差异清单

> 只读分析产出。分析对象：
> - 原型：`docs/platform-prototype/index.html`（单文件 HTML，JS 函数渲染；行很长）
> - 实现：`web/src/components/DebugDrawer.tsx`（1280 行，JSX 689–1244）、`web/src/styles/tokens.css`（643–733）、`web/src/pages/UiPage.tsx`（392–620 挂载）
> - 分支：`integration/prototype-alignment`（未提交改动：DebugDrawer.tsx 38 行、tokens.css 4 行，方向是「三栏常驻 / mode-image 选择器」）
> - 权威规格：`docs/plan/prototype-alignment-spec.md` §6.9 + AC-DBG-01..05（下文简称「规格」）
> 本文件不修改任何源码。

---

## 0. 结论摘要

当前实现**已经**把调试工作区从「右侧抽屉」改成了页面内三栏（`.inspector`），并复用了原型的大部分原子类（`.attribute-list` / `.attribute` / `.locator-option` / `.code-block` / `.badge` / `.notice` / `.toolbar`）。用户能感知的「不一致」集中在 4 处：

1. **面板包裹缺失**：原型三栏是「左 `.phone-panel` + 中右两个 `.panel`（带 `.panel-head` 底边分隔线）」；当前三栏只是裸 `.debug-section`（只有一行 h3，无卡片、无分隔线），而且外层还多包了一层页面级 `.panel`（UiPage 的 `<Panel>` + 标题「调试」+ hint），原型没有这层卡片。
2. **定位方式切换器位置与选中样式错了**：原型里它是**独立一行、在 toolbar 之前**，选中态是 `.btn.soft`（浅蓝底），并带一句 muted 提示；当前被塞进 toolbar 末尾、选中态用 `kind="primary"`（实心蓝），提示语缺失。
3. **设备状态徽章被 WS 连接状态顶替**：原型 `badge(deviceState)` 显示 可用/占用中/离线/待授权；当前显示「已连接/连接中/未连接」（WS），设备占用语义完全丢失，`leaseHint` 虽在 UiPage 中计算却**从未渲染**。
4. **图像模式结构不同**：原型是把 inspector 的**第 2、3 列**替换成「框选与保存模板」「重新匹配验证」两个 `.panel.panel-pad.image-form`；当前是隐藏第 2、3 列、改在 inspector **下方**全宽渲染「图像识别（模板库）」。原型的 `.image-stage/.image-overlay/.image-box/.image-preview/.image-coords/.image-form/.image-status` 在当前 CSS 中**一条都没有**。

另有 3 条历史遗留需要 Lead 决策：`.debug-pane` / `body.debug-pane-open` / `.debug-work` 是死 CSS（组件已改页面内嵌），但 DebugDrawer 顶部注释仍写「右侧全高面板」，与规格 §6.9「右侧全高面板是 D1 已批准的布局例外」也对不上；`.phone-panel` / `.tree` / `.tree-row` 三组原型类已定义却未被 JSX 使用。

---

## 1. 原型 native 模式 DOM 骨架（可直接照写 JSX）

来源：`uiPage()` L192 → `inspectorPage()` L203 → `nativeInspectorPage()` L224–229，`phoneMarkup()` L193，`nodeDetails()` L230。

### 1.1 页面级顺序

```html
<!-- #main = context() + uiPage() -->
<div class="context-strip">…</div>            <!-- 原型 context() L124，对应当前 ContextBar -->
<div class="page-heading">                    <!-- heading('UI 自动化', '当前工作区：Android · 复用 pytest 用例、设备调试与失败证据。', btn('+ 新建 UI 任务','new','data-module="ui"','primary')) -->
  <div><h1>UI 自动化</h1><p>当前工作区：Android · 复用 pytest 用例、设备调试与失败证据。</p></div>
  <div class="flex actions"><button class="btn primary">＋ 新建 UI 任务</button></div>
</div>
<div class="tabs">                            <!-- 只有 3 个页签 -->
  <button class="tab"        data-action="ui-tab" data-value="suites"   aria-pressed="false">测试套件</button>
  <button class="tab active" data-action="ui-tab" data-value="inspect"  aria-pressed="true">设备调试</button>
  <button class="tab"        data-action="ui-tab" data-value="templates" aria-pressed="false">图像模板</button>
</div>

<!-- ↓ uiTab==='inspect' → inspectorPage() = switcher + nativeInspectorPage()
     顺序要点：切换器在 toolbar **之前**，不是 toolbar 的成员 -->
<div class="flex wrap mb" role="group" aria-label="定位方式">
  <button class="btn soft" data-action="inspect-mode" data-value="native" aria-pressed="true">原生节点</button>
  <button class="btn"      data-action="inspect-mode" data-value="image"  aria-pressed="false">图像模板</button>
  <span class="small muted">图像流程为本地模拟，不连接设备或匹配服务。</span>   <!-- 演示专属 -->
</div>
```

> 激活态由 `btn(label,'inspect-mode',…, v===inspectMode?'soft':'')`（L120 起）生成 → **`.btn.soft`**（`background:var(--blue-light);border-color:transparent;color:var(--blue)`），未激活是裸 `.btn`。不是 primary。

### 1.2 toolbar（`nativeInspectorPage` L225，一行 `.toolbar`）

```html
<div class="toolbar">
  <select id="inspect-device" aria-label="调试设备">
    <!-- 选项 = devices.filter(d => ['idle','busy'].includes(deviceState(d)))；文案 name / os -->
    <option value="d2">Pixel 7 / Android 14</option>
  </select>

  <span class="badge green"><i class="dot"></i>可用</span>
  <!-- badge(deviceState(d))：idle→green 可用 / busy→blue 占用中 /
       offline→gray 离线 / unauthorized→amber 待授权（statusMap L72） -->

  <span class="spacer"></span>

  <label class="flex small">
    <input type="checkbox" id="direct-control" checked disabled>
    直接控制（演示）
  </label>                                      <!-- 演示专属，不应照搬；disabled = !ready || frozen -->

  <button class="btn primary">                  <!-- frozen 时：class="btn"（去掉 primary） -->
    <svg class="icon">freeze</svg> 采集检查      <!-- frozen 时：play 图标 + 文案「恢复预览」 -->
  </button>
</div>
```

按钮顺序固定为：**select → 状态徽章 → spacer → 直接控制复选框 → 采集/恢复**。整个 toolbar 只有 1 个按钮——冻结是这同一个按钮的切换态，不是另外加一个按钮。

### 1.3 notice（L226，仅设备非 idle 时出现）

```html
<div class="notice mb">
  <svg class="icon">alert</svg>
  <span>设备正在执行任务，当前仅可观察示意画面；采集与控制受到设备租约限制。</span>
</div>
```

### 1.4 `.inspector` 三栏（L227–229）

```html
<div class="inspector">
  <!-- ── 第 1 栏：.phone-panel（灰底圆角面板，注意不是 .panel）── -->
  <section class="phone-panel">
    <div class="between">
      <span class="badge amber"><i class="dot"></i>冻结快照</span>   <!-- 未冻结：badge blue 预览示意 -->
      <span class="small muted">非真实投屏</span>
    </div>

    <div class="phone">                        <!-- 见 1.5 -->
      <div class="phone-camera"></div>
      …
    </div>

    <div class="between small muted">
      <span>快照 SNAP-DEMO-01</span>            <!-- 未冻结「设备画面示意」；image 模式「快照 SNAP-IMAGE-{n}」 -->
      <span>1080 × 2400</span>                  <!-- d.res -->
    </div>

    <div class="flex mt" style="justify-content:center">
      <button class="btn small" data-action="phone-key" data-key="返回" disabled>返回</button>
      <button class="btn small" data-action="phone-key" data-key="主屏" disabled>主屏</button>
    </div>                                     <!-- 演示专属，不应照搬 -->
  </section>

  <!-- ── 第 2 栏：.panel + .panel-head + .tree + 底部提示行 ── -->
  <section class="panel">
    <div class="panel-head">
      <h2>UI 层级树</h2>
      <span class="small muted">3 个节点示例</span>   <!-- 演示专属；真实版应为节点数 -->
    </div>
    <div class="tree">
      <div class="tree-row">⌄ android.widget.FrameLayout</div>              <!-- 非叶子用 div，不可点 -->
      <div class="tree-row level1">⌄ android.widget.LinearLayout</div>
      <button class="tree-row level2 selected" data-action="pick-node" data-node="checkout">Button · 去结算</button>
      <button class="tree-row level2" data-action="pick-node" data-node="title">TextView · 星河生活</button>
      <button class="tree-row level2" data-action="pick-node" data-node="product">TextView · 轻盈随行杯</button>
      <!-- 未冻结时 level2 按钮 disabled；.selected 仅在 selectedNode===id && frozen 时加 -->
    </div>
    <div style="padding:17px;border-top:1px solid var(--line)" class="small muted">
      已绑定同一次冻结快照，点击节点查看定位描述。   <!-- 未冻结：「先点击「采集检查」，冻结画面与 UI 树。」 -->
    </div>
  </section>

  <!-- ── 第 3 栏：.panel + .panel-head + .attribute-list（其余内容都在 attribute-list 内）── -->
  <section class="panel">
    <div class="panel-head">
      <h2>元素与定位描述</h2>
      <span class="badge gray">原生定位</span>       <!-- 手写 span，无 dot -->
    </div>
    <div class="attribute-list">
      <!-- 冻结且选中节点时（nodeDetails()）： -->
      <div class="attribute"><span>text</span><span>去结算</span></div>
      <div class="attribute"><span>class</span><span class="mono">android.widget.Button</span></div>
      <div class="attribute"><span>clickable</span><span>true</span></div>

      <h3 style="margin:20px 0 10px;font-size:12px">定位候选</h3>
      <div class="locator-option active">
        <div class="between"><b>resource-id</b><span class="badge green">优先候选</span></div>
        <code>com.example.xinghe:id/checkout</code>
      </div>
      <div class="locator-option">
        <div class="between"><b>text</b><span class="small text-amber">文案变动会失效</span></div>
        <code>去结算</code>
      </div>
      <pre class="code-block" id="locator-expression">Target(Locator.RESOURCE_ID, "com.example.xinghe:id/checkout")</pre>
      <div class="flex wrap">
        <button class="btn primary small">验证定位</button>
        <button class="btn small"><svg class="icon">copy</svg> 复制表达式</button>
      </div>
      <p id="locator-result" class="small muted mt" role="status">验证当前演示快照中的节点匹配。</p>

      <!-- 未冻结 / 未选中时（empty()）：<div class="attribute-list"><div class="empty">
           <svg class="icon">search</svg><strong>等待拾取</strong>冻结快照后，点击画面按钮或树节点。</div></div> -->
    </div>
  </section>
</div>
```

照写时最容易漏的点：
- 属性行只有 **3 行**：`text` / `class` / `clickable`；`class` 用 `.mono`，`clickable` 是布尔文本。
- 「定位候选」标题内联 `margin:20px 0 10px;font-size:12px`。
- `.locator-option` 是 **`div`**，内含 `.between` 行 + `<code>`；第一项固定 `.active`，第二项不 active。
- 「验证定位」是 `btn primary small`，「复制表达式」是 `btn small`，两者与 `pre.code-block` 同在第 3 栏，**下方紧跟 `p#locator-result`（role=status）**。
- 空态图标是 `search`（`empty()` L123 固定用 search），不是 check。

### 1.5 `phoneMarkup()`（L193）结构

```html
<div class="phone">
  <div class="phone-camera"></div>
  <div class="phone-top"><b>14:32</b><span>▮▮▮  Wi-Fi  ▰</span></div>
  <div class="phone-app">
    <div class="phone-logo">星河生活</div>
    <p>把好物，带进日常。</p>
    <div class="phone-banner"><b>发现生活的小美好</b><p style="margin-top:8px">本周精选 / 秋日上新</p></div>
    <div class="phone-product"><div class="phone-product-icon">◒</div><div><strong>轻盈随行杯</strong><small>暖白 / 350 ml</small></div><span style="margin-left:auto;font-size:10px">¥ 89</span></div>
    <div class="phone-product">…</div>
    <button class="phone-cta selected" data-action="pick-node" data-node="checkout">去结算</button>
    <div class="phone-nav"><span>首页</span><span>分类</span><span style="color:#526fbd">购物袋</span><span>我的</span></div>
  </div>
  <div class="phone-bottom"></div>
</div>
```

这是**假手机画面（静态电商页）**，`.phone-cta` 点击 = 模拟点击（`toast('已模拟点击；没有向真实设备发送操作。')`）。真实实现必须换成 vendor 帧 canvas，**只保留手机外壳（`.phone` + `.phone-camera`），删掉 phone-app 全部内容**——当前实现正是这么做的，这一条已经对齐。

---

## 2. 原型 image 模式：slice 切割 + `imagePanel()`，以及 `templatesPage` 归属

### 2.1 切割方式（`inspectorPage()` L203，原文一行）

```js
function inspectorPage(){
  const html = nativeInspectorPage(), switcher = /* 定位方式切换器 */ '';
  if (inspectMode === 'native') return switcher + html;
  const cut = html.indexOf('<section class="panel"><div class="panel-head"><h2>UI 层级树');
  return switcher + html.slice(0, cut) + imagePanel() + '</div>'
}
```

- 锚点是**第 2 栏（UI 层级树）section 的起始字符串**。
- `html.slice(0, cut)` = 切换器之后的 toolbar + notice + `<div class="inspector">` + 完整第 1 栏 `<section class="phone-panel">…</section>`。
- `imagePanel()` 返回**两个并列的 `<section class="panel panel-pad image-form">`**，因此它们自然成为 `.inspector` 的 grid 第 2、3 列。
- 末尾补 `'</div>'` 关闭 `.inspector`（原生 HTML 里那个收尾 `</div>` 已被切掉）。

**结论：image 模式仍然是 3 列网格，不是隐藏列、不是全宽。**
`280px` = 手机画面（含 `.image-stage` 框选叠层）｜`minmax(210px,1fr)` = 框选与保存模板｜`minmax(260px,1.1fr)` = 重新匹配验证。

第 1 栏在 image 模式下由 `inspectorPhone()`（L202）换成：

```html
<div class="image-stage">                     <!-- width:226px; margin:15px auto; touch-action:none -->
  <div class="phone">…phoneMarkup(false)…</div>   <!-- 无 data-action，phone-cta disabled -->
  <div class="image-overlay" id="image-selection" aria-label="冻结快照框选画布；也可使用右侧坐标输入">
    <!-- inset:6px; border-radius:23px; overflow:hidden; cursor:crosshair -->
    <div class="image-box" style="left:x%;top:y%;width:w%;height:h%"><span>选区</span></div>
    <!-- 匹配后：class="image-box matched" + <span>匹配</span> -->
  </div>
</div>
```

### 2.2 第 2 栏：框选与保存模板（`imagePanel()` L204 第一段）

```html
<section class="panel panel-pad image-form">          <!-- display:grid; gap:12px -->
  <h2>框选与保存模板</h2>                              <!-- 没有 .panel-head，直接 h2 -->
  <p class="small muted">在冻结画面上拖动框选，或填写坐标后应用。 坐标单位：设备像素，范围 1080 × 2400。</p>
  <!-- 未 ready：「先选择空闲设备并点击「采集检查」。」 -->
  <fieldset disabled>                                  <!-- ready 时无 disabled -->
    <div class="image-coords">                          <!-- grid 2 列, gap 8 -->
      <label class="field"><span>X</span><input id="image-coord-0" type="number" min="0" value="0"></label>
      <label class="field"><span>Y</span><input id="image-coord-1" type="number" min="0" value="0"></label>
      <label class="field"><span>宽度</span><input id="image-coord-2" type="number" min="1" value="0"></label>
      <label class="field"><span>高度</span><input id="image-coord-3" type="number" min="1" value="0"></label>
    </div>
    <button class="btn small mt">应用坐标选区</button>
  </fieldset>
  <p class="small muted">选区 [X, Y, 宽度, 高度]：[0, 0, 0, 0]</p>   <!-- 未框选：「尚未框选区域」 -->
  <div id="image-region-preview" class="image-preview" aria-label="选区预览">
    <!-- height:110px; overflow:hidden; border:1px solid var(--line); border-radius:7px; background:#eef2f8 -->
    <!-- 无选区：<p class="muted small" style="padding:16px">选区预览会显示在这里</p> -->
  </div>
  <label class="field"><span>模板逻辑名</span><input id="image-name" value="home/checkout" maxlength="80" placeholder="home/checkout"></label>
  <p class="small muted">同名保存会新增版本，保留旧版本。本地保存示意区域，不生成真实 PNG。</p>
  <button class="btn primary" disabled>保存模板版本</button>   <!-- !ready || !region 时 disabled -->
</section>
```

### 2.3 第 3 栏：重新匹配验证（`imagePanel()` 第二段）

```html
<section class="panel panel-pad image-form">
  <h2>重新匹配验证</h2>
  <label class="field"><span>已保存的模板版本</span>
    <select id="image-template">
      <option value="-1">选择模板</option>
      <option value="0">home/checkout / v1</option>
    </select>
  </label>
  <p class="small muted">来源：演示设备 · 预置演示；版本 v1</p>
  <label class="field"><span>匹配阈值（0.10 至 1.00）</span><input id="image-threshold" type="number" min=".1" max="1" step=".01" value="0.90"></label>
  <p id="image-threshold-error" class="small text-red"></p>     <!-- 无效时才有文案 -->
  <label class="field"><span>新画面模拟场景</span>               <!-- 演示专属 -->
    <select id="image-outcome">
      <option value="present">目标存在，模拟分数 0.96</option>
      <option value="absent">目标未出现，模拟分数 0.42</option>
    </select>
  </label>
  <button class="btn primary" disabled>模拟采集新画面并重新匹配</button>   <!-- 演示专属 -->
  <div class="image-status small" role="status">                <!-- min-height:48px -->
    尚未验证。修改模板、选区或阈值后需重新验证。
  </div>
  <pre class="code-block" id="locator-expression">Target(Locator.IMAGE, "home/checkout", confidence=0.9, region=[x,y,w,h])</pre>
  <button class="btn small" disabled>复制 IMAGE 表达式</button>
  <p class="small muted">表达式按逻辑名解析模板。此处可选择历史版本查看，复制不锁定版本；正式运行以模板清单为准。</p>
</section>
```

### 2.4 `templatesPage()`（L231）归属：**独立页签，不属于 inspector**

- 归属：`uiPage()` 的 `uiTab` 三选一（`suites` / `inspect` / `templates`），`templates` → `templatesPage()`。
- 内容：`.notice.blue.mb`（说明「共享本地演示版本，不生成真实 PNG」）+ 一个 `.panel`：
  - `.panel-head`：`<h2>图像模板库</h2>` + `btn('+ 新建模板演示','template-new','','small')`。
  - 表格列：`逻辑名 / 模板版本 / 匹配阈值 / 来源 / 操作`；来源列固定「演示冻结快照」；操作列 `link-btn`「查看定位描述」。
- 关键：**模板「登记/保存」不在这个页签里**，只在调试页 image 模式（2.2）里做；这个页签只读列表 +「新建模板演示」会切回 `uiTab='inspect'; inspectMode='image'`。
- 当前实现正好相反：`模板` 页签里放了完整登记表单（逻辑名 / 快照 id / 裁剪四值 / 期望旧摘要），调试页下方又有「图像识别（模板库）」列表 + 登记表单（重复两份）；模板列表字段是 `逻辑名 / 版本 id / 摘要`（无阈值、无来源——真实数据也没有这两个字段，见 4.7）。

---

## 3. 原型相关 CSS 关键声明（对照当前 `tokens.css`）

原型 `<style>` 集中在 L14（inspector/phone/tree/attribute/locator）、L46（image-*）、L11–13（原子类）。当前实现对应 `web/src/styles/tokens.css:643–733`（另复用 198–210、272–275、329 等早期对齐段）。

| 选择器 | 原型声明 | 当前实现 | 判定 |
| --- | --- | --- | --- |
| `.inspector` | `display:grid; grid-template-columns:280px minmax(210px,1fr) minmax(260px,1.1fr); gap:18px; align-items:start` | `minmax(240px,300px) minmax(200px,1fr) minmax(250px,1.1fr)`，gap `--space-8`(18px)，start | **差异**：第 1 列由固定 280 变弹性 240–300，2/3 列下限各下调 10px |
| `.inspector` 断点 | 无（只有全局 1000/760 影响其他块） | 1100→2 列、820→1 列 | 追加（可保留） |
| `.phone-panel` | `padding:16px; background:#eef2f8; border-radius:12px; border:1px solid #dfe6f0` | 同左，**但 JSX 从未使用该 class** | **差异**：类存在却未使用 |
| `.phone-stage`（当前独有，替代 phone-panel） | — | `background:#eef2f8; border:1px solid #dfe6f0; display:flex; justify-content:center; padding:16px 8px` + 继承 `.debug-stage` 的 `border-radius:var(--radius-sm)`(8px)、`min-height:340px`、`background:#0b0f14`（被覆盖） | **差异**：圆角 8px（原型 12px）、左右内边距 8px（原型 16px）、多 min-height 340 |
| `.phone` | `width:226px; margin:15px auto; border:6px solid #26354e; border-radius:29px; background:white; box-shadow:0 12px 25px #1c305b15; overflow:hidden; position:relative; min-height:438px` | `width:226px; border:6px solid #26354e; border-radius:29px; background:#0b0f14; box-shadow:…; overflow:hidden; position:relative; padding-top:12px`（`.phone-stage .phone`） | **差异**：无 `margin:15px auto`、无 `min-height:438px`、底色白→深（因内嵌 canvas） |
| `.phone-camera` | `36×9; border-radius:7px; background:#26354e; position:absolute; left:89px; top:5px` | 同尺寸 + `border:1px solid #3c4c64; left:50%; translateX(-50%); top:4px; z-index:2` | 差异（居中算法 vs 固定 89px；视觉近似） |
| `.tree` | `padding:14px 12px; font-family:Consolas,monospace; font-size:10px` | 同左 **+ `max-height:320px; overflow:auto`**；且 JSX 未使用 | **差异**：加了限高；类未使用 |
| `.tree-row` | `padding:8px; border-radius:5px; white-space:nowrap; border:0; background:none; width:100%; text-align:left; color:#7687a2`；`.level1 padding-left:20px`、`.level2 padding-left:34px`；`.selected{background:#edf1ff;color:var(--blue)}`；`:disabled{opacity:.5}` | 定义齐全，但 JSX 用 `.link-btn` + 内联 `paddingLeft: depth?16:0` | **差异**：原型缩进/选中底色/禁用态全部未生效 |
| `.attribute-list` | `padding:17px` | 同 | 一致 |
| `.attribute` | `display:flex; justify-content:space-between; gap:16px; padding:7px 0; border-bottom:1px solid #f2f4f8; font-size:11px`；`span:first-child{color:var(--muted)}` | 同 | 一致 |
| `.locator-option` | `border:1px solid #e2e8f3; border-radius:7px; padding:10px 12px; margin:10px 0; font-size:11px` | 同 **+ `width:100%`**（JSX 用作 button 的必要补充） | 一致 |
| `.locator-option.active` | `background:#f7f9ff; border-color:#b4c2fc` | `border-color:var(--blue)`（**无背景**） | **差异** |
| `.locator-option code` | `font-size:10px; display:block; margin-top:5px; overflow-wrap:anywhere` | 未单独定义（落到全局 `code/pre`，字号继承 11px，无上边距） | 差异（小） |
| `.code-block` | `background:#f6f8fc; border:1px solid #e5eaf3; border-radius:7px; padding:16px; color:#516383; font-size:11px; line-height:1.85; white-space:pre-wrap; word-break:break-word; margin:12px 0` | `tokens.css:329` 逐项等价（`--code-bg/--code-ink/--space-7/--space-5`） | 一致 |
| `.panel` | `background:#fff; border:1px solid var(--line); border-radius:12px; min-width:0` | 同 | 一致 |
| `.panel-head` | `padding:19px 21px; display:flex; align-items:center; justify-content:space-between; gap:14px; border-bottom:1px solid var(--line)` | 同 | 一致 |
| `.panel-head h2` | `font-size:14px` | `font-size:var(--fs-sm)` = **12px** | **差异**（三栏若改用 panel-head，标题会比原型小 2px） |
| `.panel-pad` | `padding:22px` | `var(--space-10)` = 22px | 一致 |
| `.toolbar` | `display:flex; align-items:center; gap:10px; margin-bottom:18px; flex-wrap:wrap` | 同（`--space-4`/`--space-8`） | 一致 |
| `.badge` / `.badge.green/red/blue/amber/gray` / `.dot` | 见 L11/L14 | 同 | 一致 |
| `.notice` / `.blue/green/red` | L13 | 同 | 一致 |
| `.empty` | `padding:45px 20px; text-align:center; color:#8a95a7; font-size:13px`；icon 30px `#bcc6d7`；`strong` 块级 | 同 | 一致 |
| `.debug-section + header h3`（当前独有） | — | `font-size:var(--fs-md)`=13px；`margin-bottom:var(--space-4)` | 替代了原型的 `.panel` + `.panel-head h2`(14px) + 分隔线 |
| `.debug-tree`（当前独有） | — | `max-height:400px; overflow:auto; border:1px solid var(--line); border-radius:8px; padding:10px 12px; font-size:13px` | 自造容器，绕开了 `.tree/.tree-row` |
| `.debug-frame canvas`（当前独有） | — | `max-width:100%; max-height:74vh` | 真实帧约束（保留） |
| `.image-stage` | `position:relative; width:226px; margin:15px auto; touch-action:none` | **无** | **未实现** |
| `.image-overlay` | `position:absolute; inset:6px; border-radius:23px; overflow:hidden; cursor:crosshair` | **无**（当前用 `.debug-box` 叠层近似） | **未实现** |
| `.image-box` / `.matched` / `span` | `border:2px dashed #b07000; background:#e9ac2520`；matched `2px solid var(--green)`；标签白底 10px | `.debug-box`：`2px solid #34d399`、`.pick` 橙色虚线；标签彩色底 | 差异（配色不同，功能等价） |
| `.image-preview` | `height:110px; overflow:hidden; border:1px solid var(--line); border-radius:7px; position:relative; background:#eef2f8` | **无** | **未实现** |
| `.image-coords` | `display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px` | 近似 `.debug-form`：2 列、gap `--space-4/--space-5` | 近似 |
| `.image-form` | `display:grid; gap:12px`（表单竖排） | **无**（当前表单散在 section 里） | **未实现** |
| `.image-status` | `min-height:48px` | **无** | **未实现** |
| `.field` | `display:flex; flex-direction:column; gap:7px; font-size:12px` | `tokens.css:573` `.field { display:grid; gap:var(--space-2); min-width:0 }` + 子规则（`.field input{width:100%}` 等） | 近似（display 等价、gap 6 vs 7、缺 `font-size:12px`） |
| `.debug-pane` / `.debug-pane-head/body` / `body.debug-pane-open` / `.debug-work` | — | 当前独有，**JSX 全部未使用** | **死代码** |
| `.phone-panel img` | — | 当前独有，未使用 | **死代码** |

---

## 4. 当前实现 vs 原型：逐项差异

当前 DOM 根（`DebugDrawer.tsx:692`）：

```
<Panel>（UiPage.tsx:413，.panel 卡片）
  <PanelHead title="调试" hint="调试会话与自动运行竞争同一资源租约；切页签保持会话，关闭工作区才释放" />
  <div class="debug-workspace">
    <div class="toolbar mb">…</div>
    <div class="debug-workspace-body">
      Notice(wsNotice) / Notice(closeError) / Empty×2
      <div class="inspector"> 3 个裸 <div> 列
      <section class="debug-section">图像识别（模板库）</section>
    </div>
    <footer class="debug-pane-foot">…关闭会话</footer>
  </div>
</Panel>
```

### 4.1 结构层级与卡片/面板包裹 — **主要不一致**

| # | 原型 | 当前 | 类型 |
| --- | --- | --- | --- |
| 1 | 调试内容直接挂在 `#main`（heading + tabs + switcher + toolbar + notice + inspector） | 外面多一层 `.panel`（UiPage）并带 `.panel-head` 标题「调试」+ hint | 结构差异 |
| 2 | 第 2、3 栏是 `.panel`（白底 + 边框 + 12px 圆角 + `.panel-head` 底边线） | 三列都是裸 `.debug-section`（只有 h3 行 + 内容，无卡片、无分隔线） | **结构差异（视觉最明显）** |
| 3 | 第 1 栏是 `.phone-panel`（灰底 + 边框 + 12px 圆角 + 16px 内边距） | `.debug-stage.phone-stage` 近似灰底，但圆角 8px、左右 padding 8px | 结构差异（近） |
| 4 | inspector 是页面级唯一网格，无额外 body 容器 | `.debug-workspace-body`（grid, gap 20px）再包一层，「图像识别」section 与三栏之间恒有 20px 间隔 | 结构差异（小） |
| 5 | 无关闭/返回 footer | `footer.debug-pane-foot`：hint「关闭面板会同时关闭调试会话并释放资源租约」+「关闭会话」 | 真实语义（保留） |
| 6 | 标题用 `h2`（panel-head，14px） | 用 `h3`（`.debug-section > header`，13px） | 差异（字号/层级） |

### 4.2 列宽与三栏内容分布

| 列 | 原型 | 当前 |
| --- | --- | --- |
| 1 | `280px` 固定：只放 `.phone-panel`（画面 + 快照/分辨率 + 返回/主屏） | `minmax(240px,300px)`：放**两个** section ——「实时预览」+「定位结果」（定位结果表在原型里没有对应区块） |
| 2 | `minmax(210px,1fr)`：只放 UI 层级树 | 同宽模型：只放 UI 层级树 |
| 3 | `minmax(260px,1.1fr)`：元素与定位描述（含定位候选/表达式/验证按钮/结果行） | 同宽模型：元素与定位描述 + **定位验证表单**（定位方式 select / 定位值 input / 阈值 / 验证定位）——原型是单表达式「验证定位」，无表单 |
| 图像识别 | image 模式下成为第 2、3 列 | 全宽 section 放在 inspector 外面（三栏下方） |

### 4.3 toolbar 控件顺序与语义

| 位置 | 原型 | 当前 | 类型 |
| --- | --- | --- | --- |
| 切换器位置 | **toolbar 之前**独立一行（`.flex.wrap.mb[role=group]`），后接 muted 提示 | **toolbar 内**、spacer 之后 | 结构差异 |
| 1 | `select#inspect-device`，选项含 idle+busy，文案 name / os | 同（name / os 已对齐），但 devices 只传 `status==='ready' && !busy`（UiPage:179-181），**占用中设备不出现在下拉里** | 真实数据差异 |
| 2 | `badge(deviceState)` → 可用(green)/占用中(blue)/离线(gray)/待授权(amber) | `Badge tone={wsTone}` → 已连接(green)/连接中(blue)/未连接(gray)；另加一个 `Badge amber 画面已冻结` | **真实数据差异（徽章语义被替换）** |
| 3 | `span.spacer` | 同 | 一致 |
| 4 | `label.flex.small` + 复选框「直接控制（演示）」（`!ready\|\|frozen` disabled） | **无** | 原型演示专属 |
| 5 | 单按钮：未冻结 = `btn primary` + freeze 图标 +「采集检查」；冻结 = `btn` + play 图标 +「恢复预览」 | **两个按钮**：`Button small 恢复实时`（仅冻结时出现，default kind）+ `Button primary small icon="image" 采集检查`（恒在，文案「采集中…」） | 差异（按钮合并/顺序） |
| 6 | （无） | `Button small 返回设备池` | 真实语义补充（可保留，建议移到末尾或 footer） |
| 尾部顺序 | 采集检查在最后 | 恢复实时 → 定位方式组 → 返回设备池 → 采集检查 | 差异 |

补充：原型「采集检查」图标是 `freeze`（Icon 组件已有 `freeze` / `play`），当前用 `image`，语义不贴。

### 4.4 左栏手机面板

| 位置 | 原型 | 当前 | 类型 |
| --- | --- | --- | --- |
| 顶部 `.between` | `badge`：冻结→amber「冻结快照」/ 未冻结→blue「预览示意」+ `span.small.muted`「非真实投屏」 | 无徽章；顶部是 `.debug-section > header`：h3「实时预览」+ muted 文本（`画面已冻结 · snapshot xxx` / `命中 N 个` / `拖拽画面可框选模板区域`） | 结构差异 |
| 画面 | `.phone`（226px，白底假手机画面） | `.phone` 深底 + `.debug-frame` 内 canvas 真实帧（`frameSize` 为 null 时 `display:none`，另显示 `.debug-stage-empty`：「等待设备画面…」/「画面尚未连接（未连接）」） | 保留（真实帧） |
| 底部 `.between` | 快照标识（「快照 SNAP-DEMO-01」/ 未冻结「设备画面示意」）+ 分辨率 `1080 × 2400` | **无**；快照 id 只在 header 文本里；分辨率（`frameSize.w × frameSize.h` 已有）**未展示** | 差异（缺信息） |
| 手机按键 | `btn small`「返回」「主屏」 | **无** | 原型演示专属 |
| 图例 | 无 | `.debug-kv`：「绿框 = 最近一次定位命中」「橙框 = 框选区域（用于新建模板）」 | 真实补充（可保留） |
| 错误 | 无 | `Notice red`「会话详情获取失败（code）」+ `viewer_unavailable` / `debug_session_not_active` 补充提示 | 真实语义（保留） |

### 4.5 UI 层级树（第 2 栏）

| 位置 | 原型 | 当前 | 类型 |
| --- | --- | --- | --- |
| 容器 | `.panel` + `.panel-head` + `.tree` + 底部 `padding:17px;border-top` 提示行 | `.debug-section` header + `.debug-tree`；无底部提示行 | 结构差异 |
| head 右侧 | `span.small.muted`「3 个节点示例」（演示） | `span.small.muted`（snapshot id /「先点「采集检查」冻结画面与 UI 树」），**且下方再重复一行** `div.muted.small.mono`「snapshot xxx」 | 差异（重复信息） |
| 行样式 | `.tree-row`（8px padding、`level1`/`level2` 缩进 20/34px、`.selected` 浅蓝底、`:disabled` 0.5 透明、mono 10px） | `TreeBranch`：`div[style paddingLeft: depth?16:0]` + `link-btn` 折叠三角 + `link-btn.mono` 节点名 + `muted` bounds；**无选中态高亮**（`selected` state 不参与 class） | **差异（缩进/选中态）** |
| 空态文案 | 「先点击「采集检查」，冻结画面与 UI 树。」（底部提示行） | `.debug-tree` 内 `span.muted`：「点「采集快照」后展示 vendor 采集的层级树（POST /snapshots → GET /tree）。」 | 差异（动作名不一致） |
| 无树 | 不存在 | 「该快照没有 UI 树（vendor 未采集或设备不支持）。」 | 真实语义 |
| 限高 | 无 | `.debug-tree` `max-height:400px`（`.tree` 另定 320px） | 差异（可保留，真实树可达数百节点） |

> 文案不一致：toolbar 按钮叫「采集检查」，树空态/下方提示（L937、L1164）叫「采集快照」，同一动作两个名字。

### 4.6 元素与定位描述 / 定位验证（第 3 栏）

| 位置 | 原型 | 当前 | 类型 |
| --- | --- | --- | --- |
| 卡片 | `.panel` + `.panel-head`（h2 14px + `badge gray`「原生定位」） | `.debug-section` header（h3 13px + 手写 `<span class="badge gray">`） | 差异 |
| 属性行 | text / class / clickable（3 行） | text / resource-id / class / clickable / bounds（5 行，class 与 bounds 用 mono） | 真实数据差异（更完整，保留） |
| 空态 | `empty()`：icon=**search**，「等待拾取」「冻结快照后，点击画面按钮或树节点。」 | `Empty` icon=**check**，「等待拾取」「在层级树中点击节点，这里显示它的属性与定位候选。」；且 `Empty` 被塞进 `.attribute-list`（17px）+ `.empty`（45px）双层内边距 | 差异（图标/文案/内边距） |
| 定位候选标题 | `h3 style="margin:20px 0 10px;font-size:12px"` | `h3 style={{margin:'14px 0 4px',fontSize:12}}` | 差异（小） |
| locator-option | `div`；resource-id 项恒 `.active`（浅蓝底）；text 项带 `.small.text-amber`「文案变动会失效」 | `button`（可点切换 locatorBy），active 由当前 locatorBy 决定，**`.active` 只有边框无背景** | 语义改进 + 样式差异 |
| 表达式 + 按钮 | `pre.code-block#locator-expression` 后紧跟 `btn primary small`「验证定位」+ `btn small`「复制表达式」 | `pre.code-block` 后只有 `LinkButton`「复制表达式」；「验证定位」在下方独立区块（`primary small` + check 图标） | 差异（顺序/位置） |
| 验证输入 | 无（用选中节点的表达式直接验证） | 有：选中节点摘要行 + `debug-form`（定位方式 6 选项 / 定位值 input）+ 图像时「阈值 0.10-1.00」input | 真实能力（保留） |
| 验证结果 | `p#locator-result.small.muted.mt[role=status]`，就地一行文本 | 左栏单独「定位结果」section：header（尚未验证 / 唯一匹配 / 零匹配 / 多匹配 N 个 + 定位快照 id）+ 6 列表格（# / x / y / 宽 / 高 / 置信度）或 muted 文本 | 真实数据差异（保留，但位置与原型不同） |
| 结果文案 | 「验证当前演示快照中的节点匹配。」 | 「在右栏选节点或填表达式后点「验证定位」，命中框会画在画面上。」 | 差异（小） |

### 4.7 图像模式 / 模板

| 项 | 原型 | 当前 |
| --- | --- | --- |
| 切入方式 | 切换器「图像模板」→ `inspectMode='image'` | 同（按钮 kind 从 soft 改 primary；位置在 toolbar） |
| inspector 形态 | 仍是 3 栏；第 2/3 栏换成「框选与保存模板」「重新匹配验证」 | `.inspector.mode-image > div:nth-child(2/3){display:none}` → 只剩第 1 栏（实时预览 + 定位结果），下方全宽「图像识别（模板库）」 |
| 框选 | 画面 `.image-stage > .image-overlay` + `.image-box`（虚线橙框/绿框）；坐标四输入（`.image-coords` 2×2）+「应用坐标选区」+ `.image-preview` 110px 裁片预览 | 画面 `.debug-box.pick` 拖拽框选（mouse 事件，8×8 最小）；`.debug-form` 里 x/y/宽/高 四输入（编辑即改 region）+「模板逻辑名（.png，POSIX 相对路径）」+「从框选登记模板」「清除框选」；**无裁片预览、无「应用坐标选区」** |
| 模板保存 | 「保存模板版本」（`primary`，`!ready\|\|!region` disabled） | 「从框选登记模板」（`primary small`，要求 snapshotId + region + newLogical）+「清除框选」；服务端裁剪（vendor 不收浏览器图），与规格 §6.9 一致 |
| 匹配 | 第 3 栏「重新匹配验证」：模板 select + 阈值 number（0.10–1.00，step .01）+「模拟采集新画面并重新匹配」+ `.image-status`（score/threshold/SNAP-IMAGE-n）+ IMAGE 表达式 +「复制 IMAGE 表达式」 | 两个入口：① 第 3 栏「定位验证」（定位方式=图像模板 + 定位值=逻辑名 + 阈值）→ `/templates/validate`；②「图像识别」表格每行「图像匹配」按钮。结果落左栏「定位结果」表 + 画面绿框 |
| 模板清单位置 | 独立「图像模板」页签（只读表） | 调试页「图像识别（模板库）」section（表：逻辑名 / 版本 / 摘要 / 操作-图像匹配 + 刷新）+ `模板` 页签的登记表单（**清单与登记各出现两次**） |
| 原型的图像 CSS | `.image-stage/-overlay/-box/-preview/-coords/-form/-status` 全套 | **一条都没有**（只用 `.debug-box` 近似命中框） |

### 4.8 文案对照表（标题与空态）

| 语义 | 原型 | 当前 |
| --- | --- | --- |
| 页头标题/描述 | 「UI 自动化」/「当前工作区：Android · 复用 pytest 用例、设备调试与失败证据。」 | 「UI 自动化」/「用例、套件与执行记录：断言结果可追溯到报告与现场证据」 |
| 页签 | 测试套件 / 设备调试 / 图像模板（3 个） | 执行记录 / 用例套件 / 用例 / 调试 / 模板（5 个） |
| 第 1 栏标题 | 无 h2（只有徽章 + 提示行） | 「实时预览」 |
| 第 2 栏标题 | 「UI 层级树」+「3 个节点示例」 | 「UI 层级树」+ snapshot/提示 |
| 第 3 栏标题 | 「元素与定位描述」+ 原生定位 | 同 |
| 新增区块 | 无 | 「定位结果」「图像识别（模板库）」「定位验证」 |
| 树空态 | 先点击「采集检查」，冻结画面与 UI 树。 | 点「采集快照」后展示 vendor 采集的层级树（POST /snapshots → GET /tree）。 |
| 元素空态 | 等待拾取 / 冻结快照后，点击画面按钮或树节点。 | 等待拾取 / 在层级树中点击节点，这里显示它的属性与定位候选。 |
| 会话空态 | 原型无此状态 | 「尚未建立调试会话」/「POST /api/v1/debug-sessions 建立会话后，三栏会填充实时预览与 UI 树。」或「当前没有 ready 且空闲的设备…」；「正在创建调试会话」/「正在请求 POST /api/v1/debug-sessions」 |
| 设备忙提示 | 「设备正在执行任务，当前仅可观察示意画面；采集与控制受到设备租约限制。」 | 无（busy 设备根本不进下拉） |
| 演示提示 | 「图像流程为本地模拟，不连接设备或匹配服务。」「非真实投屏」 | 无（改成真实状态文本） |

### 4.9 分类：真实数据差异 vs 原型演示专属（不应照搬）

**A. 真实数据差异（应保留真实语义，只在展示形态上向原型靠）**

1. 设备状态徽章：原型用 `deviceState`（idle/busy/offline/unauthorized）；当前用 WS 连接状态。真实可用的语义在 `ResourceRecord.status + busy + lease`（`RESOURCE_STATUS_MAP`：ready=green 可用 / offline=gray 离线 / unauthorized=amber 待授权 / draining=blue；busy 需由 `ready && busy` 推导为「占用中」blue，参考 `DevicesPage` 的 `deviceState()` L91-95）。
2. `DebugTarget.leaseHint`（DebugDrawer L56、UiPage L636-641）已计算「运行 xxx 占用中」/「调试会话占用中」，但**从未渲染**；`toWorkspaceTarget` 还把它写成 `null`（L88），切换设备后提示丢失。
3. 原型「选项含 idle+busy 设备、busy 只读观察」——规格 §6.9 明确「busy 设备只读预览，不新建调试会话」，所以当前**只列空闲设备是可接受的**；但应在 toolbar/空态显式说明「占用中设备不在此列表」，而不是让徽章显示 WS 状态。
4. 分辨率：原型 `d.res`（1080 × 2400）；当前有 `frameSize` 但没显示。设备档案里也有 `profile.screen_resolution`。
5. 快照标识：原型 `SNAP-DEMO-01`（假）；当前是真实 `snapshot_id`。应显示真实 id，但不能沿用「SNAP-」前缀文案。
6. 定位结果：原型一行 `#locator-result` 模拟文本；当前 6 列真实表格（x/y/宽/高/置信度/命中框）+ 定位快照 id 与「vendor 重新采集」提示。**保留表格**（真实数据），但可把「定位结果」并入第 3 栏 `p#locator-result` 的位置（原型顺序），或保留独立区块。
7. 模板字段：原型「匹配阈值 / 来源」两列在真实 `TemplateRecord`（`logical` / `version_id` / `image_sha256`）中没有对应字段 → **不要为了像原型而伪造这两列**。
8. 空态/错误态（Empty / Notice `viewer_unavailable` / `debug_session_not_active` / 关闭失败）：原型恒有演示数据，没有这些状态；真实实现必须保留。
9. 关闭会话释放租约（footer）：原型没有，但规格要求（不得留孤儿会话）；保留。
10. 跨页签保活（UiPage `debugEngaged` + `display:none`）：原型切页签即重渲染、无会话概念；当前为了模板页签复用 session_id 必须保活。保留（行为差异，不是 UI 差异）。

**B. 原型演示专属、不应照搬**

1. `直接控制（演示）` 复选框——无真实注入通道，且规格要求「不额外注入输入」。
2. `返回` / `主屏` 手机按键——假按键，`toast('已模拟…操作。')`。
3. `phoneMarkup()` 的假电商画面（14:32 / Wi-Fi / 星河生活 / 轻盈随行杯 / ¥89 / 购物袋导航 / `.phone-banner`），以及 `data-action="pick-node"` 的「模拟点击 = 修改页面文案」。
4. `SNAP-DEMO-01` / `SNAP-IMAGE-{n}` /「3 个节点示例」/「非真实投屏」/「图像流程为本地模拟，不连接设备或匹配服务」。
5. `imagePanel()` 的「新画面模拟场景」下拉（0.96 / 0.42）+「模拟采集新画面并重新匹配」+「模拟匹配成功：1 个区域」+ `.image-status` 里的假分数。**规格 §6.9 / AC-DBG-05 明确禁止**：「真实匹配能力不可用或未执行时返回明确不可用状态，不能显示模拟成功或占位分数」。
6. `templatesPage()` 的「新建模板演示」「演示冻结快照」「不生成真实 PNG」「共享本地演示版本」提示。
7. `inspectorPage()` 用字符串 `indexOf` 切割 HTML 的做法（脆弱，模板字面量格式一变即失效）——结构可参考，实现方式不可照搬。
8. 原型的 `.locator-option` 是 `div`（不可点）；当前做成 button 是正确改进，不必回退。

---

## 5. 最小改动建议（只给方案，不改源码）

### P0（必须改，直接对应「和原型不一致」的观感）

1. **三栏套回面板**（`DebugDrawer.tsx:783-1094`）
   - 第 2 栏：`<section className="debug-section">UI 层级树…` → `<section className="panel">`，head 换成 `<div className="panel-head"><h2>UI 层级树</h2><span className="small muted">…</span></div>`，树容器改用 `className="tree"`（或保留 `.debug-tree` 但去掉它自身的 border/radius，避免双层框）。
   - 第 3 栏同理：`<section className="panel">` + `.panel-head`（`<h2>元素与定位描述</h2><span className="badge gray">原生定位</span>`）。
   - 第 1 栏：给 `.debug-stage.phone-stage` 外层补 `className="phone-panel"`，或把 `.phone-stage` 的 padding/圆角改成 16px/12px；header 的 h3 行换成原型那种顶部 `.between` 徽章行。
   - 注意 `.panel-head h2` 当前是 12px（原型 14px）：**不要动全局规则**，需要时给调试区加 `.inspector .panel-head h2 { font-size:14px }`。
2. **切换器移出 toolbar**（`DebugDrawer.tsx:731-743`）
   - 移到 `<div className="debug-workspace-body">` 之前（与原型一致：切换器 → toolbar → notice → inspector），容器 `className="flex wrap mb"`、`role="group" aria-label="定位方式"`；
   - 激活态 `kind="soft"`（Button 组件已支持 `soft`）；
   - 追加 `<span className="small muted">` 提示，文案用真实语义（例如「图像匹配经 vendor TemplateStore 校验，需冻结快照与有效阈值」），不要照抄「本地模拟」。
3. **设备状态徽章**（`DebugDrawer.tsx:716`）
   - 用真实设备状态替换/并列 WS 状态：`<Badge tone={ready?'green':'blue'} dot>{ready?'可用':'占用中'}</Badge>`（tone/文案参考 `RESOURCE_STATUS_MAP` + `DevicesPage` 的 `deviceState()`）；
   - WS 状态降级为 `<span className="small muted">{wsText}</span>` 或保留为第二个 gray 徽章；
   - 渲染 `target.leaseHint`（字段已有），并修正 `UiPage.toWorkspaceTarget`（L88 不要写 null）。
4. **`.locator-option.active` 补背景**（`tokens.css:719`，1 行）
   - `.locator-option.active { background:#f7f9ff; border-color:#b4c2fc; }`（原型 L14 原值）。视觉差异明显。
5. **采集按钮图标**（`DebugDrawer.tsx:748`）
   - `icon="image"` → `icon={frozen ? 'play' : 'freeze'}`（Icon 组件已有 freeze/play）；
   - 冻结后的「恢复实时」可与「采集检查」按原型合并成一个切换按钮（未冻结 primary「采集检查」/ 冻结 default「恢复预览」）。

### P1（结构补全，需少量新增 CSS）

6. **图像模式改成原型的三栏切分**：把「图像识别（模板库）」里的 ①坐标/预览/逻辑名/保存 移到 `.inspector` 第 2 栏 `.panel.panel-pad.image-form`，②模板选择/阈值/匹配/表达式/复制 移到第 3 栏，删掉 `.inspector.mode-image > div:nth-child(2/3){display:none}`；模板清单要么留在下方，要么按原型归属到 `模板` 页签（一并解决重复）。
   - 需补的 CSS 只有：`.image-form{display:grid;gap:12px}`、`.image-coords{grid:2 列 gap 8}`、`.image-preview{height:110px;…}`、`.image-status{min-height:48px}`、`.field{display:flex;flex-direction:column;gap:7px;font-size:12px}`（`.field` 已有 `tokens.css:573` 定义，只需补 `font-size:12px` / `gap:7px`）。
7. **左栏面板底行**：`.between.small.muted` 显示真实快照 id + `frameSize.w × frameSize.h`；顶部 `.between` 用 `<Badge tone={frozen?'amber':'blue'} dot>{frozen?'冻结快照':'实时画面'}</Badge>` + `<span className="small muted">vendor viewer 实时帧</span>`。可同时删掉 toolbar 里重复的「画面已冻结」徽章。
8. **层级树用回 `.tree-row`**：`TreeBranch` 输出从 `link-btn` 改 `className={'tree-row level' + Math.min(depth,2)}`，选中节点加 `selected`（`selected?.index === node.index`）。`.tree` 的 `max-height` 建议从 320 提到与 `.debug-tree` 一致的 400（真实树 91 节点）。
9. **文案统一与去重**：「采集快照」统一为「采集检查」；删掉第 2 栏 header 下重复的 snapshot 行；空态 `Empty` 的 icon 从 `check` 改 `search`（与原型 `empty()` 一致），并把 `Empty` 移出 `.attribute-list`（双层 17+45px 内边距）。

### P2（清理与决策项）

10. **死 CSS**：`.debug-pane / .debug-pane-head / .debug-pane-body / body.debug-pane-open / .debug-work / .phone-panel img`（以及 P1-8 不采用时的 `.tree/.tree-row`）要么接入要么删除；`.debug-pane-foot` 现在被当普通 footer 用，名字易误导；`.foot-hint` 只有 `.dialog-foot .foot-hint` 有样式，在 `.debug-pane-foot` 里无样式。
11. **注释与现实不符**：DebugDrawer L4-6 写「占据右侧工作区的全高面板（.debug-pane）」，实际是页面内嵌；规格 §6.9 又说「右侧全高面板是 D1 已批准的布局例外」。**需要 Lead 明确：回到右侧全高面板（恢复 .debug-pane + body.debug-pane-open），还是维持页面内嵌（更贴原型）并修注释/删 CSS。** 这不影响下文对原型 DOM/CSS 的结论。
12. **模板清单重复**：调试页「图像识别（模板库）」与 `模板` 页签各有一份清单与登记入口；建议保留一处（原型是「列表在页签、登记在 inspector」）。

### 保留（不要为了像原型而改）

- 定位验证表单（定位方式 6 选项 / 定位值 / 阈值）与 6 列定位结果表：真实 vendor 契约需要 by/value，规格 AC-DBG-03/05 要求表达式与结果同源。
- 所有 Empty / Notice 错误态与 `viewer_unavailable` / `debug_session_not_active` 提示。
- 「关闭会话」footer 与卸载/关闭时释放会话的保活逻辑。
- 手机外壳 `.phone` + `.phone-camera` + `.debug-frame` canvas（原型外壳保留、内容换成真实帧）。
- 已对齐的部分（不要回退）：`.attribute-list/.attribute/.code-block/.badge/.notice/.toolbar/.panel/.empty` 的声明值；设备下拉 name / os 文案；`.inspector` gap 18px；`.attribute` 行结构。

---

## 6. 附：顺带发现的问题（不影响原型对照结论）

1. `DebugDrawer` 在 `UiPage` 里被包在 `<Panel>` 内，PanelHead 的 hint（「调试会话与自动运行竞争同一资源租约…」）是技术说明，不属于原型页面信息；若追求原型一致可移到 toolbar 的 muted 文本或去掉。
2. `wsNotice`（Notice amber title=「调试会话」）与 `createMutation` 错误共用同一字段，`wsNotice` 存在时会**顶掉**「尚未建立调试会话」Empty（L769 条件 `&& !wsNotice`）——会话创建失败时用户看到的是 amber 提示，不是错误态，信息层级偏轻。
3. 未提交改动把三栏改成常驻后，Empty 与三栏空壳**同时渲染**（`!session && !pending && !wsNotice` 时仍渲染 inspector），视觉重复；建议空态与三栏二选一，或把空态下放到各栏内部。
4. `toWorkspaceTarget(device)` 丢弃 `leaseHint`（L88 硬编码 null），与 `toDebugTarget`（UiPage L636）重复且不一致——两处建 `DebugTarget` 的逻辑应对齐。
5. `<span className="badge gray">原生定位</span>`、`<span className="badge green">优先候选</span>` 绕过 `Badge` 组件（无 `<i class="dot">`）——与原型一致（原型也是手写）；若后续统一改用 `Badge` 会多出圆点。
6. 图像模式隐藏第 2/3 栏后，**阈值输入随第 3 栏一起消失**，图像匹配只能从「图像识别」表格的行内按钮触发；按 P1-6 改成原型三栏后该入口应回归第 3 栏面板。
7. 原型 `.tree-row` 用 `<div>`（不可点）表示非叶子节点；当前所有节点都是可点 `link-btn`——真实场景下这是改进（可选中任意节点做定位），保留。

---

## 7. 证据与可复现位置

| 内容 | 位置 |
| --- | --- |
| 原型 tabs/heading | `docs/platform-prototype/index.html` L192（`uiPage`） |
| 原型 inspector 切换 + slice | L203（`inspectorPage`） |
| 原型 imagePanel 两栏 | L204 |
| 原型 native 三栏 + toolbar + notice | L224–229（`nativeInspectorPage`） |
| 原型节点详情 | L230（`nodeDetails`） |
| 原型模板页签 | L231（`templatesPage`） |
| 原型假手机 | L193（`phoneMarkup`）、L202（`inspectorPhone`） |
| 原型 CSS（inspector/phone/tree/attribute/locator） | L14 |
| 原型 CSS（image-*） | L46 |
| 原型状态色映射 | L72（`statusMap`） |
| 当前三栏 JSX | `web/src/components/DebugDrawer.tsx:692-1244`（关键：694-755 toolbar、783-1094 inspector、1096-1233 图像识别、1236-1241 footer） |
| 当前调试 CSS | `web/src/styles/tokens.css:643-733`（另有 705-719 原型类复刻段） |
| 当前挂载 | `web/src/pages/UiPage.tsx:413-621`（Panel/PanelHead + debugEngaged 保活） |
| 设备状态模型参照 | `web/src/pages/DevicesPage.tsx:91-104`；`web/src/constants.ts:20-25` |
| 规格依据 | `docs/plan/prototype-alignment-spec.md` §6.9、AC-DBG-01..05、R-UI-02/03 |

**未验证**：本文只做静态源码/原型对照，没有启动服务或截图；`.panel` 化后的实际栅格/滚动表现（如 400px 限高树放进 12px 圆角卡片、`.debug-frame canvas max-height:74vh` 在三栏等宽下实际高度）需在浏览器里复核。
