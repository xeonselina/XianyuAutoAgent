"""
Transport-level configuration for the Xianyu Interceptor relay.

Only contains settings needed to run the browser/WebSocket transport.
All business logic settings (seller_user_id, toggle_keywords, suppress_keywords,
suppress_duration, session_mapper_type, manual_mode_timeout, etc.) have moved
to ai_kefu/config/settings.py and are consumed by the AI API layer.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file's location (ai_kefu/.env),
# so the config works regardless of the process working directory.
_ENV_FILE = Path(__file__).parent.parent / ".env"


class XianyuInterceptorConfig(BaseSettings):
    """Transport-level config for the Xianyu Interceptor relay."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    # Xianyu Account (needed by the WebSocket transport for auth)
    cookies_str: str = ""

    # AI Agent Service endpoint (the API that owns all business logic)
    agent_service_url: str = "http://localhost:8000"
    agent_timeout: float = 120.0  # kept for health-check legacy callers

    # Transport mode
    use_browser_mode: bool = True
    browser_headless: bool = False
    browser_viewport_width: int = 1280
    browser_viewport_height: int = 720

    # Image handling
    image_save_dir: str = "./xianyu_images"

    # Debug flag: mirrors enable_ai_reply from settings for logging purposes only
    enable_ai_reply: bool = False

    # Logging
    log_level: str = "INFO"
    log_format: str = "text"  # "text" or "json"


# Global config instance
config = XianyuInterceptorConfig()
