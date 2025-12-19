# 设计文档：消息提取和 Chromium 集成

## 背景

当前的闲鱼 AI 客服系统（`main.py`、`XianyuLive`）作为纯后台守护进程运行，直接建立到闲鱼消息基础设施的 WebSocket 连接。虽然功能正常，但这种方法有几个限制：

1. **可见性有限**：运行期间没有可视化反馈，调试困难
2. **紧密耦合**：消息处理、业务逻辑和 AI 智能体交织在一起
3. **功能臃肿**：包含许多用户不需要的模块（定价、库存）
4. **维护负担**：更改消息逻辑需要浏览复杂的智能体代码

目标是将其转变为更模块化的、基于浏览器的架构：
- 通过真实的 Chromium 浏览器窗口提供可视化反馈
- 将消息关注点与业务逻辑分离
- 使可选功能真正可选
- 保持与现有部署的向后兼容性

## 目标 / 非目标

### 目标
1. **关注点分离**：将消息逻辑提取为可复用的、传输无关的模块
2. **浏览器集成**：启用基于 Chromium 的操作，使用 CDP WebSocket 拦截
3. **配置灵活性**：允许用户启用/禁用功能（浏览器模式、智能体）
4. **向后兼容性**：为无头服务器保留现有的直接 WebSocket 模式
5. **可维护性**：通过使架构更模块化来降低认知负荷

### 非目标
1. **UI 开发**：不构建 Web 仪表板或管理面板
2. **协议变更**：不修改闲鱼的消息格式或认证
3. **智能体逻辑变更**：不改变 AI 提示、决策或 LLM 集成
4. **数据库迁移**：聊天历史架构保持不变

## 架构决策

### 决策 1：抽象传输层

**选择**：创建 `MessageTransport` 抽象基类，包含两种实现：
- `DirectWebSocketTransport`（传统）
- `BrowserWebSocketTransport`（新）

**理由**：
- 允许通过配置切换模式而无需代码更改
- 封装传输特定的复杂性（CDP、浏览器管理）
- 支持未来的传输选项（例如，用于测试的模拟传输）

**考虑的替代方案**：
- **单一实现使用 if/else**：由于分离性差和可维护性差而拒绝
- **单独的代码库**：由于代码重复和分歧风险而拒绝
- **插件架构**：对于两个已知实现过于复杂

**权衡**：
- 优点：干净的抽象，易于测试，可维护
- 缺点：增加一层间接性，前期代码稍多

### 决策 2：Playwright vs Puppeteer

**选择**：使用 Playwright 进行浏览器自动化

**理由**：
- **跨平台**：在 Windows、macOS、Linux 上一致工作
- **内置浏览器管理**：自动下载 Chromium，处理版本控制
- **更好的 CDP 支持**：更强大的 DevTools Protocol 集成
- **积极开发**：Microsoft 支持，频繁更新
- **Python 优先**：原生 Python API（Puppeteer 是 Node.js 优先）

**考虑的替代方案**：
- **Puppeteer 配合 pyppeteer**：由于 pyppeteer 已停止维护而拒绝
- **Selenium**：由于缺乏 CDP 支持和性能较慢而拒绝
- **原始 CDP 客户端（pychrome）**：由于需要手动管理浏览器二进制文件而拒绝

**权衡**：
- 优点：可靠、文档完善、跨平台
- 缺点：较大的依赖（~100MB Chromium 下载），对于简单的 CDP 使用来说过于复杂

### 决策 3：CDP WebSocket 拦截方法

**选择**：监控 `Network.webSocketFrameReceived` 事件，并通过在页面上下文中执行 JavaScript 的 `Runtime.evaluate` 发送消息

**理由**：
- **非侵入性**：不修改页面的 WebSocket 对象，降低破坏风险
- **完全可见性**：捕获所有帧，包括二进制和文本
- **可靠发送**：使用页面现有的 WebSocket 连接，无需复制握手
- **调试友好**：可以同时在真实的 Chrome DevTools 中检查帧

**考虑的替代方案**：
- **拦截和代理 WebSocket**：由于复杂性和协议不匹配的可能性而拒绝
- **覆盖 WebSocket 构造函数**：由于破坏页面行为的风险而拒绝
- **使用浏览器扩展**：由于安装复杂性和 manifest v3 限制而拒绝

**权衡**：
- 优点：简单、可靠、可维护
- 缺点：需要 JavaScript 注入（在受信任的上下文中是轻微的安全考虑）

### 决策 4：可选智能体系统

**选择**：通过环境标志使智能体（PriceAgent、ScheduleAgent 等）可选

**理由**：
- **用户灵活性**：许多用户不需要库存或定价功能
- **降低复杂性**：基本用例的设置更简单
- **减少依赖**：如果不使用库存功能，可以跳过腾讯文档 API 安装
- **逐步采用**：用户可以逐步启用功能

**实现**：
```python
# 在 XianyuAgent.__init__() 中：
self.agents = {'classify': ClassifyAgent(...)}
if os.getenv('ENABLE_PRICE_AGENT', 'false').lower() == 'true':
    self.agents['price'] = PriceAgent(...)
if os.getenv('ENABLE_SCHEDULE_AGENT', 'false').lower() == 'true':
    self.agents['schedule'] = ScheduleAgent(...)
self.agents['default'] = DefaultAgent(...)
```

**考虑的替代方案**：
- **插件加载器系统**：对于当前需求过度设计而拒绝
- **单独的包**：由于分发复杂性而拒绝
- **始终加载所有智能体**：由于用户反馈不必要的功能而拒绝

**权衡**：
- 优点：对新用户更清晰，依赖开销更少
- 缺点：需要记录更多配置选项

### 决策 5：基于配置的模式切换

**选择**：使用 `USE_BROWSER_MODE` 环境变量在直连和浏览器模式之间切换

**理由**：
- **简单**：一个布尔标志，易于理解
- **运行时灵活性**：无需代码修改即可更改模式
- **部署友好**：不同环境（开发、生产、无头服务器）使用不同的 .env

**默认**：`USE_BROWSER_MODE=true`（新用户默认使用浏览器模式）

**考虑的替代方案**：
- **命令行标志**：对于守护进程部署不太方便而拒绝
- **配置文件**：为保持现有 .env 模式而拒绝
- **自动检测**：由于潜在的意外行为而拒绝

**权衡**：
- 优点：清晰、明确、易于记录
- 缺点：需要编辑 .env 文件来切换模式

## 组件架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  应用初始化                                                 │ │
│  │  - 加载 .env 配置                                          │ │
│  │  - 基于 USE_BROWSER_MODE 创建 TransportFactory             │ │
│  │  - 使用传输初始化 XianyuLive                               │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
         ┌────────────────────────────────────────┐
         │      TransportFactory                  │
         │  if USE_BROWSER_MODE:                  │
         │    return BrowserWebSocketTransport()  │
         │  else:                                 │
         │    return DirectWebSocketTransport()   │
         └────────────────────────────────────────┘
                              │
           ┌──────────────────┴──────────────────┐
           ▼                                     ▼
┌──────────────────────────┐      ┌──────────────────────────┐
│ DirectWebSocketTransport │      │ BrowserWebSocketTransport│
│  - websockets 库         │      │  + BrowserController     │
│  - 直接连接              │      │  + CDPInterceptor        │
│  - 心跳循环              │      │  - CDP 消息捕获          │
│  - token 刷新            │      │  - JS 消息注入           │
└──────────────────────────┘      └──────────────────────────┘
           │                                     │
           │          ┌──────────────────────────┘
           │          │
           ▼          ▼
    ┌──────────────────────────┐
    │   XianyuMessageCodec     │
    │  - encode_message()      │
    │  - decode_message()      │
    │  - classify_message()    │
    └──────────────────────────┘
                 │
                 ▼
    ┌──────────────────────────┐
    │     MessageRouter        │
    │  - register_handler()    │
    │  - dispatch(message)     │
    └──────────────────────────┘
                 │
                 ▼
    ┌──────────────────────────┐
    │   XianyuLive             │
    │  - handle_message()      │
    │  - context_manager       │
    │  - manual_mode tracking  │
    └──────────────────────────┘
                 │
                 ▼
    ┌──────────────────────────┐
    │   XianyuAgent            │
    │  - ClassifyAgent (核心)  │
    │  - PriceAgent (可选)     │
    │  - ScheduleAgent (可选)  │
    │  - DefaultAgent (核心)   │
    └──────────────────────────┘
```

## 浏览器集成细节

### 浏览器生命周期
```python
class BrowserController:
    async def launch(self):
        # 使用用户数据目录启动 Playwright 浏览器
        # 从 COOKIES_STR 注入 cookies
        # 导航到 www.goofish.com
        # 返回 CDP 会话

    async def ensure_alive(self):
        # 检查浏览器进程是否运行
        # 如果崩溃，重启并恢复状态

    async def close(self):
        # 将 cookies 保存到 .env
        # 优雅地关闭浏览器
```

### CDP 拦截
```python
class CDPInterceptor:
    async def setup(self, cdp_session):
        # 启用 Network 域
        # 订阅 webSocketFrameReceived
        # 订阅 webSocketCreated/Closed

    async def on_frame_received(self, event):
        # 提取帧数据
        # 如果需要则解码
        # 传递给 MessageRouter

    async def send_message(self, websocket_id, frame_data):
        # 使用 Runtime.evaluate 执行：
        # document.querySelector('websocket').send(data)
```

## 迁移路径

### 对于现有用户
1. 更新代码：`git pull`
2. 安装新依赖：`pip install -r requirements.txt`
3. 运行浏览器安装：`playwright install chromium`
4. **选项 A（浏览器模式）**：在 .env 中添加 `USE_BROWSER_MODE=true`
5. **选项 B（传统模式）**：在 .env 中添加 `USE_BROWSER_MODE=false`（不需要更改）

### 对于新用户
1. 默认配置使用浏览器模式
2. 首次运行通过 Playwright 自动下载 Chromium
3. 浏览器打开显示闲鱼界面
4. 所有交互的可视化反馈

## 风险和缓解措施

### 风险 1：浏览器稳定性
**风险**：Chromium 崩溃或挂起，中断服务
**缓解**：
- 实现崩溃检测（监控浏览器进程健康）
- 使用指数退避自动重启
- 内存限制监控（超过阈值时重启）
- 如果浏览器反复失败，回退到直连模式

### 风险 2：闲鱼页面变更
**风险**：闲鱼更新网页，破坏 WebSocket 选择器或 CDP 拦截
**缓解**：
- CDP 通过 ID 监控 WebSocket（不是 DOM 选择器），对页面变更有弹性
- JavaScript 注入使用浏览器现有的 WebSocket 实例，不是页面 DOM
- 在 README 中记录故障排除步骤
- 保留直接 WebSocket 模式作为回退

### 风险 3：资源开销
**风险**：浏览器消耗大量 RAM/CPU
**缓解**：
- 服务器上默认为无头模式（BROWSER_HEADLESS=true）
- 实现内存监控和定期重启
- 记录资源需求（预期 ~200MB RAM）
- 为资源受限环境提供直连模式

### 风险 4：CDP 协议变更
**风险**：Playwright 或 Chrome DevTools Protocol API 变更
**缓解**：
- 在 requirements.txt 中固定 Playwright 版本
- 针对特定 Chromium 版本测试
- 监控 Playwright 发布说明以了解破坏性变更
- 保持直连模式作为回退

## 性能考虑

### 浏览器模式
- **内存**：Chromium 进程约 150-250MB
- **CPU**：空闲时最小，活跃消息期间约 5-10%
- **延迟**：与直连模式相比每条消息 +10-50ms（CDP 开销）
- **启动时间**：约 2-5 秒（浏览器启动 + 页面加载）

### 直连模式
- **内存**：约 20-50MB（仅 Python 进程）
- **CPU**：活跃消息期间 <5%
- **延迟**：每条消息 <10ms
- **启动时间**：<1 秒

### 建议
- **开发/调试**：使用浏览器模式（有头）以获得可见性
- **生产（有显示的服务器）**：使用浏览器模式（无头）
- **生产（无头 VPS）**：使用直连模式以提高效率

## 待解决的问题

1. **Q**：是否应该支持其他浏览器（Firefox、WebKit）？
   **A**：不，仅支持 Chromium 以简化。闲鱼 Web 应用无论如何都是为 Chrome 优化的。

2. **Q**：浏览器模式是否应该支持代理？
   **A**：是，添加 BROWSER_PROXY 配置。传递给 Playwright 启动选项。

3. **Q**：如何处理多个账户？
   **A**：不在此变更范围内。用户可以使用不同的 .env 文件运行多个实例。

4. **Q**：是否应该为配置提供 GUI？
   **A**：不，.env 编辑对目标用户（开发人员）来说足够了。

5. **Q**：如何处理浏览器更新？
   **A**：Playwright 自动管理 Chromium 更新。固定 Playwright 版本以控制更新计划。

## 成功指标

1. ✅ 浏览器模式启动并捕获消息，帧丢失率 <1%
2. ✅ 消息发送与直连模式具有相同的可靠性（>99.9%）
3. ✅ 浏览器崩溃恢复在 10 秒内完成
4. ✅ 内存使用在 24 小时以上的运行中保持在 300MB 以下
5. ✅ 用户可以通过单个配置更改在模式之间切换
6. ✅ 现有直连模式用户体验零回归
