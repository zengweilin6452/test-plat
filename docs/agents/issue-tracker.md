# Issue tracker：本地 Markdown

本仓库的 issue 与规格以 Markdown 文件存放在 `.scratch/` 下，不使用远程 issue 系统。

## 约定

- 每个特性一个目录：`.scratch/<feature-slug>/`
- 规格为 `.scratch/<feature-slug>/spec.md`；本仓库的权威规格可位于 `docs/plan/`，此时 `spec.md` 只作入口指针，不复制正文
- 工单为 `.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 编号，一票一文件，禁止合并成单个 tickets 文件
- 每个工单顶部用 `Status:` 记录分诊状态，取值见 `triage-labels.md`
- 用 `Blocked by:` 记录阻塞边，列出编号与标题；无阻塞写 `None (can start immediately)`
- 评论与讨论追加到文件底部 `## Comments` 标题下

## 技能说“发布到 issue tracker”时

在 `.scratch/<feature-slug>/` 下创建或更新对应文件；目录不存在时创建。

## 技能说“读取相关工单”时

读取引用路径的文件。用户通常会直接给出路径或编号。

## Wayfinding

由 `/wayfinder` 使用。**地图**是一个文件，每个工单一个**子文件**。

- **地图**：`.scratch/<effort>/map.md`，记录 Notes、Decisions-so-far 与 Fog。
- **子工单**：`.scratch/<effort>/issues/NN-<slug>.md`，从 `01` 编号，正文写问题。`Type:` 记录类型（`research`/`prototype`/`grilling`/`task`）；`Status:` 记录 `claimed`/`resolved`。
- **阻塞**：顶部 `Blocked by: NN, NN`。所列文件全部 `resolved` 时解除阻塞。
- **前沿**：扫描 `.scratch/<effort>/issues/`，取开放、未阻塞、未认领的文件，编号最小者优先。
- **认领**：开始工作前先写 `Status: claimed` 并保存。
- **解决**：在 `## Answer` 标题下追加答案，写 `Status: resolved`，再把上下文指针（要点与链接）追加到 `map.md` 的 Decisions-so-far。
