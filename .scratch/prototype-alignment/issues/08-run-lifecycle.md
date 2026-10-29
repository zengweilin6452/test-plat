# 08: 运行创建、事件恢复与取消

**What to build:** 浏览器显式绑定修订发起运行；WS 与 REST 事件按序号可恢复；取消事实不丢，且不覆盖固定输入。

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] AC-LIVE-01：断线重连不丢终态、不重复事件
- [ ] AC-CONTRACT-03：超过 500 条事件后仍可补拉，取消事实不丢失
- [ ] 显式提交应用、平台、任务、修订与幂等键；跨归属引用拒绝
- [ ] overrides、source_dir、test_paths 不能改写固定输入
- [ ] 取消先受理后收敛；与完成竞争不伪造 cancelled
