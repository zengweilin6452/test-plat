# 15: 资源就绪检查与占用语义

**What to build:** 在线、空闲候选与占用分别展示；busy 设备不探测；检查只读不自愈；正式运行在独占后重新检查。

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] AC-RES-01：ready+idle、ready+busy、offline、unauthorized、draining 计数准确
- [ ] AC-RES-02：占用预览不新建调试、不额外采屏、不抢租约
- [ ] AC-RES-03：按测试类型检查，未知项不冒充通过
- [ ] AC-READ-01：手动检查和运行准备均不执行 tcpip/connect、安装或设置修改
- [ ] 检查失败不自动自愈，设备保持不可分配并说明原因
