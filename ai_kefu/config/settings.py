"""
Configuration management using pydantic-settings.
Loads configuration from environment variables and .env files.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Qwen API Configuration
    api_key: str
    model_name: str = "qwen-plus"
    model_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    qwen_temperature: float = 0.7
    qwen_top_p: float = 0.9
    qwen_max_tokens: int = 2048
    
    # Redis Configuration
    redis_url: str = "redis://localhost:6379"
    redis_session_ttl: int = 1800  # 30 minutes
    
    # Chroma Configuration
    chroma_persist_path: str = str(Path(__file__).parent.parent / "chroma_data")
    
    # API Service Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # Agent Configuration
    max_turns: int = 50
    turn_timeout_seconds: int = 120
    loop_detection_threshold: int = 5
    
    # Logging Configuration
    log_level: str = "INFO"
    log_format: str = "json"  # json or text
    
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=()
    )


# Global settings instance
settings = Settings()
