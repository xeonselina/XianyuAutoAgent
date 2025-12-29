"""
Xianyu Interceptor module.

Integrates Xianyu message interception with AI Agent HTTP service.
"""

from .config import config, XianyuInterceptorConfig
from .models import (
    XianyuMessage,
    XianyuMessageType,
    SessionMapping,
    AgentChatRequest,
    AgentChatResponse,
    AgentClientConfig,
    HTTPClientMetrics,
    ManualModeState
)
from .message_converter import convert_xianyu_to_agent, convert_agent_to_xianyu
from .session_mapper import SessionMapper, MemorySessionMapper, RedisSessionMapper
from .manual_mode import ManualModeManager
from .http_client import AgentClient
from .message_handler import MessageHandler
from .conversation_models import ConversationMessage, MessageType, ConversationSummary
from .conversation_store import ConversationStore
from .exceptions import (
    XianyuInterceptorError,
    AgentAPIError,
    SessionMapperError,
    MessageConversionError,
    BrowserControlError,
    InterceptorConfigError
)
from .logging_setup import setup_logging
from .main_integration import (
    initialize_interceptor,
    run_interceptor,
    setup_agent_client,
    setup_session_mapper,
    setup_manual_mode_manager,
    setup_conversation_store
)

__all__ = [
    # Config
    "config",
    "XianyuInterceptorConfig",

    # Models
    "XianyuMessage",
    "XianyuMessageType",
    "SessionMapping",
    "AgentChatRequest",
    "AgentChatResponse",
    "AgentClientConfig",
    "HTTPClientMetrics",
    "ManualModeState",

    # Conversation Models
    "ConversationMessage",
    "MessageType",
    "ConversationSummary",

    # Converters
    "convert_xianyu_to_agent",
    "convert_agent_to_xianyu",

    # Session Management
    "SessionMapper",
    "MemorySessionMapper",
    "RedisSessionMapper",

    # Manual Mode
    "ManualModeManager",

    # HTTP Client
    "AgentClient",

    # Message Handler
    "MessageHandler",

    # Conversation Store
    "ConversationStore",

    # Exceptions
    "XianyuInterceptorError",
    "AgentAPIError",
    "SessionMapperError",
    "MessageConversionError",
    "BrowserControlError",
    "InterceptorConfigError",

    # Setup
    "setup_logging",
    "initialize_interceptor",
    "run_interceptor",
    "setup_agent_client",
    "setup_session_mapper",
    "setup_manual_mode_manager",
    "setup_conversation_store",
]
