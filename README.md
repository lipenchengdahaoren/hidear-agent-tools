# HiDear 信息与行动助手

面向聋人、听障与语障用户，把公开信息整理成可核验线索、行动清单和跟进事项，使用清晰文字表达。复用蓝心小V的搜索、资讯、OCR和语音转文字。

## 当前状态

本地版本可运行。Skill有可执行客户端；后端提供七个用户接口和三个隔离的公开查询接口。公网部署、vivo Tool注册、Skill挂载和新版Agent发布尚未完成。16项测试通过，包含Skill客户端经真实HTTP调用服务，不代表手机真机测试已通过。

已支持：信息线索保存、查询与详情、行动清单、待办创建/查询/修改、过期公告处理、日历导出。用户隔离、幂等写入和版本冲突检查已实现。

未支持：自动全网采集、自动报名、后台手机推送、vivo用户身份联邦登录、MCP服务器。导出日历需要用户导入并确认权限；记录成功不等于已设置手机通知。

## 本地使用

需要Python 3.10或更新版本，本地服务无第三方依赖。在项目目录运行：

```text
python backend/setup_local.py
python backend/app.py serve
```

打开 http://127.0.0.1:8765 ，从本地 backend/data/console.token 复制体验凭证后连接。凭证不进入公开仓库；不要将它发送到对话或其他网站。体验库只含明确标记的模拟公告，不是真实报名信息。

操作页支持查询公告、查看清单、保存公开线索、记录未来事项、完成/取消和导出.ics日历文件。日历提醒必须在日历应用中确认；取消待办后已导入手机的日历事件需要自行更新。

## Skill与Tool

Skill目录：skills/hidear-information-action/，打包输出为dist/hidear-information-action.zip。包括SKILL.md、核验规则、七个工具参数、OpenAPI和执行脚本。

宿主配置HIDEAR_BASE_URL和当前用户隔离的私有HIDEAR_TOKEN_FILE，不把凭证放入提示词或Skill包。JSON参数从标准输入调用：

```text
python skills/hidear-information-action/scripts/hidear_tool.py search_information
python skills/hidear-information-action/scripts/hidear_tool.py create_followup --request-id <稳定唯一操作标识>
```

具体参数见skills/hidear-information-action/references/tools.md。写操作结果未知时保留request-id重试。宿主不支持脚本时可按OpenAPI注册工具；蓝心小V脚本运行环境与旧Agent挂载独立Skill的方式仍需平台验证。

| 工具 | POST路径 | 用途 |
|---|---|---|
| save_information | /tools/save_information | 保存当前用户公告线索，始终未核实 |
| search_information | /tools/search_information | 查询已收录信息，默认排除过期/撤回 |
| get_information | /tools/get_information | 读取原文、日期和核验状态 |
| prepare_action | /tools/prepare_action | 生成材料与步骤，不提交报名 |
| create_followup | /tools/create_followup | 用户确认后记录事项，不发送通知 |
| list_followups | /tools/list_followups | 当前用户全部或到期事项 |
| update_followup | /tools/update_followup | 完成、取消、改期，检查版本 |

这些接口需要Authorization: Bearer <用户凭证>，写操作另需Idempotency-Key，不接受模型指定user_id。体验凭证默认30天有效，正式版需接入账号登录、续期与撤销机制。

三个公开接口使用/public/tools/search_information、/public/tools/get_information、/public/tools/prepare_action，只读取管理员导入的公开信息，不读取用户线索。可以先用于vivo Web Service。不得共享个人账号凭证给所有手机用户。

结果包含code（0成功/1失败）、success、request_id、result、error。notification_status=not_configured只能说已记录，不能说已安排手机通知。时间使用带时区ISO 8601；用户展示时转换成确认的时区。

## 维护信息

运营者本地导入JSON列表：

```text
python backend/app.py import --file <公告列表.json>
```

必填title、source_url（HTTPS）、city、topic、summary。可填deadline_at、published_at、checked_at、materials、conditions、action_url和unknown_fields。verified/partially_verified必须附checked_at与verification_evidence。这是人工核验记录，程序不会自动证明公告真实性。没有数据时返回空结果，不代表没有相关政策。真实库不导入体验公告。

## 测试与打包

```text
python -m unittest discover -s backend -p "test_*.py" -v
python build_release.py
```

OpenAPI由GET /openapi.json提供。打包脚本生成Skill ZIP、接口规范和vivo公开Tool注册草稿；没有真实HTTPS地址时skillUrl为空，不能提交上线。

## 部署与vivo

backend/Dockerfile使用Waitress运行服务；需要HTTPS网关、限流和持久磁盘挂载到/data。开发服务仅监听本机回环地址。数据库、凭证、私有配置和截图均不上传GitHub。

目前未选择云账号，没有付费或授予云权限。无持久存储的免费实例不能用于真实跟进数据。vivo表单和接入进度见docs/vivo-registration.md。个人工具须待用户身份和签名协议核实后接入；当前先准备三个公开查询Tool。

平台依据：[接入文档](https://aitools.vivo.com.cn/docs?pane=ch2)、[Agent入口](https://aitools.vivo.com.cn/publish/agent-entry)、[支付宝合作案例](https://www.vivo.com.cn/brand/news/detail?id=1379&type=0)。

仓库公开可见，尚未选择开源许可证。公开发布不包含用户个人数据、凭证或登录截图。
