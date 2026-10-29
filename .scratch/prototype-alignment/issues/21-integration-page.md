# 21: 接入页真实示例与能力探测

**What to build:** 接入说明中的路由、请求模型、错误码和表名与实际 OpenAPI 一致；存活与能力探测分开呈现三态。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] AC-INT-01：逐条验证示例与实际接口，不公开内部协议为普通接入 API
- [ ] AC-INT-02：DB 不可达、vendor 缺失、runner 未知分别反映
- [ ] ok=null 不渲染成失败；存活 200 不冒充全能力健康
- [ ] 探测不启动运行或占用设备，无凭据输出
