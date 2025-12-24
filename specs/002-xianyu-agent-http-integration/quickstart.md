# 快速开始: 闲鱼拦截器 + AI Agent HTTP 集成

**项目**: 002-xianyu-agent-http-integration  
**更新日期**: 2025-12-24

本指南帮助您快速部署和测试重构后的闲鱼消息拦截器与 AI Agent 服务集成。

---

## 前置要求

### 1. AI Agent 服务已启动

**启动 Agent 服务**:
```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent

# 方式 1: 直接启动
python -m uvicorn ai_kefu.api.main:app --reload --port 8000

# 方式 2: 使用 Makefile
make dev

# 方式 3: 使用 Docker
docker-compose up -d
```

**验证服务**:
```bash
curl http://localhost:8000/health

# 预期输出
{
  "status": "healthy",
  "checks": {
    "redis": "ok",
    "chroma": "ok",
    "qwen_api": "ok"
  }
}
```

### 2. Redis 已启动

```bash
# 启动 Redis
redis-server

# 验证
redis-cli ping
# 输出: PONG
```

### 3. 闲鱼账号 Cookie

从浏览器登录闲鱼后，获取 Cookie 字符串。

**获取方法**:
1. 打开 Chrome DevTools (F12)
2. 访问 https://2.taobao.com
3. Network → 任意请求 → Headers → Cookie
4. 复制完整 Cookie 字符串

---

## 安装

### 1. 克隆项目（如果尚未克隆）

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent
```

### 2. 安装依赖

```bash
# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 如果需要额外依赖
pip install httpx playwright redis loguru
```

### 3. 安装 Playwright 浏览器

```bash
playwright install chromium
```

---

## 配置

### 编辑 `.env` 文件

创建或编辑 `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/.env`:

```bash
# ============================================================
# 闲鱼拦截器配置
# ============================================================

# 闲鱼账号 Cookie（必填）
COOKIES_STR=your_xianyu_cookies_here

# ============================================================
# AI Agent 服务配置
# ============================================================

# Agent 服务地址
AGENT_SERVICE_URL=http://localhost:8000

# HTTP 客户端配置
AGENT_TIMEOUT=10.0
AGENT_MAX_RETRIES=3
AGENT_RETRY_DELAY=1.0

# ============================================================
# 浏览器模式配置
# ============================================================

# 是否使用浏览器模式
USE_BROWSER_MODE=true

# 无头模式（true=无界面，false=显示浏览器）
BROWSER_HEADLESS=false

# 浏览器窗口大小
BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=720

# ============================================================
# 会话映射配置
# ============================================================

# 会话映射存储类型（memory 或 redis）
SESSION_MAPPER_TYPE=memory

# Redis 配置（如果 SESSION_MAPPER_TYPE=redis）
REDIS_URL=redis://localhost:6379
SESSION_TTL=3600

# ============================================================
# 手动模式配置
# ============================================================

# 切换关键词（发送此关键词切换自动/手动模式）
TOGGLE_KEYWORDS=。

# 手动模式超时（秒）
MANUAL_MODE_TIMEOUT=3600

# ============================================================
# 日志配置
# ============================================================

# 日志级别（DEBUG, INFO, WARNING, ERROR）
LOG_LEVEL=INFO

# 日志格式（json 或 text）
LOG_FORMAT=text
```

---

## 启动

### 1. 启动 AI Agent 服务

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent
make dev

# 或
python -m uvicorn ai_kefu.api.main:app --reload --port 8000
```

### 2. 初始化知识库（首次运行）

```bash
python ai_kefu/scripts/init_knowledge.py
```

### 3. 启动闲鱼拦截器

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
python main.py
```

**预期输出**:
```
[INFO] Starting Xianyu Interceptor...
[INFO] Agent Service URL: http://localhost:8000
[INFO] Browser mode: True (headless=False)
[INFO] Launching Chromium browser...
[INFO] Browser launched successfully
[INFO] Navigating to Xianyu...
[INFO] WebSocket detected: wss://wss-goofish.dingtalk.com/...
[INFO] Message interceptor ready
```

---

## 测试

### 测试 1: 基本对话

1. **发送测试消息**:
   - 在闲鱼网页上找到一个对话
   - 发送消息: "你好"

2. **观察日志**:
   ```
   [INFO] Received message from chat_id=12345
   [INFO] User: 你好
   [INFO] Calling Agent API...
   [INFO] Agent response: 您好！我是 AI 客服助手，很高兴为您服务。请问有什么可以帮您的？
   [INFO] Sent reply to chat_id=12345
   ```

3. **验证回复**:
   - 闲鱼对话中应该看到 AI 的回复

### 测试 2: 知识库检索

1. **发送问题**:
   - "如何申请退款？"

2. **预期回复**:
   - AI 应该根据知识库回复退款政策（7天内无理由退款等）

3. **验证**:
   - 检查日志中是否调用了 `knowledge_search` 工具

### 测试 3: 手动模式切换

1. **进入手动模式**:
   - 发送: "。"

2. **预期响应**:
   - "已切换到手动模式"

3. **手动回复**:
   - 手动输入消息
   - AI 不应自动回复

4. **退出手动模式**:
   - 再次发送: "。"
   - "已切换到自动模式"

### 测试 4: 降级场景

1. **停止 Agent 服务**:
   ```bash
   # 停止 uvicorn
   Ctrl+C
   ```

2. **发送消息**:
   - "测试消息"

3. **预期行为**:
   - 日志显示: `[ERROR] Agent API failed: Connection refused`
   - 不回复用户（降级策略）

4. **重启 Agent 服务**:
   ```bash
   make dev
   ```

5. **再次发送消息**:
   - 应该正常回复

---

## 故障排查

### 问题 1: 无法连接到 Agent 服务

**症状**:
```
[ERROR] Agent API failed: Connection refused
```

**解决**:
1. 检查 Agent 服务是否启动:
   ```bash
   curl http://localhost:8000/health
   ```

2. 检查环境变量:
   ```bash
   echo $AGENT_SERVICE_URL
   ```

3. 检查端口占用:
   ```bash
   lsof -i :8000
   ```

### 问题 2: 浏览器无法启动

**症状**:
```
[ERROR] Failed to launch browser
```

**解决**:
1. 安装 Playwright 浏览器:
   ```bash
   playwright install chromium
   ```

2. 检查权限:
   ```bash
   ls -la ~/.cache/ms-playwright
   ```

3. 尝试无头模式:
   ```bash
   # .env 中设置
   BROWSER_HEADLESS=true
   ```

### 问题 3: WebSocket 未检测到

**症状**:
```
[WARN] WebSocket not detected after 30 seconds
```

**解决**:
1. 检查 Cookie 是否有效
2. 手动刷新页面
3. 检查闲鱼网站是否可访问
4. 查看浏览器控制台错误

### 问题 4: Redis 连接失败

**症状**:
```
[ERROR] Failed to connect to Redis
```

**解决**:
1. 检查 Redis 是否启动:
   ```bash
   redis-cli ping
   ```

2. 检查 Redis URL 配置:
   ```bash
   echo $REDIS_URL
   ```

3. 切换到内存模式:
   ```bash
   # .env 中设置
   SESSION_MAPPER_TYPE=memory
   ```

### 问题 5: 消息解析错误

**症状**:
```
[ERROR] Failed to parse message: KeyError
```

**解决**:
1. 检查闲鱼消息格式是否变更
2. 查看 raw_data 日志
3. 更新消息解析逻辑

---

## 监控与日志

### 查看日志

**实时日志**:
```bash
tail -f logs/xianyu_interceptor.log
```

**过滤错误**:
```bash
grep ERROR logs/xianyu_interceptor.log
```

### 性能指标

**HTTP 客户端指标**:
```bash
# 在 Python 中
from ai_kefu.xianyu_interceptor.http_client import agent_client

metrics = agent_client.get_metrics()
print(f"Success rate: {metrics.get_success_rate():.2%}")
print(f"Avg response time: {metrics.get_avg_response_time():.2f}s")
```

**Agent 服务健康**:
```bash
curl http://localhost:8000/health
```

---

## 高级配置

### 使用 Redis 会话映射

```bash
# 1. 启动 Redis
redis-server

# 2. 配置 .env
SESSION_MAPPER_TYPE=redis
REDIS_URL=redis://localhost:6379

# 3. 重启拦截器
python main.py
```

### 流式响应模式

```python
# 在 http_client.py 中启用流式模式
agent_client = AgentClient(
    base_url=AGENT_SERVICE_URL,
    stream_mode=True
)
```

### 自定义降级策略

```python
# 在 config.py 中
FALLBACK_MESSAGE = "抱歉，我暂时无法回复，请稍后再试。"

# 启用降级回复
ENABLE_FALLBACK_REPLY = True
```

---

## 生产部署建议

### 1. 使用 Docker

```bash
# 构建镜像
docker build -t xianyu-interceptor:latest .

# 运行容器
docker run -d \
  --name xianyu-interceptor \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  xianyu-interceptor:latest
```

### 2. 使用 systemd

创建 `/etc/systemd/system/xianyu-interceptor.service`:

```ini
[Unit]
Description=Xianyu Message Interceptor
After=network.target redis.service

[Service]
Type=simple
User=nobody
WorkingDirectory=/path/to/XianyuAutoAgent/ai_kefu
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务:
```bash
sudo systemctl daemon-reload
sudo systemctl enable xianyu-interceptor
sudo systemctl start xianyu-interceptor
sudo systemctl status xianyu-interceptor
```

### 3. 监控告警

**Prometheus 指标**:
```python
# 导出指标到 Prometheus
from prometheus_client import start_http_server, Counter, Histogram

request_count = Counter('agent_requests_total', 'Total requests')
response_time = Histogram('agent_response_seconds', 'Response time')
```

**日志聚合**:
- 使用 ELK Stack 或 Loki 聚合日志
- 设置告警规则（错误率 > 10%）

---

## 下一步

1. **性能优化**: 根据实际负载调整配置
2. **监控部署**: 部署 Prometheus + Grafana
3. **扩展功能**: 添加更多 AI 能力
4. **文档完善**: 更新 API 文档

---

## 参考资料

- [AI Agent API 文档](http://localhost:8000/docs)
- [plan.md](./plan.md) - 实施计划
- [data-model.md](./data-model.md) - 数据模型
- [research.md](./research.md) - 技术研究

---

**支持**: 如有问题请查看日志或联系技术团队
