# 🔍 XianyuAutoAgent 项目结构全面探索报告

**探索时间**: 2026-04-25  
**项目根路径**: `/Users/jimmypan/git_repo/XianyuAutoAgent`

---

## 📋 目录结构概览

```
XianyuAutoAgent/
├── ai_kefu/                    # ✅ AI 客服系统（主要服务）
├── InventoryManager/           # ✅ 库存管理系统
├── cocs/                       # 其他服务
├── tools/                      # 工具模块
├── docs/                       # 文档
├── .git/                       # Git 仓库
└── [配置文件和说明文档]
```

---

## 🎯 三个主要服务的位置

### 1️⃣ **拦截器服务 (Interceptor)**

**位置**: `ai_kefu/xianyu_interceptor/` 和 `ai_kefu/scripts/interceptor/`

**核心文件**:
- `ai_kefu/xianyu_interceptor/` - 完整的拦截器模块
  - `cdp_interceptor.py` - Chrome DevTools Protocol 拦截器
  - `browser_controller.py` - 浏览器控制
  - `conversation_store.py` - 对话存储
  - `messaging_core.py` - 消息处理核心
  - 以及 20+ 个支持模块

- `ai_kefu/scripts/interceptor/` - 拦截器部署脚本
  - `install.sh` - 安装脚本
  - `run.sh` - 运行脚本
  - `requirements.interceptor.txt` - 拦截器依赖

**启动命令**:
```bash
cd ai_kefu
make run-xianyu                    # 启动浏览器模式拦截器
python run_xianyu.py              # 直接运行
```

---

### 2️⃣ **API 服务 (API Backend)**

**位置**: `ai_kefu/api/`

**核心文件**:
- `ai_kefu/api/main.py` - FastAPI 应用入口
- `ai_kefu/api/models.py` - Pydantic 数据模型
- `ai_kefu/api/dependencies.py` - 依赖注入配置
- `ai_kefu/api/routes/` - API 路由（包含多个端点）

**Dockerfile**:
- `ai_kefu/Dockerfile.api` - 生产环境 API 镜像

**启动命令**:
```bash
cd ai_kefu
make run-api                       # 生产模式（4个worker）
make run-api-dev                   # 开发模式（热重载）
```

**技术栈**:
- FastAPI 0.108.0
- Uvicorn (ASGI 服务器)
- Gunicorn (WSGI 应用服务器)
- Pydantic 2.5.0

---

### 3️⃣ **AI 控制台 (Console/Admin UI)**

**位置**: `ai_kefu/ui/`

**包含两个 Vue3 SPA**:

**A. 知识库管理 UI**
- 位置: `ai_kefu/ui/knowledge/`
- 构建工具: Vite
- 框架: Vue 3
- 构建脚本: `npm run build` → 输出到 `/dist`

**B. 对话管理 UI**
- 位置: `ai_kefu/ui/conversations/`
- 构建工具: Vite  
- 框架: Vue 3
- 构建脚本: `npm run build` → 输出到 `/dist`

**Dockerfile**:
- `ai_kefu/Dockerfile.console` - 包含两个 UI + Nginx 反向代理

**Nginx 配置**:
- `ai_kefu/docker/nginx.console.conf` - 路由配置
  - `/ui/knowledge/` → 知识库 UI
  - `/ui/conversations/` → 对话管理 UI
  - `/` → 反向代理到 API (8000)

**启动命令**:
```bash
cd ai_kefu
make ui-install                    # 安装依赖
make ui-dev                        # 开发模式（:5173）
make ui-build                      # 生产构建
```

---

## 🐳 Dockerfile 文件位置汇总

| # | 文件 | 位置 | 镜像类型 | 基础镜像 | 平台 |
|----|------|------|--------|--------|------|
| 1 | Dockerfile | `ai_kefu/` | 轻量级 API (Alpine) | python:3.10-alpine | x86 |
| 2 | Dockerfile.api | `ai_kefu/` | **生产 API** | python:3.10-slim | linux/amd64 |
| 3 | Dockerfile.console | `ai_kefu/` | **Web 控制台** | node:20 + nginx:1.26 | linux/amd64 |
| 4 | Dockerfile | `ai_kefu/xianyu_provider/upstream/` | 上游提供者 | python:3.12-slim | 默认 |
| 5 | Dockerfile | `InventoryManager/` | **库存管理** | python:3.10-slim-bookworm | 多架构 |

**注**:
- 推荐使用 `Dockerfile.api` 和 `Dockerfile.console` (支持 linux/amd64)
- 原始 `Dockerfile` 使用 Alpine，不如 slim/bookworm 稳定

---

## 🔧 Docker Compose 配置

### ai_kefu/docker-compose.yml

**服务**:
1. **XianyuAutoAgent** (AI 客服机器人)
   - 镜像: `shaxiu/xianyuautoagent:latest`
   - 端口: 8000
   - 依赖: MySQL, Redis
   
2. **MySQL 8.0**
   - 容器名: `xianyu-mysql`
   - 端口: 3306
   - 数据库: xianyu
   
3. **Redis 7-Alpine**
   - 容器名: `xianyu-redis`
   - 端口: 6379
   - 持久化: RDB + AOF

**网络**: `xianyu-network` (bridge)

---

### InventoryManager/docker-compose.yml

**服务**:
1. **MySQL 8.0**
   - 容器名: `inventory_mysql`
   - 数据库: inventory_db
   - 端口: 3306
   
2. **Redis 7-Alpine**
   - 容器名: `inventory_redis`
   - 端口: 6379
   
3. **应用 (Flask)**
   - 构建: 本地 Dockerfile
   - 容器名: `inventory_app`
   - 端口: 5001
   - 依赖: MySQL, Redis
   
4. **Nginx (可选)**
   - 镜像: `nginx:alpine`
   - 端口: 80, 443
   - 反向代理到应用

**网络**: `inventory_network` (bridge)

---

## 🛠️ 构建配置和命令

### ai_kefu/Makefile

**构建 Docker 镜像**:
```bash
make build-api                     # 构建 API 镜像 (linux/amd64)
make build-console                 # 构建控制台镜像
make build-all                     # 同时构建两个

# 镜像标签控制
IMAGE_TAG=20260425-0903 make build-all
```

**镜像仓库配置**:
```makefile
REGISTRY      := docker.cnb.cool/tdcc-demo/jimmy
API_IMAGE     := $(REGISTRY)/aikefu-api
CONSOLE_IMAGE := $(REGISTRY)/aikefu-console
IMAGE_TAG     ?= $(shell date +%Y%m%d-%H%M)  # YYYYMMDD-HHMM
```

**推送镜像**:
```bash
make push-api                      # 推送 API 镜像
make push-console                  # 推送控制台镜像
make push-all                       # 推送全部
```

**其他命令**:
```bash
make run-xianyu                    # 启动拦截器
make run-api                       # 启动 API 服务
make ui-build                      # 构建 UI
make init-knowledge                # 初始化知识库
```

---

### InventoryManager/Makefile

**主要命令**:
```bash
make docker-build                  # 构建镜像
make docker-up                     # 启动容器
make docker-down                   # 停止容器
```

---

## 📦 package.json 文件位置

### ai_kefu/ui/knowledge/package.json
```json
{
  "name": "knowledge-management-ui",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }
}
```

### ai_kefu/ui/conversations/package.json
- 对话管理 UI

### InventoryManager/frontend/package.json
- 库存管理前端
- Node 版本: ^20.19.0 || >=22.12.0
- 框架: Vue 3 + TypeScript + Element Plus

---

## 📋 requirements.txt 依赖

**位置**: `ai_kefu/requirements.txt`

**核心依赖**:
- OpenAI SDK (1.65.5)
- FastAPI (0.108.0)
- Uvicorn (0.25.0)
- Gunicorn (21.2.0)
- ChromaDB (1.4.0) - 向量数据库
- Redis (5.0.1)
- PyMySQL (1.1.0)
- Playwright (>=1.40.0) - 浏览器自动化
- PyExecJS (>=1.5.1) - 闲鱼签名算法

**拦截器特定依赖**: `ai_kefu/scripts/interceptor/requirements.interceptor.txt`

---

## 🔐 镜像仓库配置

### 主要镜像仓库

**Registry**: `docker.cnb.cool`
```
Registry: docker.cnb.cool/tdcc-demo/jimmy

镜像列表:
- docker.cnb.cool/tdcc-demo/jimmy/aikefu-api:[TAG]
- docker.cnb.cool/tdcc-demo/jimmy/aikefu-console:[TAG]
```

**镜像标签策略**:
- 默认: `YYYYMMDD-HHMM` (如 `20260425-0903`)
- 手动指定: `IMAGE_TAG=xxx make build-all`

### 其他镜像

**开源镜像** (在 docker-compose 中使用):
- `mysql:8.0` - MySQL 数据库
- `redis:7-alpine` - Redis 缓存
- `node:20-alpine` - Node.js 构建环境
- `nginx:1.26-alpine` - Nginx 反向代理

---

## ❌ GitHub Workflows

**状态**: 未配置

**当前**: 没有 `.github/workflows/` 目录

**建议创建**:
- `build-and-push.yml` - Docker 镜像构建和推送
- `tests.yml` - 自动化测试
- `lint.yml` - 代码检查

---

## 📁 关键配置文件清单

### 环境变量文件 (.env)

| 文件 | 位置 | 状态 |
|------|------|------|
| .env | `ai_kefu/` | ✅ 存在 |
| .env.example | `ai_kefu/` | ✅ 存在 |
| .env | `InventoryManager/` | ✅ 存在 |
| .env.docker | `InventoryManager/` | ✅ 存在 |
| .env.example | `InventoryManager/` | ✅ 存在 |

### Docker 特定配置

| 文件 | 位置 | 用途 |
|------|------|------|
| .dockerignore | `ai_kefu/` | Docker 构建忽略 |
| .dockerignore | `InventoryManager/` | Docker 构建忽略 |
| nginx.console.conf | `ai_kefu/docker/` | Nginx 路由配置 |
| nginx.conf | `InventoryManager/docker/nginx/` | Nginx 配置 |

---

## 🚀 部署架构

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Registry                        │
│      docker.cnb.cool/tdcc-demo/jimmy/                    │
└─────────────────────────────────────────────────────────┘
                           ↓
              ┌────────────┴────────────┐
              ↓                         ↓
    ┌──────────────────┐      ┌──────────────────┐
    │  aikefu-api      │      │ aikefu-console   │
    │  (Python 3.10)   │      │ (Node 20 + Nginx)│
    │  FastAPI/Gunicorn│      │ Knowledge + Conv │
    │  Port: 8000      │      │ Port: 80         │
    └────────┬─────────┘      └──────────────────┘
             │
    ┌────────┴──────────┐
    ↓                   ↓
┌─────────┐         ┌─────────┐
│ MySQL   │         │ Redis   │
│ Port3306│         │Port 6379│
└─────────┘         └─────────┘
```

---

## 📊 服务端口映射

| 服务 | 容器端口 | 主机端口 | 协议 |
|------|---------|---------|------|
| AI API | 8000 | 8000 | HTTP |
| Console/Nginx | 80 | 80 | HTTP |
| MySQL | 3306 | 3306 | TCP |
| Redis | 6379 | 6379 | TCP |
| InventoryManager App | 5001 | 5001 | HTTP |
| InventoryManager Nginx | 80/443 | 80/443 | HTTP/HTTPS |

---

## 🔍 文件大小统计

```
Total Project Size: ~3-4 GB (包含 node_modules 和 .venv)

关键目录:
- ai_kefu/                : ~2 GB (含依赖)
- InventoryManager/       : ~1 GB (含依赖)
- ai_kefu/ui/knowledge/   : ~500 MB
- ai_kefu/ui/conversations: ~300 MB
```

---

## ✅ 检查清单

- [x] 三个服务位置已确定
- [x] 所有 Dockerfile 已找到
- [x] docker-compose 配置已找到
- [x] Makefile 构建命令已记录
- [x] 镜像仓库配置已提取
- [x] package.json 已定位
- [x] requirements.txt 已定位
- [x] 环境变量文件已列举
- [ ] GitHub Workflows 未配置（需要创建）

---

## 📞 后续建议

1. **创建 CI/CD 流程** - 建立 GitHub Actions 自动构建和推送
2. **容器镜像优化** - 考虑进一步减小镜像大小
3. **安全扫描** - 集成容器安全扫描工具
4. **多架构支持** - 扩展到 ARM64 支持
5. **本地开发** - 创建完整的 docker-compose 本地开发环境
