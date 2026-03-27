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

### 📱 手机租赁业务系统（tools/）
- **信息收集**: 自动收集租赁日期、地址等关键信息
- **物流计算**: 基于顺丰标快计算全国物流时效
- **档期查询**: 对接档期管理 API 实时查询可用设备
- **动态报价**: 支持租期折扣、客户折扣、旺季加价
- **知识库**: 押金政策、使用须知、赔偿标准等

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

#### 1. 安装和启动 Redis

Redis 用于会话缓存和状态管理，是运行 AI Agent API 的必需依赖。

**macOS 安装（推荐使用 Homebrew）**：
```bash
# 安装 Redis
brew install redis

# 启动 Redis 服务
brew services start redis

# 验证 Redis 是否运行
redis-cli ping
# 应该返回: PONG
```

**Linux 安装**：
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install redis-server

# 启动 Redis 服务
sudo systemctl start redis
sudo systemctl enable redis  # 开机自启

# CentOS/RHEL
sudo yum install redis
sudo systemctl start redis
sudo systemctl enable redis
```

**使用 Docker（推荐用于开发和测试）**：
```bash
# 启动 Redis 容器
docker run -d \
  --name redis \
  -p 6379:6379 \
  redis:7-alpine

# 查看容器状态
docker ps | grep redis

# 停止 Redis
docker stop redis

# 重新启动
docker start redis
```

**配置 Redis 连接**：

编辑 `.env` 文件，添加 Redis 配置：
```ini
# Redis 连接 URL
REDIS_URL=redis://localhost:6379

# Redis 会话过期时间（秒，默认 30 分钟）
REDIS_SESSION_TTL=1800
```

**常见 Redis URL 格式**：
```ini
# 本地 Redis（无密码）
REDIS_URL=redis://localhost:6379

# 本地 Redis（有密码）
REDIS_URL=redis://:your_password@localhost:6379

# 远程 Redis（有密码和端口）
REDIS_URL=redis://:your_password@your-redis-host:6379

# 指定数据库编号（0-15，默认 0）
REDIS_URL=redis://localhost:6379/0

# 使用 SSL/TLS 连接
REDIS_URL=rediss://:your_password@your-redis-host:6379
```

**验证 Redis 连接**：
```bash
# 测试连接
redis-cli ping

# 查看 Redis 信息
redis-cli info

# 查看当前键数量
redis-cli dbsize

# 清空当前数据库（谨慎使用）
redis-cli flushdb
```

#### 2. 初始化知识库
```bash
# 初始化通用知识库
make init-knowledge

# 初始化租赁业务知识库
python scripts/init_rental_knowledge.py
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
│   ├── system_prompt.py    # 通用客服提示词
│   └── rental_system_prompt.py  # 租赁业务提示词
├── scripts/                 # 工具脚本
│   ├── init_knowledge.py   # 通用知识库初始化
│   └── init_rental_knowledge.py  # 租赁知识库初始化
├── services/                # 业务服务
├── storage/                 # 存储层（Redis/Chroma）
├── tools/                   # Agent 工具
│   ├── knowledge_search.py      # 知识库检索
│   ├── check_availability.py    # 档期查询（租赁）
│   ├── calculate_logistics.py   # 物流计算（租赁）
│   ├── calculate_price.py       # 价格计算（租赁）
│   └── collect_rental_info.py   # 信息收集（租赁）
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
MODEL_NAME=qwen3.5-plus
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

**租赁业务 API 配置**：
```ini
# 档期管理 API 地址
RENTAL_API_BASE_URL=http://13uy63225pa7.vicp.fun/api/rentals

# 档期查询端点
RENTAL_FIND_SLOT_ENDPOINT=/find-slot
```

## 手机租赁业务系统

### 业务流程

手机租赁客服的标准工作流程：

```
1. 信息收集阶段
   ├─ 收货日期（用户希望什么时候收到）
   ├─ 归还日期（用户什么时候寄回）
   └─ 收货地址（至少省市）

2. 物流时间计算
   └─ 根据目的地计算物流天数（顺丰标快）

3. 档期查询
   ├─ 开始日期 = 收货日期 + 1天
   ├─ 结束日期 = 归还日期 - 1天
   └─ 调用档期 API 查询可用设备

4. 报价计算
   ├─ 基础日租金 × 天数
   ├─ 应用客户折扣（老客户95折）
   ├─ 应用租期折扣（7天+有折扣）
   └─ 应用旺季加价（春节/五一/国庆+15%）

5. 押金说明
   ├─ 芝麻信用 ≥ 650分可免押
   ├─ 老客户记录良好可免押
   └─ 否则需支付押金（按设备型号）

6. 使用须知（按需查询知识库）
   ├─ 设备使用注意事项
   ├─ 磕碰划痕处理规则
   └─ 激光雕刻免责说明
```

### 租赁工具说明

#### 1. collect_rental_info - 信息收集
收集和验证租赁必需信息（收货日期、归还日期、地址）

#### 2. calculate_logistics - 物流计算
根据目的地计算物流时间（从深圳发顺丰标快）
- 广东省内：1天
- 华南华东：2天
- 华北华中西南：3天
- 东北西北：4天
- 新疆西藏：6-7天

#### 3. check_availability - 档期查询
调用档期管理 API 查询指定时间段的可用设备

#### 4. calculate_price - 价格计算
根据租期、客户类型、季节计算租金报价

#### 5. knowledge_search - 知识库检索
查询租赁政策、使用须知等信息

### 租赁知识库内容

运行 `python scripts/init_rental_knowledge.py` 初始化以下知识：

- **租赁定价规则**: 折扣策略、旺季加价等
- **免押金条件**: 芝麻信用、老客户等免押条件
- **租赁流程说明**: 完整租赁流程介绍
- **设备使用注意事项**: 保管、使用建议
- **激光雕刻免责说明**: 关于设备标识的说明
- **设备磕碰划痕处理**: 赔偿标准和规则
- **物流配送说明**: 物流时效和注意事项

### 日期关系说明

理解租赁日期关系很重要：

```
用户时间轴：
收货日期 -----(用户使用期间)-----> 归还日期
   |                                  |
 +1天物流                          -1天物流
   ↓                                  ↓
租赁开始 ------------------------ 租赁结束
      (实际占用设备档期的时间)
```

**示例**：
- 用户要求：2月10日收货，2月20日归还
- 实际租赁档期：2月11日 至 2月19日（9天）
- 查询档期参数：`start_date="2024-02-11"`, `end_date="2024-02-19"`

### 测试租赁工具

```bash
# 测试物流计算
python -c "from ai_kefu.tools.calculate_logistics import calculate_logistics; print(calculate_logistics('北京'))"

# 测试档期查询
python -c "from ai_kefu.tools.check_availability import check_availability; print(check_availability('2024-02-11', '2024-02-19', 3))"

# 测试价格计算
python -c "from ai_kefu.tools.calculate_price import calculate_price; print(calculate_price('2024-02-11', '2024-02-19', 'iPhone 15 Pro Max', 50.0, 'new'))"

# 测试知识库检索
python -c "from ai_kefu.tools.knowledge_search import knowledge_search; print(knowledge_search('租赁定价规则'))"
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

### Q5: Redis 连接失败

**可能原因**：
1. Redis 服务未启动
2. Redis 端口被占用
3. 连接配置错误

**解决方案**：
```bash
# 检查 Redis 是否运行
redis-cli ping
# 应该返回: PONG

# 查看 Redis 服务状态（macOS）
brew services list | grep redis

# 查看 Redis 服务状态（Linux）
sudo systemctl status redis

# 重启 Redis 服务（macOS）
brew services restart redis

# 重启 Redis 服务（Linux）
sudo systemctl restart redis

# 查看 Redis 日志
# macOS: brew services logs redis
# Linux: sudo journalctl -u redis -f

# 检查端口占用
lsof -i :6379
```

### Q6: API 服务启动失败

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
