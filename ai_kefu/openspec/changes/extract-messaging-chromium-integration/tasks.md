# 实施任务清单

## 1. 核心消息抽象
- [ ] 1.1 创建 `messaging_core.py` 包含抽象基类
  - [ ] 1.1.1 定义 `MessageTransport` 抽象基类
  - [ ] 1.1.2 定义 `Message` 数据类用于标准化消息
  - [ ] 1.1.3 实现 `MessageHandler` 协议接口
- [ ] 1.2 从 `XianyuLive` 提取消息协议逻辑
  - [ ] 1.2.1 将消息编码逻辑（`send_msg` 方法）提取到 `XianyuMessageCodec`
  - [ ] 1.2.2 将消息解码/解析逻辑提取到 `XianyuMessageCodec`
  - [ ] 1.2.3 提取消息分类方法（is_chat_message、is_typing_status 等）
- [ ] 1.3 创建 `MessageRouter` 用于处理器注册和分发
  - [ ] 1.3.1 实现按消息类型注册处理器
  - [ ] 1.3.2 实现消息分发到已注册的处理器
  - [ ] 1.3.3 添加错误处理和日志记录

## 2. 浏览器集成
- [ ] 2.1 设置浏览器自动化框架
  - [ ] 2.1.1 在 requirements.txt 中添加 `playwright`
  - [ ] 2.1.2 在 .env.example 中添加浏览器配置选项
  - [ ] 2.1.3 创建浏览器启动配置类
- [ ] 2.2 创建 `browser_controller.py` 模块
  - [ ] 2.2.1 实现浏览器生命周期管理（启动、关闭、重启）
  - [ ] 2.2.2 实现 cookie 注入和提取
  - [ ] 2.2.3 实现崩溃检测和恢复
  - [ ] 2.2.4 添加无头/有头模式支持
- [ ] 2.3 创建 `cdp_interceptor.py` 用于 WebSocket 拦截
  - [ ] 2.3.1 实现到浏览器的 CDP 连接
  - [ ] 2.3.2 订阅 Network.webSocketFrameReceived 事件
  - [ ] 2.3.3 订阅 Network.webSocketCreated/Closed 事件
  - [ ] 2.3.4 实现用于发送消息的 JavaScript 注入
- [ ] 2.4 实现调试功能
  - [ ] 2.4.1 添加错误时截屏功能
  - [ ] 2.4.2 添加控制台日志监控
  - [ ] 2.4.3 添加远程调试端口配置

## 3. 传输实现
- [ ] 3.1 创建 `DirectWebSocketTransport`（传统模式）
  - [ ] 3.1.1 将现有 `XianyuLive` WebSocket 逻辑重构为传输类
  - [ ] 3.1.2 实现 `MessageTransport` 接口
  - [ ] 3.1.3 保留心跳和 token 刷新逻辑
- [ ] 3.2 创建 `BrowserWebSocketTransport`（新浏览器模式）
  - [ ] 3.2.1 集成 `BrowserController` 进行浏览器管理
  - [ ] 3.2.2 集成 `CDPInterceptor` 进行消息捕获
  - [ ] 3.2.3 通过 CDP JavaScript 执行实现消息发送
  - [ ] 3.2.4 实现连接状态监控

## 4. 主应用重构
- [ ] 4.1 更新 `main.py` 以支持两种模式
  - [ ] 4.1.1 添加 USE_BROWSER_MODE 配置解析
  - [ ] 4.1.2 基于模式创建传输工厂
  - [ ] 4.1.3 初始化适当的传输
- [ ] 4.2 重构 `XianyuLive` 类
  - [ ] 4.2.1 移除直接 WebSocket 代码（移至 DirectWebSocketTransport）
  - [ ] 4.2.2 接受传输作为依赖注入
  - [ ] 4.2.3 使用 MessageRouter 进行处理器注册
- [ ] 4.3 使 AI 智能体变为可选/可插拔
  - [ ] 4.3.1 创建智能体配置标志（ENABLE_PRICE_AGENT、ENABLE_SCHEDULE_AGENT）
  - [ ] 4.3.2 基于配置有条件地初始化智能体
  - [ ] 4.3.3 更新 `XianyuAgent.py` 以支持可选智能体

## 5. 配置和文档
- [ ] 5.1 更新 `.env.example` 添加新变量
  - [ ] 5.1.1 添加 USE_BROWSER_MODE=true
  - [ ] 5.1.2 添加 BROWSER_HEADLESS=false
  - [ ] 5.1.3 添加 BROWSER_DEBUG_PORT（可选）
  - [ ] 5.1.4 添加 BROWSER_USER_DATA_DIR=./browser_data
  - [ ] 5.1.5 添加智能体启用/禁用标志
- [ ] 5.2 更新 requirements.txt
  - [ ] 5.2.1 添加 playwright>=1.40.0
  - [ ] 5.2.2 将 tencent-docs-api 标记为可选
- [ ] 5.3 更新 README.md
  - [ ] 5.3.1 记录浏览器模式设置
  - [ ] 5.3.2 记录配置选项
  - [ ] 5.3.3 添加浏览器问题故障排除章节
  - [ ] 5.3.4 添加对比表：浏览器模式 vs 直连模式

## 6. 测试和验证
- [ ] 6.1 测试浏览器模式
  - [ ] 6.1.1 验证浏览器启动并加载闲鱼
  - [ ] 6.1.2 验证 cookie 注入工作正常
  - [ ] 6.1.3 验证 WebSocket 拦截捕获消息
  - [ ] 6.1.4 验证通过 CDP 发送消息工作正常
- [ ] 6.2 测试传统模式兼容性
  - [ ] 6.2.1 验证 USE_BROWSER_MODE=false 使用直接 WebSocket
  - [ ] 6.2.2 验证现有功能保持不变
- [ ] 6.3 测试智能体切换功能
  - [ ] 6.3.1 验证系统在所有智能体禁用时工作正常
  - [ ] 6.3.2 验证系统在仅启用选定智能体时工作正常
- [ ] 6.4 测试错误场景
  - [ ] 6.4.1 测试浏览器崩溃和恢复
  - [ ] 6.4.2 测试网络断开处理
  - [ ] 6.4.3 测试无效 cookie 处理

## 7. 迁移和部署
- [ ] 7.1 创建迁移指南
  - [ ] 7.1.1 记录从旧版本升级的步骤
  - [ ] 7.1.2 记录如何在模式之间切换
  - [ ] 7.1.3 记录数据兼容性（聊天历史数据库不变）
- [ ] 7.2 性能测试
  - [ ] 7.2.1 测量浏览器内存使用
  - [ ] 7.2.2 测量浏览器模式 vs 直连模式的消息延迟
  - [ ] 7.2.3 记录资源需求
