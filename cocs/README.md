# 咸鱼AI客服系统

一个基于 Playwright 和 AI 大模型的咸鱼自动客服系统，支持自动回复客户消息，并在需要时通知人工介入。

## 功能特性

- 🤖 **自动化浏览器操作**：使用 Playwright 自动打开和操作咸鱼页面
- 💬 **智能消息处理**：自动监控客户消息，使用 AI 生成回复
- 🧠 **多AI模型支持**：支持 Dify 框架和阿里云 Qwen 模型
- 📊 **置信度评估**：评估 AI 回复的置信度，低置信度时通知人工
- 📱 **微信通知**：通过微信机器人及时通知人工介入
- 📧 **邮件通知**：支持邮件通知作为备用方案
- 🔍 **智能DOM解析**：自动识别咸鱼页面结构，适应页面变化
- 📝 **完整日志记录**：详细记录系统运行状态和消息处理过程

## 系统架构

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   浏览器模块     │    │   消息服务       │    │   AI服务        │
│  ┌───────────┐  │    │  ┌───────────┐  │    │  ┌───────────┐  │
│  │ Playwright │◄─┼───►│ MessageSvc │◄─┼───►│ Dify/Qwen │  │
│  └───────────┘  │    │  └───────────┘  │    │  └───────────┘  │
│  ┌───────────┐  │    └─────────────────┘    └─────────────────┘
│  │DOM Parser │  │              │
│  └───────────┘  │              ▼
└─────────────────┘    ┌─────────────────┐
                       │   通知服务       │
                       │  ┌───────────┐  │
                       │  │WeChat/Mail│  │
                       │  └───────────┘  │
                       └─────────────────┘
```

## 安装和配置

### 1. 环境要求

- Python 3.8+
- Chrome/Chromium 浏览器

### 2. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. 配置环境变量

复制配置文件模板：
```bash
cp .env.example .env
```

编辑 `.env` 文件，填入相应配置：

```bash
# AI服务配置
AI_SERVICE_TYPE=dify  # 或 qwen
DIFY_API_URL=https://api.dify.ai
DIFY_API_KEY=your_dify_api_key

# 或使用Qwen
QWEN_API_KEY=your_qwen_api_key

# 微信通知
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key

# 其他配置...
```

### 4. 启动系统

```bash
python main.py
```

## 使用说明

### 1. 启动流程

1. 运行 `python main.py`
2. 系统会自动打开浏览器访问咸鱼页面
3. 在浏览器中手动登录咸鱼账号
4. 登录成功后，系统开始自动监控消息

### 2. 工作流程

1. **消息监控**：系统持续监控咸鱼聊天界面的新消息
2. **AI处理**：收到客户消息后，发送给AI模型生成回复
3. **置信度判断**：
   - 置信度 ≥ 0.7：自动发送AI回复
   - 置信度 < 0.7：通知人工介入
4. **人工介入**：通过微信/邮件通知相关人员处理

### 3. API接口

系统提供REST API用于监控和管理：

- `POST /messages` - 接收新消息
- `GET /messages/{chat_id}` - 获取聊天记录
- `GET /chats` - 获取所有聊天会话
- `POST /messages/{message_id}/response` - 发送AI回复

## 配置说明

### AI服务配置

#### Dify模式
```bash
AI_SERVICE_TYPE=dify
DIFY_API_URL=https://api.dify.ai
DIFY_API_KEY=your_api_key
```

#### Qwen模式
```bash
AI_SERVICE_TYPE=qwen
QWEN_API_KEY=your_api_key
QWEN_MODEL_NAME=qwen-turbo
```

### 通知配置

#### 微信机器人
1. 在企业微信群中添加机器人
2. 获取Webhook URL
3. 配置 `WECHAT_WEBHOOK_URL`

#### 邮件通知
```bash
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=your_email@gmail.com
EMAIL_PASSWORD=your_password
EMAIL_RECIPIENTS=admin@company.com,support@company.com
```

## 项目结构

```
cocs/
├── main.py                 # 主程序入口
├── requirements.txt        # 依赖包列表
├── .env.example           # 配置文件模板
├── browser/               # 浏览器模块
│   ├── goofish_browser.py # 咸鱼浏览器操作
│   └── dom_parser.py      # DOM解析器
├── service/               # 服务模块
│   ├── message_service.py # 消息处理服务
│   ├── ai_service.py      # AI服务
│   └── notification_service.py # 通知服务
├── config/                # 配置模块
│   └── settings.py        # 配置管理
└── utils/                 # 工具模块
    └── logger.py          # 日志工具
```

## 常见问题

### Q1: 浏览器启动失败
**A**: 确保已安装 Playwright 浏览器：
```bash
playwright install chromium
```

### Q2: 登录超时
**A**: 增加登录超时时间：
```bash
BROWSER_LOGIN_TIMEOUT=600000  # 10分钟
```

### Q3: AI服务调用失败
**A**: 检查API密钥配置和网络连接

### Q4: DOM解析失败
**A**: 咸鱼页面结构可能有更新，系统会自动尝试多种选择器

## 开发说明

### 扩展AI服务
1. 在 `ai_service.py` 中创建新的AI服务类
2. 继承基础接口，实现 `process_message` 方法
3. 在配置中添加新的服务类型

### 自定义通知渠道
1. 在 `notification_service.py` 中创建新的通知服务类
2. 实现 `notify_human_required` 方法
3. 在初始化时添加到通知管理器

## 文档

### 核心文档
- **[功能规格说明](./FUNCTIONAL_SPEC.md)** - 详细的功能需求、业务流程和用户场景
- **[技术架构规格说明](./TECHNICAL_SPEC.md)** - 技术架构、模块设计和实现细节
- **[函数调用流程图](./COCS_Function_Call_Flow.md)** - 系统函数调用关系和数据流

### 技术文档
- **[消息去重机制](./FUNCTIONAL_SPEC.md#44-消息去重详细机制)** - 消息去重的设计和实现
- **[串行处理说明](./browser/README_serial_processing.md)** - 串行消息处理机制
- **[选择器更新](./SELECTOR_UPDATE_SUMMARY.md)** - DOM选择器更新记录

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request来改进这个项目。