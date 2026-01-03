# 历史消息API调试指南

## 目的

捕获并分析闲鱼在加载聊天历史记录时使用的HTTP API，以便后续实现自动保存历史消息的功能。

## 已添加的调试功能

### 1. HTTP响应监听
- ✅ 监听所有闲鱼相关的API响应
- ✅ 自动识别消息相关的API（包含message、conversation、chat、idlemessage等关键词）
- ✅ 记录API的URL、状态码、Content-Type

### 2. 响应体捕获
- ✅ 自动获取API响应的完整内容
- ✅ 解析JSON格式的响应
- ✅ 美化输出（限制3000字符，避免日志过大）

### 3. 数据结构分析
- ✅ 自动分析响应的数据结构
- ✅ 识别可能包含消息列表的字段
- ✅ 显示消息对象的字段名称

## 使用步骤

### 第1步：启动拦截器

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
make run-xianyu
```

启动后你会看到：
```
[INFO] ✅ 历史消息API监听器已启用（调试模式）
```

### 第2步：打开浏览器并访问聊天窗口

1. 等待浏览器自动打开闲鱼网站
2. 登录后，点击"消息中心"
3. **随便打开一个用户的聊天窗口**
4. **观察终端日志输出**

### 第3步：观察日志输出

当你打开聊天窗口时，应该会看到类似这样的日志：

```
[INFO] 🔍 [调试] 检测到闲鱼消息相关API:
[INFO]    URL: https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.queryMessageList/...
[INFO]    状态码: 200
[INFO]    Content-Type: application/json

[INFO] 📥 [调试] 正在获取API响应体...
[INFO]    URL: https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.queryMessageList/...

[INFO] 📄 [调试] API响应内容:
[INFO]    长度: 5234 字节
[INFO]    JSON内容:
[INFO]    {
[INFO]      "ret": ["SUCCESS::调用成功"],
[INFO]      "data": {
[INFO]        "messageList": [
[INFO]          {
[INFO]            "content": "你好，这个手机还在吗？",
[INFO]            "senderId": "123456",
[INFO]            "timestamp": 1704067200000,
[INFO]            ...
[INFO]          }
[INFO]        ]
[INFO]      }
[INFO]    }

[INFO] 🔬 [调试] 数据结构分析:
[INFO]    顶层字段: ['ret', 'data']
[INFO]    ✅ 发现可能的消息列表: data.messageList
[INFO]       - 长度: 25
[INFO]       - 第一项字段: ['content', 'senderId', 'timestamp', 'conversationId', ...]
[INFO]       - 匹配的消息字段: ['content', 'senderId']
```

### 第4步：测试不同场景

为了获取完整的API信息，请测试以下场景：

1. **首次打开聊天窗口** - 观察初始加载的API
2. **向上滚动** - 观察加载更多历史消息的API
3. **刷新页面** - 观察重新加载的API
4. **切换不同的聊天** - 观察API的通用性

### 第5步：收集日志

1. **复制完整的日志输出**（特别是标记为`[调试]`的部分）
2. **保存到文件**或直接提供给我分析
3. 重点关注：
   - API的完整URL
   - 响应的JSON结构
   - 数据结构分析结果

## 下一步

当你提供日志后，我将：

1. ✅ 确认历史消息API的准确端点
2. ✅ 确定响应的数据结构
3. ✅ 编写消息提取逻辑
4. ✅ 实现历史消息保存功能
5. ✅ 添加去重机制

## 常见场景

### 场景1：没有看到任何API日志

**可能原因**：
- 聊天窗口还没有打开
- 历史消息已经缓存在前端，没有发起新的API请求

**解决方法**：
- 尝试打开不同的聊天窗口
- 清除浏览器缓存后重试
- 向上滚动加载更多消息

### 场景2：API日志太多，难以找到关键信息

**解决方法**：
- 只关注包含`[调试]`标记的日志
- 查找包含`idlemessage`、`message`、`conversation`的URL
- 将日志保存到文件：`make run-xianyu > debug.log 2>&1`

### 场景3：响应体获取失败

**可能原因**：
- 某些响应可能无法通过CDP获取（如已缓存的响应）
- 响应已经被浏览器处理

**解决方法**：
- 多尝试几次，打开不同的聊天
- 使用浏览器开发者工具的Network面板手动查看

## 备用方案：手动抓包

如果自动调试没有捕获到数据，你也可以手动查看：

1. 打开浏览器开发者工具（F12）
2. 切换到Network面板
3. 过滤：在搜索框输入"idlemessage"或"message"
4. 打开一个聊天窗口
5. 在Network面板中找到相关的请求
6. 点击请求，查看Response标签页
7. 复制响应内容并提供给我

## 文件位置

- 调试代码：`xianyu_interceptor/cdp_interceptor.py:943-1111`
- 技术方案：`docs/CHAT_HISTORY_CAPTURE.md`
- 本指南：`docs/HISTORY_API_DEBUG_GUIDE.md`

## 注意事项

⚠️ **这是临时的调试代码**
- 目前会记录所有消息相关的API响应
- 日志可能会很多，这是正常的
- 分析完成后，我会将其改为正式的历史消息捕获功能
- 不会影响现有的WebSocket实时消息拦截

✅ **安全性**
- 只监听HTTP响应，不修改任何数据
- 不会影响聊天的正常功能
- 所有数据仅在本地日志中记录
