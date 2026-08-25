"""
库存管理服务 Flask应用初始化
"""

import base64
import ipaddress
import logging
import os
import re
import weakref
from logging.handlers import RotatingFileHandler
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix

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


_DNS_LABEL = re.compile(
    r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$'
)


def _is_exact_http_origin(origin):
    if not isinstance(origin, str):
        return False
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme not in {'http', 'https'}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        return False

    hostname = parsed.hostname
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        labels = hostname.split('.')
        return len(hostname) <= 253 and all(
            _DNS_LABEL.fullmatch(label) for label in labels
        )


def _validated_cors_origins(configured_origins):
    if not configured_origins:
        return []
    if isinstance(configured_origins, str):
        configured_origins = [configured_origins]
    origins = list(configured_origins)
    if not all(_is_exact_http_origin(origin) for origin in origins):
        raise RuntimeError(
            'Credentialed CORS requires exact HTTP origins'
        )
    return origins


def _dispose_tenant_resources(
    control_store,
    tenant_engine_registry,
    tenant_provisioner,
):
    tenant_engine_registry.dispose_all()
    if tenant_provisioner is not None:
        tenant_provisioner.dispose()
    if control_store is not None:
        control_store.dispose()


def create_app(config_class=Config, worker_mode=False):
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
        static_folder=None if worker_mode else os.path.join(project_root, 'static'),
    )
    app.config.from_object(config_class)

    trusted_proxy_hops = int(app.config.get('TRUSTED_PROXY_HOPS') or 0)
    if trusted_proxy_hops < 0:
        raise RuntimeError('TRUSTED_PROXY_HOPS cannot be negative')
    if trusted_proxy_hops:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=trusted_proxy_hops,
            x_proto=trusted_proxy_hops,
        )

    auth_bypass_requested = bool(app.config.get('AUTH_BYPASS_FOR_TESTS'))
    if (
        not worker_mode
        and auth_bypass_requested
        and (
            not app.testing
            or app.config.get('IS_PRODUCTION')
        )
    ):
        raise RuntimeError(
            'AUTH_BYPASS_FOR_TESTS requires TESTING=True '
            'and non-production configuration'
        )

    if app.config.get('IS_PRODUCTION') or worker_mode:
        master_key = app.config.get('SAAS_MASTER_KEY')
        if (
            not master_key
            or master_key == app.config.get('DEFAULT_SAAS_MASTER_KEY')
        ):
            raise RuntimeError(
                'Production requires a non-default SAAS_MASTER_KEY'
            )
        if (
            app.config.get('IS_PRODUCTION')
            and not worker_mode
            and app.config.get('DEV_SMS_CODE')
        ):
            raise RuntimeError('Production forbids DEV_SMS_CODE')
        if not app.config.get('CONTROL_DATABASE_URL'):
            raise RuntimeError(
                'Production requires CONTROL_DATABASE_URL'
            )
        if not worker_mode and not app.config.get('PROVISIONER_DATABASE_URL'):
            raise RuntimeError(
                'Production requires PROVISIONER_DATABASE_URL'
            )
        if app.config.get('TENANT_DB_NAME_PREFIX') != 'inventory_tenant_':
            raise RuntimeError(
                'Production requires TENANT_DB_NAME_PREFIX=inventory_tenant_'
            )
        if app.config.get('TENANT_DB_USER_PREFIX') != 'im_t':
            raise RuntimeError(
                'Production requires TENANT_DB_USER_PREFIX=im_t'
            )
        tenant_host = app.config.get('TENANT_DB_HOST')
        tenant_port = app.config.get('TENANT_DB_PORT')
        if not tenant_host:
            raise RuntimeError('Production app/worker requires TENANT_DB_HOST')
        if (
            not isinstance(tenant_port, int) or not 1 <= tenant_port <= 65535
        ):
            raise RuntimeError(
                'Production app/worker requires a valid TENANT_DB_PORT'
            )
        if not app.config.get('SQLALCHEMY_DATABASE_URI'):
            raise RuntimeError('Production app/worker requires DATABASE_URL')
        if (
            app.config.get('IS_PRODUCTION')
            and not worker_mode
            and (
                not app.config.get('SECRET_KEY')
                or app.config.get('SECRET_KEY')
                == app.config.get('DEFAULT_SECRET_KEY')
            )
        ):
            raise RuntimeError('Production app requires non-default SECRET_KEY')

    cors_origins = [] if worker_mode else _validated_cors_origins(
        app.config.get('CORS_ORIGINS')
    )

    sms_sender = None if worker_mode else app.config.get('SMS_SENDER')
    if not worker_mode:
        from app.auth import AuthService, FakeSmsSender, TencentSmsSender
    if (
        not worker_mode
        and app.config.get('IS_PRODUCTION')
        and sms_sender is not None
    ):
        if not isinstance(sms_sender, TencentSmsSender):
            raise RuntimeError(
                'Production forbids FakeSmsSender or custom SMS senders'
            )
    if not worker_mode and sms_sender is None:
        tencent_settings = {
            'secret_id': app.config.get('TENCENTCLOUD_SECRET_ID'),
            'secret_key': app.config.get('TENCENTCLOUD_SECRET_KEY'),
            'sdk_app_id': app.config.get('TENCENT_SMS_SDK_APP_ID'),
            'sign_name': app.config.get('TENCENT_SMS_SIGN_NAME'),
            'template_id': app.config.get('TENCENT_SMS_TEMPLATE_ID'),
        }
        if all(tencent_settings.values()):
            sms_sender = TencentSmsSender(
                **tencent_settings,
                region=app.config.get('TENCENT_SMS_REGION'),
            )
        elif app.config.get('IS_PRODUCTION'):
            raise RuntimeError('Production requires Tencent SMS configuration')
        else:
            sms_sender = FakeSmsSender()

    if not worker_mode:
        app.extensions['tenant_auth_bypass_enabled'] = bool(
            auth_bypass_requested
            and app.testing
            and not app.config.get('IS_PRODUCTION')
        )

    secret_box = SecretBox.from_base64(app.config['SAAS_MASTER_KEY'])
    control_database_url = app.config.get('CONTROL_DATABASE_URL')
    control_store = None
    if control_database_url:
        control_store = ControlStore(
            control_database_url,
            secret_box,
            pool_size=app.config.get('CONTROL_DB_POOL_SIZE', 5),
        )
    tenant_engine_registry = TenantEngineRegistry(
        secret_box=secret_box,
        host=app.config['TENANT_DB_HOST'],
        port=app.config['TENANT_DB_PORT'],
        pool_size=app.config.get('TENANT_DB_POOL_SIZE', 2),
    )
    provisioner_database_url = app.config.get(
        'PROVISIONER_DATABASE_URL'
    )
    tenant_provisioner = None
    if not worker_mode and control_store is not None and provisioner_database_url:
        from app.provisioning import TenantProvisioner

        tenant_provisioner = TenantProvisioner(
            store=control_store,
            provisioner_database_url=provisioner_database_url,
            migrations_directory=app.config[
                'BUSINESS_MIGRATIONS_DIRECTORY'
            ],
            tenant_db_host=app.config['TENANT_DB_HOST'],
            tenant_db_port=app.config['TENANT_DB_PORT'],
            database_prefix=app.config['TENANT_DB_NAME_PREFIX'],
            user_prefix=app.config['TENANT_DB_USER_PREFIX'],
            logger=app.logger,
        )
    app.extensions['control_store'] = control_store
    if not worker_mode:
        app.extensions['sms_sender'] = sms_sender
        app.extensions['auth_service'] = (
            AuthService(
                store=control_store,
                master_key=base64.b64decode(
                    app.config['SAAS_MASTER_KEY'], validate=True,
                ),
                sender=sms_sender,
                fixed_code=app.config.get('DEV_SMS_CODE'),
                logger=app.logger,
            ) if control_store is not None else None
        )
    app.extensions['tenant_engine_registry'] = tenant_engine_registry
    if not worker_mode:
        app.extensions['tenant_provisioner'] = tenant_provisioner
    app.extensions['tenant_resource_finalizer'] = weakref.finalize(
        app,
        _dispose_tenant_resources,
        control_store,
        tenant_engine_registry,
        tenant_provisioner,
    )

    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)

    # 默认同源；仅显式白名单允许携带 Cookie 的跨域请求。
    if not worker_mode and cors_origins:
        from flask_cors import CORS

        CORS(
            app,
            origins=cors_origins,
            supports_credentials=True,
        )

    # Worker只初始化数据库上下文，不加载HTTP或平台管理功能。
    if not worker_mode:
        from app.routes import (
            auth_api,
            device_model_api,
            external_api,
            inspection,
            platform_api,
            rental_stats_api,
            settings_api,
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

        app.register_blueprint(auth_api.bp)
        app.register_blueprint(platform_api.bp)
        app.register_blueprint(settings_api.bp)
        platform_api.register_platform_commands(app)
        from app.default_tenant_migration import (
            register_default_tenant_command,
        )
        register_default_tenant_command(app)
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
