# URL 迁移实施指南

## 快速开始

本文档提供了URL结构迁移的具体实施步骤、代码示例和验证清单。

---

## 第1部分：环境准备

### 1.1 安装依赖

添加 `user-agents` 库到项目依赖：

```bash
# 安装库
pip install user-agents

# 更新 requirements.txt
echo "user-agents>=2.2.0" >> requirements.txt
```

**验证安装**
```bash
python -c "from user_agents import parse; print('Success')"
```

### 1.2 验证项目结构

```bash
# 验证静态文件目录结构
ls -la static/
# 应该看到：
# - vue-dist/          (PC应用构建输出)
# - mobile-dist/       (移动应用构建输出)

# 验证前端构建已完成
ls -la static/vue-dist/index.html
ls -la static/mobile-dist/index.html
```

---

## 第2部分：代码实现

### 2.1 创建设备检测模块

**文件**: `/Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager/app/utils/device_detection.py`

```python
"""
设备检测工具模块

用于自动检测请求是否来自移动设备或桌面设备，
基于 User-Agent HTTP 请求头进行判断。

用法示例：
    from app.utils.device_detection import is_mobile_device, get_device_type

    # 检测是否为移动设备
    if is_mobile_device():
        # 服务移动端应用
        pass

    # 获取详细设备信息
    device_info = get_device_type()
    print(f"Browser: {device_info['browser']}")
"""

from flask import request
from user_agents import parse
import logging

logger = logging.getLogger(__name__)


def is_mobile_device():
    """
    检测当前请求是否来自移动设备

    使用 user-agents 库解析 User-Agent 字符串，
    基于其内置的移动设备检测规则。

    Returns:
        bool: True 表示移动设备，False 表示桌面设备

    Examples:
        >>> if is_mobile_device():
        ...     return serve_mobile_app()
        ... else:
        ...     return serve_desktop_app()
    """
    try:
        user_agent_string = request.headers.get('User-Agent', '')
        user_agent = parse(user_agent_string)
        is_mobile = user_agent.is_mobile

        # 记录检测结果（可选）
        logger.debug(f"Device detection: mobile={is_mobile}, ua={user_agent_string[:50]}...")

        return is_mobile
    except Exception as e:
        logger.warning(f"Error detecting device type: {e}, defaulting to desktop")
        # 错误处理：默认返回桌面（保险做法）
        return False


def is_tablet_device():
    """
    检测当前请求是否来自平板设备

    Returns:
        bool: True 表示平板设备，False 表示其他设备
    """
    try:
        user_agent_string = request.headers.get('User-Agent', '')
        user_agent = parse(user_agent_string)
        return user_agent.is_tablet
    except Exception as e:
        logger.warning(f"Error detecting tablet: {e}")
        return False


def get_device_type():
    """
    获取设备类型的详细信息

    提供完整的设备识别信息，用于日志记录、分析和调试。

    Returns:
        dict: 包含以下字段的字典
            - is_mobile (bool): 是否为移动设备
            - is_tablet (bool): 是否为平板设备
            - is_desktop (bool): 是否为桌面设备
            - browser (str): 浏览器名称和版本
            - os (str): 操作系统名称和版本
            - device (str): 设备型号
            - user_agent (str): 原始 User-Agent 字符串

    Examples:
        >>> device_info = get_device_type()
        >>> print(f"Browser: {device_info['browser']}")
        >>> print(f"OS: {device_info['os']}")
    """
    try:
        user_agent_string = request.headers.get('User-Agent', '')
        user_agent = parse(user_agent_string)

        return {
            'is_mobile': user_agent.is_mobile,
            'is_tablet': user_agent.is_tablet,
            'is_desktop': not user_agent.is_mobile and not user_agent.is_tablet,
            'browser': str(user_agent.browser.family),
            'browser_version': str(user_agent.browser.version_string),
            'os': str(user_agent.os.family),
            'os_version': str(user_agent.os.version_string),
            'device': str(user_agent.device.family),
            'device_brand': str(user_agent.device.brand),
            'user_agent': user_agent_string
        }
    except Exception as e:
        logger.warning(f"Error getting device type details: {e}")
        return {
            'is_mobile': False,
            'is_tablet': False,
            'is_desktop': True,
            'browser': 'Unknown',
            'browser_version': 'Unknown',
            'os': 'Unknown',
            'os_version': 'Unknown',
            'device': 'Unknown',
            'device_brand': 'Unknown',
            'user_agent': request.headers.get('User-Agent', '')
        }


def serve_assets_for_device(filename=''):
    """
    根据设备类型选择正确的资源目录

    用于路由处理器中自动选择是否提供 vue-dist 或 mobile-dist。

    Args:
        filename (str): 请求的文件名或路径（仅用于日志）

    Returns:
        str: 资源目录名称，'vue-dist' 或 'mobile-dist'

    Examples:
        >>> dist_dir = serve_assets_for_device('js/app.js')
        >>> # Returns 'vue-dist' for desktop or 'mobile-dist' for mobile
    """
    dist_dir = 'mobile-dist' if is_mobile_device() else 'vue-dist'
    logger.debug(f"Serving {filename or 'index'} from {dist_dir}")
    return dist_dir


def should_serve_spa_index(filename):
    """
    判断是否应该返回 SPA index.html

    对于 SPA（单页应用），访问不带文件扩展名的路径时应返回 index.html，
    允许前端路由器处理这些路由。

    Args:
        filename (str): 请求的文件名或路径

    Returns:
        bool: True 表示应返回 index.html，False 表示返回实际文件

    Examples:
        >>> if should_serve_spa_index('gantt'):
        ...     return send_file('index.html')
        >>> elif should_serve_spa_index('assets/app.js'):
        ...     return send_file('assets/app.js')
    """
    # 如果文件名包含点号，说明有文件扩展名
    # 如果不包含，则是路由，应返回 index.html
    return '.' not in filename.split('/')[-1]
```

### 2.2 更新 Vue 应用路由

**文件**: `/Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager/app/routes/vue_app.py`

```python
"""
Vue应用路由
PC端和移动端前端 - 支持新旧 URL 结构

路由映射：
  新 URL（推荐）：
    - /               -> 自动检测并提供相应应用
    - /app/           -> 同上
    - /app/<path>     -> 资源或前端路由
    - /<path>         -> 资源或前端路由

  旧 URL（已废弃，使用302临时重定向）：
    - /vue/           -> 重定向到 /
    - /vue/<path>     -> 重定向到 /
    - /mobile/        -> 重定向到 /
    - /mobile/<path>  -> 重定向到 /

迁移计划：
  第1-8周：使用 302 临时重定向（便于灵活调整）
  第9-24周：升级为 301 永久重定向（大部分用户已迁移）
  第25周+：可选择移除旧URL路由
"""

from flask import Blueprint, render_template, send_from_directory, current_app, redirect, request
import os
import logging

# 导入设备检测工具
from app.utils.device_detection import (
    is_mobile_device,
    serve_assets_for_device,
    should_serve_spa_index,
    get_device_type
)

bp = Blueprint('vue_app', __name__)
logger = logging.getLogger(__name__)

# =============================================================================
# 新路由：统一入口 - 自动检测设备类型（推荐使用）
# =============================================================================

@bp.route('/')
def app_index_root():
    """
    应用根路径

    功能：
    1. 自动检测设备类型（移动或桌面）
    2. 返回相应的应用版本

    示例：
      - 桌面用户访问 / -> 获得 PC 应用
      - 移动用户访问 / -> 获得移动应用

    支持的设备：
      - 移动设备：iPhone, iPad, Android, Windows Mobile 等
      - 桌面设备：Windows, macOS, Linux 等
    """
    try:
        dist_dir = serve_assets_for_device('')
        dist_path = os.path.join(current_app.root_path, '..', 'static', dist_dir)

        logger.info(f"Serving root index from {dist_dir}, user-agent: {request.headers.get('User-Agent', '')[:60]}")

        return send_from_directory(dist_path, 'index.html')
    except Exception as e:
        logger.error(f"Error serving root index: {e}")
        return f"Error: {str(e)}", 500


@bp.route('/app')
@bp.route('/app/')
def app_index_app():
    """
    /app 路径 - 与根路径功能相同

    提供备选的应用访问路径，提高发现性。
    两个路由指向同一处理器，行为完全一致。
    """
    return app_index_root()


@bp.route('/<path:filename>')
@bp.route('/app/<path:filename>')
def app_assets(filename):
    """
    应用资源和前端路由处理

    功能：
    1. 自动检测设备类型
    2. 返回 vue-dist 或 mobile-dist 中的文件
    3. 对于不带文件扩展名的路径，返回 index.html 支持前端路由

    路由示例：
      - /assets/app.js -> 返回 assets/app.js
      - /gantt         -> 返回 index.html（前端路由）
      - /booking       -> 返回 index.html（前端路由）

    Args:
        filename (str): 请求的文件路径

    Returns:
        Flask response: 文件内容或错误信息
    """
    try:
        dist_dir = serve_assets_for_device(filename)
        dist_path = os.path.join(current_app.root_path, '..', 'static', dist_dir)

        # 对于不带扩展名的路径（前端路由），返回 index.html
        # 这样可以支持客户端路由：/gantt, /booking, /shipping/<id> 等
        if should_serve_spa_index(filename):
            logger.debug(f"Serving SPA index for route: /{filename}")
            return send_from_directory(dist_path, 'index.html')

        # 其他情况返回实际文件（CSS, JS, 图片等）
        logger.debug(f"Serving asset: {filename} from {dist_dir}")
        return send_from_directory(dist_path, filename)

    except FileNotFoundError:
        # 文件不存在时，尝试返回 index.html（支持前端路由降级）
        logger.warning(f"File not found: {filename}, serving index.html as fallback")
        dist_dir = serve_assets_for_device(filename)
        dist_path = os.path.join(current_app.root_path, '..', 'static', dist_dir)
        return send_from_directory(dist_path, 'index.html')

    except Exception as e:
        logger.error(f"Error serving asset {filename}: {e}")
        return f"Error: {str(e)}", 500


@bp.route('/favicon.ico')
def favicon():
    """
    网站图标

    返回构建后的应用中的 favicon.ico 文件。
    """
    try:
        dist_dir = serve_assets_for_device('')
        dist_path = os.path.join(current_app.root_path, '..', 'static', dist_dir)
        return send_from_directory(dist_path, 'favicon.ico')
    except FileNotFoundError:
        logger.warning("favicon.ico not found")
        return "Not Found", 404


# =============================================================================
# 旧路由：废弃 - 使用 302 临时重定向至新 URL
# =============================================================================

def _log_legacy_access(old_path, new_path='/', reason='deprecated'):
    """记录遗留URL访问"""
    device_info = get_device_type()
    logger.warning(
        f"Legacy URL access - Old: {old_path} -> New: {new_path} "
        f"(Device: {device_info['os']}, Browser: {device_info['browser']}, Reason: {reason})"
    )


@bp.route('/vue')
@bp.route('/vue/')
@bp.route('/vue/<path:filename>')
def vue_redirect(filename=''):
    """
    旧 PC 端 URL - 已废弃

    功能：
    1. 捕获所有对 /vue/* 的请求
    2. 以 302 临时重定向方式指向新 URL
    3. 记录访问日志用于迁移分析

    重定向代码：
    - 302（临时）：在前8周使用，便于灵活调整
    - 301（永久）：8周后升级，保护 SEO 权重

    时间表：
    - 周1-8：302 临时重定向
    - 周9-24：升级为 301 永久重定向
    - 周25+：可选择移除此路由

    Args:
        filename (str): 原始 URL 中的路径部分

    Returns:
        Flask redirect response: 302/301 重定向响应
    """
    old_path = f"/vue/{filename}" if filename else "/vue"
    _log_legacy_access(old_path, "/")

    # 当前阶段：使用 302 临时重定向
    # 升级至 301 的时机：当新 URL 访问占比 > 80% 时
    return redirect('/', code=302)


@bp.route('/mobile')
@bp.route('/mobile/')
@bp.route('/mobile/<path:filename>')
def mobile_redirect(filename=''):
    """
    旧移动端 URL - 已废弃

    功能同 vue_redirect，处理所有对 /mobile/* 的请求。

    Args:
        filename (str): 原始 URL 中的路径部分

    Returns:
        Flask redirect response: 302/301 重定向响应
    """
    old_path = f"/mobile/{filename}" if filename else "/mobile"
    _log_legacy_access(old_path, "/")

    # 当前阶段：使用 302 临时重定向
    # 升级至 301 的时机：当新 URL 访问占比 > 80% 时
    return redirect('/', code=302)


# =============================================================================
# 注意：以下代码为注释出的备用方案，不同时使用
# =============================================================================

# 方案 B：继续完全支持旧 URL（不推荐，复杂度高）
# 如果选择此方案，启用下面的路由代替上面的重定向

"""
@bp.route('/vue')
@bp.route('/vue/')
def vue_index_deprecated():
    '''Vue应用首页(PC端) - 已废弃，建议使用 / 代替'''
    try:
        vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
        logger.info("Serving deprecated /vue endpoint")
        return send_from_directory(vue_dist_path, 'index.html')
    except Exception as e:
        logger.error(f"Error serving vue index: {e}")
        return f"Error: {str(e)}", 500


@bp.route('/vue/<path:filename>')
def vue_assets_deprecated(filename):
    '''Vue应用静态资源(PC端) - 已废弃'''
    try:
        vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
        return send_from_directory(vue_dist_path, filename)
    except Exception as e:
        logger.error(f"Error serving vue assets: {e}")
        return f"Error: {str(e)}", 500


@bp.route('/assets/<path:filename>')
def vue_assets_absolute_deprecated(filename):
    '''Vue应用绝对路径静态资源(PC端) - 已废弃'''
    try:
        vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist', 'assets')
        return send_from_directory(vue_dist_path, filename)
    except Exception as e:
        logger.error(f"Error serving vue absolute assets: {e}")
        return f"Error: {str(e)}", 500


@bp.route('/mobile/<path:filename>')
def mobile_assets_deprecated(filename):
    '''Vue应用静态资源(移动端) - 已废弃'''
    try:
        mobile_dist_path = os.path.join(current_app.root_path, '..', 'static', 'mobile-dist')

        # 如果是访问子路由(不包含文件扩展名),返回 index.html
        if '.' not in filename.split('/')[-1]:
            logger.debug(f"Serving SPA index for mobile route: /mobile/{filename}")
            return send_from_directory(mobile_dist_path, 'index.html')

        return send_from_directory(mobile_dist_path, filename)
    except Exception as e:
        logger.error(f"Error serving mobile assets: {e}")
        return f"Error: {str(e)}", 500
"""

# =============================================================================
# 调试端点（仅在开发环境启用）
# =============================================================================

@bp.route('/__debug/device-info')
def debug_device_info():
    """
    调试端点：显示当前请求的设备检测信息

    仅在开发环境使用，用于测试和验证设备检测逻辑。

    示例：
      curl http://localhost:5002/__debug/device-info

    返回 JSON 格式的设备信息：
      {
        "is_mobile": true,
        "is_tablet": false,
        "is_desktop": false,
        "browser": "Chrome",
        "os": "Android",
        "device": "POCO X5 Pro",
        "user_agent": "..."
      }
    """
    if not current_app.debug:
        return "Not Available", 404

    device_info = get_device_type()
    return device_info, 200


@bp.route('/__debug/routes')
def debug_routes():
    """
    调试端点：显示当前应用的所有路由

    仅在开发环境使用。
    """
    if not current_app.debug:
        return "Not Available", 404

    routes = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint != 'static':
            routes.append({
                'rule': str(rule),
                'endpoint': rule.endpoint,
                'methods': list(rule.methods - {'HEAD', 'OPTIONS'})
            })

    return {'routes': routes}, 200
```

### 2.3 更新 requirements.txt

```bash
# 添加 user-agents 库
echo "user-agents>=2.2.0" >> requirements.txt

# 验证
pip install -r requirements.txt
```

---

## 第3部分：测试验证

### 3.1 单元测试

**文件**: `/Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager/tests/test_device_detection.py`

```python
"""
设备检测模块的单元测试
"""

import unittest
from app import create_app, db
from app.utils.device_detection import is_mobile_device, get_device_type


class DeviceDetectionTestCase(unittest.TestCase):
    """设备检测测试用例"""

    def setUp(self):
        """测试前准备"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        """测试后清理"""
        self.app_context.pop()

    def test_mobile_user_agent_detection(self):
        """测试移动设备 User-Agent 检测"""
        mobile_user_agents = [
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15',
            'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36',
            'Mozilla/5.0 (iPad; CPU OS 17_7 like Mac OS X) AppleWebKit/605.1.15',
        ]

        for user_agent in mobile_user_agents:
            with self.client:
                response = self.client.get(
                    '/__debug/device-info',
                    headers={'User-Agent': user_agent}
                )
                data = response.get_json()
                self.assertTrue(
                    data['is_mobile'] or data['is_tablet'],
                    f"Failed for UA: {user_agent}"
                )

    def test_desktop_user_agent_detection(self):
        """测试桌面设备 User-Agent 检测"""
        desktop_user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        ]

        for user_agent in desktop_user_agents:
            with self.client:
                response = self.client.get(
                    '/__debug/device-info',
                    headers={'User-Agent': user_agent}
                )
                data = response.get_json()
                self.assertTrue(
                    data['is_desktop'],
                    f"Failed for UA: {user_agent}"
                )

    def test_root_path_redirect(self):
        """测试根路径返回正确的应用"""
        response = self.client.get('/', follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_legacy_url_redirect(self):
        """测试旧 URL 重定向"""
        # /vue 应重定向到 /
        response = self.client.get('/vue', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/'))

        # /mobile 应重定向到 /
        response = self.client.get('/mobile', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/'))


if __name__ == '__main__':
    unittest.main()
```

**运行测试**
```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager
python -m pytest tests/test_device_detection.py -v
```

### 3.2 手动功能测试

**测试用例**: `/Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager/docs/URL_MIGRATION_TESTING_CHECKLIST.md`

```markdown
# URL 迁移测试清单

## 环境配置
- [ ] 应用在本地运行：http://localhost:5002
- [ ] 前端已编译：static/vue-dist 和 static/mobile-dist 存在
- [ ] user-agents 库已安装

## 1. 路由响应测试

### 新 URL 测试
使用 `curl` 或浏览器测试：

```bash
# 1.1 测试根路径
curl -i http://localhost:5002/

# 期望：200 OK, 返回 index.html

# 1.2 测试 /app 路径
curl -i http://localhost:5002/app
curl -i http://localhost:5002/app/

# 期望：200 OK, 返回 index.html

# 1.3 测试前端路由（不带扩展名）
curl -i http://localhost:5002/gantt
curl -i http://localhost:5002/booking

# 期望：200 OK, 返回 index.html

# 1.4 测试资源路径（带扩展名）
curl -i http://localhost:5002/assets/app.js
curl -i http://localhost:5002/favicon.ico

# 期望：200 OK, 返回相应资源

# 1.5 测试调试端点
curl -i http://localhost:5002/__debug/device-info
curl -i http://localhost:5002/__debug/routes

# 期望：200 OK, 返回 JSON 格式数据
```

### 旧 URL 重定向测试

```bash
# 2.1 测试 /vue 重定向
curl -i http://localhost:5002/vue

# 期望：302 Found, Location: /

# 2.2 测试 /vue/ 重定向
curl -i http://localhost:5002/vue/

# 期望：302 Found, Location: /

# 2.3 测试 /mobile 重定向
curl -i http://localhost:5002/mobile

# 期望：302 Found, Location: /

# 2.4 测试 /mobile/ 重定向
curl -i http://localhost:5002/mobile/

# 期望：302 Found, Location: /

# 2.5 测试带路径的旧 URL
curl -i http://localhost:5002/vue/assets/app.js
curl -i http://localhost:5002/mobile/gantt

# 期望：302 Found, Location: / (或 /gantt)
```

## 2. 设备检测测试

### 桌面设备

**测试方法**：使用浏览器开发者工具修改 User-Agent

在 Chrome 开发者工具中：
1. F12 打开开发者工具
2. Ctrl+Shift+P 或 Cmd+Shift+P 打开命令面板
3. 输入 "User-Agent Client Hints"
4. 选择一个预设的 User-Agent

**测试用例**：
```bash
# Windows 桌面 - Chrome
curl -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36" \
  http://localhost:5002/__debug/device-info

# 期望：is_desktop=true, is_mobile=false

# macOS 桌面 - Safari
curl -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15" \
  http://localhost:5002/__debug/device-info

# 期望：is_desktop=true, is_mobile=false

# Linux 桌面 - Firefox
curl -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0" \
  http://localhost:5002/__debug/device-info

# 期望：is_desktop=true, is_mobile=false
```

### 移动设备

**测试用例**：
```bash
# iPhone - Safari
curl -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1" \
  http://localhost:5002/__debug/device-info

# 期望：is_mobile=true, is_desktop=false

# Android - Chrome
curl -H "User-Agent: Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Mobile Safari/537.36" \
  http://localhost:5002/__debug/device-info

# 期望：is_mobile=true, is_desktop=false

# iPad - Safari
curl -H "User-Agent: Mozilla/5.0 (iPad; CPU OS 17_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1" \
  http://localhost:5002/__debug/device-info

# 期望：is_tablet=true（iPad 可能被检测为 tablet）
```

## 3. 浏览器兼容性测试

使用实际设备或模拟器测试：

### PC 浏览器
- [ ] Chrome (Windows)
- [ ] Firefox (Windows)
- [ ] Safari (macOS)
- [ ] Edge (Windows)

### 移动浏览器
- [ ] Safari (iPhone)
- [ ] Chrome (Android)
- [ ] Samsung Internet (Android)

### 平板浏览器
- [ ] Safari (iPad)
- [ ] Chrome (Android Tablet)

## 4. 功能测试

在完整应用中测试以下功能：

### PC 应用功能
- [ ] 甘特图加载和交互
- [ ] 表单提交
- [ ] 数据导出
- [ ] 打印功能
- [ ] API 请求成功

### 移动应用功能
- [ ] 界面适配移动屏幕
- [ ] 触摸交互正常
- [ ] 弹窗和对话框正确显示
- [ ] 表单可以正确填写和提交

## 5. 性能测试

```bash
# 使用 curl 测试响应时间
time curl http://localhost:5002/

# 期望：< 100ms

# 测试重定向性能
time curl -i http://localhost:5002/vue

# 期望：< 10ms（只是 302 响应，无实际处理）
```

## 6. 日志检查

```bash
# 检查应用日志
tail -f logs/inventory_service.log

# 应该看到以下日志：
# - Serving root index from vue-dist (desktop)
# - Serving root index from mobile-dist (mobile)
# - Legacy URL access: /vue/... (deprecated)
# - Serving SPA index for route: /gantt
```

## 7. 浏览器缓存测试

1. 访问 http://localhost:5002/vue
2. 开发者工具 > Network 选项卡
3. 观察响应头：`Location: /`
4. 刷新浏览器
5. 再次访问 /vue
6. 验证：302 响应未被缓存（每次都发起请求）

## 测试结果记录

| 测试项目 | 预期结果 | 实际结果 | 状态 |
|---------|---------|---------|------|
| 根路径 / | 200 | | |
| /app 路径 | 200 | | |
| /vue 重定向 | 302 → / | | |
| /mobile 重定向 | 302 → / | | |
| iPhone 检测 | mobile-dist | | |
| Windows 检测 | vue-dist | | |
| 甘特图加载 | 正常 | | |
| API 请求 | 正常 | | |
| 日志记录 | 完整 | | |
```

---

## 第4部分：部署和监控

### 4.1 部署步骤

```bash
# 1. 停止当前应用
sudo systemctl stop inventory-manager  # 或根据实际情况调整

# 2. 拉取最新代码
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager
git pull origin main

# 3. 安装依赖
pip install -r requirements.txt

# 4. 前端构建（如果有前端代码变化）
cd frontend
npm install
npm run build
cd ..

# 5. 数据库迁移（如果需要）
flask db upgrade

# 6. 启动应用
python run.py  # 或根据实际情况调整

# 7. 验证
curl http://localhost:5002/__debug/device-info
```

### 4.2 监控指标

#### 访问日志分析脚本

```python
"""
日志分析脚本：统计新旧 URL 的访问比例

用法：
  python analyze_logs.py --log logs/inventory_service.log --days 7
"""

import re
from datetime import datetime, timedelta
from collections import defaultdict


def analyze_url_migration(log_file, days=7):
    """分析 URL 迁移进度"""

    new_url_pattern = re.compile(r'Serving root index|Serving asset|Serving SPA index')
    legacy_url_pattern = re.compile(r'Legacy URL access')

    new_url_count = 0
    legacy_url_count = 0

    with open(log_file, 'r') as f:
        for line in f:
            if new_url_pattern.search(line):
                new_url_count += 1
            elif legacy_url_pattern.search(line):
                legacy_url_count += 1

    total = new_url_count + legacy_url_count

    if total > 0:
        print(f"URL 访问统计（过去 {days} 天）")
        print(f"新 URL 访问: {new_url_count} ({100*new_url_count/total:.1f}%)")
        print(f"旧 URL 访问: {legacy_url_count} ({100*legacy_url_count/total:.1f}%)")
        print(f"总计: {total}")

        return {
            'new_url_count': new_url_count,
            'legacy_url_count': legacy_url_count,
            'new_url_percentage': 100 * new_url_count / total,
            'legacy_url_percentage': 100 * legacy_url_count / total
        }


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='分析 URL 迁移进度')
    parser.add_argument('--log', required=True, help='日志文件路径')
    parser.add_argument('--days', type=int, default=7, help='分析天数')

    args = parser.parse_args()

    analyze_url_migration(args.log, args.days)
```

**运行分析**
```bash
python analyze_logs.py --log logs/inventory_service.log --days 7
```

### 4.3 升级到 301 的时机判断

根据监控指标，当满足以下条件时，可升级为 301 永久重定向：

1. 新 URL 访问占比 > 80%
2. 旧 URL 访问 < 100 次/天
3. 用户反馈投诉 < 5 个

升级步骤：
```python
# 在 vue_app.py 中修改重定向代码
@bp.route('/vue')
@bp.route('/vue/')
@bp.route('/vue/<path:filename>')
def vue_redirect(filename=''):
    """旧 PC 端 URL - 已废弃"""
    old_path = f"/vue/{filename}" if filename else "/vue"
    _log_legacy_access(old_path, "/")
    # 改为 301 永久重定向
    return redirect('/', code=301)  # 从 302 改为 301
```

---

## 第5部分：故障排查

### 问题 1: 新 URL 返回 404

**症状**：访问 / 或 /app 返回 404

**原因**：
- 前端构建输出目录不存在或 index.html 缺失
- Flask 蓝图注册顺序问题

**解决**：
```bash
# 检查构建输出
ls -la static/vue-dist/index.html
ls -la static/mobile-dist/index.html

# 重新编译前端
cd frontend && npm run build && cd ..

# 检查蓝图注册
python -c "from app import create_app; app = create_app(); print([r for r in app.url_map.iter_rules() if '/' in str(r)])"
```

### 问题 2: 旧 URL 返回 200 而不是 302

**症状**：访问 /vue 返回 200（提供旧内容）而不是重定向

**原因**：可能启用了备用方案（注释掉的旧路由）

**解决**：
```python
# 确保只有一套路由生效
# 检查 vue_app.py 中是否有重复的路由定义

# 正确的方式：使用重定向处理旧 URL
@bp.route('/vue')
def vue_redirect(filename=''):
    return redirect('/', code=302)  # 必须有这个

# 错误的方式：同时定义内容和重定向
# @bp.route('/vue')
# def vue_index():
#     return send_from_directory(...)
# @bp.route('/vue')
# def vue_redirect():
#     return redirect(...)
```

### 问题 3: 设备检测不准确

**症状**：桌面用户被检测为移动设备，或反之

**原因**：user-agents 库的检测规则可能与预期不符

**解决**：
```python
# 检查具体的 User-Agent 字符串
curl -H "User-Agent: YOUR_USER_AGENT" http://localhost:5002/__debug/device-info

# 如果检测错误，可以添加自定义规则
def is_mobile_device():
    user_agent_string = request.headers.get('User-Agent', '')
    ua = parse(user_agent_string)

    # 自定义规则（可选）
    if 'iPad' in user_agent_string:
        return False  # 强制 iPad 被视为桌面设备

    return ua.is_mobile
```

### 问题 4: 资源加载失败（404）

**症状**：CSS、JS、图片等资源返回 404

**原因**：资源路径不正确或前端构建有问题

**解决**：
```bash
# 检查资源是否存在
find static -name "*.css" -o -name "*.js" | head -20

# 检查前端构建配置
cat frontend/vite.config.ts | grep -A 5 "outDir"

# 确保构建输出正确
cd frontend && npm run build
ls -la ../static/vue-dist/assets/
```

---

## 附录：快速参考

### 重定向升级流程

```
第1-8周：302 临时重定向
  └─ 用户反馈收集
  └─ 访问比例监控
  └─ 问题修复

第8-24周：升级为 301 永久重定向
  └─ 修改 code=302 为 code=301
  └─ 更新 SEO 相关配置
  └─ 继续监控访问比例

第25周+：可选移除旧 URL 路由
  └─ 确认旧 URL 访问 < 5%
  └─ 删除旧 URL 处理代码
  └─ 保持 301 重定向（长期）
```

### 关键文件清单

| 文件 | 用途 | 修改状态 |
|-----|------|--------|
| `/app/utils/device_detection.py` | 设备检测模块 | 新建 |
| `/app/routes/vue_app.py` | 主路由处理 | 修改 |
| `requirements.txt` | 依赖列表 | 新增 user-agents |
| `docs/BACKWARD_COMPATIBILITY_STRATEGY.md` | 策略文档 | 新建 |
| `docs/URL_MIGRATION_IMPLEMENTATION_GUIDE.md` | 实施指南 | 新建 |

### 验证命令速查

```bash
# 快速验证部署
curl -i http://localhost:5002/               # 应返回 200
curl -i http://localhost:5002/vue             # 应返回 302
curl -i http://localhost:5002/__debug/device-info  # 应返回 JSON

# 检查日志
tail -20 logs/inventory_service.log

# 查看当前路由
python -c "from app import create_app; app = create_app(); [print(r) for r in app.url_map.iter_rules() if 'vue' in str(r) or 'app' in str(r)]"

# 运行测试
python -m pytest tests/test_device_detection.py -v
```

---

**文档版本**: 1.0
**最后更新**: 2026-01-01
