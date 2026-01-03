# 闲鱼聊天历史记录捕获方案

## 背景分析

当打开浏览器访问某个用户的聊天框时，闲鱼会通过HTTP API加载该客户的聊天历史记录。当前系统**只监听WebSocket实时消息**，无法捕获这些通过API加载的历史消息。

## 闲鱼消息加载机制分析

### 1. 实时消息（已实现）
- **传输方式**: WebSocket
- **触发时机**: 用户发送新消息时
- **当前状态**: ✅ 已通过CDP拦截器捕获

### 2. 历史消息（待实现）
- **传输方式**: HTTP API (mtop协议)
- **API域名**: `h5api.m.goofish.com`
- **可能的端点**:
  - `mtop.taobao.idlemessage.queryMessageList` - 查询消息列表
  - `mtop.taobao.idlemessage.queryHistoryMessage` - 查询历史消息
  - `mtop.taobao.idlemessage.getConversationDetail` - 获取会话详情
- **触发时机**:
  - 打开某个用户的聊天窗口
  - 向上滚动加载更多历史消息
  - 刷新聊天页面
- **当前状态**: ❌ 未捕获

## 技术方案

### 方案概述

通过CDP的`Network.responseReceived`事件监听所有HTTP响应，过滤和解析mtop API的响应数据，提取历史消息并存储到数据库。

### 实现步骤

#### 第1步：添加HTTP响应监听

在`xianyu_interceptor/cdp_interceptor.py`中添加Network响应监听：

```python
# 在 setup() 方法中添加
self.cdp_session.on("Network.responseReceived", self._on_response_received)
self.cdp_session.on("Network.loadingFinished", self._on_loading_finished)
```

#### 第2步：实现响应处理器

```python
async def _on_response_received(self, params: Dict[str, Any]) -> None:
    """
    HTTP响应接收事件处理

    监听闲鱼mtop API的响应，提取历史消息
    """
    try:
        response = params.get("response", {})
        url = response.get("url", "")
        request_id = params.get("requestId")

        # 只处理闲鱼的mtop API
        if "h5api.m.goofish.com" not in url:
            return

        # 检查是否是消息相关API
        if any(keyword in url for keyword in [
            "idlemessage.queryMessageList",
            "idlemessage.queryHistoryMessage",
            "idlemessage.getConversationDetail",
            "idlemessage.pc"
        ]):
            logger.info(f"📜 检测到历史消息API: {url[:100]}")

            # 保存请求ID，等待响应体加载完成
            self._pending_history_requests[request_id] = {
                "url": url,
                "timestamp": time.time()
            }
    except Exception as e:
        logger.error(f"处理响应接收事件失败: {e}")

async def _on_loading_finished(self, params: Dict[str, Any]) -> None:
    """
    资源加载完成事件处理

    获取响应体并解析历史消息
    """
    try:
        request_id = params.get("requestId")

        # 检查是否是我们关注的历史消息API
        if request_id not in self._pending_history_requests:
            return

        request_info = self._pending_history_requests.pop(request_id)
        logger.info(f"📥 正在获取历史消息响应体...")

        # 获取响应体
        response_body = await self.cdp_session.send(
            "Network.getResponseBody",
            {"requestId": request_id}
        )

        body_text = response_body.get("body", "")
        if not body_text:
            return

        # 解析mtop响应
        try:
            mtop_response = json.loads(body_text)
            await self._process_history_messages(mtop_response, request_info)
        except json.JSONDecodeError:
            logger.warning(f"无法解析mtop响应: {body_text[:200]}")

    except Exception as e:
        logger.error(f"处理加载完成事件失败: {e}")

async def _process_history_messages(
    self,
    mtop_response: Dict[str, Any],
    request_info: Dict[str, Any]
) -> None:
    """
    处理历史消息数据

    Args:
        mtop_response: mtop API响应
        request_info: 请求信息
    """
    try:
        # mtop响应格式：{"ret": [...], "data": {...}}
        if not mtop_response.get("data"):
            return

        data = mtop_response["data"]

        # 不同API的数据结构可能不同，需要适配
        # 这里是一个通用的处理逻辑
        messages = []

        # 尝试从常见字段提取消息列表
        message_list = (
            data.get("messageList") or
            data.get("messages") or
            data.get("conversationMessages") or
            []
        )

        for msg in message_list:
            # 解析每条历史消息
            try:
                # 提取消息字段（需要根据实际API响应调整）
                chat_id = msg.get("conversationId") or msg.get("chatId")
                user_id = msg.get("senderId") or msg.get("userId")
                content = msg.get("content") or msg.get("text")
                timestamp = msg.get("timestamp") or msg.get("createTime")

                if chat_id and user_id and content:
                    # 创建标准化消息对象
                    from .models import XianyuMessage, XianyuMessageType

                    history_message = XianyuMessage(
                        message_type=XianyuMessageType.CHAT,
                        chat_id=str(chat_id),
                        user_id=str(user_id),
                        content=content,
                        timestamp=timestamp,
                        raw_data=msg,
                        metadata={
                            "source": "history_api",
                            "api_url": request_info["url"]
                        }
                    )

                    messages.append(history_message)
            except Exception as e:
                logger.warning(f"解析单条历史消息失败: {e}")
                continue

        if messages:
            logger.info(f"✅ 成功提取 {len(messages)} 条历史消息")

            # 调用消息回调处理历史消息
            if self.message_callback:
                for msg in messages:
                    # 将XianyuMessage转换为dict格式传递给回调
                    await self.message_callback({
                        "type": "history_message",
                        "message": msg
                    })
        else:
            logger.debug(f"未从API响应中提取到消息: {request_info['url'][:100]}")
            logger.debug(f"响应数据结构: {list(data.keys())}")

    except Exception as e:
        logger.error(f"处理历史消息失败: {e}", exc_info=True)
```

#### 第3步：修改消息处理流程

在`run_xianyu.py`中更新消息回调，处理历史消息：

```python
async def on_message(message_data: dict):
    """
    处理拦截到的消息（包括WebSocket实时消息和HTTP历史消息）
    """
    try:
        # 检查是否是历史消息
        if message_data.get("type") == "history_message":
            xianyu_message = message_data["message"]
            logger.info(
                f"📜 历史消息: {xianyu_message.content[:50]}... "
                f"(chat_id={xianyu_message.chat_id}, "
                f"user_id={xianyu_message.user_id})"
            )

            # 保存到数据库（如果配置了）
            if conversation_store:
                # 转换为ConversationMessage格式
                from xianyu_interceptor.conversation_models import (
                    ConversationMessage,
                    MessageType
                )

                conv_msg = ConversationMessage(
                    chat_id=xianyu_message.chat_id,
                    user_id=xianyu_message.user_id,
                    seller_id="",  # 从配置获取
                    item_id=xianyu_message.item_id or "",
                    message_content=xianyu_message.content,
                    message_type=MessageType.CHAT,
                    context=xianyu_message.metadata
                )

                conversation_store.save_message(conv_msg)
                logger.debug(f"历史消息已保存到数据库")

            return  # 历史消息不需要AI回复

        # 原有的WebSocket实时消息处理逻辑
        # ... （保持不变）
```

#### 第4步：添加配置选项

在`xianyu_interceptor/config.py`中添加配置：

```python
# HTTP History Capture
enable_history_capture: bool = True  # 是否捕获历史消息
history_capture_deduplicate: bool = True  # 是否去重（避免重复保存）
```

## 技术挑战与注意事项

### 1. API响应格式未知

**问题**: 闲鱼的历史消息API响应格式需要通过实际抓包分析。

**解决方案**:
1. 先启用详细日志，记录所有mtop API响应
2. 手动打开聊天窗口，触发历史消息加载
3. 分析日志中的API响应结构
4. 根据实际格式调整解析逻辑

### 2. 消息去重

**问题**: 历史消息可能被多次加载（滚动加载、刷新页面等），导致重复存储。

**解决方案**:
```python
# 在数据库表中添加唯一索引
CREATE UNIQUE INDEX idx_unique_message ON conversations(
    chat_id, user_id, timestamp, message_content(100)
);

# 插入时使用 INSERT IGNORE 或 ON DUPLICATE KEY UPDATE
```

### 3. 性能影响

**问题**: 监听所有HTTP响应可能影响性能。

**解决方案**:
- 只监听`h5api.m.goofish.com`域名的响应
- 使用异步处理，不阻塞主流程
- 对大批量历史消息分批处理

### 4. 数据一致性

**问题**: 历史消息和实时消息的时间戳格式可能不同。

**解决方案**:
- 统一时间戳格式（转换为毫秒级Unix时间戳）
- 添加`source`字段标识消息来源（`websocket` vs `history_api`）

## 实施建议

### 阶段1: 调研（1-2天）

1. 在浏览器开发者工具中手动观察：
   - 打开闲鱼聊天窗口
   - 查看Network面板
   - 找到历史消息加载的API调用
   - 记录请求URL、参数、响应格式

2. 使用现有CDP拦截器添加调试日志：
   ```python
   # 临时添加到setup()中
   async def debug_all_responses(params):
       response = params.get("response", {})
       url = response.get("url", "")
       if "goofish.com" in url:
           logger.debug(f"🔍 闲鱼API: {url}")

   self.cdp_session.on("Network.responseReceived", debug_all_responses)
   ```

### 阶段2: 实现（2-3天）

1. 实现`_on_response_received`和`_on_loading_finished`
2. 根据调研结果实现`_process_history_messages`
3. 更新消息处理流程支持历史消息
4. 添加去重逻辑

### 阶段3: 测试（1-2天）

1. 测试不同场景：
   - 首次打开聊天窗口
   - 滚动加载更多历史消息
   - 刷新页面
2. 验证数据完整性和去重效果
3. 检查性能影响

## 预期效果

实现后，系统将能够：

1. ✅ 捕获用户打开聊天窗口时加载的历史消息
2. ✅ 捕获向上滚动时加载的更多历史消息
3. ✅ 自动去重，避免重复存储
4. ✅ 将历史消息保存到MySQL数据库
5. ✅ 在日志中区分实时消息和历史消息

## 示例日志输出

```
[INFO] 📄 设置页面监控: https://www.goofish.com/message/...
[INFO] ✅ Fetch 域已启用（底层 WebSocket 拦截）
[INFO] 📜 检测到历史消息API: https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.queryMessageList/...
[INFO] 📥 正在获取历史消息响应体...
[INFO] ✅ 成功提取 25 条历史消息
[INFO] 📜 历史消息: 你好，这个手机还在吗？ (chat_id=123456, user_id=789012)
[INFO] 📜 历史消息: 在的，价格可以商量 (chat_id=123456, user_id=654321)
[DEBUG] 历史消息已保存到数据库
[INFO] 📥 收到实时消息: {"headers":{...},"body":{...}}
[INFO] ✅ 实时消息: 那我出500可以吗？ (chat_id=123456, user_id=789012)
```

## 参考资料

- Chrome DevTools Protocol - Network Domain: https://chromedevtools.github.io/devtools-protocol/tot/Network/
- mtop API协议分析（基于XianyuApis.py中的实现）
- 现有WebSocket拦截实现（xianyu_interceptor/cdp_interceptor.py）
