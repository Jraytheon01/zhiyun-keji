# Toby AI 录音内容本机注入工具

此目录独立于 `ingest + MCP`、Bridge 和 moben 仓库，不属于最终提交内容。

## 1. 使用填写页面注入 MySQL

启动本地页面：

```powershell
python meeting_form_server.py
```

浏览器打开 `http://127.0.0.1:18880`。录音标题、内容摘要和逐字稿均为必填；录音 ID 可以留空自动生成。逐字稿只使用“说话人1、说话人2……”格式，不需要时间戳，工具会自动分段并估算时间轴。

使用 `AI_RECORDING_PROMPT_TEMPLATE.md` 让上游 AI 一次生成标题、摘要和自然逐字稿。日常只需修改场景、录音时长和说话人数。

## 2. 使用 JSON 脚本注入（可选）

复制 `meeting.example.json` 为 `meeting.local.json`，填写：

- `meeting_id`：必须是未使用的正整数。
- `user_id`：必须与演示 MCP key 对应，本机当前可用值为 `1001`。
- `phone`：ingest POST 中必须使用完全相同的值。
- `title`、`create_time`、`summary`。
- `segments`：每段包含毫秒级 `begin_time/end_time`、`speaker` 和 `content`。

写入 MySQL：

```powershell
python inject_meeting.py meeting.local.json
```

脚本写入 `user_meeting_info` 和 `user_meeting_content`，默认拒绝覆盖已有 `meeting_id`。明确需要重写同一演示会议时才使用 `--replace`。

## 3. 导入 ApiPost

导入 `apipost.openapi.json`，按顺序执行：

1. `POST http://127.0.0.1:8769/api/v1/ingest/notifications`
2. 等待约定的演示缓冲时间。
3. `POST http://192.168.0.137:18766/events/recording-completed`

两次请求的 `meeting_id/recording_id` 必须相同；重复测试 Bridge 时应更换 `event_id`，验证幂等时则保持相同 `event_id`。
