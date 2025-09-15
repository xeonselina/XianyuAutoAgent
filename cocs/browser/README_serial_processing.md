# 咸鱼浏览器串行消息处理系统

## 概述

重构后的咸鱼浏览器消息监控系统解决了以下关键问题：

1. **持久化存储**：使用文件系统保存最后处理的消息，程序重启后不会重复处理
2. **串行处理**：每次只处理一条新消息，确保消息处理的顺序性和完整性
3. **双重检测**：结合新消息标记和消息内容双重判断，提高新消息识别准确性

## 主要改进

### 1. 持久化存储机制

```python
# 数据文件结构
./goofish_data/
├── last_messages.json     # 最后处理的消息哈希
└── contact_states.json    # 联系人状态记录
```

**last_messages.json 示例：**
```json
{
  "张三": "a1b2c3d4e5f6...",  // 消息哈希
  "李四": "b2c3d4e5f6a1...",
  "王五": "c3d4e5f6a1b2..."
}
```

### 2. 新消息检测策略

#### 双重检测机制：
1. **新消息标记检测**：检查联系人列表中的红点、徽章等视觉标记
2. **消息内容对比**：与持久化存储的最后处理消息对比

#### 检测流程：
```
1. 扫描联系人列表 → 找到有新消息标记的联系人
2. 逐个进入聊天 → 获取最新消息列表
3. 对比消息哈希 → 找到真正的新消息
4. 串行处理消息 → 更新持久化存储
5. 继续下一个联系人
```

### 3. 串行处理保证

- **一次一条**：等待一条消息完全处理完毕再处理下一条
- **顺序保证**：按照发现新消息的顺序处理
- **错误隔离**：单条消息处理失败不影响其他消息

## 使用方法

### 基本用法

```python
import asyncio
from goofish_browser import GoofishBrowser

async def handle_message(message):
    """消息处理函数"""
    print(f"收到消息: {message['text']}")
    # 这里可以调用AI、数据库等处理逻辑
    await asyncio.sleep(2)  # 模拟处理时间
    print("处理完成")

async def main():
    # 创建浏览器实例
    browser = GoofishBrowser(
        headless=False, 
        data_dir="./my_data"  # 指定数据存储目录
    )
    
    try:
        await browser.start()
        await browser.wait_for_login()
        
        # 开始串行监控
        await browser.monitor_new_messages(handle_message)
        
    finally:
        await browser.close()

asyncio.run(main())
```

### 高级功能

#### 1. 查看消息统计
```python
stats = browser.get_message_stats()
print(f"已处理联系人: {stats['total_contacts']}")
print(f"联系人列表: {stats['contacts_with_history']}")
```

#### 2. 重置消息历史
```python
# 重置特定联系人
browser.reset_message_history("张三")

# 重置所有历史
browser.reset_message_history()
```

#### 3. 自定义数据目录
```python
browser = GoofishBrowser(data_dir="./custom_data_dir")
```

## 新消息标记检测

系统会自动检测以下常见的新消息标记：

### 支持的选择器
- `.unread-badge` - 未读徽章
- `.message-count` - 消息计数
- `.red-dot` - 红点标记
- `.new-message-indicator` - 新消息指示器
- `[class*="unread"]` - 包含"unread"的类名
- `[class*="new"]` - 包含"new"的类名
- `.badge` - 通用徽章
- `.notification-dot` - 通知点

### 检测策略
1. **视觉元素检测**：查找红点、数字徽章等可见元素
2. **CSS类名检测**：检查是否包含新消息相关的样式类
3. **可见性验证**：确保标记元素实际可见

## 消息哈希机制

为了准确识别消息是否已处理，系统使用MD5哈希：

```python
def _generate_message_hash(self, message: Dict) -> str:
    """生成消息唯一标识"""
    content = f"{message.get('text', '')}{message.get('timestamp', '')}{message.get('sender', '')}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()
```

### 哈希内容包括：
- 消息文本内容
- 时间戳
- 发送者信息

## 错误处理和日志

### 日志级别
- `INFO`: 重要状态变更（开始监控、发现新消息、处理完成）
- `DEBUG`: 详细调试信息（哈希计算、选择器匹配）
- `WARNING`: 可恢复错误（联系人无法进入、标记误报）
- `ERROR`: 严重错误（存储失败、处理异常）

### 错误恢复
- **存储错误**：自动重试，使用内存备份
- **网络错误**：增加等待时间，自动重连
- **处理异常**：记录错误但继续处理下一条消息

## 性能优化

### 1. 轮询间隔调整
```python
# 修改检查间隔（默认2秒）
await browser._wait_for_next_new_message(poll_interval=1.0)
```

### 2. 批量操作
- 持久化存储批量写入
- 联系人状态批量检查

### 3. 内存管理
- 定期清理过期数据
- 限制消息历史长度

## 调试和测试

### 1. 启用详细日志
```python
from loguru import logger
logger.add("debug.log", level="DEBUG")
```

### 2. 测试新消息标记
```python
# 检查特定联系人的新消息标记
contacts = await browser.check_for_new_message_indicators()
for contact in contacts:
    print(f"{contact['name']}: {contact['has_new_message_indicator']}")
```

### 3. 模拟消息处理
```python
async def slow_handler(message):
    print(f"开始处理: {message['text']}")
    await asyncio.sleep(5)  # 模拟慢处理
    print("处理完成")
```

## 常见问题

### Q: 程序重启后是否会重复处理消息？
A: 不会。使用持久化存储保存最后处理的消息哈希，重启后会从上次停止的地方继续。

### Q: 如何处理消息处理失败的情况？
A: 系统会记录错误但不会停止整个监控流程，继续处理下一条消息。可以通过日志查看具体错误。

### Q: 新消息标记检测不准确怎么办？
A: 可以通过DOM检查器工具找到页面实际使用的选择器，然后修改 `_check_new_message_indicator` 方法中的选择器列表。

### Q: 如何提高处理性能？
A: 
1. 减少轮询间隔
2. 优化消息处理回调函数
3. 使用异步处理代替同步处理

### Q: 数据文件太大怎么办？
A: 可以定期调用 `reset_message_history()` 清理历史数据，或手动删除数据目录下的JSON文件。

## 扩展功能

系统设计考虑了扩展性，可以轻松添加：

1. **消息过滤器**：只处理特定类型的消息
2. **优先级队列**：重要联系人优先处理
3. **批量回复**：模板化消息批量发送
4. **统计分析**：消息频率、处理时间等统计
5. **外部API集成**：与AI服务、CRM系统等集成

---

这个重构后的系统解决了原始广度优先遍历的复杂性问题，提供了可靠的串行消息处理机制，适合生产环境使用。