"""
库存管理服务 Flask应用初始化
"""

import logging
import os
import weakref
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from app.control.store import ControlStore
from app.crypto import SecretBox
from app.tenant_context import TenantEngineRegistry, TenantSession

# 提前加载 .env，确保 Config 读取到环境变量
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.environ.get('TESTING', '').lower() != 'true':
    load_dotenv(os.path.join(_BASE_DIR, '.env'))

from config import Config, config as config_map  # noqa: E402

# 初始化扩展
db = SQLAlchemy(session_options={"class_": TenantSession})
migrate = Migrate()


def _dispose_tenant_resources(control_store, tenant_engine_registry):
    tenant_engine_registry.dispose_all()
    if control_store is not None:
        control_store.dispose()


def create_app(config_class=Config):
    """应用工厂函数"""
    if isinstance(config_class, str):
        try:
            config_class = config_map[config_class]
        except KeyError as exc:
            raise ValueError(f'未知应用配置: {config_class}') from exc

    # 获取项目根目录的绝对路径
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..')
    )

    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, 'templates'),
        static_folder=os.path.join(project_root, 'static'),
    )
    app.config.from_object(config_class)

    if (
        app.config.get('AUTH_BYPASS_FOR_TESTS')
        and (
            not app.testing
            or app.config.get('IS_PRODUCTION')
        )
    ):
        raise RuntimeError(
            'AUTH_BYPASS_FOR_TESTS requires TESTING=True '
            'and non-production configuration'
        )

    if app.config.get('IS_PRODUCTION'):
        master_key = app.config.get('SAAS_MASTER_KEY')
        if (
            not master_key
            or master_key == app.config.get('DEFAULT_SAAS_MASTER_KEY')
        ):
            raise RuntimeError(
                'Production requires a non-default SAAS_MASTER_KEY'
            )
        if app.config.get('DEV_SMS_CODE'):
            raise RuntimeError('Production forbids DEV_SMS_CODE')

    secret_box = SecretBox.from_base64(app.config['SAAS_MASTER_KEY'])
    control_database_url = app.config.get('CONTROL_DATABASE_URL')
    control_store = None
    if control_database_url:
        control_store = ControlStore(control_database_url, secret_box)
    tenant_engine_registry = TenantEngineRegistry(
        secret_box=secret_box,
        host=app.config['TENANT_DB_HOST'],
        port=app.config['TENANT_DB_PORT'],
        pool_size=app.config.get('TENANT_DB_POOL_SIZE', 2),
    )
    app.extensions['control_store'] = control_store
    app.extensions['tenant_engine_registry'] = tenant_engine_registry
    app.extensions['tenant_resource_finalizer'] = weakref.finalize(
        app,
        _dispose_tenant_resources,
        control_store,
        tenant_engine_registry,
    )

    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)

    # 启用CORS
    CORS(app)

    # 注册蓝图
    from app.routes import (
        device_model_api,
        external_api,
        inspection,
        rental_stats_api,
        sf_test_api,
        sf_tracking_api,
        shipping_batch_api,
        statistics_api,
        tracking_api,
        vue_app,
        web,
    )
    app.before_request(web.bind_request_tenant)
    app.teardown_request(web.reset_request_tenant)

    app.register_blueprint(web.bp)
    app.register_blueprint(external_api.bp, url_prefix='/external-api')
    app.register_blueprint(vue_app.bp)
    app.register_blueprint(tracking_api.bp)
    app.register_blueprint(device_model_api.bp)
    app.register_blueprint(statistics_api.bp)
    app.register_blueprint(shipping_batch_api.bp)
    app.register_blueprint(sf_test_api.bp)
    app.register_blueprint(sf_tracking_api.bp)
    app.register_blueprint(inspection.inspection_bp)
    app.register_blueprint(rental_stats_api.bp)

    # 配置日志
    if not app.debug and not app.testing:
        if not os.path.exists('logs'):
            os.mkdir('logs')

        # 应用日志
        file_handler = RotatingFileHandler(
            'logs/inventory_service.log',
            maxBytes=10240000,
            backupCount=10,
        )
        file_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s %(levelname)s: %(message)s '
                '[in %(pathname)s:%(lineno)d]'
            )
        )
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

        # 访问日志
        access_handler = RotatingFileHandler(
            'logs/access.log',
            maxBytes=10240000,
            backupCount=10,
        )
        access_handler.setFormatter(
            logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
        )
        access_handler.setLevel(logging.INFO)
        app.logger.addHandler(access_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.info('库存管理服务启动')

    return app


from app import models  # noqa: E402,F401
