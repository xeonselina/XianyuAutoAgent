"""
库存管理服务 Flask应用初始化
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_migrate import Migrate
from dotenv import load_dotenv
import os

# 提前加载 .env，确保 Config 读取到环境变量
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(_BASE_DIR, '.env'))

from config import Config
import logging
from logging.handlers import RotatingFileHandler
import os

# 初始化扩展
db = SQLAlchemy()
migrate = Migrate()

def create_app(config_class=Config):
    """应用工厂函数"""
    # 获取项目根目录的绝对路径
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    app = Flask(__name__, 
                template_folder=os.path.join(project_root, 'templates'),
                static_folder=os.path.join(project_root, 'static'))
    app.config.from_object(config_class)
    
    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    
    # 启用CORS
    CORS(app)
    
    # 注册蓝图
    from app.routes import web, external_api, vue_app, tracking_api, device_model_api, statistics_api
    app.register_blueprint(web.bp)
    app.register_blueprint(external_api.bp, url_prefix='/external-api')
    app.register_blueprint(vue_app.bp)
    app.register_blueprint(tracking_api.bp)
    app.register_blueprint(device_model_api.bp)
    app.register_blueprint(statistics_api.bp)
    
    # 启动定时调度器
    try:
        from app.utils.scheduler import init_scheduler
        init_scheduler(app)
        app.logger.info('定时调度器已启动')
    except Exception as e:
        app.logger.error(f'启动定时调度器失败: {e}')
    
    # 配置日志
    if not app.debug and not app.testing:
        if not os.path.exists('logs'):
            os.mkdir('logs')
        
        # 应用日志
        file_handler = RotatingFileHandler(
            'logs/inventory_service.log', 
            maxBytes=10240000, 
            backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        
        # 访问日志
        access_handler = RotatingFileHandler(
            'logs/access.log', 
            maxBytes=10240000, 
            backupCount=10
        )
        access_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s'
        ))
        access_handler.setLevel(logging.INFO)
        app.logger.addHandler(access_handler)
        
        app.logger.setLevel(logging.INFO)
        app.logger.info('库存管理服务启动')
    
    return app

from app import models
