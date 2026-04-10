"""
Configuration management using pydantic-settings.
Loads configuration from environment variables and .env files.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Qwen API Configuration
    api_key: str
    model_name: str = "qwen-plus"
    model_name_light: str = "qwen3.5-flash"  # 轻量模型，用于置信度评估/摘要/情感分类等简单任务
    model_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_temperature: float = 0.3
    qwen_top_p: float = 0.9
    qwen_max_tokens: int = 256
    
    # Redis Configuration
    redis_url: str = "redis://localhost:6379"
    redis_session_ttl: int = 86400  # 24 hours (Redis LRU handles memory pressure)
    
    # Chroma Configuration
    chroma_persist_path: str = str(Path(__file__).parent.parent / "chroma_data")

    # MySQL Configuration (for knowledge entries and conversations)
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = "xianyu_conversations"

    # API Service Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # Qwen API Timeout (单次调用超时，SDK 默认 300s 太长)
    qwen_api_timeout: float = 30.0
    
    # Agent Configuration
    max_turns: int = 50
    turn_timeout_seconds: int = 100  # Agent 单轮超时（需小于 interceptor 的 120s）
    loop_detection_threshold: int = 5
    enable_loop_detection: bool = True
    
    # Rental Business API Configuration
    rental_api_base_url: str
    rental_find_slot_endpoint: str
    
    # Logging Configuration
    log_level: str = "INFO"
    log_format: str = "json"  # json or text

    # Confidence guard configuration
    enable_confidence_guard: bool = True
    response_confidence_threshold: float = 0.80  # 0~1

    # DingTalk Robot Configuration (钉钉群聊机器人)
    dingtalk_webhook_url: str = ""   # 钉钉机器人 Webhook URL（Incoming，用于发通知到群里）
    dingtalk_secret: str = ""        # 加签密钥（可选，推荐配置）
    dingtalk_outgoing_token: str = ""  # (兼容) Outgoing Webhook Token（旧模式，可不配置）

    # DingTalk Stream 模式（推荐，无需公网回调地址）
    dingtalk_app_key: str = ""       # 钉钉应用 Client ID (AppKey)
    dingtalk_app_secret: str = ""    # 钉钉应用 Client Secret (AppSecret)

    # Xianyu Configuration
    xianyu_cookie: str = ""   # 闲鱼 Cookie（从浏览器开发者工具中获取，用于调用闲鱼 API）
    # Interceptor browser cookie (env var COOKIES_STR, set by the interceptor's .env).
    # Used as a fallback source for xianyu_cookie when XIANYU_COOKIE is not explicitly set.
    cookies_str: str = ""

    @model_validator(mode="after")
    def _fill_xianyu_cookie_from_cookies_str(self) -> "Settings":
        """
        If XIANYU_COOKIE is not set but COOKIES_STR is, use COOKIES_STR as the
        xianyu_cookie value.  Both env vars point to the same Xianyu session
        cookie — COOKIES_STR is just the traditional interceptor name.
        """
        if not self.xianyu_cookie and self.cookies_str:
            self.xianyu_cookie = self.cookies_str
        return self

    # Xianyu Business Logic Configuration (used by /xianyu/inbound endpoint)
    seller_user_id: str = ""           # 卖家用户ID，用于区分消息方向
    toggle_keywords: str = "。"        # 切换手动/自动模式的关键词（逗号分隔）
    suppress_keywords: str = "。"      # 临时抑制 AI 回复的暗号（逗号分隔）
    suppress_duration: int = 600       # AI 抑制持续时间（秒），默认 10 分钟
    enable_ai_reply: bool = False      # 是否启用 AI 自动回复（False = 仅调试模式）
    session_mapper_type: str = "memory"  # session mapper 类型: "memory" 或 "redis"
    manual_mode_timeout: int = 3600    # 手动模式超时（秒），默认 1 小时
    xianyu_session_ttl: int = 3600     # Xianyu 会话 TTL（秒），用于 session mapper 清理

    # Eval mock configuration (for check_availability)
    eval_mock_availability: bool = False
    eval_mock_availability_available_ratio: float = 0.80
    
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=()
    )


# Global settings instance
settings = Settings()
