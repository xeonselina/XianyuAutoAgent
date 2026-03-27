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
