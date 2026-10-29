# 06: 类型化清单与任务验证

**What to build:** UI、performance、joint 各自使用明确的清单形状与就绪规则；空清单失败，性能场景不伪造 pytest 用例。

**Blocked by:** 04、05

**Status:** ready-for-agent

- [ ] AC-INPUT-03：三种类型分别验证，套件与修订测试类型不匹配失败
- [ ] AC-CORE-02：缺构建、缺套件、无效归属、空或不适用清单显示准确 missing/invalid
- [ ] 声明式性能场景没有虚假 cases
- [ ] joint 缺少 UI 或性能任一部分时验证失败
- [ ] 错误可读、可修复，不以占位数据通过验证
