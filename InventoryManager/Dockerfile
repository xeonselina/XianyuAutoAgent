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

# 只装运行时依赖；数据库、代理和健康检查由运行环境提供。
RUN apt-get update && apt-get install -y --no-install-recommends \
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
    FLASK_APP=run.py \
    FLASK_ENV=production

# ── 应用代码 ──────────────────────────────────────────────────────────────────
COPY . .

RUN mkdir -p logs uploads static/uploads tmp

# 非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app/static /app/logs /app/uploads

USER appuser

EXPOSE 5002

CMD ["gunicorn", "--config", "gunicorn_config.py", "run:app"]
