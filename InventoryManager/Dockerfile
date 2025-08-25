# 支持多架构构建的Python 3.11基础镜像
# ARG指令必须在FROM之前定义（BuildKit要求）
ARG TARGETPLATFORM
ARG BUILDPLATFORM
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 构建信息标签
LABEL org.opencontainers.image.title="Inventory Manager"
LABEL org.opencontainers.image.description="库存管理系统 - 支持ARM64和AMD64架构"
LABEL org.opencontainers.image.source="https://github.com/your-repo/InventoryManager"

# 显示构建平台信息（调试用）
RUN echo "Building on: $BUILDPLATFORM, targeting: $TARGETPLATFORM"

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV APP_PORT=5001

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    default-libmysqlclient-dev \
    libssl-dev \
    libffi-dev \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libwebp-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libxcb1-dev \
    curl \
    vim \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 复制requirements文件并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p logs && \
    mkdir -p uploads && \
    mkdir -p static/uploads && \
    mkdir -p tmp

# 设置文件权限
RUN chmod +x app.py

# 创建非root用户并设置权限
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app/static && \
    chmod -R 755 /app/logs && \
    chmod -R 755 /app/uploads

# 切换到非root用户
USER appuser

# 暴露端口
EXPOSE 5001

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5001/ || exit 1

# 启动命令 - 使用生产级配置
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5001", \
     "--workers", "4", \
     "--worker-class", "gevent", \
     "--worker-connections", "1000", \
     "--timeout", "120", \
     "--keep-alive", "2", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--preload", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "app:app"]
