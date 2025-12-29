# Change: Disable AI Auto-Reply and Add MySQL Conversation Logging

## Why

当前闲鱼客服机器人启动后,xianyu_interceptor会自动调用后端AI Agent API进行智能回复。用户需要暂时禁用AI自动回复功能,同时将所有对话数据完整保存到MySQL数据库中,以便未来对自动回复系统进行评测和分析。

后端AI Agent API将继续保持运行可供测试,但 xianyu_interceptor 在接收到消息后不会调用后端API,只记录对话数据。

## What Changes

- **移除旧代码**: 删除 main.py 中基于 XianyuReplyBot 的旧自动回复逻辑
- **移除旧代码**: 删除 XianyuAgent.py 和相关的直接AI调用代码
- **核心变更**: 在 xianyu_interceptor/message_handler.py 中添加配置开关,禁用对后端AI Agent API的调用
- **新增功能**: 实现MySQL数据库连接和对话持久化存储层
- **数据模型**: 创建conversations表结构,存储完整的对话数据(用户消息、卖家消息、上下文等)
- **配置管理**: 添加 ENABLE_AI_REPLY 环境变量和MySQL连接配置
- **向后兼容**: 保留后端AI Agent API代码和xianyu_interceptor的集成代码,仅通过配置开关控制是否调用

## Impact

### Affected Specs
- **新增**: `conversation-persistence` - 对话持久化到MySQL数据库的能力

### Affected Code
- **删除**: `main.py` - 删除基于XianyuReplyBot的旧启动脚本
- **删除**: `XianyuAgent.py` - 删除旧的AI回复机器人实现
- **删除**: `XianyuApis.py` - 删除旧的闲鱼API调用模块(如果不被其他地方使用)
- **删除**: `context_manager.py` - 删除旧的SQLite上下文管理器
- **删除**: `messaging_core.py` - 删除旧的消息核心模块(已被xianyu_interceptor替代)
- **删除**: `transports.py` - 删除旧的传输层实现(已被xianyu_interceptor替代)
- **删除**: `browser_controller.py` - 删除旧的浏览器控制器(已被xianyu_interceptor替代)
- **删除**: `cdp_interceptor.py` - 删除旧的CDP拦截器(已被xianyu_interceptor替代)
- `xianyu_interceptor/config.py` - 添加 ENABLE_AI_REPLY 配置和MySQL配置
- `xianyu_interceptor/message_handler.py` - 添加AI回复禁用逻辑和对话记录逻辑
- `xianyu_interceptor/main_integration.py` - 集成MySQL连接和ConversationStore
- `.env.example` - 添加MySQL连接配置和AI禁用开关
- 新增 `xianyu_interceptor/conversation_store.py` - MySQL对话存储实现
- 新增 `xianyu_interceptor/conversation_models.py` - 对话数据模型
- 新增 `migrations/001_create_conversations_table.sql` - 数据库迁移脚本
- `requirements.txt` - 添加MySQL驱动依赖(pymysql或mysql-connector-python)
- `README.md` - 更新文档,移除旧机器人说明,只保留xianyu_interceptor说明

### 配置变更
新增环境变量:
- `ENABLE_AI_REPLY` - 是否启用AI自动回复 (默认: false)
- `MYSQL_HOST` - MySQL主机地址 (默认: localhost)
- `MYSQL_PORT` - MySQL端口 (默认: 3306)
- `MYSQL_USER` - MySQL用户名
- `MYSQL_PASSWORD` - MySQL密码
- `MYSQL_DATABASE` - MySQL数据库名 (默认: xianyu_conversations)

### 行为变更
- xianyu_interceptor 启动后,默认只记录对话,不调用后端AI Agent API
- 所有对话数据会实时存储到MySQL数据库:
  - 用户发送的消息
  - 卖家手动回复的消息
  - 会话元数据(chat_id, user_id, item_id等)
  - 时间戳和消息类型
- 手动模式切换仍然正常工作
- 后端AI Agent API不会被调用,但服务可独立运行供测试
- 如需启用AI回复,设置 ENABLE_AI_REPLY=true 即可恢复原有功能
