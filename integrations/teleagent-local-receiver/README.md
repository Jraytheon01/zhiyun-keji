# TeleAgent 展示电脑本地接收器

`moben-monitor` 在展示电脑上接收录音卡服务器 Bridge 转发的事件。它是唯一访问 TeleAgent 本地数据目录和 `im-service.db` 的组件，服务器端不会接触远程 SQLite 文件。

```text
服务器 Bridge
  -> HTTP POST /events/recording-completed（结构化事件 + 内置 Prompt）
  -> moben receiver
  -> TeleAgent 本地 IM SQLite 队列
  -> 创建/路由会话并置前 TeleAgent
  -> Toby.AI录音卡助手 -> meeting-assistant MCP -> PPT 能力
```

## 展示电脑配置

```powershell
Copy-Item config.example.json config.json
python scripts/auto_ppt_service.py --config config.json
```

关键配置：

- `bridge_mode`: 固定为 `receiver`。
- `host` / `port`: 展示电脑监听 `0.0.0.0:18767` 或其指定局域网 IP；Bridge 的目标 URL 必须使用展示电脑可达的局域网 IP。
- `bridge_token`: 可选 token，必须与服务器 Bridge 的 `display_bridge_token` 一致。
- `teleagent_data_dir`: 留空时自动发现 TeleAgent 数据目录，发现失败时再显式配置。
- `channel`: 当前 POC 使用 `wecom` 内部队列。
- `new_session_per_event`: 每个新 `event_id` 清空通道路由会话，尝试创建新会话。
- `focus_teleagent_on_submit`: 注入任务后恢复并置前 TeleAgent 窗口。
- `dry_run`: 为 `true` 时验证事件、幂等和 Prompt，但不写 TeleAgent SQLite。

接口：

```text
POST /events/recording-completed  接收 Bridge 事件
GET  /jobs/{event_id}             查询消息状态、结果文本和 PPT 文件路径
GET  /health                      检查接收器和 TeleAgent 数据目录
```

接收器沿用 Bridge 的 `event_id` 作为幂等键。Bridge 传入的 `prompt` 会直接进入 TeleAgent；只有单独调试接收器且请求未带 Prompt 时，才使用本地同义的 Toby 默认 Prompt。

## 兼容风险

当前实现使用 TeleAgent 桌面版非公开的 IM SQLite 结构，并允许未配置的 `wecom` 通道充当内部任务队列。它不是稳定公共 API；TeleAgent 升级后，表结构、状态值、会话路由或进程唤醒方式都可能变化，展会版本升级前必须重新做兼容性联调。
