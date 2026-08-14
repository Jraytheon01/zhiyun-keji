# 智云课迹比赛平台

这不是录音产品，也不是把练习搬进网页的通用 AI 学习应用。平台负责保存真实课程内容、可信作答证据和长期成长状态；课程复盘、思维导图、跨课回顾和逐题检测由 TeleAgent 完成。

## 启动

1. 项目目录已配置现有 MySQL、AI 与项目专用 TeleAgent Receiver；如需迁移环境，再参考 `.env.example`。
2. 推荐从上一级目录运行 `start-zhiyun-keji.ps1`，一次启动 MCP、Ingest、Receiver 和平台。
3. 仅调试网页时可运行本目录 `start-platform.ps1`，访问 `http://127.0.0.1:18910`。

未配置 MySQL、AI 或 Bridge 时，平台仍可使用双学习者演示数据和规则回退；模拟回流只作为无 TeleAgent 环境下的明确备用入口。

## 现有能力复用

- `MYSQL_*`：直接读取 `user_meeting_info` 和 `user_meeting_content`，按 phone 查询课程与逐字稿。
- `INGEST_API_URL`：新增课程后可通知现有 ingest 链路建立向量索引。
- `AI_*`：仅服务端使用，用于课程复盘和成长阶段总结。
- `TELEAGENT_RECEIVER_URL`：调用现有 Bridge Receiver，携带课程任务并打开 TeleAgent。
- `PLATFORM_PUBLIC_URL`：供 MCP 的 `submit_learning_result` 把结构化互动结果回流平台。

平台本身不做登录鉴权。左下角可直接切换数据库中的学习者；数据归属、课程读取和回流仍按 learner/phone 隔离。

## 关键闭环

课程导入 → 平台 AI 复盘 → 发送 TeleAgent → TeleAgent 逐题互动 → MCP 结构化回流 → 平台更新可信知识状态 → 平台 AI 生成计划 → 完成反思留痕 → 下一次客观作答再验证。

课程页负责调用 TeleAgent；成长中心由平台 AI 独立处理。完成计划不会直接判定“已掌握”，只有新的客观作答证据才能改变掌握状态。
