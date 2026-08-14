# Zhiyun Learning MCP

智云课迹的独立教育领域 MCP。它使用独立的 `zhiyun_learning` MySQL 数据库与
`zyk_learning_` Milvus 集合，保留 MCP Key→phone 隔离，但不读取会议数据，
也不暴露会议待办、议程、周报等会议工具。

主要能力：课程读取、课程原文语义检索、跨课关联、长期学习上下文读取，以及
TeleAgent 学习对话的受控回流。服务标识为 `zhiyun-learning`，默认端口 `8768`。

本目录是项目副本，可独立演进；不会修改原始会议 MCP 工程。
