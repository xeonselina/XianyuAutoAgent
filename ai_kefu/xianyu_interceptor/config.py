"""
Configuration management for Xianyu Interceptor.

Uses pydantic-settings for environment-based configuration.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class XianyuInterceptorConfig(BaseSettings):
    """Xianyu Interceptor configuration."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields in .env
        protected_namespaces=()  # Disable protected namespaces to allow model_ prefix
    )

    # Xianyu Account
    cookies_str: str = ""

    # AI Model Configuration (for backend API)
    api_key: str = ""
    model_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    model_name: str = "qwen-max"
    qwen_api_key: str = ""  # Alias for api_key

    # AI Agent Service
    enable_ai_reply: bool = False  # Whether to enable AI auto-reply
    agent_service_url: str = "http://localhost:8000"
    agent_timeout: float = 10.0
    agent_max_retries: int = 3
    agent_retry_delay: float = 1.0
    
    # Browser Mode
    use_browser_mode: bool = True
    browser_headless: bool = False
    browser_viewport_width: int = 1280
    browser_viewport_height: int = 720

    # Image Handling
    image_save_dir: str = "./xianyu_images"

    # Session Mapping
    session_mapper_type: str = "memory"  # "memory" or "redis"
    redis_url: str = "redis://localhost:6379"
    session_ttl: int = 3600  # seconds
    
    # Manual Mode
    toggle_keywords: str = "。"
    manual_mode_timeout: int = 3600  # seconds
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "text"  # "text" or "json"

    # MySQL Database for Conversation Persistence
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = "xianyu_conversations"
    mysql_pool_size: int = 5


# Global config instance
config = XianyuInterceptorConfig()
