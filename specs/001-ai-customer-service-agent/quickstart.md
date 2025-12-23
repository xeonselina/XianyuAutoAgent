# 快速开始: AI 客服 Agent 系统

**项目**: 001-ai-customer-service-agent  
**更新日期**: 2025-12-22

本指南帮助您在本地或内网环境快速搭建并运行 AI 客服 Agent 系统。

---

## 前置要求

### 系统要求
- **操作系统**: Linux / macOS
- **Python**: 3.11+
- **内存**: 至少 4GB RAM
- **磁盘**: 至少 2GB 可用空间

### 外部服务
- **Redis**: 7.x (非持久化配置)
- **Gemini API**: 需要 Google AI API Key

---

## 第一步: 环境准备

### 1.1 安装 Python 3.11+

```bash
# macOS (使用 Homebrew)
brew install python@3.11

# Ubuntu/Debian
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip

# 验证版本
python3.11 --version
```

### 1.2 安装 Redis

```bash
# macOS
brew install redis

# Ubuntu/Debian
sudo apt install redis-server

# 启动 Redis (非持久化配置)
redis-server --save "" --appendonly no --maxmemory 2gb --maxmemory-policy volatile-lru
```

**验证 Redis**:
```bash
redis-cli ping
# 输出: PONG
```

### 1.3 获取 Gemini API Key

1. 访问 [Google AI Studio](https://makersuite.google.com/app/apikey)
2. 创建 API Key
3. 保存 Key (后续配置使用)

---

## 第二步: 项目初始化

### 2.1 克隆代码 (或创建目录)

```bash
cd /path/to/XianyuAutoAgent
```

### 2.2 创建虚拟环境

```bash
python3.11 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate  # Windows
```

### 2.3 安装依赖

创建 `ai_kefu/requirements.txt`:

```text
# Web 框架
fastapi==0.108.0
uvicorn[standard]==0.25.0
pydantic==2.5.0
pydantic-settings==2.1.0

# AI/ML
google-generativeai==0.3.0
chromadb==0.4.18

# 存储
redis==5.0.1

# 工具
python-dotenv==1.0.0
tenacity==8.2.3

# 开发/测试
pytest==7.4.3
httpx==0.25.2
pytest-asyncio==0.21.1
```

安装:
```bash
pip install -r ai_kefu/requirements.txt
```

---

## 第三步: 配置

### 3.1 创建配置文件

创建 `ai_kefu/.env`:

```bash
# Gemini API
GEMINI_API_KEY=你的_API_KEY_放这里

# Redis
REDIS_URL=redis://localhost:6379
REDIS_SESSION_TTL=1800  # 30分钟

# Chroma
CHROMA_PERSIST_PATH=./chroma_data

# 服务配置
API_HOST=0.0.0.0
API_PORT=8000

# Agent 配置
MAX_TURNS=50
TURN_TIMEOUT_SECONDS=120
LOOP_DETECTION_THRESHOLD=5

# 日志
LOG_LEVEL=INFO
```

### 3.2 初始化知识库 (可选)

创建 `ai_kefu/scripts/init_knowledge.py`:

```python
import chromadb
from google import generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# 初始化 Chroma
client = chromadb.PersistentClient(path="./chroma_data")
collection = client.get_or_create_collection(name="knowledge_base")

# 示例知识
knowledge_data = [
    {
        "id": "kb_001",
        "title": "退款政策",
        "content": "用户在收到商品后7天内可申请无理由退款。退款流程: 1. 在订单页面点击申请退款 2. 填写退款原因 3. 等待审核 4. 审核通过后原路退回",
        "category": "售后服务",
        "tags": ["退款", "售后"]
    },
    {
        "id": "kb_002",
        "title": "发货时间",
        "content": "订单通常在付款后24小时内发货。节假日可能延迟1-2天。您可以在订单详情页查看物流信息。",
        "category": "物流配送",
        "tags": ["发货", "物流"]
    },
]

# 生成嵌入并添加到 Chroma
for item in knowledge_data:
    # 使用 Gemini Embeddings API
    result = genai.embed_content(
        model="models/embedding-001",
        content=item["content"],
        task_type="retrieval_document"
    )
    
    collection.add(
        ids=[item["id"]],
        embeddings=[result['embedding']],
        documents=[item["content"]],
        metadatas=[{
            "title": item["title"],
            "category": item["category"],
            "tags": ",".join(item["tags"])
        }]
    )
    print(f"✅ 已添加: {item['title']}")

print(f"\n知识库初始化完成,共 {collection.count()} 条记录")
```

运行初始化:
```bash
cd ai_kefu
python scripts/init_knowledge.py
```

---

## 第四步: 启动服务

### 4.1 开发模式启动

```bash
cd ai_kefu
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4.2 验证服务

打开浏览器访问:
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

预期响应:
```json
{
  "status": "healthy",
  "checks": {
    "redis": "ok",
    "chroma": "ok",
    "gemini_api": "ok"
  }
}
```

---

## 第五步: 测试对话

### 5.1 使用 curl 测试

**同步对话**:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何申请退款?"
  }'
```

**流式对话**:
```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "我的订单什么时候发货?"
  }'
```

### 5.2 使用 Python 测试

创建 `test_client.py`:

```python
import httpx
import json

# 测试同步接口
response = httpx.post(
    "http://localhost:8000/chat",
    json={"query": "如何申请退款?"}
)
print("同步响应:")
print(json.dumps(response.json(), indent=2, ensure_ascii=False))

# 测试流式接口
with httpx.stream(
    "POST",
    "http://localhost:8000/chat/stream",
    json={"query": "我的订单什么时候发货?"},
    timeout=30.0
) as response:
    print("\n流式响应:")
    for line in response.iter_lines():
        if line.startswith("data: "):
            data = json.loads(line[6:])
            print(data)
```

运行:
```bash
python test_client.py
```

### 5.3 测试 Human-in-the-Loop 功能

创建 `test_human_loop.py`:

```python
import httpx
import json
import time
from threading import Thread

BASE_URL = "http://localhost:8000"

def simulate_agent():
    """模拟 Agent 请求人工协助"""
    print("=== Agent 开始对话 ===")
    response = httpx.post(
        f"{BASE_URL}/chat",
        json={
            "query": "帮我查一下订单 #12345 的发货时间"
        }
    )
    result = response.json()
    session_id = result['session_id']
    print(f"会话 ID: {session_id}")
    print(f"Agent 状态: {result['status']}")
    
    # Agent 会调用 ask_human_agent，状态变为 waiting_for_human
    if result['status'] == 'waiting_for_human':
        print("Agent 正在等待人工回复...")
        return session_id
    return None

def simulate_human_agent(session_id):
    """模拟人工客服回复"""
    print("\n=== 人工客服查看待处理请求 ===")
    
    # 查询待处理请求
    response = httpx.get(f"{BASE_URL}/human-agent/pending-requests")
    requests = response.json()
    print(f"待处理请求数: {requests['total']}")
    
    if requests['total'] > 0:
        req = requests['items'][0]
        print(f"请求 ID: {req['request_id']}")
        print(f"问题: {req['question']}")
        print(f"类型: {req['question_type']}")
        
        # 查看详情
        detail = httpx.get(
            f"{BASE_URL}/sessions/{session_id}/pending-request"
        ).json()
        print(f"\n对话历史: {len(detail['conversation_history'])} 条消息")
        
        # 人工回复
        print("\n=== 人工客服回复 ===")
        response = httpx.post(
            f"{BASE_URL}/sessions/{session_id}/human-response",
            json={
                "request_id": req['request_id'],
                "human_agent_id": "agent_001",
                "response": "订单已于 2025-12-20 发货，物流单号 SF123456"
            }
        )
        result = response.json()
        print(f"回复结果: {result['message']}")

# 执行测试
session_id = simulate_agent()
if session_id:
    time.sleep(2)  # 等待 Agent 暂停
    simulate_human_agent(session_id)
    
    # 查看最终结果
    time.sleep(1)
    session = httpx.get(f"{BASE_URL}/sessions/{session_id}").json()
    print(f"\n=== 最终会话状态 ===")
    print(f"状态: {session['status']}")
    print(f"最后消息: {session['messages'][-1]['content']}")
```

运行:
```bash
python test_human_loop.py
```

预期输出:
```
=== Agent 开始对话 ===
会话 ID: 550e8400-e29b-41d4-a716-446655440000
Agent 状态: waiting_for_human
Agent 正在等待人工回复...

=== 人工客服查看待处理请求 ===
待处理请求数: 1
请求 ID: req_abc123
问题: 请帮我查询订单 #12345 的发货时间和物流单号
类型: information_query

对话历史: 2 条消息

=== 人工客服回复 ===
回复结果: Agent 已继续执行

=== 最终会话状态 ===
状态: completed
最后消息: 您的订单已于 12 月 20 日发货，物流单号为 SF123456...
```

---

## 第六步: 生产部署

### 6.1 使用 Gunicorn (多进程)

```bash
pip install gunicorn

# 启动 4 个 worker 进程
gunicorn ai_kefu.main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

### 6.2 使用 systemd (Linux)

创建 `/etc/systemd/system/ai-kefu.service`:

```ini
[Unit]
Description=AI Customer Service Agent
After=network.target redis.service

[Service]
Type=notify
User=www-data
WorkingDirectory=/path/to/XianyuAutoAgent/ai_kefu
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/gunicorn main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

启动服务:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-kefu
sudo systemctl start ai-kefu
sudo systemctl status ai-kefu
```

### 6.3 使用 Docker (可选)

创建 `ai_kefu/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
```

创建 `docker-compose.yml`:

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    command: redis-server --save "" --appendonly no --maxmemory 2gb --maxmemory-policy volatile-lru
    ports:
      - "6379:6379"
  
  ai-kefu:
    build: ./ai_kefu
    ports:
      - "8000:8000"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./chroma_data:/app/chroma_data
    depends_on:
      - redis
```

启动:
```bash
docker-compose up -d
```

---

## 常见问题

### Q1: Redis 连接失败
**A**: 检查 Redis 是否启动: `redis-cli ping`

### Q2: Gemini API 报 403 错误
**A**: 检查 API Key 是否正确,是否有配额限制

### Q3: Chroma 数据库为空
**A**: 运行 `python scripts/init_knowledge.py` 初始化知识库

### Q4: 流式响应中断
**A**: 检查网络连接,确保客户端支持 SSE

### Q5: 性能不足
**A**: 增加 Gunicorn workers 数量: `-w 8`

---

## 下一步

1. **添加更多知识**: 通过 POST `/knowledge` 接口添加业务知识
2. **自定义 Prompt**: 修改 `ai_kefu/prompts/system_prompt.py`
3. **监控日志**: 配置日志聚合 (ELK/Loki)
4. **性能优化**: 根据实际负载调整 workers 和 Redis 配置

---

## 参考资料

- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [Gemini API 文档](https://ai.google.dev/docs)
- [Chroma 文档](https://docs.trychroma.com/)
- [Redis 文档](https://redis.io/docs/)

**支持**: 如有问题请联系开发团队
