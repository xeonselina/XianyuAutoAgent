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
        case_sensitive=False
    )
    
    # Xianyu Account
    cookies_str: str = ""
    
    # AI Agent Service
    agent_service_url: str = "http://localhost:8000"
    agent_timeout: float = 10.0
    agent_max_retries: int = 3
    agent_retry_delay: float = 1.0
    
    # Browser Mode
    use_browser_mode: bool = True
    browser_headless: bool = False
    browser_viewport_width: int = 1280
    browser_viewport_height: int = 720
    
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


# Global config instance
config = XianyuInterceptorConfig()
