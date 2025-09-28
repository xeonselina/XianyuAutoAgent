"""
库存管理服务配置文件
"""

import os
from datetime import timedelta


# 智能选择数据库连接：如果在Docker容器中，使用DATABASE_URL，否则使用DATABASE_URL_HOST
def _get_database_uri():
    # 检查是否在Docker容器中（通过检查/.dockerenv文件）
    is_docker = os.path.exists('/.dockerenv')

    if is_docker:
        # 在Docker容器中，使用DATABASE_URL (host.docker.internal)
        return os.environ.get('DATABASE_URL') or \
            'mysql+pymysql://root:password@host.docker.internal/inventory_management'
    else:
        # 在本地环境中，优先使用DATABASE_URL_HOST (localhost)
        return os.environ.get('DATABASE_URL_HOST') or \
            os.environ.get('DATABASE_URL') or \
            'mysql+pymysql://root:password@localhost/inventory_management'


class Config:
    """基础配置类"""

    # 基础配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # 数据库配置
    SQLALCHEMY_DATABASE_URI = _get_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True
    }
    
    # 应用配置
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    UPLOAD_FOLDER = 'uploads'
    
    # 分页配置
    POSTS_PER_PAGE = 20
    
    # 缓存配置
    CACHE_TYPE = "simple"
    CACHE_DEFAULT_TIMEOUT = 300
    
    # 日志配置
    LOG_LEVEL = os.environ.get('LOG_LEVEL') or 'INFO'
    LOG_FILE = 'logs/inventory_service.log'
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5
    
    # 安全配置
    SESSION_COOKIE_SECURE = False  # 生产环境设为True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # 跨域配置
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*').split(',')
    
    # 业务配置
    DEFAULT_RENTAL_DAYS = 7
    MAX_RENTAL_DAYS = 30
    MIN_ADVANCE_BOOKING_DAYS = 1
    
    # 时区配置
    TIMEZONE = 'Asia/Shanghai'
    
    # 邮件配置（可选）
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True
    SQLALCHEMY_ECHO = True
    LOG_LEVEL = 'DEBUG'


class TestingConfig(Config):
    """测试环境配置"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False
    SQLALCHEMY_ECHO = False
    
    # 生产环境安全设置
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    
    # 生产环境日志级别
    LOG_LEVEL = 'WARNING'


class DockerConfig(Config):
    """Docker环境配置"""
    # Docker环境下的数据库连接
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql+pymysql://inventory_user:inventory_pass@mysql:3306/inventory_management'
    
    # Docker环境下的Redis连接（如果使用）
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://redis:6379/0'


# 配置映射
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'docker': DockerConfig,
    'default': DevelopmentConfig
}
