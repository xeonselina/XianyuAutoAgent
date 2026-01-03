# 调试历史消息捕获指南

## 目的

增强调试功能，完整记录所有WebSocket消息和HTTP API响应，确保能够找到并捕获闲鱼的历史聊天消息。

## 已添加的增强调试功能

### 1. WebSocket消息完整记录 ✅

**位置**: `run_xianyu.py:103-141`

**功能**:
- ✅ 记录所有包含历史消息关键词的WebSocket消息
- ✅ 显示完整的消息内容（限制2000字符）
- ✅ 标记无法被现有解码器解析的消息
- ✅ 检查lwp路径和body内容

**关键词列表**:
- conversation
- message
- history
- list
- sync
- query
- get
- load

### 2. HTTP API增强监听 ✅

**位置**: `xianyu_interceptor/cdp_interceptor.py:962-971`

**功能**:
- ✅ 扩展了API关键词匹配范围
- ✅ 包含更多可能的历史消息相关API

### 3. 数据结构深度分析 ✅

**位置**: `xianyu_interceptor/cdp_interceptor.py:1088-1127`

**功能**:
- ✅ 自动识别所有可能的消息数组
- ✅ 显示消息对象的样本数据
- ✅ 匹配更多消息特征字段
- ✅ 显示第一项的完整JSON结构

## 使用步骤

### 第1步：启动增强调试模式

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
make run-xianyu
```

### 第2步：触发历史消息加载

**重要**：需要执行以下操作来触发历史消息加载：

1. ✅ 等待浏览器自动打开
2. ✅ 进入"消息中心"
3. ✅ **点击打开一个有聊天记录的用户**
4. ✅ **等待聊天窗口完全加载**（看到历史聊天记录）
5. ✅ 可选：向上滚动加载更多历史消息

### 第3步：观察调试日志

现在系统会输出以下类型的调试信息：

#### A. WebSocket历史消息调试日志

```
[INFO] 🔍 [历史调试] 可能包含历史消息的WebSocket消息:
[INFO]    lwp: /r/Conversation/getByCids
[INFO]    完整消息: {"lwp":"/r/Conversation/getByCids","headers":{...},"body":[...]}
[INFO]    ⚠️ 此消息无法被decode_message解码（可能需要新的解码逻辑）
```

**期望看到的lwp路径**：
- `/r/Conversation/listTop`
- `/r/Conversation/getByCids`
- `/r/Conversation/listNewestPagination`
- `/r/Message/query`
- `/r/Message/getHistory`
- 或其他包含关键词的路径

#### B. HTTP API响应调试日志

```
[INFO] 🔍 [调试] 检测到闲鱼消息相关API:
[INFO]    URL: https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.session.sync/3.0/
[INFO]    状态码: 200
[INFO]    Content-Type: application/json

[INFO] 📥 [调试] 正在获取API响应体...

[INFO] 📄 [调试] API响应内容:
[INFO]    长度: 5234 字节
[INFO]    JSON内容: {...}

[INFO] 🔬 [调试] 数据结构分析:
[INFO]    顶层字段: ['api', 'data', 'ret', 'v']
[INFO]    ✅ 发现可能的消息列表: data.sessions
[INFO]       - 长度: 10
[INFO]       - 第一项字段: ['session', 'message', 'memberFlags']
[INFO]       - 匹配的消息字段: ['message']
[INFO]       - 第一项样本数据:
[INFO]          {
[INFO]            "session": {...},
[INFO]            "message": {
[INFO]              "content": "你好，这个手机还在吗？",
[INFO]              "senderId": "123456",
[INFO]              ...
[INFO]            }
[INFO]          }
```

### 第4步：收集和分析日志

1. **保存完整日志**:
   ```bash
   # 日志会自动保存到
   logs/xianyu_interceptor_2026-01-03.log
   ```

2. **搜索关键标记**:
   ```bash
   # 搜索WebSocket历史调试日志
   grep "历史调试" logs/xianyu_interceptor_2026-01-03.log

   # 搜索发现的消息列表
   grep "发现可能的消息列表" logs/xianyu_interceptor_2026-01-03.log

   # 搜索样本数据
   grep -A 10 "样本数据" logs/xianyu_interceptor_2026-01-03.log
   ```

3. **查找特定的WebSocket路径**:
   ```bash
   grep "lwp:" logs/xianyu_interceptor_2026-01-03.log
   ```

## 预期结果

### 成功情况：找到历史消息

如果看到类似以下的日志，说明找到了历史消息：

```
[INFO] 🔍 [历史调试] 可能包含历史消息的WebSocket消息:
[INFO]    lwp: /r/Message/getHistoryList
[INFO]    完整消息: {"lwp":"/r/Message/getHistoryList","body":[{"messages":[...]}]}
```

或者：

```
[INFO] ✅ 发现可能的消息列表: data.messages
[INFO]    - 长度: 50
[INFO]    - 第一项字段: ['content', 'senderId', 'timestamp', 'chatId']
[INFO]    - 匹配的消息字段: ['content', 'senderId']
```

### 下一步行动

找到历史消息后，我将：
1. ✅ 分析消息的完整数据结构
2. ✅ 编写对应的解码/提取逻辑
3. ✅ 实现历史消息保存功能
4. ✅ 添加去重机制

### 未找到历史消息的情况

如果没有看到任何`[历史调试]`或`发现可能的消息列表`的日志：

**可能原因**：
1. 没有打开有聊天记录的用户
2. 历史消息通过其他机制加载（如懒加载、按需加载）
3. 消息已经被浏览器缓存

**解决方法**：
1. 尝试打开不同的聊天窗口
2. 向上滚动触发加载更多消息
3. 刷新页面重新加载
4. 清除浏览器缓存后重试

## 测试检查清单

运行测试时，请确保完成以下步骤：

- [ ] 启动系统 (`make run-xianyu`)
- [ ] 浏览器自动打开闲鱼网站
- [ ] 进入"消息中心"
- [ ] **重要**：点击打开一个有历史聊天记录的用户
- [ ] 等待聊天窗口完全加载
- [ ] 观察终端输出的调试日志
- [ ] 查看是否有`[历史调试]`标记的日志
- [ ] 查看是否有`发现可能的消息列表`的日志
- [ ] 可选：向上滚动加载更多历史消息
- [ ] 收集并发送完整的调试日志

## 日志文件位置

```
/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/logs/xianyu_interceptor_2026-01-03.log
```

## 重要提示

⚠️ **必须打开有聊天记录的用户**

如果打开的是新用户或者没有聊天记录的用户，将不会触发历史消息加载。

✅ **建议操作**：
- 打开一个你知道有很多聊天记录的用户
- 最好是有几十条消息的会话
- 这样更容易看到历史消息加载的过程

## 反馈信息

完成测试后，请提供以下信息：

1. 是否看到`[历史调试]`标记的日志？
2. 是否看到`发现可能的消息列表`的日志？
3. 如果看到了，请提供：
   - 完整的日志片段
   - WebSocket的lwp路径
   - 消息列表的字段名称
   - 样本数据的内容
4. 如果没看到，请确认：
   - 是否打开了有聊天记录的用户？
   - 聊天窗口是否完全加载了历史消息？
   - 是否看到了任何其他类型的调试日志？
