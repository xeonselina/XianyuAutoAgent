# 实施计划: 闲鱼消息拦截器与 AI Agent HTTP 集成

**分支**: `002-xianyu-agent-http-integration` | **日期**: 2025-12-24 | **规格**: [spec.md](./spec.md)

## 概要

重构现有闲鱼消息拦截器代码，移除旧的 AI 客服逻辑，通过 HTTP 对接到新实现的 AI Agent 服务。保留消息拦截、解析、会话管理等核心功能，新增 HTTP 集成层实现与 Agent 服务的通信。

## 技术上下文

**语言/版本**: Python 3.11+

**主要依赖**:
- `playwright>=1.40.0` - 浏览器自动化
- `httpx>=0.25.0` - 异步 HTTP 客户端
- `redis>=5.0.0` - 会话映射存储（可选）
- `loguru>=0.7.0` - 日志
- `python-dotenv>=1.0.0` - 环境变量管理

**架构**:
```
┌─────────────────┐
│  Xianyu WebApp  │
│  (in Chromium)  │
└────────┬────────┘
         │ WebSocket (CDP intercepted)
         ↓
┌─────────────────────────────────────┐
│   CDP Interceptor (ai_kefu/main.py) │
│  ┌──────────────────────────────┐  │
│  │ 1. browser_controller.py     │  │
│  │    - Launch Chromium         │  │
│  │    - CDP connection          │  │
│  └──────────────────────────────┘  │
│  ┌──────────────────────────────┐  │
│  │ 2. cdp_interceptor.py        │  │
│  │    - Intercept WS messages   │  │
│  │    - Parse Xianyu protocol   │  │
│  └──────────────────────────────┘  │
│  ┌──────────────────────────────┐  │
│  │ 3. messaging_core.py         │  │
│  │    - Session management      │  │
│  │    - Manual mode handling    │  │
│  └──────────────────────────────┘  │
│  ┌──────────────────────────────┐  │
│  │ 4. http_client.py (NEW)      │  │
│  │    - AgentClient class       │  │
│  │    - HTTP → AI Agent         │  │
│  └──────────────────────────────┘  │
└─────────────┬───────────────────────┘
              │ HTTP POST /chat
              ↓
┌─────────────────────────────────────┐
│   AI Agent Service (Port 8000)      │
│  ┌──────────────────────────────┐  │
│  │ FastAPI API                   │  │
│  │ - POST /chat (sync)          │  │
│  │ - POST /chat/stream          │  │
│  │ - Knowledge search           │  │
│  │ - Human-in-the-Loop          │  │
│  └──────────────────────────────┘  │
└─────────────────────────────────────┘
```

**目标平台**: 
- 开发: ARM Mac (Apple Silicon)
- 生产: Linux 服务器

**性能目标**:
- 消息转发延迟: < 500ms
- AI Agent 响应: < 2s (P95)
- 并发对话: 支持 10-50 个

**约束**:
- 必须保持现有浏览器自动化功能
- 不修改 AI Agent 服务代码
- 兼容现有配置文件格式

## 宪法检查

**状态**: ✅ 通过

**检查项**:
1. ✅ **代码分离**: 拦截器与 AI 逻辑解耦，符合单一职责原则
2. ✅ **可测试性**: HTTP 客户端可独立测试
3. ✅ **可维护性**: 移除冗余代码，结构更清晰
4. ✅ **向后兼容**: 保留现有配置和启动方式

## Project Structure

### 重构后的目录结构

```
ai_kefu/
├── xianyu_interceptor/           # 闲鱼拦截器（重构后）
│   ├── __init__.py
│   ├── browser_controller.py     # 浏览器控制（保留）
│   ├── cdp_interceptor.py        # CDP 拦截（保留 + 精简）
│   ├── messaging_core.py         # 消息解析（保留 + 精简）
│   ├── http_client.py            # HTTP 客户端（新增）
│   ├── session_mapper.py         # 会话映射（新增）
│   └── config.py                 # 配置管理（新增）
├── main.py                       # 启动入口（重构）
├── agent/                        # AI Agent 服务（已实现，不修改）
├── api/                          # FastAPI 路由（已实现，不修改）
├── ...                           # 其他 Agent 服务模块
└── legacy/                       # 旧代码归档（可选）
    ├── XianyuAgent.py            # 旧 AI 逻辑
    ├── XianyuApis.py
    └── context_manager.py
```

## 复杂度追踪

**无违规项** - 重构简化了架构，降低了复杂度。

---

## Phase 0: 研究（NEEDS CLARIFICATION 解决）

需要澄清的技术问题：

### R1: 闲鱼消息格式

**问题**: 闲鱼 WebSocket 消息的具体格式是什么？如何提取用户问题、订单信息等？

**研究任务**:
- 分析现有 `cdp_interceptor.py` 和 `messaging_core.py` 的消息解析逻辑
- 确认需要传递给 AI Agent 的字段

**输出**: 消息格式文档，包括：
- WebSocket 消息结构
- 用户消息提取逻辑
- 会话 ID 提取逻辑

### R2: 会话管理策略

**问题**: 如何映射闲鱼会话 ID 到 AI Agent session ID？使用内存还是 Redis？

**研究任务**:
- 评估会话生命周期
- 评估并发量和持久化需求
- 选择存储方案

**输出**: 会话映射设计文档

### R3: HTTP vs gRPC vs WebSocket

**问题**: 拦截器与 Agent 服务的通信方式？

**决策**: HTTP (已选择)

**理由**:
- AI Agent 服务已实现 HTTP API
- 简单易调试
- 支持流式响应（SSE）
- 适合当前规模

### R4: 降级策略

**问题**: AI Agent 服务不可用时如何处理？

**方案**:
1. 记录日志
2. 返回预设回复（可选）
3. 跳过回复，等待手动处理

**输出**: 降级策略文档

---

## Phase 1: 设计

### 数据模型（data-model.md）

#### 1. XianyuMessage (闲鱼消息)

```python
class XianyuMessage:
    conversation_id: str      # 闲鱼对话 ID
    user_id: str              # 买家 ID
    content: str              # 消息内容
    timestamp: int            # 时间戳
    message_type: str         # 消息类型 (text/image/order)
    metadata: Dict[str, Any]  # 额外信息（订单号等）
```

#### 2. SessionMapping (会话映射)

```python
class SessionMapping:
    xianyu_conversation_id: str   # 闲鱼对话 ID
    agent_session_id: str         # AI Agent session ID
    user_id: str                  # 用户 ID
    created_at: datetime
    last_active: datetime
    manual_mode: bool             # 是否手动模式
    manual_mode_timeout: int      # 手动模式超时（秒）
```

### API 契约（contracts/）

#### HTTP Client → AI Agent

**Endpoint**: `POST /chat`

**Request**:
```json
{
  "query": "用户的问题",
  "session_id": "agent-session-uuid",
  "user_id": "xianyu-user-id",
  "context": {
    "conversation_id": "xianyu-conversation-id",
    "source": "xianyu",
    "order_id": "optional-order-id"
  }
}
```

**Response**:
```json
{
  "session_id": "agent-session-uuid",
  "response": "AI 的回复",
  "status": "active",
  "turn_counter": 3
}
```

### 快速开始（quickstart.md）

见下方 Phase 1 输出。

---

## Phase 2: 任务分解（tasks.md）

### 任务列表

#### Phase 1: 代码重构（T001-T010）

- [ ] T001 创建 `xianyu_interceptor/` 目录结构
- [ ] T002 移动 `browser_controller.py` 到新目录
- [ ] T003 移动 `cdp_interceptor.py` 到新目录并精简
- [ ] T004 移动 `messaging_core.py` 到新目录并精简
- [ ] T005 归档旧代码到 `legacy/` 目录
- [ ] T006 创建 `xianyu_interceptor/config.py` 配置管理
- [ ] T007 更新 `main.py` 使用新结构
- [ ] T008 更新 `.env.example` 添加 `AGENT_SERVICE_URL`
- [ ] T009 更新 `requirements.txt` 添加 `httpx`
- [ ] T010 创建单元测试框架

#### Phase 2: HTTP 集成层（T011-T020）

- [ ] T011 实现 `http_client.py` - AgentClient 类
- [ ] T012 实现同步消息发送 `send_message()`
- [ ] T013 实现流式消息接收 `stream_message()`
- [ ] T014 实现错误处理和重试逻辑
- [ ] T015 实现超时处理
- [ ] T016 添加 HTTP 客户端单元测试
- [ ] T017 实现健康检查 `check_agent_health()`
- [ ] T018 实现降级策略
- [ ] T019 添加请求日志记录
- [ ] T020 添加响应缓存（可选）

#### Phase 3: 会话映射（T021-T025）

- [ ] T021 实现 `session_mapper.py` - SessionMapper 类
- [ ] T022 实现内存版会话映射
- [ ] T023 实现 Redis 版会话映射（可选）
- [ ] T024 实现会话超时清理
- [ ] T025 添加会话映射单元测试

#### Phase 4: 消息处理集成（T026-T035）

- [ ] T026 修改 `cdp_interceptor.py` 调用 HTTP 客户端
- [ ] T027 修改 `messaging_core.py` 集成会话映射
- [ ] T028 实现手动模式切换逻辑
- [ ] T029 实现消息队列处理（异步）
- [ ] T030 添加消息转换逻辑（闲鱼格式 → Agent 格式）
- [ ] T031 实现响应转换逻辑（Agent 格式 → 闲鱼格式）
- [ ] T032 添加错误处理和日志
- [ ] T033 实现并发限制
- [ ] T034 添加性能监控（可选）
- [ ] T035 集成测试

#### Phase 5: 测试与验证（T036-T040）

- [ ] T036 端到端测试：消息拦截 → Agent → 回复
- [ ] T037 手动模式测试
- [ ] T038 压力测试：并发 10 个对话
- [ ] T039 异常场景测试（Agent 不可用、超时等）
- [ ] T040 回归测试：确保浏览器自动化功能正常

#### Phase 6: 文档与部署（T041-T045）

- [ ] T041 更新 README.md 说明新架构
- [ ] T042 编写部署文档
- [ ] T043 更新 Docker 配置（如需要）
- [ ] T044 创建迁移指南
- [ ] T045 代码审查和清理

---

## Phase 1 输出示例

### quickstart.md

```markdown
# 快速开始：闲鱼拦截器 + AI Agent 集成

## 前置要求

1. **AI Agent 服务已启动**:
   ```bash
   cd ai_kefu
   make dev  # 或 docker-compose up
   ```
   验证: http://localhost:8000/health

2. **Redis 已启动**（如果使用 Redis 会话映射）:
   ```bash
   redis-server
   ```

3. **闲鱼账号 Cookie**:
   从浏览器获取闲鱼登录 Cookie

## 配置

编辑 `.env` 文件:

```bash
# 闲鱼账号
COOKIES_STR=your_cookies_here

# AI Agent 服务地址
AGENT_SERVICE_URL=http://localhost:8000

# 浏览器模式
USE_BROWSER_MODE=true
BROWSER_HEADLESS=false

# 手动模式
TOGGLE_KEYWORDS=。
MANUAL_MODE_TIMEOUT=3600

# 会话映射（可选）
SESSION_MAPPER_TYPE=memory  # or redis
REDIS_URL=redis://localhost:6379
```

## 启动

```bash
python main.py
```

## 测试

1. 打开闲鱼网页（自动）
2. 发送测试消息给自己
3. 观察 AI Agent 自动回复
4. 发送 "。" 切换手动模式
5. 手动回复后再发送 "。" 恢复自动模式
```

---

## 下一步

1. **Phase 0**: 完成研究任务，生成 `research.md`
2. **Phase 1**: 完善 `data-model.md`, `contracts/`, `quickstart.md`
3. **Phase 2**: 执行任务列表，完成重构和集成

**预估时间**: 2-3 天（1 人）

**里程碑**:
- M1: 代码重构完成（T001-T010）
- M2: HTTP 集成层完成（T011-T020）
- M3: 端到端测试通过（T036）
- M4: 文档完成，可部署（T041-T045）
