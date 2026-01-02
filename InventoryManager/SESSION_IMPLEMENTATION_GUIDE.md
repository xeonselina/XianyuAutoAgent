# Flask Session 跨设备管理 - 实施指南

## 快速入门

本文档提供可直接用于生产环境的代码实现。

---

## 第一步：环境配置（最高优先级）

### Step 1.1 更新 config.py

```python
# /config.py

import os
from datetime import timedelta

class Config:
    """基础配置类"""

    # ... 现有配置保留 ...

    # 增强 Session 配置
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)  # 会话有效期 24 小时
    SESSION_REFRESH_EACH_REQUEST = True               # 每次请求更新超时时间
    SESSION_COOKIE_HTTPONLY = True                    # 防止 JS 访问（已有）
    SESSION_COOKIE_SAMESITE = 'Lax'                   # CSRF 保护（已有）

    # 根据环境设置 HTTPS
    is_production = os.environ.get('FLASK_ENV') == 'production' or \
                    os.environ.get('ENV') == 'production'
    SESSION_COOKIE_SECURE = is_production  # 生产环境强制 HTTPS


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True
    SESSION_COOKIE_SECURE = False  # 开发环境允许 HTTP


class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False
    SESSION_COOKIE_SECURE = True   # 生产环境强制 HTTPS
    SESSION_COOKIE_SAMESITE = 'Strict'  # 加强 CSRF 防护
```

### Step 1.2 在 Flask 应用初始化时启用 Session

```python
# /app/__init__.py

from flask import Flask
from flask_session import Session

# ... 现有代码 ...

db = SQLAlchemy()
migrate = Migrate()
session_manager = Session()  # 新增

def create_app(config_class=Config):
    """应用工厂函数"""
    app = Flask(__name__,
                template_folder=os.path.join(project_root, 'templates'),
                static_folder=os.path.join(project_root, 'static'))

    app.config.from_object(config_class)

    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    session_manager.init_app(app)  # 新增

    # ... 其他初始化代码 ...

    return app
```

### Step 1.3 安装依赖

```bash
pip install user-agents
pip install Flask-Session

# 可选：用于生产环境 Redis 后端
# pip install redis
```

---

## 第二步：实现设备检测中间件

### Step 2.1 创建设备检测模块

创建文件：`/app/utils/device_utils.py`

```python
"""
设备检测和指纹生成工具
"""

from flask import request
from user_agents import parse
from datetime import datetime
import hashlib
import json


class DeviceInfo:
    """设备信息类"""

    def __init__(self, user_agent_string=None):
        """初始化设备信息"""
        ua_string = user_agent_string or request.headers.get('User-Agent', 'Unknown')
        ua = parse(ua_string)

        self.user_agent = ua_string
        self.device_type = 'mobile' if ua.is_mobile else 'desktop'
        self.device_category = self._get_device_category(ua)
        self.browser = ua.browser.family
        self.browser_version = ua.browser.version_string
        self.os = ua.os.family
        self.os_version = ua.os.version_string
        self.is_mobile = ua.is_mobile
        self.is_tablet = ua.is_tablet
        self.is_pc = ua.is_pc
        self.ip_address = request.remote_addr
        self.timestamp = datetime.utcnow().isoformat()

    def _get_device_category(self, ua):
        """获取设备分类"""
        if ua.is_mobile:
            if 'iPad' in ua.device.model or ua.is_tablet:
                return 'tablet'
            return 'mobile'
        elif ua.is_pc:
            return 'desktop'
        else:
            return 'other'

    def to_dict(self):
        """转换为字典"""
        return {
            'user_agent': self.user_agent,
            'device_type': self.device_type,
            'device_category': self.device_category,
            'browser': self.browser,
            'browser_version': self.browser_version,
            'os': self.os,
            'os_version': self.os_version,
            'is_mobile': self.is_mobile,
            'is_tablet': self.is_tablet,
            'is_pc': self.is_pc,
            'ip_address': self.ip_address,
            'timestamp': self.timestamp,
        }

    def to_json_str(self):
        """转换为 JSON 字符串（用于 session 存储）"""
        return json.dumps(self.to_dict())


def generate_device_fingerprint(device_info=None):
    """
    生成设备指纹
    基于 User-Agent 和其他浏览器信息的哈希
    """
    if device_info is None:
        device_info = DeviceInfo()

    # 组合多个因素生成指纹
    components = [
        device_info.user_agent,
        request.headers.get('Accept-Language', ''),
        request.headers.get('Accept-Encoding', ''),
        request.headers.get('Accept', ''),
    ]

    fingerprint_str = '|'.join(components)
    fingerprint_hash = hashlib.sha256(fingerprint_str.encode()).hexdigest()

    return fingerprint_hash


def check_device_consistency(session_device_info, current_device_info):
    """
    检查设备一致性
    返回 (is_consistent, changes_dict)
    """
    if not session_device_info:
        return True, {}

    session_dict = session_device_info if isinstance(session_device_info, dict) else \
                   json.loads(session_device_info) if isinstance(session_device_info, str) else {}
    current_dict = current_device_info.to_dict() if isinstance(current_device_info, DeviceInfo) \
                   else current_device_info

    changes = {}

    # 检查关键字段变化
    key_fields = ['device_type', 'browser', 'os']
    for field in key_fields:
        if session_dict.get(field) != current_dict.get(field):
            changes[field] = {
                'old': session_dict.get(field),
                'new': current_dict.get(field)
            }

    # 检查 IP 变化（可能的安全风险）
    if session_dict.get('ip_address') != current_dict.get('ip_address'):
        changes['ip_address'] = {
            'old': session_dict.get('ip_address'),
            'new': current_dict.get('ip_address')
        }

    is_consistent = len(changes) == 0

    return is_consistent, changes
```

### Step 2.2 创建设备检测蓝图

创建文件：`/app/middleware/device_detection.py`

```python
"""
设备检测中间件
在每个请求前检测和记录设备信息
"""

from flask import request, session, current_app
from app.utils.device_utils import DeviceInfo, generate_device_fingerprint, check_device_consistency
from app.models.audit_log import AuditLog
from datetime import datetime
import json


def init_device_detection(app):
    """初始化设备检测中间件"""

    @app.before_request
    def detect_and_record_device():
        """
        在每个请求前执行
        检测设备类型、生成指纹、记录变化
        """
        try:
            # Step 1: 获取当前请求的设备信息
            current_device = DeviceInfo()
            current_fingerprint = generate_device_fingerprint(current_device)

            # Step 2: 如果是新 session，保存设备信息
            if 'device_info' not in session:
                session['device_info'] = current_device.to_dict()
                session['device_fingerprint'] = current_fingerprint
                session['device_first_seen'] = datetime.utcnow().isoformat()
                session.modified = True

                # 可选：记录新设备登录
                current_app.logger.info(
                    f"New session from {current_device.device_type} "
                    f"({current_device.browser}/{current_device.os}) "
                    f"IP: {current_device.ip_address}"
                )

            # Step 3: 检查设备是否变化
            session_device = session.get('device_info', {})
            is_consistent, changes = check_device_consistency(session_device, current_device)

            if not is_consistent:
                # 设备发生变化
                current_app.logger.warning(
                    f"Device changes detected: {json.dumps(changes, indent=2)}"
                )

                # 更新 session 中的设备信息
                session['device_info'] = current_device.to_dict()
                session['device_last_changed'] = datetime.utcnow().isoformat()
                session['device_changes_count'] = session.get('device_changes_count', 0) + 1
                session.modified = True

                # Step 4: 可选的安全检查
                # 如果设备变化很频繁，可能是异常活动
                if session.get('device_changes_count', 0) > 3:
                    current_app.logger.warning(
                        f"Excessive device changes ({session.get('device_changes_count')} changes) "
                        f"in session {request.cookies.get('session_id')}"
                    )

            # Step 5: 将设备信息附加到请求上下文
            request.device_info = current_device.to_dict()
            request.device_type = current_device.device_type
            request.device_category = current_device.device_category

        except Exception as e:
            current_app.logger.error(f"Device detection error: {e}")
            # 设置默认值，防止应用崩溃
            request.device_info = {'device_type': 'unknown', 'error': str(e)}
            request.device_type = 'unknown'
```

### Step 2.3 在应用初始化时注册中间件

```python
# /app/__init__.py

def create_app(config_class=Config):
    """应用工厂函数"""
    app = Flask(__name__,
                template_folder=os.path.join(project_root, 'templates'),
                static_folder=os.path.join(project_root, 'static'))

    app.config.from_object(config_class)

    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    session_manager.init_app(app)

    # === 新增：初始化设备检测 ===
    from app.middleware.device_detection import init_device_detection
    init_device_detection(app)

    # ... 其他初始化代码 ...

    return app
```

---

## 第三步：自动设备路由

### Step 3.1 更新主页路由

```python
# /app/routes/web_pages.py

from flask import Blueprint, render_template, redirect, request

bp = Blueprint('web_pages', __name__)


@bp.route('/')
def index():
    """
    主页 - 根据设备类型自动路由
    """
    device_type = request.device_type

    if device_type == 'mobile':
        return redirect('/mobile', code=302)
    elif device_type == 'tablet':
        # 可选：为平板电脑提供特殊界面
        # return redirect('/tablet', code=302)
        return redirect('/mobile', code=302)  # 或使用移动界面
    else:
        # desktop 或 unknown
        return redirect('/vue', code=302)


# ... 保留现有路由 ...
```

### Step 3.2 更新现有路由以支持设备信息

```python
# /app/routes/vue_app.py

@bp.route('/vue')
@bp.route('/vue/')
def vue_index():
    """Vue应用首页(PC端)"""
    # 可选：在模板中注入设备信息
    device_type = request.device_type

    if device_type == 'mobile':
        current_app.logger.warning(
            f"Mobile device accessing desktop UI (/vue). "
            f"Consider redirecting to /mobile"
        )

    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/mobile')
@bp.route('/mobile/')
def mobile_index():
    """Vue应用首页(移动端)"""
    device_type = request.device_type

    if device_type not in ['mobile', 'tablet', 'unknown']:
        current_app.logger.info(
            f"Desktop device accessing mobile UI (/mobile). "
            f"Device: {device_type}"
        )

    mobile_dist_path = os.path.join(current_app.root_path, '..', 'static', 'mobile-dist')
    return send_from_directory(mobile_dist_path, 'index.html')
```

---

## 第四步：增强审计日志

### Step 4.1 扩展 AuditLog 模型

```python
# /app/models/audit_log.py

from app import db
from datetime import datetime
import uuid


class AuditLog(db.Model):
    """审计日志模型 - 增强版本"""
    __tablename__ = 'audit_logs'

    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # 关联信息
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), comment='相关设备ID')
    rental_id = db.Column(db.Integer, db.ForeignKey('rentals.id'), comment='相关租赁ID')

    # 操作信息
    action = db.Column(db.String(50), nullable=False, comment='操作类型')
    resource_type = db.Column(db.String(50), comment='资源类型')
    resource_id = db.Column(db.String(50), comment='资源ID')

    # 详细信息
    description = db.Column(db.Text, comment='操作描述')
    details = db.Column(db.JSON, comment='操作详情')

    # === 网络和设备信息（增强）===
    ip_address = db.Column(db.String(45), comment='IP地址')
    user_agent = db.Column(db.String(500), comment='用户代理')

    # 新增字段
    device_type = db.Column(db.String(50), comment='设备类型(mobile/desktop/tablet)')
    device_category = db.Column(db.String(50), comment='设备分类')
    browser = db.Column(db.String(100), comment='浏览器名称')
    browser_version = db.Column(db.String(50), comment='浏览器版本')
    os = db.Column(db.String(100), comment='操作系统')
    os_version = db.Column(db.String(50), comment='操作系统版本')

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')

    def __repr__(self):
        return f'<AuditLog {self.id}: {self.action}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'rental_id': self.rental_id,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'description': self.description,
            'details': self.details,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'device_type': self.device_type,
            'device_category': self.device_category,
            'browser': self.browser,
            'browser_version': self.browser_version,
            'os': self.os,
            'os_version': self.os_version,
            'created_at': self.created_at.isoformat()
        }

    @classmethod
    def log_action(cls, action, resource_type=None, resource_id=None,
                   description=None, details=None,
                   ip_address=None, user_agent=None,
                   device_type=None, device_category=None,
                   browser=None, browser_version=None,
                   os=None, os_version=None):
        """
        记录操作日志 - 增强版本

        Args:
            action: 操作类型
            resource_type: 资源类型
            resource_id: 资源ID
            description: 操作描述
            details: 操作详情（JSON）
            ip_address: IP 地址
            user_agent: User-Agent 字符串
            device_type: 设备类型(mobile/desktop/tablet)
            device_category: 设备分类
            browser: 浏览器
            browser_version: 浏览器版本
            os: 操作系统
            os_version: 操作系统版本
        """
        log = cls(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            description=description,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            device_type=device_type,
            device_category=device_category,
            browser=browser,
            browser_version=browser_version,
            os=os,
            os_version=os_version
        )

        db.session.add(log)
        db.session.commit()

        return log

    # ... 保留现有的查询方法 ...
```

### Step 4.2 创建审计日志帮助函数

```python
# /app/utils/audit_helper.py

from flask import request
from app.models.audit_log import AuditLog


def log_action_with_device(action, resource_type=None, resource_id=None,
                           description=None, details=None):
    """
    便利函数：自动从请求中提取设备和网络信息

    Usage:
        from app.utils.audit_helper import log_action_with_device
        log_action_with_device(
            'create',
            resource_type='rental',
            resource_id=rental.id,
            description='Created new rental'
        )
    """
    device_info = getattr(request, 'device_info', {})

    return AuditLog.log_action(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        description=description,
        details=details,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', 'Unknown'),
        device_type=device_info.get('device_type'),
        device_category=device_info.get('device_category'),
        browser=device_info.get('browser'),
        browser_version=device_info.get('browser_version'),
        os=device_info.get('os'),
        os_version=device_info.get('os_version')
    )
```

---

## 第五步：数据库迁移

### Step 5.1 创建迁移脚本

```bash
# 在项目根目录运行
flask db migrate -m "Add device tracking fields to audit_log"
```

### Step 5.2 手动编辑迁移文件（如需要）

迁移脚本应类似于：

```python
# migrations/versions/xxx_add_device_tracking_fields_to_audit_log.py

def upgrade():
    op.add_column('audit_logs',
        sa.Column('device_type', sa.String(50), nullable=True, comment='设备类型'))
    op.add_column('audit_logs',
        sa.Column('device_category', sa.String(50), nullable=True, comment='设备分类'))
    op.add_column('audit_logs',
        sa.Column('browser', sa.String(100), nullable=True, comment='浏览器'))
    op.add_column('audit_logs',
        sa.Column('browser_version', sa.String(50), nullable=True, comment='浏览器版本'))
    op.add_column('audit_logs',
        sa.Column('os', sa.String(100), nullable=True, comment='操作系统'))
    op.add_column('audit_logs',
        sa.Column('os_version', sa.String(50), nullable=True, comment='操作系统版本'))

def downgrade():
    op.drop_column('audit_logs', 'os_version')
    op.drop_column('audit_logs', 'os')
    op.drop_column('audit_logs', 'browser_version')
    op.drop_column('audit_logs', 'browser')
    op.drop_column('audit_logs', 'device_category')
    op.drop_column('audit_logs', 'device_type')
```

### Step 5.3 执行迁移

```bash
flask db upgrade
```

---

## 第六步：测试和验证

### Step 6.1 单元测试

创建文件：`/tests/test_device_detection.py`

```python
"""
设备检测功能测试
"""

import unittest
from flask import session
from app import create_app, db
from config import TestingConfig


class DeviceDetectionTestCase(unittest.TestCase):
    """设备检测测试"""

    def setUp(self):
        """测试前准备"""
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        """测试后清理"""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_mobile_device_detection(self):
        """测试移动设备检测"""
        user_agent = (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1'
        )

        response = self.client.get('/', headers={'User-Agent': user_agent})

        # 检查重定向
        self.assertEqual(response.status_code, 302)
        self.assertIn('/mobile', response.location)

    def test_desktop_device_detection(self):
        """测试桌面设备检测"""
        user_agent = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )

        response = self.client.get('/', headers={'User-Agent': user_agent})

        # 检查重定向
        self.assertEqual(response.status_code, 302)
        self.assertIn('/vue', response.location)

    def test_device_info_in_session(self):
        """测试 session 中的设备信息"""
        user_agent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15'

        with self.client:
            self.client.get('/', headers={'User-Agent': user_agent})

            # 访问 session
            self.assertIn('device_info', session)
            self.assertEqual(session['device_info']['device_type'], 'mobile')
            self.assertIn('device_fingerprint', session)
            self.assertIn('device_first_seen', session)

    def test_device_type_in_request(self):
        """测试请求中的设备类型"""
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

        with self.client:
            self.client.get('/vue', headers={'User-Agent': user_agent})

            # 在测试中访问请求上下文的设备信息
            # 这需要在蓝图中添加 @app.before_request 钩子

    def test_audit_log_with_device_info(self):
        """测试带有设备信息的审计日志"""
        from app.models.audit_log import AuditLog
        from app.utils.audit_helper import log_action_with_device

        # 模拟请求
        with self.app.test_request_context(
            '/',
            headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1)'}
        ):
            log = log_action_with_device(
                'test_action',
                resource_type='test',
                resource_id='123',
                description='Test audit log'
            )

            # 验证
            self.assertEqual(log.action, 'test_action')
            self.assertEqual(log.device_type, 'mobile')
            self.assertIsNotNone(log.browser)


if __name__ == '__main__':
    unittest.main()
```

### Step 6.2 运行测试

```bash
python -m pytest tests/test_device_detection.py -v
```

### Step 6.3 手动测试清单

- [ ] 从移动设备访问 `/` 重定向到 `/mobile`
- [ ] 从桌面访问 `/` 重定向到 `/vue`
- [ ] Session 中记录了设备信息
- [ ] 审计日志包含设备字段
- [ ] 设备变化被正确记录
- [ ] 生产环境 `SESSION_COOKIE_SECURE = True`

---

## 第七步：部署前检查清单

### 部署前安全检查

```bash
# 1. 验证依赖安装
pip list | grep -E "Flask-Session|user-agents"

# 2. 检查配置文件
grep -n "SESSION_COOKIE_SECURE" config.py
grep -n "PERMANENT_SESSION_LIFETIME" config.py

# 3. 运行所有测试
python -m pytest tests/ -v

# 4. 检查 User-Agent 解析
python -c "from user_agents import parse; print(parse('Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1)').is_mobile)"

# 5. 检查数据库迁移
flask db current
flask db upgrade

# 6. 启动应用并测试
FLASK_ENV=production python run.py &
curl -H "User-Agent: Mozilla/5.0 (iPhone)" http://localhost:5002/
```

---

## 常见问题处理

### Q1: Session 中的设备信息为空

**症状**: `request.device_type` 返回 `None` 或 `unknown`

**排查**:
```python
# 在路由中添加调试
@bp.route('/debug')
def debug():
    return {
        'device_info': request.device_info,
        'device_type': request.device_type,
        'session_device': session.get('device_info'),
        'user_agent': request.headers.get('User-Agent')
    }
```

**解决方案**:
- 确保 `init_device_detection()` 已在 `create_app()` 中被调用
- 检查 `user_agents` 库是否正确安装

### Q2: 重定向循环

**症状**: 访问 `/` 被重定向到 `/mobile`，然后 `/mobile` 又重定向回 `/`

**原因**: 路由配置冲突

**解决方案**:
```python
# 确保 /mobile 路由不重定向
@bp.route('/mobile')
@bp.route('/mobile/')
def mobile_index():
    """移动端首页 - 直接返回，不重定向"""
    mobile_dist_path = os.path.join(current_app.root_path, '..', 'static', 'mobile-dist')
    return send_from_directory(mobile_dist_path, 'index.html')
```

### Q3: Session 超时时间设置无效

**症状**: 会话立即过期或永不过期

**排查**:
```python
# 检查配置
app.config['PERMANENT_SESSION_LIFETIME']  # 应该是 timedelta 对象
app.config['SESSION_REFRESH_EACH_REQUEST']  # 应该是 True
```

**解决方案**:
```python
# 确保在路由中设置了 session.permanent
@bp.route('/some-route')
def some_route():
    session.permanent = True
    # ... 路由逻辑
```

---

## 性能优化建议

### 1. 缓存 User-Agent 解析

```python
# app/utils/device_utils.py

from functools import lru_cache

@lru_cache(maxsize=1000)
def parse_user_agent_cached(ua_string):
    """缓存 User-Agent 解析结果"""
    return parse(ua_string)

class DeviceInfo:
    def __init__(self, user_agent_string=None):
        ua_string = user_agent_string or request.headers.get('User-Agent', 'Unknown')
        ua = parse_user_agent_cached(ua_string)  # 使用缓存
        # ... 其余代码
```

### 2. 避免频繁的 Session 修改

```python
# 不好的做法：每次都修改
@app.before_request
def detect_device():
    session['device_info'] = current_device.to_dict()
    session.modified = True  # 总是 True

# 好的做法：仅在需要时修改
@app.before_request
def detect_device():
    if 'device_info' not in session:
        session['device_info'] = current_device.to_dict()
        session.modified = True  # 仅首次设置
```

### 3. 使用异步日志记录

```python
# 对于审计日志，考虑异步处理
from celery import shared_task

@shared_task
def log_audit_async(action, **kwargs):
    """异步记录审计日志"""
    AuditLog.log_action(action, **kwargs)

# 在应用中使用
log_audit_async.delay('user_login', device_type='mobile')
```

---

## 监控和告警

### 关键指标

```python
# app/utils/metrics.py

from datetime import datetime, timedelta
from app.models.audit_log import AuditLog

def get_device_distribution():
    """获取设备分布"""
    from sqlalchemy import func

    distribution = db.session.query(
        AuditLog.device_type,
        func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.created_at >= datetime.utcnow() - timedelta(days=7)
    ).group_by(AuditLog.device_type).all()

    return {device_type: count for device_type, count in distribution}

def get_session_statistics():
    """获取会话统计"""
    from sqlalchemy import func

    stats = {
        'active_sessions': get_active_sessions_count(),
        'average_session_duration': get_avg_session_duration(),
        'device_distribution': get_device_distribution(),
        'browser_distribution': get_browser_distribution(),
    }

    return stats

def detect_anomalies():
    """检测异常活动"""
    anomalies = []

    # 检查：短时间内大量设备变化
    recent_logs = AuditLog.query.filter(
        AuditLog.created_at >= datetime.utcnow() - timedelta(minutes=5)
    ).all()

    device_changes = {}
    for log in recent_logs:
        # ... 分析逻辑
        pass

    return anomalies
```

---

## 下一步

1. **实施第二阶段**：创建 UserSession 表（见主研究报告）
2. **配置 Redis**：用于生产环境会话存储
3. **实施监控**：设置审计日志分析和告警
4. **用户研究**：收集用户关于跨设备体验的反馈

---

**最后更新**: 2024-01-XX
**版本**: 1.0
