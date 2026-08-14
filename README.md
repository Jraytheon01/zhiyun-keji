# 智云课迹

“智云课迹”是面向课堂、课后服务和个人学习复盘的课程理解与长期学习档案平台。录音与转写只是课程入口；平台重点负责课程知识本、TeleAgent 学习互动、完整对话回流、可信记忆和下一步学习计划。

## 当前闭环

1. 导入课程录音或模拟转写，课程数据写入独立的 `zhiyun_learning` 数据库；表结构沿用 `user_meeting_info` 与 `user_meeting_content`，但不再读取会议库。
2. 平台 AI 生成课程知识本：摘要、章节、知识点、关键原文和知识关系。
3. 用户从课程页发起 TeleAgent 复盘、检测、思维导图或跨课回顾。
4. TeleAgent 通过独立的 `zhiyun-learning` MCP 读取课程依据。
5. 多轮交流结束时，用户发送“结束复盘并回流课迹”；Skill 调用 `complete_learning_interaction` 回传关键完整对话。
6. 平台 AI 提炼问题、误区、提示过程、自我纠正、待验证项和记忆候选。
7. SQLite 保存原始证据与可信状态账本，Milvus 仅用于按学习者隔离的语义召回。
8. 学习档案展示形成依据、当前边界和下一步计划，后续新证据继续更新状态。

## 服务与端口

| 服务 | 端口 | 说明 |
|---|---:|---|
| 平台 Web/API | `18910` | 课程、学习档案、平台 AI 与回流接口 |
| TeleAgent Receiver | `18768` | 项目副本中的桌面联动桥 |
| 智云学习 MCP | `8768` | 教育专用工具与整段对话回流 |
| 原会议 MCP | `8766` | 可并行保留，不是教育链路依赖 |
| 教育 Ingest API | `8769` | 只处理教育课程的录音入库与索引 |
| MySQL | `3307` | 独立数据库 `zhiyun_learning` |
| Milvus | `19530` | 独立数据库 `zhiyun_learning`，集合前缀 `zyk_learning_` |

`8766` 与 `8768` 不冲突，TeleAgent 可以同时启用两个 MCP。教育 Skill 明确使用 `zhiyun-learning_*` 工具。

## 目录边界

- `zhiyun-keji-interactive-prototype/`：可运行平台与平台 AI。
- `services/zhiyun-learning-mcp/`：教育专用 MCP、Ingest API 与 Worker，共用一套教育数据边界，不会启动会议工具集合。
- `integrations/zhiyun-keji-learning/`：教育版 TeleAgent Skill。
- `integrations/teleagent-local-receiver/`：项目专用 Receiver 副本。
- `tools/meeting-data-injector/`：课程模拟数据注入工具。
- `docs/`：PRD、页面结构和开发说明。

原始 `meeting_assistant_async_dist`、`moben-monitor`、原 TeleAgent Bridge 与原会议 Skill 均未在源目录上修改。

## 启动

在 PowerShell 中运行：

```powershell
Set-Location 'E:\AI公众\zhiyun-keji'
.\start-zhiyun-keji.ps1
```

随后访问 `http://127.0.0.1:18910`。

启动脚本会：

- 复用 MySQL 与 Milvus 服务进程，但两者都使用独立的 `zhiyun_learning` 数据库；Milvus 集合另加 `zyk_learning_` 前缀；
- 构建并启动教育专用 MCP、Ingest API 与 Worker；
- 不启动、不查询会议 MCP 的数据链路；
- 启动项目 Receiver 与平台。

## 安全约束

- 火山 Ark Key 只保存在平台 `.env`，不进入浏览器、MCP 配置或文档。
- MCP Key 映射到手机号，课程与记忆查询始终按 `phone` 隔离。
- Milvus 不是事实数据库；向量命中必须回到 SQLite/MySQL 证据记录。
- TeleAgent 不直接修改掌握度，只能提交对话与初步判断，由平台 AI 结合课程原文复核。
- 单次回答不会直接固化为人格、智力、家庭或稳定偏好标签。

## 验收入口

- 健康检查：`GET http://127.0.0.1:18910/api/health`
- 学习 MCP：`http://127.0.0.1:8768/mcp`
- 学习档案：`http://127.0.0.1:18910/#growth-overview`
- 记忆明细：`http://127.0.0.1:18910/#growth-profile`

更细的产品范围见 `docs/智云课迹_PRD_v0.2.md`，页面结构见 `docs/智云课迹_纯功能与页面结构说明_v1.1.md`。
