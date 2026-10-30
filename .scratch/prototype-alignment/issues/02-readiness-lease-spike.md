# 02: 设备只读检查与租约适配验证

**What to build:** 用可运行证据证明手动检查与运行准备不会触发 tcpip/connect、安装或设置修改；给出短检查 holder 的迁移、并发与安全停止方案。

**Blocked by:** 01

**Status:** ready-for-human

- [ ] 替身命令记录覆盖平台直接调用、PerfKit.ensure_ready 与插件隐式调用
- [ ] 检查失败不自动自愈，busy 设备不访问
- [ ] 短检查与运行共用数据库租约权威，并发竞争测试通过
- [ ] fence 失效拒绝写入；未确认停机时资源不可分配
- [ ] 方案与证据可供后续实现引用

## Comments

- 已合并（cf641b1、b640003）：只读 readiness、短检查租约/fence、移除 ensure_ready；迁移 0004。
