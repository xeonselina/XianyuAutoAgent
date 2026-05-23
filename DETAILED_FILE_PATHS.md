# 📄 XianyuAutoAgent 详细文件路径清单

**生成日期**: 2026-04-25

---

## 📂 完整文件树结构

### 根目录关键文件

```
XianyuAutoAgent/
│
├── 🚀 部署和快速参考文档
│   ├── DOCKER_REGISTRY_QUICK_REFERENCE.md      ← Docker 仓库速查
│   ├── EXPLORATION_SUMMARY.md                  ← 探索总结
│   ├── PROJECT_STRUCTURE_REPORT.md             ← 项目结构报告
│   ├── README_EXPLORATION_RESULTS.md           ← 探索结果说明
│   ├── FILES_DISCOVERED.txt                    ← 发现的文件列表
│   ├── CODE_FLOW_SUMMARY.txt                   ← 代码流程总结
│   └── SYSTEM_ARCHITECTURE_SUMMARY.txt         ← 系统架构总结
│
├── 📚 主要项目目录
│   ├── ai_kefu/                                ← **AI客服系统（MAIN）**
│   ├── InventoryManager/                       ← **库存管理系统**
│   ├── cocs/                                   ← 其他服务
│   ├── tools/                                  ← 工具集
│   └── docs/                                   ← 文档
│
└── 🔧 配置文件
    ├── .git/                                   ← Git 仓库
    ├── .gitignore
    ├── .gitmodules
    └── .specify/                               ← 规范配置

```

---

## 🎯 AI 客服系统 (ai_kefu) 完整结构

### 核心模块路径

```
ai_kefu/
│
├── 🐳 Docker 配置
│   ├── Dockerfile                              ← Alpine 轻量级镜像
│   ├── Dockerfile.api                          ← 生产 API (linux/amd64)
│   ├── Dockerfile.console                      ← Web 控制台 (Node + Nginx)
│   ├── docker-compose.yml                      ← Docker 编排配置
│   ├── .dockerignore
│   └── docker/
│       └── nginx.console.conf                  ← Nginx 路由配置
│
├── 🔧 构建工具
│   ├── Makefile                                ← 主要构建命令 (20+个)
│   ├── requirements.txt                        ← Python 依赖 (68个包)
│   ├── setup.py
│   └── run_xianyu.py                           ← 启动脚本
│
├── 🤖 API 服务 (FastAPI)
│   └── api/
│       ├── main.py                             ← FastAPI 应用入口
│       ├── models.py                           ← Pydantic 数据模型
│       ├── dependencies.py                     ← DI 配置
│       ├── __init__.py
│       └── routes/                             ← API 端点 (15+ 路由文件)
│           ├── __init__.py
│           ├── admin.py
│           ├── conversations.py
│           ├── knowledge.py
│           ├── health.py
│           └── ...
│
├── 🌐 拦截器服务 (Interceptor)
│   ├── xianyu_interceptor/                     ← 拦截器核心
│   │   ├── __init__.py
│   │   ├── cdp_interceptor.py                  ← Chrome DevTools Protocol
│   │   ├── browser_controller.py               ← 浏览器控制
│   │   ├── conversation_store.py               ← 对话存储 (DB + 缓存)
│   │   ├── messaging_core.py                   ← 消息处理核心
│   │   ├── message_handler.py
│   │   ├── message_converter.py
│   │   ├── session_mapper.py
│   │   ├── uid_mapper.py
│   │   ├── history_message_parser.py
│   │   ├── browser_transport.py
│   │   ├── http_client.py
│   │   ├── image_handler.py
│   │   ├── manual_mode.py
│   │   ├── logging_setup.py
│   │   ├── config.py
│   │   ├── models.py
│   │   ├── exceptions.py
│   │   └── [20+ 支持模块]
│   │
│   └── scripts/interceptor/                    ← 拦截器部署
│       ├── install.sh                          ← 安装脚本
│       ├── run.sh                              ← 运行脚本
│       └── requirements.interceptor.txt        ← 拦截器依赖
│
├── 💻 前端 UI (Vue3)
│   └── ui/
│       ├── knowledge/                          ← 知识库管理 UI
│       │   ├── package.json
│       │   ├── index.html
│       │   ├── src/
│       │   └── dist/ (构建输出)
│       │
│       └── conversations/                      ← 对话管理 UI
│           ├── package.json
│           ├── index.html
│           ├── src/
│           └── dist/ (构建输出)
│
├── 🧠 LLM 相关
│   └── llm/
│       ├── __init__.py
│       ├── qwen_api.py
│       ├── conversation_llm.py
│       └── [LLM 集成模块]
│
├── 🗄️ 存储与数据
│   ├── storage/
│   │   ├── db/
│   │   ├── chroma/                             ← ChromaDB 向量存储
│   │   └── redis/                              ← Redis 缓存
│   │
│   ├── chroma_data/                            ← 向量库数据文件
│   │   └── chroma.sqlite3
│   │
│   ├── data/                                   ← 应用数据
│   └── models/                                 ← 数据模型定义
│
├── 🛠️ 工具和工具函数
│   ├── tools/                                  ← 工具集合
│   ├── utils/                                  ├── logging/
│   │   ├── config.py                          │   ├── logger.py
│   │   ├── db.py                              │   └── formatters.py
│   │   ├── cache.py                           ├── helpers/
│   │   └── [40+ 工具模块]                     │   └── [utility functions]
│   │                                          └── ...
│
├── ⚙️ 配置管理
│   └── config/
│       ├── __init__.py
│       ├── settings.py
│       ├── database.py
│       ├── cache.py
│       ├── logging.py
│       └── security.py
│
├── 🗂️ 代理系统
│   └── agent/
│       ├── __init__.py
│       ├── base_agent.py
│       ├── conversation_agent.py
│       ├── knowledge_agent.py
│       └── [agent 实现]
│
├── 📝 数据库迁移
│   └── migrations/
│       ├── versions/
│       └── [SQL 迁移脚本]
│
├── 📋 提示词系统
│   ├── prompts/
│   │   ├── classify_prompt_example.txt
│   │   ├── price_prompt_example.txt
│   │   ├── tech_prompt_example.txt
│   │   ├── default_prompt_example.txt
│   │   └── [其他提示词]
│   │
│   └── prompts/ (运行时)
│       ├── classify_prompt.txt (由 Dockerfile COPY)
│       ├── price_prompt.txt
│       ├── tech_prompt.txt
│       └── default_prompt.txt
│
├── 🧪 测试
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── conftest.py
│   │
│   ├── testcases/
│   └── run_tests.py
│
├── 📚 文档
│   ├── docs/                                   ← 完整文档
│   │   ├── API.md
│   │   ├── ARCHITECTURE.md
│   │   ├── DEPLOYMENT.md
│   │   └── [24+ 文档文件]
│   │
│   ├── README.md                               ← 项目说明
│   ├── ARCHITECTURE_SUMMARY.md
│   ├── CODEBASE_EXPLORATION*.md
│   ├── QUICK_REFERENCE.md
│   ├── FRESH_MAC_DEPLOYMENT.md
│   ├── INTERCEPTOR_QUICK_START.md
│   ├── XIANYU_INTERCEPTOR_ANALYSIS.md
│   ├── AI_EVALUATION_*.md (多个)
│   └── [多个说明文档]
│
├── 📊 日志和报告
│   ├── logs/                                   ← 运行日志
│   ├── reports/
│   ├── debug.log
│   └── xianyu.log
│
├── 🔌 上游提供者
│   └── xianyu_provider/
│       ├── upstream/
│       │   ├── Dockerfile
│       │   ├── requirements.txt
│       │   └── [provider 实现]
│       └── ...
│
├── 🔧 其他模块
│   ├── services/                               ← 业务服务
│   ├── openspec/                               ← 规范定义
│   ├── legacy/                                 ← 旧代码 (保存)
│   ├── hooks/                                  ← Git hooks
│   └── specs/                                  ← 规范文档
│
└── ⚙️ 配置文件
    ├── .env                                    ← 环境变量 (生产)
    ├── .env.example                            ← 环境变量 (模板)
    ├── .dockerignore
    ├── .gitignore
    ├── .codebuddy/
    ├── .specify/
    └── .venv/                                  ← Python 虚拟环境
```

---

## 📦 库存管理系统 (InventoryManager) 结构

```
InventoryManager/
│
├── 🐳 Docker 配置
│   ├── Dockerfile                              ← 多架构镜像
│   ├── docker-compose.yml                      ← 4 服务编排
│   ├── .dockerignore
│   ├── docker/
│   │   └── nginx/
│   │       ├── nginx.conf
│   │       └── ssl/
│   └── init.sql                                ← 数据库初始化
│
├── 🔧 构建工具
│   ├── Makefile                                ← 构建命令
│   ├── requirements.txt                        ← Python 依赖
│   ├── setup.py
│   ├── gunicorn_config.py                      ← Gunicorn 配置
│   └── run.py                                  ← 启动脚本
│
├── 🌐 Web 应用 (Flask)
│   ├── app.py                                  ← Flask 主应用
│   ├── config.py                               ← 配置管理
│   └── application/
│       ├── __init__.py
│       ├── models/                             ← 数据模型
│       ├── routes/                             ← 路由处理
│       ├── services/                           ← 业务逻辑
│       ├── templates/                          ← HTML 模板
│       ├── static/                             ← 静态文件
│       └── utils/
│
├── 💻 前端 (Vue3 + TypeScript)
│   └── frontend/
│       ├── package.json                        ← Node 依赖
│       ├── index.html
│       ├── src/
│       │   ├── main.ts
│       │   ├── App.vue
│       │   ├── components/
│       │   ├── views/
│       │   ├── router/
│       │   ├── stores/ (Pinia)
│       │   └── types/
│       ├── dist/                               ← 构建输出
│       └── vite.config.ts                      ← Vite 配置
│
├── 📚 文档
│   ├── README.md
│   ├── QUICK_START.md
│   ├── README-Docker.md
│   ├── DEPLOYMENT_CHECKLIST.md
│   ├── IMPLEMENTATION_SUMMARY.md
│   └── [多个说明文档]
│
├── 🔐 配置文件
│   ├── .env                                    ← 环境变量
│   ├── .env.example
│   ├── .env.docker
│   ├── .gitignore
│   └── .dockerignore
│
└── 📁 目录结构
    ├── logs/                                   ← 应用日志
    ├── uploads/                                ← 用户上传
    ├── tmp/
    └── static/uploads/                         ← 静态上传

```

---

## 🔑 关键文件详细信息

### Dockerfile 清单

| # | 路径 | 大小 | 行数 | 用途 |
|----|------|------|------|------|
| 1 | `ai_kefu/Dockerfile` | ~2KB | 70 | Alpine 轻量镜像 |
| 2 | `ai_kefu/Dockerfile.api` | ~2.5KB | 81 | FastAPI 生产镜像 |
| 3 | `ai_kefu/Dockerfile.console` | ~2.2KB | 59 | 控制台镜像 |
| 4 | `ai_kefu/xianyu_provider/upstream/Dockerfile` | - | - | 上游提供者 |
| 5 | `InventoryManager/Dockerfile` | ~5KB | 153 | 多架构镜像 |

### Makefile 清单

| 路径 | 行数 | 主要目标数 | 用途 |
|------|------|---------|------|
| `ai_kefu/Makefile` | 300+ | 30+ | 完整的构建和部署 |
| `InventoryManager/Makefile` | 400+ | 20+ | Flask 应用管理 |

### requirements.txt 清单

| 路径 | 包数 | 大小 | 关键依赖 |
|------|------|------|---------|
| `ai_kefu/requirements.txt` | 68 | ~2KB | FastAPI, ChromaDB, Playwright |
| `ai_kefu/scripts/interceptor/requirements.interceptor.txt` | 10+ | <1KB | 拦截器专用 |
| `InventoryManager/requirements.txt` | 40+ | ~1.5KB | Flask, SQLAlchemy, PIL |

### docker-compose.yml 清单

| 路径 | 服务数 | 镜像 | 网络 |
|------|-------|------|------|
| `ai_kefu/docker-compose.yml` | 3 | shaxiu/xianyuautoagent:latest | xianyu-network |
| `InventoryManager/docker-compose.yml` | 4 | 本地构建 | inventory_network |

---

## 🔍 配置文件内容摘要

### ai_kefu/.env.example (样板)

```ini
# 大模型 API 配置
QWEN_API_KEY=sk-xxxxxxx
OPENAI_API_KEY=sk-xxxxxxx

# 数据库配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=xianyu_user
MYSQL_PASSWORD=xxxxxxx
MYSQL_DATABASE=xianyu

# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# 浏览器模式
BROWSER_MODE=true
HEADLESS=false

# AI 回复
ENABLE_AI_REPLY=false

# 其他
TZ=Asia/Shanghai
```

### InventoryManager/.env.example (样板)

```ini
# 数据库
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/inventory_db
SQLALCHEMY_DATABASE_URI=...

# 钉钉和阿里云集成
SF_PARTNER_ID=xxxxxxx
SF_CHECKWORD=xxxxxxx
ALIBABA_CLOUD_ACCESS_KEY_ID=xxxxxxx
ALIBABA_CLOUD_ACCESS_KEY_SECRET=xxxxxxx

# 应用设置
SECRET_KEY=your-secret-key-change-in-production
FLASK_ENV=production

# 其他
TZ=Asia/Shanghai
```

---

## 📊 代码统计

### ai_kefu/

- **Python 文件**: ~150+
- **总代码行数**: ~50,000+
- **主要模块**: 拦截器、API、LLM、存储、工具
- **前端文件**: Vue3 SPA (2个)

### InventoryManager/

- **Python 文件**: ~80+
- **前端文件**: Vue3 TypeScript
- **总代码行数**: ~20,000+
- **主要功能**: 库存管理、订单处理、报表

---

## 🚀 快速命令参考

### 构建 Docker 镜像

```bash
cd ai_kefu

# 构建 API 镜像
make build-api

# 构建控制台镜像
make build-console

# 同时构建两个
make build-all IMAGE_TAG=20260425-0903

# 推送到仓库
make push-all
```

### 运行服务

```bash
cd ai_kefu

# 启动拦截器
make run-xianyu

# 启动 API
make run-api

# 开发模式
make run-api-dev

# 构建 UI
make ui-build
```

### Docker Compose

```bash
cd ai_kefu
docker-compose up -d              # 启动
docker-compose down               # 停止
docker-compose logs -f            # 查看日志
```

---

## ⚙️ 镜像仓库配置

### Registry 信息

- **主仓库**: `docker.cnb.cool`
- **命名空间**: `tdcc-demo/jimmy`
- **完整路径**: `docker.cnb.cool/tdcc-demo/jimmy/`

### 镜像清单

```
docker.cnb.cool/tdcc-demo/jimmy/aikefu-api:20260425-0903
docker.cnb.cool/tdcc-demo/jimmy/aikefu-console:20260425-0903
```

### 标签策略

- **默认**: `YYYYMMDD-HHMM` (由 Makefile 自动生成)
- **自定义**: `IMAGE_TAG=v1.0.0 make build-all`

---

## 📞 重要联系信息

### 代码维护者

```
Maintainer: coderxiu<coderxiu@qq.com>
License: 按照 LICENSE 文件规定
Repository: GitHub (git submodules)
```

---

## 🔒 安全提示

⚠️ **注意**: 以下文件包含敏感信息，不要提交到版本控制：

- `ai_kefu/.env`
- `InventoryManager/.env`
- `ai_kefu/.env.docker`
- 数据库密钥
- API 密钥

✅ **正确做法**:

1. 使用 `.env.example` 作为模板
2. 本地复制为 `.env` 并修改
3. 添加 `.env` 到 `.gitignore`
4. 通过环境变量传入敏感信息

---

**文档生成日期**: 2026-04-25
**最后更新**: 请参考各文件的修改时间
