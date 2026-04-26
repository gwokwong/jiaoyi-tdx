FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY src/ ./src/
COPY config/ ./config/

# 设置工作目录
WORKDIR /app/src

# 暴露日志目录
VOLUME ["/app/logs"]

# 启动命令
CMD ["python", "monitor.py", "--config", "../config/config.json"]
