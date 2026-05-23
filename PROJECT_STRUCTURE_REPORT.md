# XianyuAutoAgent 项目完整结构探索报告

**生成时间**: 2026-04-24  
**项目名称**: XianyuAutoAgent  
**Repository**: `git@github.com:xeonselina/XianyuAutoAgent.git`  
**当前分支**: main  

---

## 1️⃣ 项目根目录结构

```
XianyuAutoAgent/
├── ai_kefu/                          # 闲鱼 AI 客服机器人（核心业务）
├── InventoryManager/                 # 库存管理系统
├── cocs/                             # COCS 模块
├── tools/                            # 工具模块
├── data/                             # 数据目录
├── chroma_data/                      # Chroma 向量数据库存储
├── docs/                             # 文档目录
├── .github/                          # ❌ 不存在（需创建 GitHub Actions）
├── .git/                             # Git 仓库信息
├── .gitignore                        # Git 忽略文件
├── .gitmodules                       # Git 子模块配置
├── README_AI_EVALUATION_FEATURE.md   # AI 评估功能文档
├── AI_EVALUATION_*.md                # AI 评估相关文档（多个）
├── CODE_FLOW_SUMMARY.txt             # 代码流程总结
├── system_prompt_analysis.md         # 系统提示词分析
└── CLAUDE.md                         # Claude AI 助手指令
```

---

## 2️⃣ Dockerfile 文件清单

### 📍 位置与内容

| 路径 | 基础镜像 | 架构 | 端口 | 主要特性 |
|------|--------|------|------|---------|
| `ai_kefu/Dockerfile` | python:3.10-alpine | 多架构 | 8000 | 轻量级 FastAPI 应用 |
| `ai_kefu/Dockerfile.api` | python:3.10-slim (amd64) | linux/amd64 | 8000 | FastAPI + gunicorn + uvicorn workers |
| `ai_kefu/Dockerfile.console` | node:20 + nginx | linux/amd64 | 80 | 两个 Vue3 SPA + nginx 反向代理 |
| `ai_kefu/xianyu_provider/upstream/Dockerfile` | python:3.12-slim | - | - | Node.js + Python 混合运行 |
| `InventoryManager/Dockerfile` | python:3.10-slim-bookworm | 多架构 | 5002 | Flask + gunicorn，支持 ARM64/AMD64 |

### 🔍 关键构建阶段

#### ai_kefu/Dockerfile.api (多阶段构建)
```
Stage 1: builder (python:3.10-slim)
  - 安装编译依赖 (gcc, g++, build-essential, libffi-dev, libssl-dev)
  - 创建虚拟环境: /opt/venv
  - 安装 Python 依赖: pip install -r requirements.txt

Stage 2: 最终镜像 (python:3.10-slim)
  - 复制虚拟环境: COPY --from=builder /opt/venv /opt/venv
  - 安装运行时依赖: tzdata, nodejs (PyExecJS 运行时)
  - 工作目录: /workspace
  - 启动命令: gunicorn ai_kefu.api.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

#### ai_kefu/Dockerfile.console (3个构建阶段)
```
Stage 1: builder-knowledge (node:20-alpine)
  - 构建知识库管理 UI
  - 路径: ui/knowledge → dist
  - 基础路径: /ui/knowledge/

Stage 2: builder-conversations (node:20-alpine)
  - 构建对话管理 UI
  - 路径: ui/conversations → dist
  - 基础路径: /ui/conversations/

Stage 3: nginx:1.26-alpine
  - 复制两个 UI 构建产物到 /usr/share/nginx/html/
  - 使用 envsubst 支持运行时环境变量注入
```

#### InventoryManager/Dockerfile (多架构)
```
基础: python:3.10-slim-bookworm
构建参数: TARGETPLATFORM, BUILDPLATFORM (支持多架构)
运行时依赖: build-essential, libmysqlclient-dev, libssl-dev, 等
启动命令: gunicorn --config gunicorn_config.py run:app
```

---

## 3️⃣ docker-compose 文件

### 📍 ai_kefu/docker-compose.yml

**服务架构**:
```yaml
XianyuAutoAgent (custom image: shaxiu/xianyuautoagent:latest)
  └─ 依赖
     ├─ mysql:8.0 (xianyu-mysql:3306)
     └─ redis:7-alpine (xianyu-redis:6379)

网络: xianyu-network (bridge)
```

**主要配置**:
- 自动重启: `restart: always`
- 数据持久化: data/, prompts/, .env volume 挂载
- MySQL 凭证: MYSQL_ROOT_PASSWORD (在 .env 中)
- Redis 数据存储: redis_data volume
- 环境变量: TZ=Asia/Shanghai

### 📍 InventoryManager/docker-compose.yml

**服务架构**:
```yaml
Services:
  mysql:8.0          → inventory_mysql:3306
  redis:7-alpine     → inventory_redis:6379
  app (build)        → inventory_app:5001
  nginx:alpine       → inventory_nginx:80/443

网络: inventory_network (bridge)
```

**健康检查配置**:
- MySQL: mysqladmin ping (interval: 10s, timeout: 20s, retries: 10)
- Redis: redis-cli ping (interval: 10s, timeout: 3s, retries: 5)
- App: curl http://localhost:5001/ (interval: 30s, timeout: 10s, retries: 3)
- Nginx: curl http://localhost/health (interval: 30s)

**数据持久化**:
- mysql_data
- redis_data
- app_logs
- app_uploads

---

## 4️⃣ GitHub Actions 工作流 (.github/workflows/)

**状态**: ❌ 目录不存在，需要创建

### 推荐创建的工作流文件:

1. **docker-build-push.yml** - Docker 镜像构建与推送
2. **tests.yml** - 单元测试与集成测试
3. **lint.yml** - 代码质量检查 (ruff, mypy, eslint)
4. **security.yml** - 安全扫描 (Dependabot, SAST)
5. **deploy.yml** - 部署流程

---

## 5️⃣ 技术栈判断

### ai_kefu (Python)

**构建配置文件**:
- `requirements.txt` - 核心依赖
- `setup.py` - 包配置

**主要技术栈**:
```
Web Framework:
  - FastAPI==0.108.0
  - uvicorn[standard]==0.25.0
  - gunicorn==21.2.0

AI/ML:
  - openai==1.65.5 (连接阿里云百炼平台)
  - chromadb==1.4.0 (向量数据库)

浏览器自动化:
  - playwright>=1.40.0

数据库:
  - redis==5.0.1
  - pymysql==1.1.0

其他:
  - pydantic==2.5.0
  - requests==2.32.3
  - websockets==13.1
  - dingtalk-stream>=0.24.0
  - PyExecJS>=1.5.1 (Node.js 运行时)

开发工具:
  - pytest==7.4.3
  - ruff==0.1.9
  - mypy==1.7.1
```

### InventoryManager (Flask + Vue3)

**后端** - Python (Flask):
- `requirements.txt`
- Flask-based web application
- Gunicorn WSGI server

**前端** - Node.js (Vue3):
- `frontend/package.json`
- Vue 3 (^3.5.18)
- Vite 构建器 (^7.0.6)
- TypeScript (~5.8.0)
- Element Plus UI (^2.11.1)
- 其他库: axios, echarts, pinia, dayjs, qrcode, jsbarcode

---

## 6️⃣ 仓库信息

### Git Remote
```
Repository Name: XianyuAutoAgent
SSH URL: git@github.com:xeonselina/XianyuAutoAgent.git
GitHub Organization: xeonselina
```

### 分支信息
```
本地分支:
  - main (当前)
  - 001-ai-customer-service-agent
  - 001-useragent-detection
  - 002-device-inspection
  - 002-gantt-date-labels
  - cocs
  - feat/phone_rent

远程分支 (xianyuagent_ssh):
  - main
  - 001-ai-customer-service-agent
  - 001-simplify-rental-accessories
  - 002-device-inspection
  - 002-gantt-date-labels
  - 003-mobile-frontend
  - cocs
  - feat/phone_rent
```

### 最近提交
```
47ba836 11
ca297a9 docs: Add delivery summary for AI evaluation feature
f8df72d docs: Add master README for AI evaluation feature
49f7231 docs: Add comprehensive AI evaluation feature documentation
cb2d284 feat: Add AI evaluation feature for conversation comparison
```

---

## 7️⃣ 镜像仓库配置

### 已配置的 Registry

#### ai_kefu/docker-compose.yml
```yaml
image: shaxiu/xianyuautoagent:latest
```
- Registry: Docker Hub
- 用户名: shaxiu
- 镜像名: xianyuautoagent
- 标签: latest

#### 推荐配置结构

**环境变量配置** (.env / .env.local):
```
# Docker Registry 配置
DOCKER_REGISTRY=docker.io              # 或私有镜像仓库地址
DOCKER_USERNAME=<username>
DOCKER_PASSWORD=<password>

# 镜像标签配置
IMAGE_TAG=v1.0.0                       # 或 git 标签/提交 SHA
REGISTRY_PREFIX=shaxiu/                # 或组织名

# 具体镜像
AI_KEFU_IMAGE=shaxiu/xianyuautoagent:latest
INVENTORY_MGR_IMAGE=<org>/inventory-manager:latest
CONSOLE_IMAGE=<org>/xianyu-console:latest
```

### .env 文件现状

| 文件路径 | 包含内容 | 敏感信息 |
|--------|--------|--------|
| `ai_kefu/.env` | ✅ 存在 | API_KEY, 数据库凭证, Redis, DingTalk 密钥 |
| `ai_kefu/.env.example` | ✅ 存在 | 配置模板 |
| `cocs/.env` | ✅ 存在 | 需检查 |
| `cocs/.env.example` | ✅ 存在 | 配置模板 |
| `InventoryManager/.env` | ✅ 存在 | 数据库、API 密钥 |
| `InventoryManager/.env.docker` | ✅ 存在 | Docker 环境变量 |
| `InventoryManager/.env.example` | ✅ 存在 | 配置模板 |

---

## 8️⃣ UI 应用位置与构建

### ai_kefu 中的 Vue3 应用

| 路径 | 用途 | 框架 | 构建输出 | 启动方式 |
|------|------|------|--------|---------|
| `ai_kefu/ui/knowledge` | 知识库管理 UI | Vue3 + Vite | dist/ | npm ci + npx vite build |
| `ai_kefu/ui/conversations` | 对话管理 UI | Vue3 + Vite | dist/ | npm ci + npx vite build |

### InventoryManager 中的 Vue3 应用

| 路径 | 用途 | 框架 | Node 版本要求 |
|------|------|------|-------------|
| `InventoryManager/frontend` | 库存管理前端 | Vue3 + Vite + TypeScript | ^20.19.0 \|\| >=22.12.0 |

---

## 9️⃣ API 模块结构

### ai_kefu/api/

```
api/
├── __init__.py
├── main.py (FastAPI 应用入口)
├── dependencies.py (依赖注入)
├── models.py (数据模型)
└── routes/
    ├── ai_reply.py
    ├── conversations.py
    ├── knowledge_base.py
    └── [其他路由]
```

**FastAPI 启动命令**:
```bash
gunicorn ai_kefu.api.main:app -w 4 -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 --timeout 120 --access-logfile -
```

---

## 🔟 核心配置文件清单

| 文件 | 位置 | 类型 | 用途 |
|------|------|------|------|
| Dockerfile | ai_kefu/ | 容器 | Alpine 轻量级镜像 |
| Dockerfile.api | ai_kefu/ | 容器 | 生产 API 镜像 (amd64) |
| Dockerfile.console | ai_kefu/ | 容器 | 管理控制台 (nginx) |
| docker-compose.yml | ai_kefu/ | 编排 | 完整服务栈 |
| docker-compose.yml | InventoryManager/ | 编排 | 库存系统栈 |
| requirements.txt | ai_kefu/ | Python | 依赖列表 |
| requirements.txt | InventoryManager/ | Python | 依赖列表 |
| setup.py | ai_kefu/ | Python | 包配置 |
| package.json | InventoryManager/frontend/ | Node | 前端依赖 |
| nginx.conf | InventoryManager/docker/ | Nginx | Web 服务器配置 |
| nginx.console.conf | ai_kefu/docker/ | Nginx | 控制台反向代理配置 |
| .env | 各模块 | 配置 | 敏感信息（勿提交） |
| .env.example | 各模块 | 配置 | 配置模板 |

---

## 1️⃣1️⃣ 推荐的 GitHub Actions 工作流

### 模板 1: Docker 多架构构建与推送

```yaml
name: Build and Push Docker Images

on:
  push:
    branches: [main]
    tags: ['v*']
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        image:
          - name: ai-kefu-api
            dockerfile: ai_kefu/Dockerfile.api
            context: ai_kefu
          - name: ai-kefu-console
            dockerfile: ai_kefu/Dockerfile.console
            context: ai_kefu
          - name: inventory-manager
            dockerfile: InventoryManager/Dockerfile
            context: InventoryManager

    steps:
      - uses: actions/checkout@v4
      
      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: ${{ matrix.image.context }}
          file: ${{ matrix.image.dockerfile }}
          platforms: linux/amd64,linux/arm64
          push: ${{ github.event_name == 'push' }}
          tags: |
            ${{ secrets.DOCKER_REGISTRY }}/${{ matrix.image.name }}:latest
            ${{ secrets.DOCKER_REGISTRY }}/${{ matrix.image.name }}:${{ github.sha }}
```

### 模板 2: Python 测试与 Lint

```yaml
name: Tests and Lint

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']

    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install -r ai_kefu/requirements.txt
          pip install pytest pytest-cov ruff mypy
      
      - name: Lint with ruff
        run: ruff check ai_kefu/
      
      - name: Type check with mypy
        run: mypy ai_kefu/
      
      - name: Run tests
        run: pytest ai_kefu/tests/ --cov=ai_kefu
```

---

## 📋 总结表格

| 组件 | 技术 | 状态 | 优先级 |
|------|------|------|--------|
| **Docker 镜像** | Python 3.10/3.12, Node 20 | ✅ 完成 | ⭐⭐⭐ |
| **docker-compose** | 完整栈定义 | ✅ 完成 | ⭐⭐⭐ |
| **GitHub Actions** | CI/CD 流程 | ❌ 缺失 | ⭐⭐⭐ |
| **镜像仓库** | Docker Hub (shaxiu/*) | ⚠️ 部分配置 | ⭐⭐ |
| **环境变量** | .env 文件 | ✅ 完成 | ⭐⭐ |
| **API 文档** | FastAPI (自动生成) | ✅ 完成 | ⭐ |
| **前端构建** | Vite + Vue3 | ✅ 完成 | ⭐⭐ |

---

## 🚀 下一步行动

1. **创建 `.github/workflows/` 目录** 并添加 CI/CD 流程
2. **规范 Docker Registry 配置** 统一镜像命名和标签策略
3. **添加 Kubernetes 部署配置** (如需容器编排)
4. **完善 GitHub Actions Secrets** 配置
5. **建立镜像扫描与签名流程** 提升安全性

