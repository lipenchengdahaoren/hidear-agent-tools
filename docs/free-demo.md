# 免费公开查询演示部署

目标：公开信息查询、公告详情、行动准备。不会开放个人记录接口。

## Render 表单

- 通过 Public Git Repository 地址连接 https://github.com/lipenchengdahaoren/hidear-agent-tools
- Runtime：Docker；Branch：main
- Dockerfile：backend/Dockerfile；Docker context：backend
- Instance Type：Free（若页面显示费用，不提交）
- 环境变量：HIDEAR_PUBLIC_ONLY=1
- Health check：/health
- 不添加付款方式或持久磁盘。暂不需要 GitHub 私有仓库权限。

仓库根目录的 render.yaml 也提供了同样配置。首次创建账号的条款和授权由用户处理。

## 限制与验证

Render 免费服务闲置15分钟会休眠，唤醒约1分钟，超过蓝心 Tool 最长30秒调用时限。因此本服务用于接入演示；在测试蓝心调用前先打开演示首页唤醒。不可通过定时请求规避休眠。持续可用的正式服务另行选型。

每次启动从公开的 backend/public-information.json 恢复收录记录。当前收录北京残疾人服务官方导航，部分核验；没有自动爬取、报名或个人资格认定。

取得实际 HTTPS 地址后，执行 build_release.py --base-url HTTPS地址，生成3个 Web Service 草稿。部署完成不表示通过 vivo 审核，也不表示 Agent 已能调用：须完成平台注册、关联、实际调试和手机验证。

资料：https://render.com/docs/free
