import os
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class BrowserConfig(BaseModel):
    """浏览器配置"""
    headless: bool = False
    viewport_width: int = 1000
    viewport_height: int = 800
    user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    login_timeout: int = 300000  # 5分钟


class AIConfig(BaseModel):
    """AI服务配置"""
    # Dify配置
    dify_api_url: Optional[str] = None
    dify_api_key: Optional[str] = None
    
    # 阿里云Qwen配置
    qwen_api_key: Optional[str] = None
    qwen_model_name: str = "qwen-turbo"
    
    # AI选择：dify 或 qwen
    ai_service_type: str = "dify"  # dify, qwen
    
    # 置信度阈值
    confidence_threshold: float = 0.7


class NotificationConfig(BaseModel):
    """通知配置"""
    # 微信机器人webhook
    wechat_webhook_url: Optional[str] = None
    
    # 邮件配置
    email_smtp_server: Optional[str] = None
    email_smtp_port: int = 587
    email_username: Optional[str] = None
    email_password: Optional[str] = None
    email_recipients: list = []
    
    # 通知开关
    enable_notifications: bool = True


class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False


class LogConfig(BaseModel):
    """日志配置"""
    level: str = "INFO"
    log_file: Optional[str] = "logs/goofish_ai.log"
    max_file_size: str = "10 MB"
    retention_days: int = 30


class Settings(BaseModel):
    """应用设置"""
    
    # 应用信息
    app_name: str = "咸鱼AI客服"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # 各模块配置
    browser: BrowserConfig = BrowserConfig()
    ai: AIConfig = AIConfig()
    notification: NotificationConfig = NotificationConfig()
    server: ServerConfig = ServerConfig()
    log: LogConfig = LogConfig()
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._load_from_env()
    
    def _load_from_env(self):
        """从环境变量加载配置"""
        
        # 调试模式
        if os.getenv("DEBUG"):
            self.debug = os.getenv("DEBUG").lower() in ["true", "1", "yes"]
        
        # 浏览器配置
        if os.getenv("BROWSER_HEADLESS"):
            self.browser.headless = os.getenv("BROWSER_HEADLESS").lower() in ["true", "1", "yes"]
        
        # AI配置
        if os.getenv("DIFY_API_URL"):
            self.ai.dify_api_url = os.getenv("DIFY_API_URL")
        if os.getenv("DIFY_API_KEY"):
            self.ai.dify_api_key = os.getenv("DIFY_API_KEY")
        if os.getenv("QWEN_API_KEY"):
            self.ai.qwen_api_key = os.getenv("QWEN_API_KEY")
        if os.getenv("QWEN_MODEL_NAME"):
            self.ai.qwen_model_name = os.getenv("QWEN_MODEL_NAME")
        if os.getenv("AI_SERVICE_TYPE"):
            self.ai.ai_service_type = os.getenv("AI_SERVICE_TYPE")
        if os.getenv("CONFIDENCE_THRESHOLD"):
            try:
                self.ai.confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD"))
            except ValueError:
                pass
        
        # 通知配置
        if os.getenv("WECHAT_WEBHOOK_URL"):
            self.notification.wechat_webhook_url = os.getenv("WECHAT_WEBHOOK_URL")
        if os.getenv("EMAIL_SMTP_SERVER"):
            self.notification.email_smtp_server = os.getenv("EMAIL_SMTP_SERVER")
        if os.getenv("EMAIL_SMTP_PORT"):
            try:
                self.notification.email_smtp_port = int(os.getenv("EMAIL_SMTP_PORT"))
            except ValueError:
                pass
        if os.getenv("EMAIL_USERNAME"):
            self.notification.email_username = os.getenv("EMAIL_USERNAME")
        if os.getenv("EMAIL_PASSWORD"):
            self.notification.email_password = os.getenv("EMAIL_PASSWORD")
        if os.getenv("EMAIL_RECIPIENTS"):
            self.notification.email_recipients = os.getenv("EMAIL_RECIPIENTS").split(",")
        if os.getenv("ENABLE_NOTIFICATIONS"):
            self.notification.enable_notifications = os.getenv("ENABLE_NOTIFICATIONS").lower() in ["true", "1", "yes"]
        
        # 服务器配置
        if os.getenv("SERVER_HOST"):
            self.server.host = os.getenv("SERVER_HOST")
        if os.getenv("SERVER_PORT"):
            try:
                self.server.port = int(os.getenv("SERVER_PORT"))
            except ValueError:
                pass
        
        # 日志配置
        if os.getenv("LOG_LEVEL"):
            self.log.level = os.getenv("LOG_LEVEL").upper()
        if os.getenv("LOG_FILE"):
            self.log.log_file = os.getenv("LOG_FILE")
    
    def validate_config(self) -> bool:
        """验证配置"""
        errors = []
        
        # 验证AI配置
        if self.ai.ai_service_type == "dify":
            if not self.ai.dify_api_url or not self.ai.dify_api_key:
                errors.append("使用Dify服务时，必须配置DIFY_API_URL和DIFY_API_KEY")
        elif self.ai.ai_service_type == "qwen":
            if not self.ai.qwen_api_key:
                errors.append("使用Qwen服务时，必须配置QWEN_API_KEY")
        else:
            errors.append(f"不支持的AI服务类型: {self.ai.ai_service_type}")
        
        # 验证通知配置
        if self.notification.enable_notifications:
            if not self.notification.wechat_webhook_url and not self.notification.email_smtp_server:
                errors.append("启用通知时，至少需要配置微信webhook或邮件服务")
        
        if errors:
            for error in errors:
                print(f"配置错误: {error}")
            return False
        
        return True


# 全局设置实例
settings = Settings()


def get_settings() -> Settings:
    """获取设置实例"""
    return settings