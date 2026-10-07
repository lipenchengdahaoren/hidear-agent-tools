# vivo 接入记录

现有Agent：HiDear你好！聋人（58755257）。编辑草稿已更新，旧页面显示“已发布”，不表示本次草稿已经发布。

Web Service真实表单已核实的字段：所属应用、应用ID、工具名称、工具ID、版本、功能概述/场景/约束/输出/示例、最低智能体版本、设备与执行场景、工具权限、5-20条召回话术、接口URL、请求头、默认参数、超时、同步/异步。表单提供“保存草稿”和“下一页”。

官方示例JSON含 operationId、name、appCode、appName、description（JSON字符串）、kitVer、callDemo（JSON字符串）、skillUrl、httpHeaders（JSON字符串）、defBodyParams（JSON字符串）、timeout、skillProtocol（JSON字符串）、triggerQueries。skillProtocol含 parameters、returns 和platformConfigs。

打包脚本依照该样例生成三个公开Tool注册草稿。原样例supportDevice=5、executeScenarios=7、skillFw2_4仍需按真实表单与平台协议核对，不能凭示例认定所有设备和锁屏场景都可执行。returns可空字段的兼容性和调用样例也需在导入界面验证。

目前未提供公网HTTPS地址，因此skillUrl为空，未提交注册。不能使用本机127.0.0.1作为手机端可用服务。

当前表单请求头配置看起来是固定JSON；还未核实vivo的签名用户身份、OAuth和保留userId字段的真实性校验。示例里的userId=xx不是安全身份协议，不可直接信任。三个公开查询接口独立于个人记录，可作为先接入的能力。个人待办接口要等身份机制验证后接入，不能共享一个个人凭证。

Skill表单与旧Agent编辑器的直接关联尚未验证。“技能声明”只有图片/文档输入和地理位置声明，不等于SKILL.md挂载。完整Skill包可在支持脚本的宿主调用后端，vivo上需验证运行环境或通过工作流/插件接入同一接口。

正式发布顺序：部署并验证HTTPS公开Tool → 导入注册并平台调试 → 明确Skill消费方式 → HiDear关联工具/工作流 → 真机调试 → 用户确认提交新版Agent/Skill/Tool。主动通知另需受支持的通道与授权。
