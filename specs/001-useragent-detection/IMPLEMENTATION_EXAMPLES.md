# User-Agent 检测库 - 实现示例

## 完整代码示例与最佳实践

---

## 方案 A: user-agents (推荐)

### 1. 安装依赖

```bash
# pip
pip install user-agents

# poetry
poetry add user-agents

# pipenv
pipenv install user-agents
```

### 2. 基础使用

#### app/utils/device_detector.py

```python
"""设备检测工具模块"""
from functools import lru_cache
from user_agents import parse
from typing import Optional, Dict, Literal


@lru_cache(maxsize=1024)
def parse_user_agent(ua_string: str):
    """
    解析 user-agent 字符串 (带缓存)

    Args:
        ua_string: User-Agent 头字符串

    Returns:
        user_agents.UserAgent 对象
    """
    return parse(ua_string)


def detect_device_type(ua_string: str) -> Literal['mobile', 'desktop']:
    """
    检测设备类型

    Args:
        ua_string: User-Agent 头字符串

    Returns:
        'mobile' 或 'desktop'
        - 'mobile': 移动设备 (手机或平板)
        - 'desktop': 桌面设备

    示例:
        >>> detect_device_type('Mozilla/5.0 (iPhone; CPU iPhone OS 16_6...')
        'mobile'
        >>> detect_device_type('Mozilla/5.0 (Windows NT 10.0; Win64; x64)...')
        'desktop'
        >>> detect_device_type('')  # 缺失 UA 时
        'desktop'  # 默认桌面
    """
    if not ua_string:
        return 'desktop'

    try:
        ua = parse_user_agent(ua_string)

        # 判断是否为移动设备 (包括手机和平板)
        if ua.is_mobile or ua.is_tablet:
            return 'mobile'
        else:
            return 'desktop'
    except Exception as e:
        print(f"Error parsing UA: {e}")
        return 'desktop'  # 任何错误都默认返回桌面


def is_mobile(ua_string: str) -> bool:
    """检测是否为手机设备"""
    if not ua_string:
        return False
    try:
        ua = parse_user_agent(ua_string)
        return ua.is_mobile
    except:
        return False


def is_tablet(ua_string: str) -> bool:
    """检测是否为平板设备"""
    if not ua_string:
        return False
    try:
        ua = parse_user_agent(ua_string)
        return ua.is_tablet
    except:
        return False


def is_desktop(ua_string: str) -> bool:
    """检测是否为桌面设备"""
    if not ua_string:
        return True  # 默认为桌面
    try:
        ua = parse_user_agent(ua_string)
        return ua.is_pc
    except:
        return True


def get_device_info(ua_string: str) -> Dict:
    """
    获取详细的设备信息

    Args:
        ua_string: User-Agent 头字符串

    Returns:
        包含设备信息的字典:
        {
            'type': 'mobile' | 'desktop',
            'device_family': str,           # iPhone, iPad, SM-S910B 等
            'os_family': str,               # iOS, Android, Windows 等
            'os_version': str,              # 操作系统版本
            'browser_family': str,          # Chrome, Safari, Firefox 等
            'browser_version': str,         # 浏览器版本
            'is_mobile': bool,
            'is_tablet': bool,
            'is_pc': bool,
            'is_bot': bool,
        }

    示例:
        >>> get_device_info('Mozilla/5.0 (iPhone; CPU iPhone OS 16_6...')
        {
            'type': 'mobile',
            'device_family': 'iPhone',
            'os_family': 'iOS',
            'os_version': '16.6',
            'browser_family': 'Mobile Safari',
            'browser_version': '16.6',
            'is_mobile': True,
            'is_tablet': False,
            'is_pc': False,
            'is_bot': False,
        }
    """
    default_info = {
        'type': 'desktop',
        'device_family': 'Unknown',
        'os_family': 'Unknown',
        'os_version': 'Unknown',
        'browser_family': 'Unknown',
        'browser_version': 'Unknown',
        'is_mobile': False,
        'is_tablet': False,
        'is_pc': True,
        'is_bot': False,
    }

    if not ua_string:
        return default_info

    try:
        ua = parse_user_agent(ua_string)

        # 构建版本字符串
        os_version = f"{ua.os.major}.{ua.os.minor}" if ua.os.major else "Unknown"
        browser_version = f"{ua.browser.major}.{ua.browser.minor}" if ua.browser.major else "Unknown"

        return {
            'type': 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop',
            'device_family': ua.device.family or 'Unknown',
            'os_family': ua.os.family or 'Unknown',
            'os_version': os_version,
            'browser_family': ua.browser.family or 'Unknown',
            'browser_version': browser_version,
            'is_mobile': ua.is_mobile,
            'is_tablet': ua.is_tablet,
            'is_pc': ua.is_pc,
            'is_bot': ua.is_bot,
        }
    except Exception as e:
        print(f"Error getting device info: {e}")
        return default_info


def is_webview(ua_string: str) -> Optional[str]:
    """
    检测是否为应用内浏览器 (WebView)

    Args:
        ua_string: User-Agent 头字符串

    Returns:
        如果是 WebView 返回应用名称,否则返回 None

        支持的应用:
        - 'wechat': WeChat (微信)
        - 'qq': QQ
        - 'alipay': Alipay (支付宝)
        - 'facebook': Facebook
        - 'instagram': Instagram
        - 'line': LINE
        - 'dingtalk': DingTalk (钉钉)
        - 'baidu': Baidu (百度)

    示例:
        >>> is_webview('Mozilla/.../MicroMessenger/8.0.16...')
        'wechat'
        >>> is_webview('Mozilla/.../FBAN/FB4A...')
        'facebook'
        >>> is_webview('Mozilla/.../Chrome/119.0...')
        None
    """
    if not ua_string:
        return None

    # WebView 标识符映射
    webview_indicators = {
        'wechat': ['MicroMessenger', 'WeChat'],
        'qq': ['QQ/', 'QQBrowser'],
        'alipay': ['Alipay'],
        'facebook': ['FBAN/FB4A', 'fban/fb4a'],
        'instagram': ['Instagram'],
        'line': [' Line/', ' LINE '],
        'dingtalk': ['Dingtalk', 'DingTalk'],
        'baidu': ['baidubrowser'],
    }

    for app, indicators in webview_indicators.items():
        for indicator in indicators:
            if indicator in ua_string:
                return app

    return None


def detect_device_mode(ua_string: str) -> Literal['mobile', 'desktop', 'tablet']:
    """
    检测设备模式 (更细粒度的分类)

    Args:
        ua_string: User-Agent 头字符串

    Returns:
        - 'mobile': 手机设备
        - 'tablet': 平板设备
        - 'desktop': 桌面设备

    注意:
        此函数比 detect_device_type 更细粒度,但通常在实际应用中
        我们会将 'tablet' 当作 'mobile' 处理。
    """
    if not ua_string:
        return 'desktop'

    try:
        ua = parse_user_agent(ua_string)

        if ua.is_tablet:
            return 'tablet'
        elif ua.is_mobile:
            return 'mobile'
        else:
            return 'desktop'
    except:
        return 'desktop'
```

### 3. Flask 应用集成

#### app/routes/vue_app.py

```python
"""前端路由 - 基于 user-agent 的自动设备检测"""
from flask import Blueprint, render_template, request, send_from_directory, jsonify
from app.utils.device_detector import (
    detect_device_type,
    get_device_info,
    is_webview,
)

# 创建蓝图
vue_bp = Blueprint('vue', __name__)


@vue_bp.route('/', methods=['GET'])
@vue_bp.route('/app/', methods=['GET'])
def index():
    """
    统一入口 - 根据 user-agent 自动检测设备类型并提供相应的前端

    流程:
    1. 从请求头提取 User-Agent
    2. 使用 device_detector 检测设备类型
    3. 记录设备信息用于分析
    4. 返回相应的前端文件 (desktop 或 mobile)
    """
    ua_string = request.headers.get('User-Agent', '')
    device_type = detect_device_type(ua_string)
    device_info = get_device_info(ua_string)
    webview_app = is_webview(ua_string)

    # 日志记录 (用于监控和分析)
    log_msg = (
        f"Device: {device_type} | "
        f"OS: {device_info['os_family']} {device_info['os_version']} | "
        f"Device: {device_info['device_family']} | "
        f"Browser: {device_info['browser_family']}"
    )
    if webview_app:
        log_msg += f" | WebView: {webview_app}"

    current_app.logger.info(log_msg)

    # 返回相应的前端
    if device_type == 'mobile':
        return send_from_directory('static/mobile-dist', 'index.html')
    else:
        return send_from_directory('static/vue-dist', 'index.html')


@vue_bp.route('/api/device-info', methods=['GET'])
def api_device_info():
    """
    API 端点 - 返回设备检测信息

    用途:
    - 前端可以调用此 API 获取服务器检测的设备信息
    - 进行客户端检测,与服务器检测结果对比
    - 用于调试和分析

    返回值:
    {
        'type': 'mobile' | 'desktop',
        'device_family': str,
        'os_family': str,
        'os_version': str,
        'browser_family': str,
        'browser_version': str,
        'is_mobile': bool,
        'is_tablet': bool,
        'is_pc': bool,
        'is_bot': bool,
    }
    """
    ua_string = request.headers.get('User-Agent', '')
    device_info = get_device_info(ua_string)

    # 添加其他元数据
    device_info['timestamp'] = int(time.time())
    device_info['user_agent'] = ua_string

    return jsonify(device_info)


@vue_bp.route('/api/webview-check', methods=['GET'])
def api_webview_check():
    """
    API 端点 - 检查是否为 WebView

    返回值:
    {
        'is_webview': bool,
        'app': 'wechat' | 'qq' | 'alipay' | ... | None
    }
    """
    ua_string = request.headers.get('User-Agent', '')
    webview_app = is_webview(ua_string)

    return jsonify({
        'is_webview': webview_app is not None,
        'app': webview_app,
    })


# 可选: 向后兼容旧 URL
@vue_bp.route('/vue/<path:path>', methods=['GET'])
def vue_legacy(path):
    """
    向后兼容旧 /vue/ URL

    迁移选项:
    1. 301 永久重定向到新 URL (完全迁移后)
    2. 继续服务 (过渡期)
    3. 返回错误提示用户更新书签
    """
    # 选项 1: 永久重定向 (完全迁移后使用)
    # return redirect(url_for('vue.index'), code=301)

    # 选项 2: 继续服务 (过渡期使用)
    return send_from_directory('static/vue-dist', 'index.html')

    # 选项 3: 返回错误提示 (激进迁移)
    # return render_template('migration_notice.html',
    #                      old_url=request.path,
    #                      new_url='/'), 301


@vue_bp.route('/mobile/<path:path>', methods=['GET'])
def mobile_legacy(path):
    """向后兼容旧 /mobile/ URL"""
    # 与 /vue/ 路由类似的处理
    return send_from_directory('static/mobile-dist', 'index.html')


# 在 Flask 应用中注册蓝图
def register_routes(app):
    """注册所有路由"""
    app.register_blueprint(vue_bp)
```

### 4. 单元测试

#### tests/unit/test_device_detector.py

```python
"""设备检测单元测试"""
import pytest
from app.utils.device_detector import (
    detect_device_type,
    detect_device_mode,
    is_mobile,
    is_tablet,
    is_desktop,
    get_device_info,
    is_webview,
)


class TestDeviceDetection:
    """设备检测功能测试"""

    # ===== iOS 用户代理 =====
    UA_IPHONE_15 = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 "
        "Mobile/15E148 Safari/604.1"
    )

    UA_IPHONE_16 = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
        "Mobile/15E148 Safari/604.1"
    )

    UA_IPAD_AIR = (
        "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
        "Mobile/15E148 Safari/604.1"
    )

    UA_IPAD_PRO = (
        "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
        "Mobile/15E148 Safari/604.1"
    )

    # ===== Android 用户代理 =====
    UA_ANDROID_PHONE = (
        "Mozilla/5.0 (Linux; Android 13; SM-S910B) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Mobile Safari/537.36"
    )

    UA_ANDROID_TABLET = (
        "Mozilla/5.0 (Linux; Android 13; SM-X900) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    )

    # ===== 桌面用户代理 =====
    UA_CHROME_WINDOWS = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    )

    UA_SAFARI_MACOS = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.1 Safari/605.1.15"
    )

    UA_FIREFOX_LINUX = (
        "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) "
        "Gecko/20100101 Firefox/120.0"
    )

    UA_EDGE_WINDOWS = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0"
    )

    # ===== WebView 用户代理 =====
    UA_WECHAT = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "MicroMessenger/8.0.16(0x18001037) NetType/WIFI Language/zh_CN"
    )

    UA_FACEBOOK = (
        "Mozilla/5.0 (Linux; Android 11; SM-G991B) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.120 Mobile Safari/537.36 "
        "FBAN/FB4A;FBAV/123.0.0.0.0"
    )

    UA_QQ = (
        "Mozilla/5.0 (Linux; Android 11; Xiaomi Mi 11) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/86.0.4240.185 Mobile Safari/537.36 "
        "QQ/10.8.50"
    )

    # ===== 边界情况 =====
    UA_EMPTY = ""
    UA_NONE = None
    UA_UNKNOWN = "UnknownBrowser/1.0"

    # ========== 测试: detect_device_type ==========

    class TestDetectDeviceType:
        """测试 detect_device_type 函数"""

        def test_iphone_is_mobile(self):
            assert detect_device_type(TestDeviceDetection.UA_IPHONE_15) == 'mobile'
            assert detect_device_type(TestDeviceDetection.UA_IPHONE_16) == 'mobile'

        def test_ipad_is_mobile(self):
            """平板被当作移动设备"""
            assert detect_device_type(TestDeviceDetection.UA_IPAD_AIR) == 'mobile'
            assert detect_device_type(TestDeviceDetection.UA_IPAD_PRO) == 'mobile'

        def test_android_phone_is_mobile(self):
            assert detect_device_type(TestDeviceDetection.UA_ANDROID_PHONE) == 'mobile'

        def test_android_tablet_is_mobile(self):
            """平板被当作移动设备"""
            assert detect_device_type(TestDeviceDetection.UA_ANDROID_TABLET) == 'mobile'

        def test_chrome_windows_is_desktop(self):
            assert detect_device_type(TestDeviceDetection.UA_CHROME_WINDOWS) == 'desktop'

        def test_safari_macos_is_desktop(self):
            assert detect_device_type(TestDeviceDetection.UA_SAFARI_MACOS) == 'desktop'

        def test_firefox_linux_is_desktop(self):
            assert detect_device_type(TestDeviceDetection.UA_FIREFOX_LINUX) == 'desktop'

        def test_edge_windows_is_desktop(self):
            assert detect_device_type(TestDeviceDetection.UA_EDGE_WINDOWS) == 'desktop'

        def test_empty_ua_defaults_to_desktop(self):
            """缺失 UA 时默认为桌面"""
            assert detect_device_type(TestDeviceDetection.UA_EMPTY) == 'desktop'

        def test_none_ua_defaults_to_desktop(self):
            """None UA 时默认为桌面"""
            assert detect_device_type(None) == 'desktop'

        def test_unknown_ua_defaults_to_desktop(self):
            """无法识别的 UA 时默认为桌面"""
            assert detect_device_type(TestDeviceDetection.UA_UNKNOWN) == 'desktop'

    # ========== 测试: detect_device_mode ==========

    class TestDetectDeviceMode:
        """测试 detect_device_mode 函数 (更细粒度)"""

        def test_iphone_is_mobile(self):
            mode = detect_device_mode(TestDeviceDetection.UA_IPHONE_15)
            assert mode == 'mobile'

        def test_ipad_is_tablet(self):
            """平板返回 'tablet'"""
            mode = detect_device_mode(TestDeviceDetection.UA_IPAD_AIR)
            assert mode == 'tablet'

        def test_android_phone_is_mobile(self):
            mode = detect_device_mode(TestDeviceDetection.UA_ANDROID_PHONE)
            assert mode == 'mobile'

        def test_android_tablet_is_tablet(self):
            """平板返回 'tablet'"""
            mode = detect_device_mode(TestDeviceDetection.UA_ANDROID_TABLET)
            assert mode == 'tablet'

        def test_desktop_is_desktop(self):
            mode = detect_device_mode(TestDeviceDetection.UA_CHROME_WINDOWS)
            assert mode == 'desktop'

    # ========== 测试: is_mobile / is_tablet / is_desktop ==========

    class TestBooleanFunctions:
        """测试布尔检测函数"""

        def test_is_mobile_iphone(self):
            assert is_mobile(TestDeviceDetection.UA_IPHONE_15) is True
            assert is_tablet(TestDeviceDetection.UA_IPHONE_15) is False

        def test_is_mobile_ipad(self):
            """iPad 不是 is_mobile,但是 is_tablet"""
            assert is_mobile(TestDeviceDetection.UA_IPAD_AIR) is False
            assert is_tablet(TestDeviceDetection.UA_IPAD_AIR) is True

        def test_is_desktop_chrome(self):
            assert is_desktop(TestDeviceDetection.UA_CHROME_WINDOWS) is True
            assert is_mobile(TestDeviceDetection.UA_CHROME_WINDOWS) is False

    # ========== 测试: get_device_info ==========

    class TestGetDeviceInfo:
        """测试 get_device_info 函数"""

        def test_iphone_info(self):
            info = get_device_info(TestDeviceDetection.UA_IPHONE_16)
            assert info['type'] == 'mobile'
            assert info['device_family'] == 'iPhone'
            assert info['os_family'] == 'iOS'
            assert info['browser_family'] == 'Mobile Safari'
            assert info['is_mobile'] is True
            assert info['is_pc'] is False

        def test_chrome_windows_info(self):
            info = get_device_info(TestDeviceDetection.UA_CHROME_WINDOWS)
            assert info['type'] == 'desktop'
            assert info['os_family'] == 'Windows'
            assert info['browser_family'] == 'Chrome'
            assert info['is_pc'] is True
            assert info['is_mobile'] is False

        def test_empty_ua_returns_defaults(self):
            info = get_device_info(TestDeviceDetection.UA_EMPTY)
            assert info['type'] == 'desktop'
            assert info['device_family'] == 'Unknown'
            assert info['os_family'] == 'Unknown'

    # ========== 测试: is_webview ==========

    class TestIsWebView:
        """测试 is_webview 函数"""

        def test_wechat_detection(self):
            app = is_webview(TestDeviceDetection.UA_WECHAT)
            assert app == 'wechat'

        def test_facebook_detection(self):
            app = is_webview(TestDeviceDetection.UA_FACEBOOK)
            assert app == 'facebook'

        def test_qq_detection(self):
            app = is_webview(TestDeviceDetection.UA_QQ)
            assert app == 'qq'

        def test_regular_browser_not_webview(self):
            app = is_webview(TestDeviceDetection.UA_IPHONE_15)
            assert app is None

        def test_empty_ua_not_webview(self):
            app = is_webview(TestDeviceDetection.UA_EMPTY)
            assert app is None


# 集成测试示例
class TestDeviceDetectionIntegration:
    """集成测试"""

    def test_complete_workflow(self):
        """测试完整的检测工作流"""
        ua_string = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
            "Mobile/15E148 Safari/604.1"
        )

        # 步骤 1: 检测设备类型
        device_type = detect_device_type(ua_string)
        assert device_type == 'mobile'

        # 步骤 2: 获取详细信息
        device_info = get_device_info(ua_string)
        assert device_info['type'] == 'mobile'
        assert device_info['device_family'] == 'iPhone'

        # 步骤 3: 检查是否为 WebView
        webview_app = is_webview(ua_string)
        assert webview_app is None

        # 步骤 4: 确定要返回的前端
        if device_type == 'mobile':
            frontend = 'mobile-dist'
        else:
            frontend = 'vue-dist'

        assert frontend == 'mobile-dist'
```

### 5. 前端集成 (Vue 3)

#### src/composables/useDeviceDetection.ts

```typescript
/**
 * 设备检测组合 (Composition API)
 *
 * 用途:
 * - 从服务器获取设备检测信息
 * - 进行客户端备用检测
 * - 处理检测不匹配情况
 */
import { ref, onMounted, computed } from 'vue'

export interface DeviceInfo {
  type: 'mobile' | 'desktop'
  device_family: string
  os_family: string
  os_version: string
  browser_family: string
  browser_version: string
  is_mobile: boolean
  is_tablet: boolean
  is_pc: boolean
  is_bot: boolean
}

export function useDeviceDetection() {
  const isMobile = ref(false)
  const isTablet = ref(false)
  const isDesktop = ref(false)
  const deviceInfo = ref<DeviceInfo | null>(null)
  const detectionSource = ref<'server' | 'client' | 'error'>('error')
  const loading = ref(true)
  const error = ref<string | null>(null)

  // 客户端检测 (备用)
  function detectClientDevice(): boolean {
    const ua = navigator.userAgent
    const mobileRegex = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i
    return mobileRegex.test(ua)
  }

  // 从服务器获取设备信息
  async function fetchDeviceInfo() {
    try {
      const response = await fetch('/api/device-info')

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data: DeviceInfo = await response.json()
      deviceInfo.value = data

      isMobile.value = data.is_mobile || data.is_tablet
      isTablet.value = data.is_tablet
      isDesktop.value = data.is_pc

      detectionSource.value = 'server'

      // 客户端验证
      const clientDetected = detectClientDevice()
      if (isMobile.value !== clientDetected) {
        console.warn('Device detection mismatch:', {
          server: isMobile.value,
          client: clientDetected,
          serverInfo: data,
        })
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Unknown error'
      console.error('Failed to fetch device info:', e)

      // 回退: 使用客户端检测
      const clientDetected = detectClientDevice()
      isMobile.value = clientDetected
      isDesktop.value = !clientDetected
      detectionSource.value = 'client'
    } finally {
      loading.value = false
    }
  }

  // 生命周期: 组件挂载时获取设备信息
  onMounted(() => {
    fetchDeviceInfo()
  })

  // 计算属性
  const deviceType = computed(() => {
    if (isTablet.value) return 'tablet'
    if (isMobile.value) return 'mobile'
    return 'desktop'
  })

  return {
    // 状态
    isMobile,
    isTablet,
    isDesktop,
    deviceInfo,
    detectionSource,
    loading,
    error,

    // 计算属性
    deviceType,

    // 方法
    detectClientDevice,
    fetchDeviceInfo,
  }
}

// 使用示例:
/*
<script setup lang="ts">
import { useDeviceDetection } from '@/composables/useDeviceDetection'

const { isMobile, isDesktop, deviceInfo, loading } = useDeviceDetection()
</script>

<template>
  <div v-if="loading">Loading...</div>
  <div v-else>
    <MobileView v-if="isMobile" />
    <DesktopView v-else />

    <DebugInfo v-if="isDev">
      {{ deviceInfo }}
    </DebugInfo>
  </div>
</template>
*/
```

### 6. Flask 应用初始化

#### app/__init__.py

```python
"""Flask 应用工厂"""
from flask import Flask
import logging
from app.routes import vue_app  # 导入路由蓝图


def create_app(config=None):
    """创建和配置 Flask 应用"""
    app = Flask(__name__)

    # 配置
    app.config['JSON_SORT_KEYS'] = False

    if config:
        app.config.update(config)

    # 设置日志
    setup_logging(app)

    # 注册路由
    app.register_blueprint(vue_app.vue_bp)

    return app


def setup_logging(app):
    """设置应用日志"""
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    handler.setFormatter(formatter)

    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
```

---

## 方案 B: ua-parser (备选)

### 基础实现

```python
"""使用 ua-parser 的设备检测"""
from ua_parser.user_agent_parser import Parse
from typing import Dict

# 移动设备 family 列表
MOBILE_DEVICE_FAMILIES = {
    'iPhone', 'iPad', 'Android', 'HTC', 'Nexus', 'Samsung',
    'LG', 'Sony', 'Motorola', 'BlackBerry', 'Windows Phone',
    'Nokia', 'Palm', 'Kindle', 'Generic Smartphone', 'Generic Tablet',
}

def detect_device_ua_parser(ua_string: str) -> str:
    """使用 ua-parser 检测设备类型"""
    if not ua_string:
        return 'desktop'

    try:
        result = Parse(ua_string)
        device_family = result['device']['family']

        if device_family in MOBILE_DEVICE_FAMILIES:
            return 'mobile'
        else:
            return 'desktop'
    except:
        return 'desktop'

def get_device_info_ua_parser(ua_string: str) -> Dict:
    """使用 ua-parser 获取详细设备信息"""
    if not ua_string:
        return {
            'device': 'Unknown',
            'os': 'Unknown',
            'browser': 'Unknown',
            'is_mobile': False,
        }

    try:
        result = Parse(ua_string)
        device = result['device']
        os = result['os']
        browser = result['user_agent']

        device_family = device['family']
        is_mobile = device_family in MOBILE_DEVICE_FAMILIES

        return {
            'device': device['family'],
            'device_brand': device.get('brand', 'Unknown'),
            'os': os['family'],
            'os_version': f"{os.get('major', '?')}.{os.get('minor', '?')}",
            'browser': browser['family'],
            'browser_version': f"{browser.get('major', '?')}.{browser.get('minor', '?')}",
            'is_mobile': is_mobile,
        }
    except Exception as e:
        print(f"Error parsing UA: {e}")
        return {
            'device': 'Unknown',
            'os': 'Unknown',
            'browser': 'Unknown',
            'is_mobile': False,
        }
```

---

## 方案 C: werkzeug 仅

### 基础实现

```python
"""使用 werkzeug 内置功能的设备检测"""
from werkzeug.useragents import UserAgent

def detect_device_werkzeug(environ) -> str:
    """使用 werkzeug 检测设备类型"""
    ua = UserAgent(environ)

    # werkzeug 的 platform 属性值
    mobile_platforms = ['iphone', 'android', 'mobile', 'blackberry']

    if ua.platform in mobile_platforms:
        return 'mobile'
    else:
        return 'desktop'

# 在 Flask 路由中使用
from flask import request

@app.route('/')
def index():
    device_type = detect_device_werkzeug(request.environ)

    if device_type == 'mobile':
        return serve_mobile()
    else:
        return serve_desktop()
```

**注意**: werkzeug 方案不推荐用于生产,因为无法识别平板设备。

---

## 性能优化建议

### 1. 缓存策略

```python
from functools import lru_cache
from user_agents import parse

# 使用 LRU 缓存避免重复解析
@lru_cache(maxsize=1024)
def parse_user_agent(ua_string):
    return parse(ua_string)

# 缓存统计
def cache_info():
    """获取缓存统计信息"""
    return parse_user_agent.cache_info()
    # 输出: CacheInfo(hits=1000, misses=100, maxsize=1024, currsize=100)
```

### 2. 批量处理

```python
def detect_batch(ua_strings: List[str]) -> List[str]:
    """批量检测设备类型"""
    return [detect_device_type(ua) for ua in ua_strings]

# 或使用并发处理大量请求
from concurrent.futures import ThreadPoolExecutor

def detect_concurrent(ua_strings: List[str]) -> List[str]:
    with ThreadPoolExecutor(max_workers=4) as executor:
        return list(executor.map(detect_device_type, ua_strings))
```

### 3. 预热

```python
def warmup_cache():
    """预热缓存"""
    common_user_agents = [
        # iPhone
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6...",
        # Android
        "Mozilla/5.0 (Linux; Android 13; SM-S910B)...",
        # Chrome Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
        # Safari macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
        # Firefox Linux
        "Mozilla/5.0 (X11; Linux x86_64; rv:120.0)...",
    ]

    for ua in common_user_agents:
        parse_user_agent(ua)

    print(f"Cache warmed: {parse_user_agent.cache_info()}")

# 在应用启动时调用
if __name__ == '__main__':
    app = create_app()
    warmup_cache()
    app.run()
```

---

## 监控与日志

### 集中日志记录

```python
"""设备检测监控"""
import logging
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger('device_detection')

class DeviceDetectionMonitor:
    """设备检测监控器"""

    def __init__(self):
        self.stats = defaultdict(int)
        self.errors = defaultdict(int)

    def record_detection(self, device_type: str, device_family: str):
        """记录设备检测"""
        self.stats[f"{device_type}_{device_family}"] += 1

    def record_error(self, error: str):
        """记录错误"""
        self.errors[error] += 1

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            'total_detections': sum(self.stats.values()),
            'by_device': self.stats,
            'errors': self.errors,
        }

# 使用
monitor = DeviceDetectionMonitor()

def detect_device_with_monitor(ua_string):
    try:
        device_type = detect_device_type(ua_string)
        monitor.record_detection(device_type, get_device_info(ua_string)['device_family'])
        return device_type
    except Exception as e:
        monitor.record_error(str(e))
        raise

# 定期输出统计
@app.route('/api/monitoring/device-stats')
def device_stats():
    return jsonify(monitor.get_stats())
```

---

## 故障排查

### 常见问题

#### 问题 1: 某些设备无法正确识别

```python
# 解决方案: 增加日志和调试信息
def detect_device_debug(ua_string):
    """带调试信息的设备检测"""
    ua = parse(ua_string)

    print(f"User-Agent: {ua_string}")
    print(f"  - Device: {ua.device.family}")
    print(f"  - OS: {ua.os.family} {ua.os.major}.{ua.os.minor}")
    print(f"  - Browser: {ua.browser.family} {ua.browser.major}.{ua.browser.minor}")
    print(f"  - is_mobile: {ua.is_mobile}")
    print(f"  - is_tablet: {ua.is_tablet}")
    print(f"  - is_pc: {ua.is_pc}")

    return 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop'
```

#### 问题 2: 性能下降

```python
# 解决方案: 检查缓存命中率
def check_cache_performance():
    """检查缓存性能"""
    cache_info = parse_user_agent.cache_info()
    hit_rate = cache_info.hits / (cache_info.hits + cache_info.misses) if cache_info.misses > 0 else 0

    print(f"Cache hit rate: {hit_rate:.2%}")
    print(f"Cache size: {cache_info.currsize}/{cache_info.maxsize}")

    if hit_rate < 0.8:
        print("WARNING: Low cache hit rate, consider increasing maxsize")
```

---

**文档版本**: 1.0
**最后更新**: 2026-01-01
**状态**: 完成

