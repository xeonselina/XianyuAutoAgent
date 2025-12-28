# 数据模型设计: 闲鱼拦截器 HTTP 集成

**项目**: 002-xianyu-agent-http-integration  
**日期**: 2025-12-24  
**版本**: 1.0

---

## 概述

本文档定义闲鱼消息拦截器与 AI Agent HTTP 集成所需的核心数据模型，包括会话映射、消息转换、配置管理等。

---

## 1. SessionMapping (会话映射)

### 用途
将闲鱼对话 ID 映射到 AI Agent session ID，支持双向查找。

### 存储位置
- 内存（默认）
- Redis（可选，用于持久化和分布式）

### 数据结构

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class SessionMapping(BaseModel):
    """会话映射模型"""
    
    # 主键
    xianyu_chat_id: str = Field(..., description="闲鱼对话 ID")
    agent_session_id: str = Field(..., description="AI Agent session ID (UUID)")
    
    # 关联信息
    user_id: str = Field(..., description="买家用户 ID")
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    
    # 状态
    manual_mode: bool = Field(default=False, description="是否手动模式")
    manual_mode_entered_at: Optional[datetime] = Field(None, description="进入手动模式时间")
    
    # 元数据
    item_id: Optional[str] = Field(None, description="商品 ID")
    metadata: dict = Field(default_factory=dict)
    
    class Config:
        json_schema_extra = {
            "example": {
                "xianyu_chat_id": "12345",
                "agent_session_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "buyer_001",
                "created_at": "2025-12-24T10:00:00Z",
                "last_active": "2025-12-24T10:05:00Z",
                "manual_mode": False,
                "item_id": "item_67890"
            }
        }
```

### Redis 存储示例

```python
# 键设计
KEY_FORMAT = {
    "forward": "xianyu:session:{chat_id}",           # chat_id → session_id
    "reverse": "xianyu:session:rev:{session_id}",   # session_id → chat_id  
    "metadata": "xianyu:session:meta:{chat_id}"     # 完整映射对象
}

# 示例
redis.set("xianyu:session:12345", "550e8400-...")
redis.set("xianyu:session:rev:550e8400-...", "12345")
redis.setex("xianyu:session:meta:12345", 3600, json.dumps({
    "xianyu_chat_id": "12345",
    "agent_session_id": "550e8400-...",
    "user_id": "buyer_001",
    ...
}))
```

---

## 2. MessageConversion (消息转换)

### 用途
定义闲鱼消息格式与 AI Agent API 格式之间的转换规则。

### 闲鱼消息格式 (输入)

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any


class XianyuMessageType(str, Enum):
    """闲鱼消息类型"""
    CHAT = "chat"
    ORDER = "order"
    TYPING = "typing"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass
class XianyuMessage:
    """闲鱼原始消息（已解析）"""
    
    message_type: XianyuMessageType
    chat_id: str                          # 对话 ID
    user_id: str                          # 买家 ID
    content: Optional[str] = None         # 消息内容
    item_id: Optional[str] = None         # 商品 ID
    timestamp: Optional[int] = None       # 毫秒时间戳
    raw_data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
```

### Agent API 格式 (输出)

```python
class AgentChatRequest(BaseModel):
    """发送给 AI Agent 的请求"""
    
    query: str = Field(..., description="用户查询", min_length=1)
    session_id: Optional[str] = Field(None, description="Agent session ID")
    user_id: Optional[str] = Field(None, description="用户 ID")
    context: Dict[str, Any] = Field(default_factory=dict, description="上下文信息")


class AgentChatResponse(BaseModel):
    """AI Agent 的响应"""
    
    session_id: str
    response: str
    status: str
    turn_counter: int
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### 转换规则

```python
def convert_xianyu_to_agent(
    xianyu_msg: XianyuMessage,
    agent_session_id: str
) -> AgentChatRequest:
    """闲鱼消息 → Agent API 请求"""
    
    return AgentChatRequest(
        query=xianyu_msg.content,
        session_id=agent_session_id,
        user_id=xianyu_msg.user_id,
        context={
            "conversation_id": xianyu_msg.chat_id,
            "source": "xianyu",
            "item_id": xianyu_msg.item_id,
            "timestamp": xianyu_msg.timestamp,
            "message_type": xianyu_msg.message_type.value
        }
    )


def convert_agent_to_xianyu(
    agent_response: AgentChatResponse,
    xianyu_chat_id: str,
    xianyu_user_id: str
) -> Dict[str, str]:
    """Agent 响应 → 闲鱼回复"""
    
    return {
        "chat_id": xianyu_chat_id,
        "user_id": xianyu_user_id,
        "content": agent_response.response
    }
```

---

## 3. AgentClientConfig (配置模型)

### 用途
管理 HTTP 客户端配置参数。

### 数据结构

```python
class AgentClientConfig(BaseModel):
    """Agent HTTP 客户端配置"""
    
    # 服务地址
    base_url: str = Field(
        default="http://localhost:8000",
        description="AI Agent 服务地址"
    )
    
    # 超时设置
    timeout: float = Field(default=10.0, description="请求超时（秒）")
    connect_timeout: float = Field(default=5.0, description="连接超时（秒）")
    
    # 重试策略
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_delay: float = Field(default=1.0, description="重试延迟（秒）")
    retry_backoff: float = Field(default=2.0, description="退避系数")
    
    # 健康检查
    health_check_interval: int = Field(default=60, description="健康检查间隔（秒）")
    health_check_path: str = Field(default="/health", description="健康检查路径")
    
    # 降级策略
    enable_fallback: bool = Field(default=True, description="启用降级")
    fallback_message: Optional[str] = Field(
        None,
        description="降级回复（None = 不回复）"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "base_url": "http://localhost:8000",
                "timeout": 10.0,
                "max_retries": 3,
                "enable_fallback": True
            }
        }
```

---

## 4. ManualModeState (手动模式状态)

### 用途
跟踪手动模式状态。

### 数据结构

```python
class ManualModeState(BaseModel):
    """手动模式状态"""
    
    chat_id: str = Field(..., description="对话 ID")
    enabled: bool = Field(default=False, description="是否启用")
    entered_at: datetime = Field(default_factory=datetime.utcnow, description="进入时间")
    timeout: int = Field(default=3600, description="超时时间（秒）")
    
    def is_expired(self) -> bool:
        """检查是否超时"""
        elapsed = (datetime.utcnow() - self.entered_at).total_seconds()
        return elapsed > self.timeout
    
    def refresh(self):
        """刷新活动时间"""
        self.entered_at = datetime.utcnow()
```

---

## 5. HTTPClientMetrics (性能指标)

### 用途
记录 HTTP 客户端性能指标，用于监控。

### 数据结构

```python
from collections import defaultdict


class HTTPClientMetrics(BaseModel):
    """HTTP 客户端性能指标"""
    
    # 请求统计
    total_requests: int = Field(default=0, description="总请求数")
    successful_requests: int = Field(default=0, description="成功请求数")
    failed_requests: int = Field(default=0, description="失败请求数")
    
    # 响应时间统计
    total_response_time: float = Field(default=0.0, description="总响应时间（秒）")
    min_response_time: Optional[float] = Field(None, description="最小响应时间")
    max_response_time: Optional[float] = Field(None, description="最大响应时间")
    
    # 错误统计
    error_counts: Dict[str, int] = Field(
        default_factory=lambda: defaultdict(int),
        description="错误类型计数"
    )
    
    # 健康状态
    is_healthy: bool = Field(default=True, description="服务是否健康")
    last_health_check: Optional[datetime] = Field(None, description="最后健康检查时间")
    
    def add_request(self, success: bool, response_time: float, error: Optional[str] = None):
        """记录请求"""
        self.total_requests += 1
        
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if error:
                self.error_counts[error] += 1
        
        self.total_response_time += response_time
        
        if self.min_response_time is None or response_time < self.min_response_time:
            self.min_response_time = response_time
        
        if self.max_response_time is None or response_time > self.max_response_time:
            self.max_response_time = response_time
    
    def get_avg_response_time(self) -> float:
        """获取平均响应时间"""
        if self.total_requests == 0:
            return 0.0
        return self.total_response_time / self.total_requests
    
    def get_success_rate(self) -> float:
        """获取成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
```

---

## 6. 数据流图

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Xianyu WebSocket 消息到达                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    ┌──────▼────────┐
                    │ XianyuMessage │
                    │ (已解析)      │
                    └──────┬────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │ SessionMapper.get_or_create()       │
        │ 查询/创建 SessionMapping             │
        └──────────────────┬──────────────────┘
                           │
                ┌──────────▼──────────┐
                │ agent_session_id     │
                └──────────┬───────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │ convert_xianyu_to_agent()           │
        │ XianyuMessage → AgentChatRequest    │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │ AgentClient.send_message()          │
        │ HTTP POST /chat                     │
        └──────────────────┬──────────────────┘
                           │
                ┌──────────▼──────────┐
                │ AgentChatResponse    │
                └──────────┬───────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │ convert_agent_to_xianyu()           │
        │ AgentChatResponse → 闲鱼回复        │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │ Transport.send_message()            │
        │ 发送到闲鱼 WebSocket                │
        └──────────────────────────────────────┘
```

---

## 7. 索引和查询模式

### Redis 键模式

```
# 会话映射
xianyu:session:{chat_id}                   # 正向映射
xianyu:session:rev:{session_id}            # 反向映射
xianyu:session:meta:{chat_id}              # 完整对象（JSON）

# 手动模式
xianyu:manual:{chat_id}                    # 手动模式状态

# 指标
xianyu:metrics:http_client                 # HTTP 客户端指标
```

### 查询示例

```python
# 获取 Agent session ID
agent_session_id = redis.get(f"xianyu:session:{chat_id}")

# 反向查询 chat ID
chat_id = redis.get(f"xianyu:session:rev:{agent_session_id}")

# 获取完整映射对象
mapping_json = redis.get(f"xianyu:session:meta:{chat_id}")
mapping = SessionMapping.model_validate_json(mapping_json)

# 检查手动模式
is_manual = redis.get(f"xianyu:manual:{chat_id}") == "1"
```

---

## 8. 数据生命周期

### SessionMapping
- **创建**: 首次收到闲鱼消息时
- **更新**: 每次消息交互时刷新 `last_active`
- **过期**: 闲鱼会话超时后（默认 24 小时）
- **删除**: 会话结束或用户主动结束

### ManualModeState
- **创建**: 用户发送切换关键词时
- **更新**: 每次切换时
- **过期**: 超时自动清除（默认 1 小时）
- **删除**: 用户退出手动模式

### HTTPClientMetrics
- **创建**: 客户端初始化时
- **更新**: 每次请求后
- **持久化**: 定期保存到日志或时序数据库
- **重置**: 定期重置或按需重置

---

## 9. 验证规则

### SessionMapping
- `xianyu_chat_id`: 非空字符串
- `agent_session_id`: UUID 格式
- `user_id`: 非空字符串
- `last_active >= created_at`

### AgentChatRequest
- `query`: 非空，长度 <= 10000
- `session_id`: UUID 格式（如果提供）
- `context`: 有效 JSON 对象

### AgentClientConfig
- `base_url`: 有效 HTTP/HTTPS URL
- `timeout > 0`
- `max_retries >= 0`
- `retry_delay > 0`

---

**文档版本**: 1.0  
**最后更新**: 2025-12-24  
**下一步**: 生成 API 契约 (contracts/) 和快速开始指南 (quickstart.md)
