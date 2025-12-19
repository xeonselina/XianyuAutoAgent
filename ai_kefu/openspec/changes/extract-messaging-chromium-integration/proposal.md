# 变更：提取闲鱼消息逻辑并集成 Chromium 浏览器控制

## 为什么

当前的 AI 客服系统作为纯后台守护进程运行，直接使用 WebSocket 连接。然而，新架构需要：
1. **可视化反馈**：能够通过 Chromium 浏览器实时查看闲鱼 Web 界面
2. **简化调试**：通过观察浏览器交互更容易排查消息流程问题
3. **功能精简**：移除不需要的模块（询价、库存管理等）
4. **关注点分离**：将消息逻辑与业务逻辑解耦，提高可维护性

当前消息处理、AI 智能体决策和业务功能之间的紧密耦合，使得系统难以在更轻量的基于浏览器的模式下使用。

## 变更内容

### 核心架构
- **提取消息层**：将 WebSocket 消息收发逻辑与 AI 智能体处理分离
- **添加 Chromium 集成**：使用浏览器自动化（Playwright/Puppeteer）控制闲鱼网页
- **拦截网络事件**：通过 Chrome DevTools Protocol (CDP) 捕获 WebSocket 帧
- **创建模块化 API**：提供独立于业务逻辑的清晰消息处理接口

### 组件变更
- **破坏性变更**：移除直接 WebSocket 连接，改用浏览器中介连接
- **破坏性变更**：移除定价智能体、档期智能体、库存管理器集成（可选模块）
- 创建新的 `BrowserController` 用于 Chromium 生命周期管理
- 创建新的 `MessageInterceptor` 用于 CDP WebSocket 帧拦截
- 重构 `XianyuLive`，将连接管理委托给浏览器
- 保持 `XianyuApis` 和认证流程基本不变
- 保留 `ChatContextManager` 和 `XianyuAgent` 作为可选模块

### 移除的功能（可选/用户可配置）
- 议价模块 (PriceAgent)
- 档期/库存管理 (ScheduleAgent, InventoryManager)
- 腾讯文档集成
- 这些功能变为可选插件，可通过配置重新启用

## 影响

### 受影响的规范
- **新增**：`messaging-core` - 核心消息收发抽象
- **新增**：`browser-integration` - Chromium 控制和 CDP 集成

### 受影响的代码
- `main.py` - 用浏览器控制器替换直接 WebSocket 连接
- `XianyuAgent.py` - 使智能体变为可选/可插拔
- 新文件：
  - `browser_controller.py` - Playwright/Puppeteer 封装
  - `message_interceptor.py` - CDP WebSocket 拦截
  - `messaging_core.py` - 抽象消息处理接口
- 配置：新增 `.env` 变量用于浏览器选项（无头模式、调试端口等）

### 迁移路径
- 现有用户运行纯后台可以继续使用传统模式
- 新安装默认使用浏览器模式
- 配置标志切换模式：`USE_BROWSER_MODE=true/false`

### 依赖项
- **新增**：`playwright` 或 `puppeteer` 用于浏览器自动化
- **新增**：`pychrome` 或类似库用于 CDP 协议通信
- **移除**：如果不使用库存功能，可选移除 `tencent-docs-api` 依赖

## 非目标
- 本变更不修改 AI 智能体的提示词逻辑
- 本变更不改变认证/cookie 管理机制
- 本变更不改变聊天历史的数据库模式

## 风险
- **浏览器开销**：Chromium 进程增加内存/CPU 使用（约 100-200MB RAM）
- **稳定性**：浏览器崩溃需要重连逻辑
- **兼容性**：闲鱼网页变更可能破坏选择器/拦截功能

## 成功标准
1. 可以启动 Chromium 加载闲鱼网页并维持会话
2. 可以通过 CDP 拦截 WebSocket 消息，无需直接连接
3. 可以通过浏览器的 WebSocket 连接发送消息
4. 消息处理逻辑保持独立和可复用
5. 配置允许在浏览器模式和无头模式之间切换
