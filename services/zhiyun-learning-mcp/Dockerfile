# zhiyun-learning —— 教育场景 MCP 服务镜像
# MySQL / Milvus 为外部服务，通过 env 配置 URI 连接。
FROM python:3.13-slim

WORKDIR /app

# 依赖（先装，利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用包
COPY zhiyun_learning_mcp ./zhiyun_learning_mcp

# PYTHONPATH=父目录使 `python -m zhiyun_learning_mcp.xxx` 可运行；
# WORKDIR=包目录使 dotenv 能找到挂载的 .env
ENV PYTHONPATH=/app
WORKDIR /app/zhiyun_learning_mcp

EXPOSE 8768

# 默认起 MCP 服务；Compose 为 ingest API 和 Worker 覆盖启动命令。
CMD ["python", "-m", "zhiyun_learning_mcp.mcp_server"]
