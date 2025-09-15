# COCS 项目函数调用逻辑图

## 项目概述

COCS (咸鱼AI客服系统) 是一个基于浏览器自动化的智能客服机器人，支持监控咸鱼平台消息并使用AI自动回复。

## 系统架构

```mermaid
flowchart TD
    A[main.py - main()] --> B[GoofishAIBot.__init__()]
    A --> C[GoofishAIBot.start()]
    
    C --> D[initialize()]
    D --> E[_init_browser()]
    D --> F[_init_ai_service()]
    D --> G[_init_message_service()]
    D --> H[_init_notification_service()]
    
    E --> I[GoofishBrowser.start()]
    E --> J[GoofishBrowser.wait_for_login()]
    E --> K[GoofishDOMParser.__init__()]
    
    F --> L{AI Service Type}
    L -->|dify| M[DifyAIService.__init__()]
    L -->|qwen| N[QwenAIService.__init__()]
    
    G --> O[MessageService.__init__()]
    G --> P[MessageService.set_ai_service()]
    G --> Q[MessageService.set_browser_service()]
    
    H --> R[NotificationManager.__init__()]
    H --> S[WechatNotificationService.__init__()]
    H --> T[EmailNotificationService.__init__()]
    
    C --> U[_monitor_messages()]
    C --> V[MessageService.start_server()]
    
    U --> W[GoofishBrowser.monitor_new_messages()]
    W --> X[_wait_for_next_new_message()]
    X --> Y[check_for_new_message_indicators()]
    X --> Z[select_contact()]
    X --> AA[get_chat_messages()]
    
    W --> BB[message_callback]
    BB --> CC[MessageService.process_incoming_message()]
    
    CC --> DD[Message object creation]
    CC --> EE[_update_chat_session()]
    CC --> FF[_handle_message_async()]
    
    FF --> GG[_process_with_ai()]
    GG --> HH[_get_chat_history()]
    GG --> II{AI Service}
    II -->|dify| JJ[DifyAIService.process_message()]
    II -->|qwen| KK[QwenAIService.process_message()]
    
    JJ --> LL[_build_context()]
    JJ --> MM[_call_dify_api()]
    JJ --> NN[_parse_dify_response()]
    
    KK --> OO[_build_messages()]
    KK --> PP[_call_qwen_api()]
    KK --> QQ[_parse_qwen_response()]
    
    GG --> RR{Confidence >= 0.7}
    RR -->|Yes| SS[GoofishBrowser.send_message()]
    RR -->|No| TT[NotificationManager.notify_human_required()]
    
    V --> UU[FastAPI Routes]
    UU --> VV[/messages - receive_message()]
    UU --> WW[/messages/{chat_id} - get_chat_messages()]
    UU --> XX[/chats - get_chat_sessions()]
    UU --> YY[/messages/{message_id}/response - send_ai_response()]
    
    VV --> CC
    YY --> SS
    
    style A fill:#e1f5fe
    style C fill:#f3e5f5
    style CC fill:#fff3e0
    style GG fill:#e8f5e8
    style SS fill:#ffebee
```

## 核心调用流程详解

### 1. 系统启动流程

```
main() 
├── GoofishAIBot.__init__()
├── bot.setup_signal_handlers()
└── bot.start()
    └── initialize()
        ├── _init_browser()
        │   ├── GoofishBrowser.start()
        │   ├── GoofishBrowser.wait_for_login()
        │   └── GoofishDOMParser.__init__()
        ├── _init_ai_service()
        │   ├── DifyAIService.__init__() (if dify)
        │   └── QwenAIService.__init__() (if qwen)
        ├── _init_message_service()
        │   ├── MessageService.__init__()
        │   ├── MessageService.set_ai_service()
        │   └── MessageService.set_browser_service()
        └── _init_notification_service()
            ├── NotificationManager.__init__()
            ├── WechatNotificationService.__init__()
            └── EmailNotificationService.__init__()
```

### 2. 消息监控流程

```
_monitor_messages()
└── GoofishBrowser.monitor_new_messages(callback)
    └── while is_running:
        └── _wait_for_next_new_message()
            ├── check_for_new_message_indicators()
            ├── select_contact(contact_name)
            ├── get_chat_messages()
            ├── _find_new_message_for_contact()
            └── _update_last_processed_message()
```

### 3. 消息处理流程

```
message_callback(new_message)
└── MessageService.process_incoming_message()
    ├── Message object creation
    ├── _update_chat_session()
    └── _handle_message_async()
        └── _process_with_ai()
            ├── _get_chat_history()
            ├── AI Service调用
            │   ├── DifyAIService.process_message()
            │   │   ├── _build_context()
            │   │   ├── _call_dify_api()
            │   │   └── _parse_dify_response()
            │   └── QwenAIService.process_message()
            │       ├── _build_messages()
            │       ├── _call_qwen_api()
            │       └── _parse_qwen_response()
            └── if confidence >= 0.7:
                ├── GoofishBrowser.send_message() (自动回复)
                └── else: NotificationManager.notify_human_required()
```

### 4. HTTP API 流程

```
FastAPI Routes
├── POST /messages
│   └── receive_message() → process_incoming_message()
├── GET /messages/{chat_id}
│   └── get_chat_messages()
├── GET /chats
│   └── get_chat_sessions()
└── POST /messages/{message_id}/response
    └── send_ai_response() → GoofishBrowser.send_message()
```

## 关键组件说明

### GoofishBrowser (browser/goofish_browser.py)
- **职责**: 浏览器自动化，消息监控和发送
- **核心方法**:
  - `start()`: 启动浏览器，打开咸鱼页面
  - `monitor_new_messages()`: 监控新消息（串行处理）
  - `send_message()`: 发送回复消息
  - `get_chat_messages()`: 获取聊天消息

### GoofishDOMParser (browser/dom_parser.py)
- **职责**: DOM结构解析，元素定位
- **核心方法**:
  - `detect_message_structure()`: 自动检测消息结构
  - `extract_all_messages()`: 提取所有消息
  - `_analyze_message_item()`: 分析单条消息

### MessageService (service/message_service.py)
- **职责**: 消息处理和路由管理
- **核心方法**:
  - `process_incoming_message()`: 处理传入消息 (line 107)
  - `_handle_message_async()`: 异步消息处理
  - `_process_with_ai()`: AI处理逻辑

### AI Services (service/ai_service.py)
- **DifyAIService**: 对接Dify平台
  - `process_message()`: 处理消息
  - `_call_dify_api()`: 调用Dify API
- **QwenAIService**: 对接阿里云Qwen模型
  - `process_message()`: 处理消息
  - `_call_qwen_api()`: 调用Qwen API

### NotificationService (service/notification_service.py)
- **职责**: 通知和告警管理
- **支持**: 微信、邮件通知

## 数据流向

1. **消息输入**: 咸鱼页面 → GoofishBrowser → MessageService
2. **AI处理**: MessageService → AI Service → API调用
3. **响应输出**: AI回复 → GoofishBrowser → 咸鱼页面
4. **人工介入**: 低置信度 → NotificationManager → 通知渠道

## 关键特性

### 串行消息处理
- 使用持久化存储记录已处理消息
- 基于消息哈希避免重复处理
- 确保消息处理顺序性

### 智能置信度机制
- 置信度 ≥ 0.7: 自动回复
- 置信度 < 0.7: 通知人工介入
- 敏感关键词检测

### 多AI服务支持
- 支持Dify和Qwen两种AI服务
- 统一的AI接口抽象
- 可配置切换AI服务

### 持久化存储
- 消息处理状态持久化
- 联系人状态记录
- 支持系统重启后恢复

## 配置文件结构

系统通过 `config/settings.py` 进行配置管理，包括：
- 浏览器配置 (headless, timeout等)
- AI服务配置 (API密钥, 模型等)
- 通知配置 (微信webhook, 邮件等)
- 服务器配置 (host, port等)

## 错误处理

每个主要组件都包含完善的异常处理：
- 浏览器连接失败自动重试
- AI API调用失败降级处理
- 消息处理失败记录和跳过
- 系统级错误通知和日志记录