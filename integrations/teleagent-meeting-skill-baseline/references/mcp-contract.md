# Meeting Assistant MCP 工具契约

所有工具都由 MCP key 映射出的 `user_id` 强制限定租户。Skill 只能调用 TeleAgent 注入的
MCP 工具，不能自行发送 HTTP 请求。

## 会议读取

### `list_recordings()`

返回当前用户可见的会议。常用字段：

- `recording_id`：后续工具调用标识
- `title` / `meeting_name`：展示和匹配
- `create_time` / `during`：时间与时长
- `has_summary` / `has_transcript` / `has_audio`：内容可用性

### `get_summary(recording_id: string)`

读取已有会议纪要，不现场生成新纪要。

### `get_transcript(recording_id: string)`

读取按时间和说话人聚合的逐字稿。

### `get_audio_url(recording_id: string, expires: int = 3600)`

返回上游保存的录音公网链接。`expires` 为兼容参数，当前不重新签名链接。

## 语义检索与会议记忆

### `search_meetings(query: string, top_k: int = 5, kind: string = "all", recording_id?: string)`

检索原始 transcript/summary chunks，返回文本、相似度和来源会议。`kind` 仅允许
`all|transcript|summary`；传 `recording_id` 可限制在单场会议。

### `recall(query: string, top_k: int = 5)`

检索活跃的蒸馏事实，如决策、项目、人物和偏好，并返回可溯源的会议与日期。关键内容需要
原话时，应再通过会议读取或原始搜索核验。

### `get_entity(name: string)`

返回项目或人物的活跃事实、相关关系和其开放待办。

### `list_entities(type: string = "project")`

列出项目或人物实体。`type` 使用 `project` 或 `person`。

### `add_memory(kind: string, subject: string, detail: object)`

为当前用户人工补录事实并返回 fact id。仅在用户明确要求保存信息时调用。

## 待办与自动化

### `get_todos(status: string = "open", due_before?: string, owner?: string)`

按状态、截止日期和负责人查询待办。日期使用服务可识别的日期字符串，优先传
`YYYY-MM-DD`。

### `remind_upcoming(days: int = 7)`

返回从北京时间当天起指定天数内到期的开放待办。

### `draft_agenda(topic: string)`

基于相关事实、原始会议片段和开放待办生成 Markdown 议程。

### `weekly_report(week: string = "last")`

基于当前用户的近期会议与开放待办生成 Markdown 周报。透传用户明确给出的范围；未给出时
使用默认值。

### `reingest(recording_id: string)`

删除目标会议的 chunks、facts、todos 后，从上游会议表重跑抽取和向量化。必须取得明确确认。

## 鉴权与错误

- TeleAgent MCP 请求头：`Authorization: Bearer <原始 mcp-key>`。
- 不要把数据库中的 SHA-256 `key_hash` 配给 TeleAgent。
- 工具不可用：提示启用 `meeting-assistant` MCP。
- 401：提示检查 MCP key；不要请求用户发送密码或数据库字段。
- 会议不存在或无权访问：只允许重新选择当前用户列表中的会议。
- “尚未生成”：说明数据状态并停止依赖该内容的生成。
- “工具执行失败”：概括错误并停止相关推断，不把它解释为空结果。
