# 闲鱼自动客服系统

基于 AI 的闲鱼自动客服解决方案，支持自动回复、人工接管、智能对话等功能。本项目包含两个系统：闲鱼客服机器人和 AI Agent 客服系统。

## 特性

### 🤖 闲鱼客服机器人（main.py）
- **浏览器 CDP 拦截**: 通过 Chromium DevTools Protocol 拦截 WebSocket 消息
- **AI 智能回复**: 基于通义千问的智能对话
- **人工接管模式**: 发送 `。` 切换自动/人工模式
- **会话管理**: 使用浏览器用户数据目录保存会话
- **消息过滤**: 自动过滤过期消息和自己发送的消息

### 🚀 AI Agent 客服系统（api/）
- **知识库检索**: 使用 Chroma 向量数据库进行语义搜索
- **Human-in-the-Loop**: 支持人工协助工作流
- **会话管理**: 基于 Redis 的会话状态管理
- **RESTful API**: FastAPI 实现的标准化接口
- **流式响应**: 支持 SSE 流式输出

## 快速开始

### 前置要求

- Python 3.8+
- 通义千问 API Key（从 [阿里云 DashScope](https://dashscope.console.aliyun.com/) 获取）
- Chromium 浏览器（通过 Playwright 自动安装）
- Redis 7.x（仅运行 AI Agent API 需要）

### 安装

#### 1. 克隆项目
```bash
git clone https://github.com/shaxiu/XianyuAutoAgent.git
cd XianyuAutoAgent/ai_kefu
```

#### 2. 安装依赖
```bash
# 使用 Makefile（推荐）
make install

# 或手动安装
pip install -r requirements.txt

# 安装 Chromium 浏览器
playwright install chromium
```

#### 3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件，配置必要的环境变量
```

**必填配置**：
```ini
# 通义千问 API Key
API_KEY=your_api_key_here

# 闲鱼 Cookie（可选，不设置则使用浏览器保存的会话）
COOKIES_STR=your_cookies_here

# 浏览器配置
BROWSER_HEADLESS=false  # true=无界面，false=显示浏览器窗口
```

### 运行闲鱼客服机器人

```bash
# 使用 Makefile
make run-xianyu

# 或直接运行
python main.py
```

**启动成功标志**：
```
INFO | 使用浏览器模式 (BrowserWebSocketTransport)
INFO | 正在启动浏览器...
INFO | 💡 提示：请在浏览器中点击进入消息中心或任意聊天
```

**人工接管功能**：
- 发送 `。`（句号）切换到人工模式，AI 停止自动回复
- 再次发送 `。` 切换回自动模式

### 运行 AI Agent API

#### 1. 启动 Redis
```bash
# macOS
brew services start redis

# Linux
sudo systemctl start redis

# Docker
docker run -d -p 6379:6379 redis:7-alpine
```

#### 2. 初始化知识库
```bash
make init-knowledge
```

#### 3. 启动 API 服务
```bash
make run-api
```

服务将在 http://localhost:8000 启动

**API 文档**：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 使用方法

### 获取闲鱼 Cookie（可选）

**注意**：Cookie 是可选的。如果不提供，系统将使用浏览器保存的会话，首次使用需要手动登录。

如果您想提供 Cookie：

1. 浏览器打开 https://www.goofish.com/
2. 按 F12 打开开发者工具
3. 切换到 Network 标签
4. 刷新页面，点击任意请求
5. 在 Headers 中找到 Cookie，复制完整值
6. 粘贴到 `.env` 文件的 `COOKIES_STR` 变量中

### 配置提示词（可选）

```bash
mv prompts/classify_prompt_example.txt prompts/classify_prompt.txt
mv prompts/price_prompt_example.txt prompts/price_prompt.txt
mv prompts/tech_prompt_example.txt prompts/tech_prompt.txt
mv prompts/default_prompt_example.txt prompts/default_prompt.txt
```

### API 使用示例

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

## Makefile 命令

查看所有可用命令：
```bash
make help
```

**常用命令**：

| 命令 | 说明 |
|------|------|
| `make install` | 安装生产环境依赖 |
| `make install-dev` | 安装开发环境依赖 |
| `make run-xianyu` | 启动闲鱼客服机器人 |
| `make run-api` | 启动 AI Agent API |
| `make init-knowledge` | 初始化知识库 |
| `make test` | 运行测试 |
| `make lint` | 代码检查 |
| `make docker-build` | 构建 Docker 镜像 |
| `make docker-up` | 启动 Docker 容器 |
| `make clean` | 清理临时文件 |

## 项目结构

```
XianyuAutoAgent/ai_kefu/
├── main.py                  # 闲鱼客服主程序入口
├── XianyuAgent.py           # 闲鱼 AI 回复机器人
├── XianyuApis.py            # 闲鱼 API 封装
├── messaging_core.py        # 消息传输核心
├── transports.py            # WebSocket 传输实现（浏览器模式）
├── browser_controller.py    # 浏览器控制器
├── cdp_interceptor.py       # CDP 拦截器
├── context_manager.py       # 上下文管理
├── Makefile                 # 自动化命令
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── api/                     # AI Agent API
│   ├── main.py             # FastAPI 应用入口
│   ├── routes/             # API 路由
│   └── models.py           # 数据模型
├── agent/                   # Agent 核心引擎
│   ├── executor.py         # 执行器
│   └── turn.py             # Turn 管理
├── config/                  # 配置管理
├── llm/                     # LLM 客户端
├── models/                  # 数据模型
├── prompts/                 # 提示词模板
├── scripts/                 # 工具脚本
│   └── init_knowledge.py   # 知识库初始化
├── services/                # 业务服务
├── storage/                 # 存储层（Redis/Chroma）
├── tools/                   # Agent 工具
├── tests/                   # 测试
│   ├── unit/               # 单元测试
│   └── integration/        # 集成测试
└── docs/                    # 文档
```

## 配置说明

### 环境变量

查看 `.env.example` 获取完整配置说明。主要配置项：

**AI 模型配置**：
```ini
API_KEY=your_api_key_here
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max
```

**闲鱼账号配置**（可选）：
```ini
# 如果不设置，将使用浏览器保存的会话
COOKIES_STR=your_cookies_here
```

**浏览器配置**：
```ini
# 是否显示浏览器窗口
BROWSER_HEADLESS=false

# 浏览器用户数据目录（用于保存登录会话）
BROWSER_USER_DATA_DIR=./browser_data

# 浏览器窗口大小
BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=720
```

**AI Agent 配置**（运行 API 需要）：
```ini
QWEN_API_KEY=your_api_key_here
REDIS_URL=redis://localhost:6379
CHROMA_PERSIST_PATH=./chroma_data
MAX_TURNS=50
```

## 工作原理

### 浏览器 CDP 拦截模式

系统使用 Chrome DevTools Protocol (CDP) 拦截浏览器中的 WebSocket 消息：

1. **启动浏览器**: 使用 Playwright 启动 Chromium 浏览器
2. **建立 CDP 会话**: 创建 CDP 会话以监控网络活动
3. **拦截 WebSocket**: 通过 CDP 注入脚本拦截 WebSocket 消息
4. **消息处理**: 拦截到的消息通过回调传递给 AI 机器人
5. **发送回复**: 通过 CDP 将 AI 生成的回复发送回闲鱼

**优势**：
- ✅ 无需手动管理 Cookie 和 Token
- ✅ 自动处理会话刷新
- ✅ 可视化界面便于调试
- ✅ 更接近真实用户行为，不易被检测

## 开发

### 运行测试
```bash
# 所有测试
make test

# 单元测试
make test-unit

# 集成测试
make test-integration

# 生成覆盖率报告
make test-cov
```

### 代码检查
```bash
make lint
make format
```

## Docker 部署

### 构建镜像
```bash
make docker-build
```

### 启动服务
```bash
make docker-up
```

### 查看日志
```bash
make docker-logs
```

### 停止服务
```bash
make docker-down
```

## 常见问题

### Q1: 系统无法建立 WebSocket 连接

**可能原因**：
1. 未手动在浏览器中进入消息中心
2. 浏览器未登录闲鱼账号
3. 页面加载未完成

**解决方案**：
- 在浏览器中手动登录闲鱼
- 点击进入消息中心或任意聊天
- 如果已进入，尝试刷新页面（F5）

### Q2: AI 不回复

**可能原因**：
1. API Key 错误 → 检查 `.env` 中的 `API_KEY`
2. 模型服务不可用 → 检查 `MODEL_BASE_URL`
3. 会话处于人工接管模式 → 发送 `。` 切换回自动模式

### Q3: Playwright 安装失败

**解决方案**：
```bash
# 手动安装 Chromium
playwright install chromium

# 如果网络问题，设置代理
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
playwright install chromium
```

### Q4: 浏览器用户数据目录权限问题

**解决方案**：
```bash
# 删除旧的用户数据目录
rm -rf browser_data/

# 重新启动系统
python main.py
```

### Q5: API 服务启动失败

**解决方案**：
```bash
# 检查 Redis 是否运行
redis-cli ping

# 初始化知识库
make init-knowledge

# 检查环境变量
make check-env
```

## 更多文档

- [快速开始指南](QUICK_START.md) - 详细的快速上手指南
- [迁移指南](MIGRATION_GUIDE.md) - 版本迁移说明
- [更新日志](CHANGELOG.md) - 版本更新记录
- [项目概览](docs/PROJECT_OVERVIEW.md) - 架构设计文档

## 许可证

[MIT License](LICENSE)

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- **Issues**: https://github.com/shaxiu/XianyuAutoAgent/issues
- **Email**: coderxiu@qq.com
