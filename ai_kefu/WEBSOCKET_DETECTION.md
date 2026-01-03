# WebSocket 检测机制说明

## 概述

闲鱼消息拦截器使用**多层 WebSocket 检测机制**来确保能够可靠地拦截消息。

## 为什么需要多层检测？

闲鱼的 WebSocket 连接具有以下特点：

1. **位置不确定**
   - 可能在主窗口中创建
   - 可能在跨域 iframe 中创建
   - 可能在新打开的 Tab 或页面中创建

2. **创建时机不确定**
   - 可能在页面加载时立即创建
   - 可能在用户点击"消息中心"后才创建
   - 可能在页面导航/刷新后重新创建

3. **浏览器限制**
   - JavaScript 无法访问跨域 iframe
   - CDP 事件可能因浏览器版本差异而不触发
   - 单一检测方式可能失效

## 三层检测机制

### 第一层：CDP Network 事件

**文件**: `xianyu_interceptor/cdp_interceptor.py:53-57`

```python
self.cdp_session.on("Network.webSocketCreated", self._on_websocket_created)
self.cdp_session.on("Network.webSocketFrameReceived", self._on_frame_received)
self.cdp_session.on("Network.webSocketFrameSent", self._on_frame_sent)
self.cdp_session.on("Network.webSocketClosed", self._on_websocket_closed)
```

**优点**:
- 官方 CDP API，最直接
- 可以拦截所有帧（包括跨域）
- 提供完整的消息内容

**缺点**:
- 某些浏览器版本可能不触发
- 需要浏览器支持

### 第二层：Fetch 域拦截

**文件**: `xianyu_interceptor/cdp_interceptor.py:70-90`

```python
await self.cdp_session.send("Fetch.enable", {
    "patterns": [
        {"urlPattern": "*wss://*", "requestStage": "Request"},
        {"urlPattern": "*ws://*", "requestStage": "Request"}
    ]
})
```

**优点**:
- 底层拦截，非常可靠
- 可以捕获跨域 iframe 中的请求
- 捕获握手阶段

**缺点**:
- 只能捕获握手，不能直接获取消息内容
- 需要额外配置

### 第三层：JavaScript 注入

**文件**: `xianyu_interceptor/cdp_interceptor.py:460-629`

```javascript
window.WebSocket = class extends OriginalWebSocket {
    constructor(...args) {
        super(...args);
        // 拦截逻辑
    }
};
```

**优点**:
- 可以拦截 WebSocket 的所有方法（send, onmessage）
- 提供详细的调试信息
- 可以主动检测页面中的 WebSocket 实例

**缺点**:
- 无法访问跨域 iframe
- 页面刷新后需要重新注入

## 多页面监听机制

**文件**: `run_xianyu.py:53-182`

### 为什么需要监听多个页面？

闲鱼的架构导致 WebSocket 可能在不同页面中创建：

1. **首页** - 用户启动时加载，通常没有 WebSocket
2. **消息中心** - 用户点击后导航，WebSocket 在这里创建
3. **聊天窗口** - 可能是新 Tab 或 Popup

### 三个关键监听器

#### 1. 监听所有已存在的页面

```python
all_existing_pages = browser_controller.context.pages
for page in all_existing_pages:
    await setup_page_monitoring(page)
```

**用途**: 为所有已打开的页面设置拦截器

#### 2. 监听新打开的页面

```python
browser_controller.context.on("page", on_new_page)
```

**用途**: 当用户打开新 Tab 或 Popup 时自动设置拦截器

#### 3. 监听页面导航

```python
page.on("framenavigated", on_navigation)
```

**用途**: 当页面跳转或刷新时重新注入拦截器

## 定期主动检测

**文件**: `run_xianyu.py:190-220`

```python
for page_id, info in page_interceptors.items():
    interceptor = info['interceptor']
    if await interceptor.check_websocket_in_page():
        # 找到 WebSocket
```

**为什么需要**:
- CDP 事件可能丢失
- WebSocket 可能在页面加载完成后才创建
- 提供兜底机制

## 问题排查

### 如果无法检测到 WebSocket

1. **检查日志中是否有以下输出**:
   - `📄 设置页面监控:` - 页面监控是否设置
   - `🆕 检测到新页面打开:` - 新页面是否被监听
   - `🔄 页面导航:` - 页面导航是否被捕获
   - `🌐 检测到 WebSocket 请求:` - Fetch 域是否拦截到

2. **检查是否删除了关键代码**:
   - `run_xianyu.py:53-182` - 多页面监听机制
   - `cdp_interceptor.py:53-110` - CDP 事件监听器
   - `cdp_interceptor.py:460-629` - JavaScript 拦截器注入

3. **手动触发**:
   - 在浏览器中手动点击"消息中心"
   - 查看是否有新页面打开或导航事件
   - 等待 5 秒让主动检测运行

## 历史记录

- **commit 7f54081** - "稳定了 ws"
  - 实现了多页面监听机制
  - 添加了 Fetch 域拦截
  - 完善了 JavaScript 拦截器

- **2026-01-03** - 添加详细注释
  - 防止关键代码被误删
  - 说明每层检测的作用
  - 提供问题排查指南

## 维护建议

1. **不要删除任何一层检测**
   - 即使看起来"冗余"
   - 每一层都有特定的用途
   - 作为互相的备份

2. **保留详细日志**
   - 有助于调试和监控
   - 了解 WebSocket 的创建时机
   - 发现新的检测场景

3. **测试多种场景**
   - 刷新页面
   - 新 Tab 打开
   - 页面导航
   - 跨域 iframe

4. **参考旧版本**
   - `git show 7f54081` 查看工作版本
   - 对比差异找出问题
   - 保持关键代码不变
