# Toby 录音完成 -> TeleAgent 自动生成会议 PPT

该仓库运行在录音卡服务器上，只负责接收上游事件并把内置 Prompt 转发给展示电脑：

```text
上游 backend
  -> 调用已部署的 ingest
  -> 等待上游设定的展示时间
  -> POST Bridge /events/recording-completed
  -> Bridge 按 display_bridge_url 转发结构化事件 + 内置 Prompt
  -> 展示电脑 moben 接收器
  -> TeleAgent 本地 IM SQLite
  -> Toby.AI录音卡助手 -> meeting-assistant MCP -> PPT 能力
```

Bridge 不调用 ingest、不轮询 ingest，也不访问远程 Windows SQLite。ingest 与 MCP 无需为展会链路做任何改动。

## 启动

从示例复制配置后，设置展示电脑的局域网地址：

```powershell
Copy-Item config.example.json config.json
python scripts/auto_ppt_service.py --config config.json
```

关键配置：

- `host` / `port`：上游 backend 调用 Bridge 的监听地址；双机部署监听 `0.0.0.0:18766` 或服务器指定局域网 IP。
- `bridge_token`：可选的上游到 Bridge token，请求使用 `X-Bridge-Token` 或 Bearer token。
- `display_bridge_url`：展示电脑接收器的局域网地址，例如 `http://192.168.x.x:18767`，不要配置为服务器自身的回环地址。
- `display_bridge_token`：可选的 Bridge 到展示电脑 token，必须与展示端 `bridge_token` 一致。
- `display_bridge_timeout_seconds`：单次 HTTP 超时。
- `display_bridge_retries`：首次失败后的重试次数。
- `display_bridge_retry_delay_seconds` / `display_bridge_retry_max_delay_seconds`：指数退避参数。
- `display_bridge_trigger_delay_seconds`：上游调用 Bridge 后的可选短缓冲；上游已经等待时保持 `0`。

所有配置也可分别用 `DISPLAY_BRIDGE_URL`、`DISPLAY_BRIDGE_TOKEN`、`DISPLAY_BRIDGE_TIMEOUT_SECONDS`、`DISPLAY_BRIDGE_RETRIES`、`DISPLAY_BRIDGE_RETRY_DELAY_SECONDS`、`DISPLAY_BRIDGE_RETRY_MAX_DELAY_SECONDS`、`DISPLAY_BRIDGE_TRIGGER_DELAY_SECONDS` 环境变量覆盖。

## 上游调用

上游在自己的展示等待结束后调用：

```json
{
  "event_id": "device-01-recording-20260810-001",
  "recording_id": "12345",
  "completed_at": "2026-08-10T10:30:00+08:00",
  "source": "recorder-backend"
}
```

如果演示只要求最近会议，也可以不传 `recording_id`，改传 `"use_latest": true`。Bridge 始终使用自身内置 Prompt，上游不能覆盖 Prompt。

接口：

```text
POST /events/recording-completed  创建或返回已有任务
GET  /jobs/{event_id}             查询转发、TeleAgent 和 PPT 结果
GET  /health                      查询 Bridge 及展示接收器健康状态
```

`event_id` 是端到端幂等键。重复请求不会重复创建任务；展示投递失败只改变 Bridge 自己的 job 状态并独立重试，不会影响上游已完成的 ingest。

## 内置 Prompt

Bridge 固定要求 TeleAgent 使用 `Toby.AI录音卡助手`，直接选择最近一场会议，优先读取纪要、缺失时读取逐字稿，再以项目团队和管理层为受众生成约 7 页、商务简约、可编辑 `.pptx`。Prompt 明确禁止提问或等待确认。

## 本机双进程联调

同一台电脑联调时建议使用不同端口：

```text
Bridge:        127.0.0.1:18766
moben receiver: 127.0.0.1:18767
```

真实双机部署时，只需把 `display_bridge_url` 改成展示电脑局域网 IP/主机名，并将展示端端口限制在可信局域网内。
