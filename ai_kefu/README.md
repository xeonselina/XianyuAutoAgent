# AI 客服 Agent 系统

基于通义千问（Qwen）的智能客服系统，提供知识库检索、人工协助和任务管理功能。

## 特性

- 🤖 **AI 对话**: 基于通义千问 Qwen 模型的智能对话
- 📚 **知识库检索**: 使用 Chroma 向量数据库进行语义搜索
- 👥 **Human-in-the-Loop**: 支持人工协助功能
- 🔄 **会话管理**: 基于 Redis 的会话状态管理
- 🐳 **Docker 部署**: 完整的容器化部署方案
- 🔌 **RESTful API**: FastAPI 实现的标准化 API 接口

## 快速开始

### 前置要求

- Python 3.11+
- Redis 7.x
- 通义千问 API Key（从[阿里云 DashScope](https://dashscope.console.aliyun.com/) 获取）

### 安装

1. **克隆项目**
```bash
git clone <repository-url>
cd XianyuAutoAgent
```

2. **安装依赖**
```bash
make install
```

3. **配置环境变量**
```bash
cp .env.example .env
# 编辑 .env 文件，设置 QWEN_API_KEY
```

4. **初始化知识库**
```bash
python ai_kefu/scripts/init_knowledge.py
```

5. **启动服务**
```bash
make dev
```

服务将在 http://localhost:8000 启动

### 使用 Docker

```bash
# 构建镜像
make docker-build

# 启动服务
docker-compose up -d
```

## API 文档

启动服务后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 主要端点

#### 聊天接口
```bash
# 同步聊天
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "如何申请退款？"}'

# 流式聊天
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "我的订单什么时候发货？"}'
```

#### 会话管理
```bash
# 查询会话
curl http://localhost:8000/sessions/{session_id}

# 删除会话
curl -X DELETE http://localhost:8000/sessions/{session_id}
```

#### 健康检查
```bash
curl http://localhost:8000/health
```

## 项目结构

```
XianyuAutoAgent/
├── ai_kefu/                 # 主应用目录
│   ├── agent/              # Agent 核心引擎
│   ├── api/                # FastAPI 路由
│   ├── config/             # 配置管理
│   ├── hooks/              # 事件钩子
│   ├── llm/                # LLM 客户端
│   ├── models/             # 数据模型
│   ├── prompts/            # 提示词
│   ├── scripts/            # 工具脚本
│   ├── services/           # 业务服务
│   ├── storage/            # 存储层
│   ├── tools/              # Agent 工具
│   └── utils/              # 工具函数
├── tests/                  # 测试
├── specs/                  # 设计文档
├── Dockerfile              # Docker 配置
├── Makefile                # 自动化命令
├── docker-compose.yml      # Docker Compose 配置
└── requirements.txt        # Python 依赖

```

## 开发

### 运行测试
```bash
make test
```

### 代码检查
```bash
make lint
```

### 清理临时文件
```bash
make clean
```

## 配置

主要配置项（.env 文件）：

```bash
# Qwen API
QWEN_API_KEY=your_api_key_here
QWEN_MODEL=qwen-plus

# Redis
REDIS_URL=redis://localhost:6379
REDIS_SESSION_TTL=1800

# Chroma
CHROMA_PERSIST_PATH=./chroma_data

# Agent
MAX_TURNS=50
TURN_TIMEOUT_SECONDS=120
LOOP_DETECTION_THRESHOLD=5

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## 架构

系统采用 Plan-Action-Check 循环架构：

1. **Plan**: 分析用户意图，规划响应策略
2. **Action**: 执行工具调用（知识检索、人工协助等）
3. **Check**: 验证结果，决定下一步行动

## 更多文档

- [完整快速开始指南](specs/001-ai-customer-service-agent/quickstart.md)
- [技术架构](specs/001-ai-customer-service-agent/plan.md)
- [数据模型](specs/001-ai-customer-service-agent/data-model.md)
- [API 规范](specs/001-ai-customer-service-agent/contracts/openapi.yaml)

## 许可证

[MIT License](LICENSE)
