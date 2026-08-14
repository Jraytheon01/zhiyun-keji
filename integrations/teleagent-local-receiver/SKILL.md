---
name: moben-monitor
description: Monitor Moben AI (墨本AI) device messages, receive recording-completed events, and bridge them to TeleAgent for processing or automatic meeting PPT generation. Use when the user needs to monitor moben.cn, connect a recorder App with TeleAgent, forward new voice/text messages, or trigger AI recorder and meeting-assistant workflows after a recording finishes. Triggers include "墨本AI", "墨本消息", "录音完成", "自动生成PPT", "moben", "监控墨本", "墨本转发".
name_cn: 墨本AI消息监控
description_cn: 监控墨本AI设备消息或接收录音完成事件，自动转发到TeleAgent处理，并可联动会议MCP生成PPT
create_source: super-agent-skill-creator
---

# 墨本AI消息监控

## 录音完成自动生成 PPT

使用 `scripts/auto_ppt_service.py` 在 TeleAgent 所在电脑上启动本地桥接服务。
录音卡 App 在会议数据入库后调用
`POST /events/recording-completed`，服务通过 TeleAgent 本地 IM SQLite 队列注入
一个无需人工回答的任务：

1. 加载“AI录音卡助手” Skill。
2. 调用 `meeting-assistant` MCP 读取指定会议的纪要或逐字稿。
3. 加载“PPT助手” Skill。
4. 根据事件中已给定的受众、风格和页数直接生成 `.pptx`。

该桥接服务必须与 TeleAgent 运行在同一台电脑上。录音卡 App 只发送
录音完成事件，不直接读写 TeleAgent 数据库。具体部署和事件格式见
`README.md`。

通过墨本AI REST API定时检查新消息，发现新消息后自动通过IM SQLite注入转发到TeleClaw AI处理，AI回复自动推送到企业微信。

## 架构

```
墨本AI设备(语音/文本) → moben.cn云端API
                              ↓ (定时轮询)
                        moben_gui.py (监控)
                              ↓ (IM SQLite注入)
                        TeleClaw IM服务 → OpenCode AI
                              ↓ (企微推送)
                        企业微信
```

## 前置条件

1. 墨本AI账号已绑定设备（moben.cn已登录）
2. TeleClaw企业微信渠道已连接（IM服务正常运行）
3. Edge浏览器用于首次获取JWT Token（Token有效期约30天，获取后可关闭浏览器）

## 快速启动

```bash
python scripts/moben_gui.py
```

GUI打开后：
1. 点击"初始化基线"记录当前最新消息
2. 点击"启动监控"开始定时检查
3. 新消息将自动发送到TeleClaw处理

## 工作流

### 消息获取（API方式）

调用墨本AI REST API获取消息，无需浏览器持续打开：

1. `GET /api/history/conversations?limit=5` — 获取对话列表（最新优先）
2. `GET /api/history/conversations/{chatId}` — 获取对话消息详情
3. 认证：`Authorization: Bearer {JWT}`
4. JWT Token自动缓存到本地文件 `.moben_token`，过期前1天自动刷新

### 新消息检测

状态比对基于 `chat_id + msg_id`，精准判断：

- 最新对话的chat_id与上次不同 → 有新消息
- 同一对话中最新用户消息的msg_id更大 → 有新消息
- 状态文件：`scripts/.moben_state`

### 消息转发（IM SQLite注入）

不依赖UI自动化，直接写入TeleClaw的IM数据库：

1. 向 `im-service.db` 的 `im_message` 表插入 `status='to_submit'` 记录
2. IM服务自动捡起（1秒内），提交给OpenCode AI
3. 轮询等待AI生成回复
4. 调用 `POST http://127.0.0.1:17802/im/common/submit-result` 完成闭环
5. IM服务将回复推送到企业微信

### TeleClaw忙检测

注入前检查IM数据库是否有 `to_submit` 或 `collecting` 状态的消息——如果TeleClaw正在处理任务，跳过本次发送，避免消息堆积。

## 首次Token获取

首次使用需要通过Edge浏览器CDP获取JWT Token：

1. Edge浏览器打开 `moben.cn/console` 并登录
2. 以调试模式启动Edge：`msedge.exe --remote-debugging-port=9222 --remote-allow-origins=*`
3. 启动GUI，Token自动从浏览器localStorage获取
4. Token缓存后可关闭Edge浏览器

Token有效期约30天，过期后需重新登录获取。

## API端点参考

墨本AI的4组API（baseURL详见JS bundle）：

| 实例 | baseURL | 用途 |
|------|---------|------|
| `hn` | `/api/auth` | 认证（send-code, login, me） |
| `it` | `/api/devices` | 设备管理 |
| `sr` | `/api/history` | 历史记录/对话 |
| `oi` | `/api/agent-connections` | Agent连接 |

关键端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history/conversations` | 对话列表，支持limit/offset分页 |
| GET | `/api/history/conversations/{chatId}` | 对话消息详情，支持beforeId/afterId |
| GET | `/api/auth/me` | 当前用户信息（验证Token有效性） |
| GET | `/api/devices` | 已绑定设备列表 |

消息数据结构：
```json
{
  "id": 961005,           // 全局递增消息ID
  "role": "user",         // user | assistant
  "content": "消息文本",   // 可能为null
  "hasAudio": true,       // 是否语音消息
  "audioPath": "1",       // 音频路径
  "createdAt": "2026-06-09T06:14:48.494Z"
}
```

## 依赖

- Python 3.12+
- requests
- websocket-client（仅首次获取Token时需要）
- tkinter（GUI，Python自带）
- TeleClaw企业微信渠道已连接

## 注意事项

- 语音消息的content字段仍包含语音转文字结果
- Token过期（约30天）后需重新通过浏览器获取
- IM SQLite路径自动探测：`%LOCALAPPDATA%/teleai-super-agent/im-service/im-service.db`
- 监控间隔最小10秒，默认30秒
