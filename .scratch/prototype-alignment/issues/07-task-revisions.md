# 07: 任务修订、同名冲突与幂等

**What to build:** 创建和编辑产生不可变修订；同名但不同配置返回冲突；同一幂等键不同内容拒绝，同内容跨重启复用。

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] AC-CONTRACT-01：同名换构建或套件不得悄悄复用旧任务
- [ ] AC-CONTRACT-02：PATCH 与 validate 均形成新修订，并发修改返回 stale_version
- [ ] validate 成功后页面采用响应中的最新 revision_id
- [ ] config 整份替换，不深合并；省略绑定字段表示不变
- [ ] 旧修订与旧运行引用不被回写
