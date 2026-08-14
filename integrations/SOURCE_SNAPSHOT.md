# 外部能力副本说明

本目录中的组件在 2026-08-14 从以下现有目录复制，后续教育场景修改只发生在当前项目副本：

- `teleagent-local-receiver/` ← `E:\AI公众\moben-monitor`
- `teleagent-upstream-bridge/` ← `E:\AI公众\ai_recorder_teleagent_bridge`
- `teleagent-meeting-skill-baseline/` ← `E:\AI公众\ai_recorder_teleagent_skill`

复制时排除了 `.git`、日志、缓存、运行时 SQLite、token、`.env` 和本机 `config.json`。

源目录核验结果：本次智云课迹开发没有写入上述三个源目录。复制前，后两个 Git 仓库已经存在未提交修改，因此未擅自执行回退或覆盖。

智云课迹使用的教育版能力：

- 本地 Receiver：`teleagent-local-receiver`，独立端口 `18768`
- 教育 Skill：`zhiyun-keji-learning`
- MCP：`..\services\meeting-assistant-mcp`
