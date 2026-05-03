# ── 支持多架构 ────────────────────────────────────────────────────────────────
ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG http_proxy
ARG https_proxy
ARG no_proxy

# ══════════════════════════════════════════════════════════════════════════════
# Stage 1: builder —— 编译 Python wheels（含 build-essential / libssl 等编译依赖）
# ══════════════════════════════════════════════════════════════════════════════
FROM python:3.10-slim-bookworm AS builder

ARG HTTP_PROXY HTTPS_PROXY http_proxy https_proxy

# 换阿里云 apt 镜像，大幅提速
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    default-libmysqlclient-dev \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 用清华 pip 镜像编译并打包成 wheel
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --upgrade pip setuptools wheel \
    && pip wheel --no-cache-dir --wheel-dir /wheels \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /tmp/requirements.txt


# ══════════════════════════════════════════════════════════════════════════════
# Stage 2: runtime —— 只复制 wheels，不带任何编译工具
# ══════════════════════════════════════════════════════════════════════════════
FROM python:3.10-slim-bookworm

ARG BUILDPLATFORM TARGETPLATFORM
RUN echo "Build: $BUILDPLATFORM  →  Target: $TARGETPLATFORM"

LABEL org.opencontainers.image.title="Inventory Manager"
LABEL org.opencontainers.image.description="库存管理系统 - 支持ARM64和AMD64架构"

WORKDIR /app

# 换阿里云 apt 镜像
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list

# 只装运行时依赖：libmariadb（PyMySQL 纯 Python 不需要，但保留以防直接用 mysqlclient）
# curl 用于 HEALTHCHECK，tzdata 设置时区，poppler-utils 用于 pdf2image（面单打印）
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev \
    curl \
    tzdata \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制已编译的 wheels 并安装（全离线，极快）
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

# ── 时区 ──────────────────────────────────────────────────────────────────────
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# ── 环境变量 ──────────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=app.py \
    FLASK_ENV=production \
    LOG_LEVEL=INFO \
    LOG_FILE=logs/inventory_service.log \
    SESSION_COOKIE_SECURE=false \
    SESSION_COOKIE_HTTPONLY=true \
    SESSION_COOKIE_SAMESITE=Lax \
    CORS_ORIGINS=* \
    DEFAULT_RENTAL_DAYS=7 \
    MAX_RENTAL_DAYS=30 \
    MIN_ADVANCE_BOOKING_DAYS=1 \
    TIMEZONE=Asia/Shanghai \
    MAX_CONTENT_LENGTH=16777216 \
    UPLOAD_FOLDER=uploads \
    CACHE_TYPE=simple \
    CACHE_DEFAULT_TIMEOUT=300 \
    POSTS_PER_PAGE=20 \
    DB_POOL_SIZE=10 \
    DB_POOL_RECYCLE=3600 \
    DB_POOL_PRE_PING=true \
    APP_PORT=5002 \
    APP_HOST=0.0.0.0 \
    HEALTH_CHECK_ENABLED=true \
    HEALTH_CHECK_TIMEOUT=30

# ── 应用代码 ──────────────────────────────────────────────────────────────────
COPY . .

RUN mkdir -p logs uploads static/uploads tmp && \
    chmod +x app.py

# 非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app/static /app/logs /app/uploads

USER appuser

EXPOSE 5002

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5002/ || exit 1

CMD ["gunicorn", "--config", "gunicorn_config.py", "run:app"]
