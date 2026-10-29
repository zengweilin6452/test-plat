# 16: joint 生命周期与结果矩阵

**What to build:** 一个运行包含 UI 与性能两个组件，性能采集窗口包围同一次 UI 执行，UI 结束立即停采，超时、失败和取消按结果矩阵收敛。

**Blocked by:** 02、13、15

**Status:** ready-for-agent

- [ ] AC-JOINT-01：两个可追溯组件共享一次资源独占
- [ ] AC-JOINT-02：短 UI 结束立即停采，达到 ui_timeout_s 记超时
- [ ] AC-JOINT-03：断言失败、无有效 UI、采集启动失败、采集中错误、取消竞争逐项符合矩阵
- [ ] AC-CONTRACT-06：合法 3600 秒执行窗不被总 deadline 截断
- [ ] 不静默降级为 UI；无法确认停机时设备不可分配
