# 浏览器集成规范 (Browser Integration Specification)

## ADDED Requirements

### Requirement: 浏览器生命周期管理 (Browser Lifecycle Management)
系统 SHALL管理 Chromium 浏览器实例的生命周期以访问闲鱼 Web 界面。

#### 场景：启动浏览器并加载闲鱼页面
- **当** 系统以浏览器模式启动时
- **则** 启动 Chromium 浏览器，使用用户数据目录以保持会话持久性
- **并且** 导航到闲鱼网页（www.goofish.com）
- **并且** 从配置恢复 cookies

#### 场景：浏览器崩溃恢复
- **当** 浏览器进程崩溃或无响应时
- **则** 在 30 秒内检测到崩溃
- **并且** 使用先前的会话状态重启浏览器
- **并且** 恢复 WebSocket 连接

#### 场景：无头模式切换
- **当** 配置为 headless=true 时
- **则** 启动浏览器但不显示可见窗口
- **当** 配置为 headless=false 时
- **则** 显示浏览器窗口以便调试

#### 场景：优雅关闭浏览器
- **当** 应用终止时
- **则** 优雅地关闭浏览器
- **并且** 保存会话 cookies
- **并且** 清理浏览器资源

### Requirement: Chrome DevTools 协议集成 (Chrome DevTools Protocol Integration)
系统 SHALL使用 CDP 拦截和注入 WebSocket 消息。

#### 场景：将 CDP 附加到浏览器
- **当** 浏览器启动时
- **则** 连接到 Chrome DevTools Protocol 端点
- **并且** 启用 Network 域以监控 WebSocket
- **并且** 订阅 WebSocket 帧事件

#### 场景：拦截入站 WebSocket 帧
- **当** 闲鱼 WebSocket 接收到帧时
- **则** CDP 通过 Network.webSocketFrameReceived 事件捕获帧数据
- **并且** 帧被解码并传递给消息处理器
- **并且** 浏览器原生 WebSocket 继续正常运行

#### 场景：通过浏览器 WebSocket 发送消息
- **当** 应用需要发送消息时
- **则** 使用 CDP Runtime.evaluate 在页面上下文中执行 JavaScript
- **并且** 在页面现有的 WebSocket 连接上调用 WebSocket.send()
- **并且** 消息通过浏览器的连接传输

#### 场景：监控 WebSocket 连接状态
- **当** 闲鱼页面建立 WebSocket 时
- **则** CDP 检测到 Network.webSocketCreated 事件
- **并且** 存储 WebSocket 标识符以供将来操作
- **当** WebSocket 关闭时
- **则** CDP 检测到 Network.webSocketClosed 事件
- **并且** 触发重连逻辑

### Requirement: Cookie 和会话管理 (Cookie and Session Management)
系统 SHALL通过浏览器存储管理认证 cookies。

#### 场景：从配置注入 cookies
- **当** 浏览器首次启动时
- **则** 从 .env 文件解析 COOKIES_STR
- **并且** 通过 CDP Network.setCookies 命令注入 cookies
- **并且** cookies 持久化在用户数据目录中

#### 场景：提取更新的 cookies
- **当** 闲鱼页面更新认证 cookies 时
- **则** CDP 通过 Network.setCookie 事件监控 cookie 变化
- **并且** 更新的 cookies 被保存回 .env 文件
- **并且** 会话在重启后保持有效

#### 场景：Cookie 过期处理
- **当** cookies 过期或失效时
- **则** 浏览器显示登录页面
- **并且** 系统通过页面标题/URL 检测登录要求
- **并且** 提醒用户手动登录或提供新的 cookies

### Requirement: 浏览器调试支持 (Browser Debugging Support)
系统 SHALL为开发和故障排查提供调试功能。

#### 场景：启用远程调试
- **当** 配置了 debug_port 时
- **则** 使用 --remote-debugging-port 标志启动浏览器
- **并且** 允许外部 Chrome DevTools 连接进行检查

#### 场景：错误时截屏
- **当** 消息处理失败或发生意外状态时
- **则** 通过 CDP Page.captureScreenshot 捕获截屏
- **并且** 保存到调试目录并附带时间戳

#### 场景：控制台日志监控
- **当** 浏览器控制台发出错误或警告时
- **则** CDP 捕获 Runtime.consoleAPICalled 事件
- **并且** 将浏览器控制台消息记录到应用日志器

### Requirement: JavaScript 执行 (JavaScript Execution)
系统 SHALL在页面上下文中执行 JavaScript 以发送消息和检查状态。

#### 场景：通过页面 JavaScript 发送消息
- **当** 通过浏览器发送消息时
- **则** 构造 JavaScript 以调用页面的 WebSocket 发送方法
- **并且** 通过 CDP Runtime.evaluate 执行
- **并且** 返回执行结果或错误

#### 场景：查询页面状态
- **当** 需要验证连接状态时
- **则** 执行 JavaScript 检查 WebSocket readyState
- **并且** 同步返回结果

### Requirement: 浏览器兼容性 (Browser Compatibility)
系统 SHALL与基于 Chromium 的浏览器一起工作并处理版本差异。

#### 场景：使用 Playwright 实现跨平台支持
- **当** 在 Windows、macOS 或 Linux 上运行时
- **则** Playwright 下载并管理适当的 Chromium 二进制文件
- **并且** 浏览器在各平台上一致启动

#### 场景：处理 Chromium 版本更新
- **当** Playwright 更新 Chromium 版本时
- **则** 系统继续使用新浏览器版本正常运行
- **并且** 保持 CDP 协议兼容性

### Requirement: 资源管理 (Resource Management)
系统 SHALL管理浏览器资源消耗。

#### 场景：限制浏览器内存使用
- **当** 浏览器内存超过阈值（可配置，默认 500MB）时
- **则** 重启浏览器以释放内存
- **并且** 重启后恢复会话

#### 场景：关闭不必要的标签页
- **当** 浏览器打开额外的标签页（弹窗、广告）时
- **则** 检测并关闭非闲鱼标签页
- **并且** 仅保持主闲鱼消息页面活动

### Requirement: 配置选项 (Configuration Options)
系统 SHALL为浏览器行为提供配置选项。

#### 场景：配置浏览器启动选项
- **当** 启动浏览器时
- **则** 从环境变量读取配置：
  - BROWSER_HEADLESS（默认值：false）
  - BROWSER_DEBUG_PORT（默认值：无）
  - BROWSER_USER_DATA_DIR（默认值：./browser_data）
  - BROWSER_VIEWPORT_WIDTH（默认值：1280）
  - BROWSER_VIEWPORT_HEIGHT（默认值：720）

#### 场景：运行时切换浏览器模式
- **当** 配置中 USE_BROWSER_MODE=false 时
- **则** 回退到传统的直接 WebSocket 模式
- **并且** 完全跳过浏览器启动
