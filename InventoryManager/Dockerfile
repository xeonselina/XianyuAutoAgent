# 支持多架构构建的Python 3.11基础镜像
# ARG指令必须在FROM之前定义（BuildKit要求）
ARG TARGETPLATFORM
ARG BUILDPLATFORM

# 代理配置参数
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG http_proxy
ARG https_proxy
ARG no_proxy

FROM python:3.10-slim-bookworm

# 设置代理环境变量
ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTPS_PROXY
ENV NO_PROXY=$NO_PROXY
ENV http_proxy=$http_proxy
ENV https_proxy=$https_proxy
ENV no_proxy=$no_proxy

# 设置工作目录
WORKDIR /app

# 构建信息标签
LABEL org.opencontainers.image.title="Inventory Manager"
LABEL org.opencontainers.image.description="库存管理系统 - 支持ARM64和AMD64架构"
LABEL org.opencontainers.image.source="https://github.com/your-repo/InventoryManager"

# 显示构建平台信息（调试用）
RUN echo "Building on: $BUILDPLATFORM, targeting: $TARGETPLATFORM"


# 安装系统依赖（临时取消代理以直接访问 Debian 仓库）
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    apt-get update && apt-get install -y --no-install-recommends \
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
    poppler-utils \
    curl \
    vim \
    tzdata \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 设置系统时区为东8区（北京时间）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 复制requirements文件并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt


# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 应用基础配置
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
# 注意: SECRET_KEY, API_KEY, DATABASE_URL 等敏感信息应通过运行时环境变量传入
# 不要在Dockerfile中硬编码敏感信息

# 日志配置
ENV LOG_LEVEL=INFO
ENV LOG_FILE=logs/inventory_service.log

# 安全配置
ENV SESSION_COOKIE_SECURE=false
ENV SESSION_COOKIE_HTTPONLY=true
ENV SESSION_COOKIE_SAMESITE=Lax
ENV CORS_ORIGINS=*

# 业务配置
ENV DEFAULT_RENTAL_DAYS=7
ENV MAX_RENTAL_DAYS=30
ENV MIN_ADVANCE_BOOKING_DAYS=1
ENV TIMEZONE=Asia/Shanghai

# 文件上传配置
ENV MAX_CONTENT_LENGTH=16777216
ENV UPLOAD_FOLDER=uploads

# 缓存配置
ENV CACHE_TYPE=simple
ENV CACHE_DEFAULT_TIMEOUT=300

# 分页配置
ENV POSTS_PER_PAGE=20

# 数据库连接池配置
ENV DB_POOL_SIZE=10
ENV DB_POOL_RECYCLE=3600
ENV DB_POOL_PRE_PING=true

# 应用端口配置
ENV APP_PORT=5002
ENV APP_HOST=0.0.0.0

# 健康检查配置
ENV HEALTH_CHECK_ENABLED=true
ENV HEALTH_CHECK_TIMEOUT=30

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p logs && \
    mkdir -p uploads && \
    mkdir -p static/uploads && \
    mkdir -p tmp

# 设置文件权限
RUN chmod +x app.py

# MySQL数据库将在容器启动时连接，无需本地初始化

# 创建非root用户并设置权限
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app/static && \
    chmod -R 755 /app/logs && \
    chmod -R 755 /app/uploads

# 切换到非root用户
USER appuser

# 暴露端口
EXPOSE 5002

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5002/ || exit 1

# 启动命令 - 使用配置文件启动,确保 monkey patch 在导入 SSL 之前完成
CMD ["gunicorn", "--config", "gunicorn_config.py", "run:app"]
