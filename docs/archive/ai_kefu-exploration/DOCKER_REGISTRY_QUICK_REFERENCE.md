# Docker Registry & CI/CD 快速参考指南

## 📦 当前镜像配置

### Docker Hub Registry

**组织**: `shaxiu`  
**镜像库**: `xianyuautoagent:latest`  

```yaml
# ai_kefu/docker-compose.yml 中的配置
services:
  XianyuAutoAgent:
    image: shaxiu/xianyuautoagent:latest
```

---

## 🏗️ Dockerfile 多镜像构建策略

### 镜像列表

| Dockerfile | 用途 | 目标架构 | 镜像名建议 |
|-----------|------|--------|----------|
| `ai_kefu/Dockerfile` | 轻量级 API | 多 (alpine) | `ai-kefu-light` |
| `ai_kefu/Dockerfile.api` | 生产 API | amd64 | `ai-kefu-api` |
| `ai_kefu/Dockerfile.console` | 管理控制台 | amd64 | `ai-kefu-console` |
| `ai_kefu/xianyu_provider/upstream/Dockerfile` | 上游提供者 | 多 | `xianyu-provider` |
| `InventoryManager/Dockerfile` | 库存系统 | 多 | `inventory-manager` |

---

## 🔐 必需的 Secrets (GitHub Actions)

### 创建步骤

1. 进入仓库设置: Settings → Secrets and variables → Actions
2. 添加以下 Secrets:

| Secret 名称 | 用途 | 示例 |
|-----------|------|------|
| `DOCKER_USERNAME` | Docker Hub 用户名 | `shaxiu` |
| `DOCKER_PASSWORD` | Docker Hub PAT/密码 | `dckr_pat_xxxxx` |
| `DOCKER_REGISTRY` | 镜像仓库地址 | `docker.io` (默认) 或私有地址 |
| `REGISTRY_PREFIX` | 镜像前缀 | `shaxiu/` |

### 登录 Docker Hub 获取 PAT

```bash
# 1. 访问 https://hub.docker.com/settings/personal-access-tokens
# 2. 点击 "Generate New Token"
# 3. 选择权限: Read & Write (用于推送镜像)
# 4. 复制 token 作为 DOCKER_PASSWORD
```

---

## 🔨 本地构建与推送命令

### 单个镜像构建

```bash
# AI Kefu API (生产环境)
docker build -f ai_kefu/Dockerfile.api \
  -t shaxiu/ai-kefu-api:v1.0.0 \
  -t shaxiu/ai-kefu-api:latest \
  ai_kefu/

# AI Kefu 管理控制台
docker build -f ai_kefu/Dockerfile.console \
  -t shaxiu/ai-kefu-console:v1.0.0 \
  ai_kefu/

# 库存管理系统
docker build -f InventoryManager/Dockerfile \
  -t shaxiu/inventory-manager:v1.0.0 \
  InventoryManager/
```

### 多架构构建 (Buildx)

```bash
# 启用 Docker Buildx
docker buildx create --use

# 构建并推送多架构镜像
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f ai_kefu/Dockerfile.api \
  -t shaxiu/ai-kefu-api:v1.0.0 \
  -t shaxiu/ai-kefu-api:latest \
  --push \
  ai_kefu/
```

### 推送到 Docker Hub

```bash
# 登录
docker login -u shaxiu

# 推送
docker push shaxiu/ai-kefu-api:v1.0.0
docker push shaxiu/ai-kefu-api:latest
```

---

## 📋 环境变量注入

### Dockerfile 中的变量替换

#### ai_kefu/Dockerfile.console 中的 Nginx 配置

```nginx
# 运行时通过 envsubst 处理
location / {
    proxy_pass http://${API_HOST:-api}:${API_PORT:-8000};
}
```

**运行时设置**:
```bash
docker run -e API_HOST=api.example.com -e API_PORT=8000 shaxiu/ai-kefu-console
```

### Docker Compose 环境变量

```yaml
# .env 文件
DATABASE_URL=mysql+pymysql://user:pass@mysql:3306/db
REDIS_URL=redis://redis:6379/0
API_HOST=api
API_PORT=8000
```

---

## 🚀 推荐的镜像标签策略

### 标签规范

```
shaxiu/<镜像名>:<标签>

标签格式:
  - latest          : 最新生产版本
  - v1.0.0          : 语义化版本
  - main-<sha>      : 对应 main 分支提交
  - feature-<name>  : 特性分支版本
  - dev             : 开发环境版本
```

### 示例

```bash
# 语义化版本
docker tag ai-kefu:v1.0.0 shaxiu/ai-kefu-api:v1.0.0
docker push shaxiu/ai-kefu-api:v1.0.0

# Git commit SHA
docker tag ai-kefu:$(git rev-parse --short HEAD) \
  shaxiu/ai-kefu-api:main-$(git rev-parse --short HEAD)

# 分支提交
docker tag ai-kefu:latest shaxiu/ai-kefu-api:latest
```

---

## 🔄 完整 CI/CD 流程

### 1️⃣ 本地开发

```bash
# 修改代码
git add .
git commit -m "feat: add new feature"

# 本地测试
docker compose -f ai_kefu/docker-compose.yml up
```

### 2️⃣ 推送到 GitHub

```bash
git push origin main
```

### 3️⃣ GitHub Actions 自动执行

- ✅ 代码检查 (Lint, Type Check)
- ✅ 单元测试
- ✅ Docker 镜像构建
- ✅ 镜像推送到 Docker Hub
- ✅ 部署通知

### 4️⃣ 拉取最新镜像

```bash
docker pull shaxiu/ai-kefu-api:latest
```

---

## 📝 创建新的 GitHub Actions 工作流

### 文件位置

```
.github/
├── workflows/
│   ├── docker-build.yml          # Docker 镜像构建
│   ├── tests.yml                 # 单元测试
│   ├── lint.yml                  # 代码检查
│   ├── security.yml              # 安全扫描
│   └── deploy.yml                # 部署流程
```

### 最小化工作流示例

```yaml
# .github/workflows/docker-build.yml
name: Build Docker Images

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}
      
      - name: Build and push AI Kefu API
        uses: docker/build-push-action@v5
        with:
          context: ai_kefu
          file: ai_kefu/Dockerfile.api
          push: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}
          tags: |
            shaxiu/ai-kefu-api:latest
            shaxiu/ai-kefu-api:${{ github.sha }}
```

---

## 🐛 常见问题排查

### 问题 1: Docker Hub 登录失败

```bash
# 确保使用 PAT 而非密码
# Settings → Personal Access Tokens → 生成新 token

# 测试登录
echo "PAT_HERE" | docker login -u shaxiu --password-stdin
```

### 问题 2: 多架构构建缓慢

```bash
# 本地构建单架构用于测试
docker build -f ai_kefu/Dockerfile.api \
  --platform linux/amd64 \
  -t shaxiu/ai-kefu-api:test \
  ai_kefu/

# 完整多架构构建用于生产
docker buildx build --push \
  --platform linux/amd64,linux/arm64 \
  ...
```

### 问题 3: 环境变量未生效

```bash
# 确保在 docker run 或 docker-compose 中正确传递
docker run -e MY_VAR=value shaxiu/my-image

# docker-compose.yml
environment:
  - MY_VAR=value
```

---

## 📊 镜像大小优化

### 检查镜像大小

```bash
docker images shaxiu/ai-kefu-api
# REPOSITORY          TAG       SIZE
# shaxiu/ai-kefu-api  latest    450MB

# 使用 dive 工具分析
dive shaxiu/ai-kefu-api:latest
```

### 优化方向

| 策略 | 效果 | 难度 |
|------|------|------|
| 使用 alpine 基础镜像 | -60% | ⭐ |
| 多阶段构建 | -40% | ⭐⭐ |
| 移除缓存 | -10% | ⭐ |
| 非 root 用户 | 无大小改变 | ⭐⭐ |

---

## 🔒 安全最佳实践

### 1. 不提交敏感信息

```bash
# ❌ 不要这样做
COPY .env .env

# ✅ 这样做
COPY .env.example .env.example

# 使用环境变量或 Docker secrets
docker run --secret db_password ...
```

### 2. 镜像签名与扫描

```bash
# 启用 Docker Content Trust (DCT)
export DOCKER_CONTENT_TRUST=1
docker push shaxiu/ai-kefu-api:v1.0.0

# 使用 Trivy 扫描漏洞
trivy image shaxiu/ai-kefu-api:latest
```

### 3. 限制镜像权限

```dockerfile
# 以非 root 用户运行
RUN useradd -m -u 1000 appuser
USER appuser
```

---

## 📚 相关文件路径

```
XianyuAutoAgent/
├── ai_kefu/
│   ├── Dockerfile                    # 轻量级镜像
│   ├── Dockerfile.api                # 生产 API
│   ├── Dockerfile.console            # 管理控制台
│   ├── docker-compose.yml            # 完整栈编排
│   ├── docker/nginx.console.conf     # Nginx 配置
│   ├── requirements.txt              # Python 依赖
│   ├── setup.py                      # 包配置
│   ├── .env                          # 环境变量 (勿提交)
│   └── .env.example                  # 环境变量模板
│
├── InventoryManager/
│   ├── Dockerfile                    # 多架构支持
│   ├── docker-compose.yml            # 库存系统栈
│   ├── docker/nginx/nginx.conf       # Nginx 配置
│   ├── requirements.txt              # Python 依赖
│   ├── frontend/package.json         # Node 依赖
│   ├── .env                          # 环境变量 (勿提交)
│   ├── .env.docker                   # Docker 环境变量
│   └── .env.example                  # 环境变量模板
│
└── .github/
    └── workflows/                    # ❌ 需创建
        ├── docker-build.yml          # Docker CI
        ├── tests.yml                 # 测试 CI
        ├── lint.yml                  # Lint CI
        └── deploy.yml                # 部署流程
```

---

## 🎯 优先级行动清单

### 第一阶段 (立即)
- [ ] 添加 GitHub Actions Secrets (DOCKER_USERNAME, DOCKER_PASSWORD)
- [ ] 创建 `.github/workflows/docker-build.yml`
- [ ] 验证本地 Docker 构建命令

### 第二阶段 (本周)
- [ ] 完整测试 CI/CD 流程
- [ ] 设置镜像签名与扫描
- [ ] 统一镜像标签策略

### 第三阶段 (本月)
- [ ] 迁移到私有镜像仓库 (如需)
- [ ] 添加 Kubernetes 部署配置
- [ ] 完善灾难恢复策略

---

## 📞 参考链接

- Docker Hub: https://hub.docker.com/
- Docker Buildx: https://docs.docker.com/buildx/working-with-buildx/
- GitHub Actions: https://docs.github.com/actions
- Trivy 镜像扫描: https://github.com/aquasecurity/trivy

