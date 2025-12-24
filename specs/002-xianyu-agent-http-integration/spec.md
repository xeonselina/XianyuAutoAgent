# 功能规格: 闲鱼消息拦截器与 AI Agent HTTP 集成

**Feature ID**: 002-xianyu-agent-http-integration  
**日期**: 2025-12-24  
**状态**: Draft

## 问题陈述

当前 `ai_kefu/` 目录包含两套代码：

1. **闲鱼消息拦截器**（保留）：
   - `cdp_interceptor.py` - Chrome DevTools Protocol 拦截 WebSocket
   - `browser_controller.py` - Chromium 浏览器控制
   - `messaging_core.py` - 消息解析和会话管理
   - `main.py` - 启动入口

2. **AI 客服 Agent**（已重新实现）：
   - `XianyuAgent.py` - 旧的 AI 客服逻辑（待移除）
   - 新的 Agent 服务已在 `ai_kefu/agent/`, `ai_kefu/api/` 等目录实现

**目标**：重构代码，将闲鱼消息拦截器通过 HTTP 对接到新的 AI Agent 服务。

## 用户故事

### US1: 消息拦截与转发（核心功能）

**作为** 闲鱼卖家  
**我希望** 系统自动拦截闲鱼消息并转发给 AI Agent 处理  
**以便** 实现自动化客服响应

**验收标准**：
- ✅ 系统通过 Chromium + CDP 拦截闲鱼 WebSocket 消息
- ✅ 解析闲鱼消息格式，提取用户问题、订单信息等
- ✅ 通过 HTTP POST 将消息发送到 AI Agent 服务（`POST /chat`）
- ✅ 接收 AI Agent 响应并通过闲鱼接口发送回复
- ✅ 保持会话状态管理（闲鱼 session ↔ AI Agent session 映射）

### US2: 手动模式支持

**作为** 闲鱼卖家  
**我希望** 能够手动接管对话  
**以便** 处理复杂或敏感问题

**验收标准**：
- ✅ 支持通过关键词（如 "。"）切换自动/手动模式
- ✅ 手动模式下，AI Agent 不自动回复
- ✅ 手动模式超时后自动恢复

### US3: 配置与监控

**作为** 系统管理员  
**我希望** 能够配置拦截器参数  
**以便** 适应不同的部署环境

**验收标准**：
- ✅ 支持配置 AI Agent 服务地址（环境变量）
- ✅ 支持配置浏览器模式（有头/无头）
- ✅ 提供日志记录所有消息交互

## 功能需求

### F1: 消息拦截模块（保留 + 精简）

**保留组件**：
- `cdp_interceptor.py` - CDP WebSocket 拦截
- `browser_controller.py` - 浏览器控制
- `messaging_core.py` - 消息解析
- `main.py` - 启动入口

**移除组件**：
- `XianyuAgent.py` - 旧的 AI 逻辑
- `XianyuApis.py` - 旧的 API 包装（如果不再需要）
- `context_manager.py` - 旧的上下文管理（如果不再需要）

**新增组件**：
- `http_client.py` - HTTP 客户端，对接 AI Agent 服务

### F2: HTTP 集成层

**职责**：
- 将闲鱼消息转换为 AI Agent API 格式
- 调用 AI Agent 服务（`POST /chat` 或 `POST /chat/stream`）
- 处理响应并发送回闲鱼

**接口设计**：
```python
class AgentClient:
    def __init__(self, agent_url: str):
        """初始化 Agent HTTP 客户端"""
        
    async def send_message(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict] = None
    ) -> AgentResponse:
        """发送消息到 AI Agent"""
        
    async def stream_message(
        self,
        query: str,
        session_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """流式接收 AI Agent 响应"""
```

### F3: 会话映射

**需求**：
- 闲鱼对话 ID → AI Agent session ID 映射
- 使用 Redis 或内存缓存存储映射关系
- 支持会话超时清理

**数据结构**：
```python
{
    "xianyu_conversation_id": {
        "agent_session_id": "uuid",
        "user_id": "xianyu_user_id",
        "created_at": "timestamp",
        "last_active": "timestamp",
        "manual_mode": false
    }
}
```

### F4: 手动模式管理

**切换逻辑**：
- 卖家发送关键词 "。" → 切换模式
- 手动模式下，拦截消息但不调用 AI Agent
- 超时（默认 1 小时）后自动恢复

## 非功能需求

### NFR1: 性能

- 消息处理延迟 < 500ms（不含 AI Agent 处理时间）
- 支持并发处理多个对话

### NFR2: 可靠性

- 网络错误时重试（最多 3 次）
- AI Agent 服务不可用时记录日志并跳过
- 浏览器崩溃时自动重启

### NFR3: 可配置性

- 所有关键参数通过环境变量配置
- 支持热重载配置（可选）

## 技术约束

- **编程语言**: Python 3.11+
- **依赖库**: 
  - `playwright` - 浏览器自动化
  - `httpx` - HTTP 客户端
  - `redis` - 会话映射存储（可选）
  - `loguru` - 日志
- **AI Agent 服务**: 已实现，运行在 `http://localhost:8000`

## 边界与限制

**范围内**：
- 重构闲鱼消息拦截器代码
- 实现 HTTP 集成层
- 会话映射管理
- 手动模式支持

**范围外**：
- 修改 AI Agent 服务代码（已完成）
- 闲鱼 WebSocket 协议解析（已实现）
- 浏览器自动化逻辑（已实现，仅需精简）

## 成功指标

- ✅ 代码重构完成，移除旧 AI 逻辑
- ✅ HTTP 集成正常工作，消息能正确转发
- ✅ 手动模式切换正常
- ✅ 日志完整，便于调试
- ✅ 测试覆盖核心流程

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| HTTP 调用延迟影响用户体验 | 高 | 中 | 使用异步调用，考虑流式响应 |
| AI Agent 服务不可用 | 高 | 低 | 实现降级策略（记录日志，跳过回复） |
| 会话映射混乱 | 中 | 低 | 使用 Redis 存储，定期清理 |
| 浏览器资源消耗过高 | 中 | 中 | 限制并发会话数 |

## 依赖关系

- **前置条件**: AI Agent 服务已实现并可访问
- **后续工作**: 性能优化、监控告警

---

**审批**:
- [ ] 产品负责人
- [ ] 技术负责人
- [ ] 架构师
