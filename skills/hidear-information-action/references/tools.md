# 工具使用规则

这些工具由本项目后端实现，不是 vivo 系统内置工具。先核实宿主已连接该服务和当前用户身份，再调用。

| 名称 | 参数 | 结果与边界 |
|---|---|---|
| save_information | title, source_url, city, topic, summary；可选 deadline_at | 保存当前用户的公告线索；固定 unverified，不提供自动真实性保证 |
| search_information | 可选 query, city, limit(1-20), include_expired | 查询信息库；scope=stored_information_only。空结果需继续联网搜索 |
| get_information | information_id | 原文、日期、核验状态；资源无权限视为不可读 |
| prepare_action | information_id | 条件、材料、步骤；submission_status=not_submitted，不最终裁定资格 |
| create_followup | title, due_at, confirmed；可选 information_id | confirmed 必须来自用户实际确认；返回记录标识及 notification_status=not_configured |
| list_followups | 可选 status(open/completed/cancelled/all), due_only | 当前用户记录，不接受 user_id |
| update_followup | followup_id, version, confirmed；可选 status/due_at（至少一项） | 完成、取消或改期；409须重新读取后请用户确认 |

时间均用带时区 ISO 8601，中文用户默认先核对 Asia/Shanghai（UTC+08:00）。截止日不明时不要传猜测日期。工具返回 UTC 可以转换成用户确认的时区展示。

成功结构：success=true、request_id、result、error=null。失败结构：success=false、result=null、error.code/message。

notification_status=not_configured：只说“已记录待办，尚未设置手机通知”；不能说“到时我会通知你”。日历 URL 需要用户认证，不能给其他用户；可通过操作页导出 .ics，用户自行导入确认权限。取消后已导入手机的事件仍须用户删除。

save_information、create_followup、update_followup 是写操作，需要幂等标识。用户资料不放进公开信息摘要和标题；不上传身份、残疾证明、医疗或财务资料。

客户端示例（参数经标准输入提供）：

```text
python scripts/hidear_tool.py search_information
输入：{"city":"广州","query":"就业","limit":5}
```

```text
python scripts/hidear_tool.py create_followup --request-id <同一操作的稳定唯一标识>
输入：{"title":"核对培训报名条件","due_at":"2027-01-01T19:00:00+08:00","confirmed":true}
```

示例时间仅说明格式，实际用用户确认的未来时间。
