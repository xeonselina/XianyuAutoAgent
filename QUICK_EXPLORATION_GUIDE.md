# ⚡ XianyuAutoAgent 项目快速导览

**最后更新**: 2026-04-25

---

## 🎯 项目三大服务速查

### 1️⃣ 拦截器 (Interceptor)
- **位置**: `ai_kefu/xianyu_interceptor/` + `ai_kefu/scripts/interceptor/`
- **启动**: `cd ai_kefu && make run-xianyu`
- **核心**: Chrome DevTools Protocol + 浏览器自动化
- **作用**: 拦截闲鱼消息并转发到 API

### 2️⃣ API 服务
- **位置**: `ai_kefu/api/`
- **框架**: FastAPI + Uvicorn + Gunicorn
- **启动**: `cd ai_kefu && make run-api`
- **构建**: `make build-api` (Docker 镜像)
- **端口**: 8000

### 3️⃣ Web 控制台
- **位置**: `ai_kefu/ui/` (knowledge + conversations)
- **框架**: Vue3 + Vite + Nginx
- **启动**: `make ui-build` (生产构建)
- **端口**: 80 (Nginx)
- **构建**: `make build-console` (Docker 镜像)

---

## 📂 关键目录速查

```
XianyuAutoAgent/
├── ai_kefu/                       ← 主系统
│   ├── api/                       ← FastAPI 入口
│   ├── xianyu_interceptor/        ← 拦截器核心
│   ├── ui/knowledge/              ← 知识库 UI
│   ├── ui/conversations/          ← 对话管理 UI
│   ├── scripts/interceptor/       ← 拦截器部署
│   ├── Dockerfile.api             ← API 镜像
│   ├── Dockerfile.console         ← 控制台镜像
│   ├── docker-compose.yml         ← 编排文件
│   ├── Makefile                   ← 构建脚本
│   └── requirements.txt           ← Python 依赖
│
└── InventoryManager/              ← 库存管理系统
    ├── app.py                     ← Flask 应用
    ├── frontend/                  ← Vue3 前端
    ├── Dockerfile
    ├── docker-compose.yml
    └── requirements.txt
```

---

## 🐳 Docker 镜像位置

| 镜像 | Dockerfile | 标签 | 用途 |
|------|-----------|------|------|
| API | `ai_kefu/Dockerfile.api` | `aikefu-api:YYYYMMDD-HHMM` | FastAPI 后台 |
| Console | `ai_kefu/Dockerfile.console` | `aikefu-console:YYYYMMDD-HHMM` | Web 控制台 |
| Inventory | `InventoryManager/Dockerfile` | - | 库存管理 |

**仓库**: `docker.cnb.cool/tdcc-demo/jimmy/`

---

## 🚀 常用命令速查

### 构建镜像

```bash
cd ai_kefu

make build-api              # 构建 API 镜像
make build-console          # 构建控制台镜像
make build-all              # 同时构建两个
make build-all IMAGE_TAG=v1.0.0  # 自定义标签

make push-api               # 推送 API
make push-console           # 推送控制台
make push-all               # 推送全部
```

### 运行服务

```bash
cd ai_kefu

make run-xianyu             # 启动拦截器（浏览器模式）
make run-api                # 启动 API 服务
make run-api-dev            # 开发模式（热重载）
make init-knowledge         # 初始化知识库

make ui-install             # 安装 UI 依赖
make ui-dev                 # UI 开发服务器（:5173）
make ui-build               # 生产构建 UI
```

### Docker Compose

```bash
cd ai_kefu
docker-compose up -d        # 启动 (后台)
docker-compose down         # 停止
docker-compose logs -f      # 查看日志
docker-compose ps           # 查看容器状态
```

---

## 🔧 配置文件速查

### 环境变量

| 文件 | 用途 | 位置 |
|------|------|------|
| .env | 生产配置 | `ai_kefu/` |
| .env.example | 配置模板 | `ai_kefu/` |
| .env.docker | Docker 配置 | `InventoryManager/` |

### Makefile 配置

```makefile
REGISTRY      := docker.cnb.cool/tdcc-demo/jimmy
API_IMAGE     := $(REGISTRY)/aikefu-api
CONSOLE_IMAGE := $(REGISTRY)/aikefu-console
IMAGE_TAG     ?= $(shell date +%Y%m%d-%H%M)
```

---

## 📊 技术栈速查

### ai_kefu (AI 客服)

**后台**: FastAPI, Uvicorn, Gunicorn, ChromaDB, Redis, MySQL
**前端**: Vue3, Vite, Nginx
**浏览器**: Playwright, Chrome DevTools Protocol

### InventoryManager (库存管理)

**后台**: Flask, SQLAlchemy, Redis, MySQL, Gunicorn
**前端**: Vue3, TypeScript, Element Plus, Vite

---

## 🔐 镜像仓库

### 推送镜像到 Registry

```bash
cd ai_kefu

# 构建并自动标记（timestamp）
make build-api
make push-api

# 或一次性
make build-all && make push-all

# 或使用自定义标签
IMAGE_TAG=20260425-1200 make build-all
make push-all
```

### 完整镜像路径

```
docker.cnb.cool/tdcc-demo/jimmy/aikefu-api:20260425-0903
docker.cnb.cool/tdcc-demo/jimmy/aikefu-console:20260425-0903
```

---

## 🧪 测试和检查

```bash
cd ai_kefu

make test               # 运行所有测试
make test-unit          # 单元测试
make test-cov           # 覆盖率报告
make lint               # 代码检查
make format             # 代码格式化
make check-env          # 检查环境
```

---

## 📚 详细文档位置

| 文档 | 位置 | 描述 |
|------|------|------|
| 完整探索报告 | `PROJECT_EXPLORATION_COMPLETE.md` | 详细的项目结构 |
| 文件路径清单 | `DETAILED_FILE_PATHS.md` | 所有关键文件路径 |
| 项目说明 | `ai_kefu/README.md` | AI 客服项目说明 |
| 快速开始 | `ai_kefu/QUICK_REFERENCE.md` | 快速参考 |
| 部署指南 | `ai_kefu/FRESH_MAC_DEPLOYMENT.md` | Mac 部署 |
| 拦截器说明 | `ai_kefu/INTERCEPTOR_QUICK_START.md` | 拦截器快速开始 |

---

## ⚠️ 常见问题

### Q: 如何修改镜像标签？
A: 使用 `IMAGE_TAG` 环境变量
```bash
IMAGE_TAG=v1.0.0 make build-all
```

### Q: Docker 镜像仓库在哪里？
A: `docker.cnb.cool/tdcc-demo/jimmy/`

### Q: 如何本地运行所有服务？
A: 使用 docker-compose
```bash
cd ai_kefu
docker-compose up -d
```

### Q: API 文档在哪里？
A: 启动 API 后访问 `http://localhost:8000/docs`

### Q: 如何重新初始化知识库？
A: 
```bash
cd ai_kefu
make init-knowledge
```

---

## 📞 重要联系

- **维护者**: coderxiu<coderxiu@qq.com>
- **仓库**: GitHub (含 git submodules)
- **许可证**: 见 LICENSE 文件

---

## ✅ 初次部署检查清单

- [ ] 克隆项目 (含 submodules)
- [ ] 安装 Python 3.10+ 和 Node 20+
- [ ] 复制 `.env.example` 为 `.env` 并配置
- [ ] 安装依赖: `make install`
- [ ] 初始化知识库: `make init-knowledge`
- [ ] 构建镜像: `make build-all`
- [ ] 推送镜像: `make push-all`
- [ ] 启动服务: `docker-compose up -d`

---

## 🔗 快速链接

| 服务 | URL |
|------|-----|
| API Docs | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |
| Console | http://localhost/ui/knowledge/ |
| MySQL | localhost:3306 |
| Redis | localhost:6379 |

---

**建议**: 先阅读 `PROJECT_EXPLORATION_COMPLETE.md` 获得全面了解。

