# User-Agent 检测边界情况处理指南

**文档类型**: Phase 0 研究补充文档
**分支**: `001-useragent-detection`
**日期**: 2026-01-01
**目的**: 详细的边界情况识别和处理策略

---

## 目录

1. [WebView 浏览器处理](#webview-浏览器处理)
2. [移动设备桌面模式](#移动设备桌面模式)
3. [隐私工具和 User-Agent 修改](#隐私工具和-user-agent-修改)
4. [缺失或无法识别的 User-Agent](#缺失或无法识别的-user-agent)
5. [爬虫和机器人](#爬虫和机器人)
6. [开发工具模拟](#开发工具模拟)
7. [综合处理策略](#综合处理策略)
8. [测试清单](#测试清单)

---

## WebView 浏览器处理

### 背景

WebView 是指在移动应用中集成的浏览器引擎。当用户通过微信、Facebook、抖音等应用内浏览器访问网站时，会发送包含应用标识符的特殊 User-Agent。

### 主要应用的 WebView 识别

#### 1. 中国主流应用

| 应用 | 识别关键词 | 优先级 | 推荐处理 |
|------|----------|--------|---------|
| **微信 (WeChat)** | `MicroMessenger`, `MMWEBID` | P0 | 移动版 + 特殊优化 |
| **支付宝 (Alipay)** | `AlipayClient`, `Alipay` | P1 | 移动版 |
| **QQ** | `QQ/`, `QQBrowser` | P1 | 移动版 |
| **抖音 (Douyin)** | `Douyin`, `ByteDance` | P1 | 移动版 |
| **微博 (Weibo)** | `Weibo`, `__weibo__` | P2 | 移动版 |
| **钉钉 (DingTalk)** | `DingTalk`, `Dingtalk` | P2 | 移动版 |
| **小红书** | `XHS` | P3 | 移动版 |

#### 2. 全球主流应用

| 应用 | 识别关键词 | 推荐处理 |
|------|----------|---------|
| **Facebook** | `FBAN`, `FBAV`, `FB4A` | 移动版 |
| **Instagram** | `Instagram`, `FBAV` | 移动版 |
| **Twitter** | `Twitter`, `Twitterbot` | 移动版 |
| **LinkedIn** | `LinkedInBot` | 移动版 |
| **TikTok** | `TikTok` | 移动版 |
| **Telegram** | `TelegramBot`, `Telegram` | 移动版 |
| **Messenger** | `FBAN`, `Messenger` | 移动版 |
| **WhatsApp** | `WhatsApp` | 移动版 |
| **Line** | `Line`, `LINE` | 移动版 |

### 典型 User-Agent 示例

#### 微信 WebView (iOS)

```
Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.16 (0x18001037) NetType/WIFI Language/zh_CN ABI/arm64
```

**识别特征**:
- 包含 `iPhone` (iOS 标识)
- 包含 `MicroMessenger/` (微信标识)
- `Mobile/` 标记 (移动设备)

#### 微信 WebView (Android)

```
Mozilla/5.0 (Linux; Android 11; MI 11) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.120 MQQBrowser/13.8 Mobile Safari/537.36 MMWEBID/8989 MicroMessenger/8.0.16 NetType/WIFI Language/zh_CN ABI/arm64
```

**识别特征**:
- 包含 `Android` (Android 标识)
- 包含 `MicroMessenger/` 或 `MMWEBID` (微信标识)
- `Mobile` 标记

#### Facebook WebView

```
Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36 FBAN/FB4A;FBAV/367.0.0.18.120;
```

**识别特征**:
- `FBAN/FB4A` 或 `FBAV` 标记 (Facebook 识别)
- `Mobile` 标记

### 检测实现

```python
# WebView 检测代码
WEBVIEW_APPS = {
    'wechat': ['MicroMessenger', 'MMWEBID'],
    'alipay': ['AlipayClient', 'Alipay'],
    'qq': ['QQ/', 'QQBrowser', 'QQNewsBrowser'],
    'facebook': ['FBAN', 'FBAV', 'FB4A'],
    'instagram': ['Instagram'],
    'twitter': ['Twitter'],
    'line': ['Line', 'LINE'],
    'telegram': ['TelegramBot', 'Telegram'],
    'dingtalk': ['DingTalk', 'Dingtalk'],
    'douyin': ['Douyin', 'ByteDance'],
    'weibo': ['Weibo', '__weibo__'],
    'whatsapp': ['WhatsApp'],
    'messenger': ['FBAN', 'Messenger'],
}

def detect_webview(user_agent):
    """
    检测 WebView 应用
    返回: (is_webview, app_name)
    """
    ua_upper = user_agent.upper()

    for app_name, indicators in WEBVIEW_APPS.items():
        for indicator in indicators:
            if indicator.upper() in ua_upper:
                return True, app_name

    return False, None

def detect_device_with_webview(user_agent):
    """
    综合 WebView 检测的设备检测
    """
    is_webview, app_name = detect_webview(user_agent)

    # WebView 应用内通常总是移动版本
    # (即使在特殊情况下)
    if is_webview:
        return {
            'device_type': 'mobile',
            'is_webview': True,
            'webview_app': app_name
        }

    # 非 WebView，使用标准检测
    from user_agents import parse
    ua = parse(user_agent)

    return {
        'device_type': 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop',
        'is_webview': False,
        'webview_app': None
    }
```

### WebView 特殊处理考虑

#### 1. 微信特殊需求

微信用户可能需要特殊的功能支持：
- **分享功能**: 微信 JSSDK 集成
- **支付功能**: 微信支付接口
- **扫一扫**: 二维码扫描
- **登录**: 微信 OAuth

```python
def should_enable_wechat_features(user_agent):
    """检查是否应启用微信特殊功能"""
    is_webview, app = detect_webview(user_agent)
    return app == 'wechat'
```

#### 2. 缓存策略

某些 WebView 有更激进的缓存行为：

```python
def get_cache_headers_for_webview(user_agent):
    """根据 WebView 类型返回适当的缓存头"""
    is_webview, app = detect_webview(user_agent)

    if app == 'wechat':
        # 微信对缓存敏感，使用较短的 TTL
        return {
            'Cache-Control': 'public, max-age=300',  # 5 分钟
            'Pragma': 'no-cache'
        }
    elif app == 'facebook':
        # Facebook 爬虫可能缓存预览，较长 TTL
        return {
            'Cache-Control': 'public, max-age=3600'  # 1 小时
        }
    else:
        # 默认缓存策略
        return {
            'Cache-Control': 'public, max-age=1800'  # 30 分钟
        }
```

#### 3. 加载和性能优化

```python
def get_performance_hints_for_webview(user_agent):
    """为 WebView 返回性能优化提示"""
    is_webview, app = detect_webview(user_agent)

    hints = {}

    if app == 'wechat':
        # 微信浏览器在某些设备上性能较弱
        hints['disable_animations'] = True
        hints['reduce_image_quality'] = True
        hints['lazy_load_resources'] = True

    elif app in ['alipay', 'qq']:
        # 支付宝和 QQ 通常性能较好
        hints['disable_animations'] = False
        hints['reduce_image_quality'] = False

    return hints
```

---

## 移动设备桌面模式

### 问题描述

现代移动浏览器提供"请求桌面站点"或"Desktop Mode"功能。当用户启用这个功能时：

1. User-Agent 会被修改（通常删除 "Mobile" 标记）
2. 视口宽度增加
3. 但实际设备仍然是移动设备

### 识别方法

#### 1. User-Agent 特征分析

**移动模式**:
```
Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) ... Mobile/15E148 Safari/604.1
```

**桌面请求模式** (iOS Safari):
```
Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) ... Safari/604.1
# 注意: "Mobile/15E148" 被移除
```

**Android Chrome 桌面请求**:
```
# 移动模式
Mozilla/5.0 (Linux; Android 11) ... Chrome/91.0.4472.120 Mobile Safari/537.36

# 桌面请求模式
Mozilla/5.0 (Linux; Android 11) ... Chrome/91.0.4472.120 Safari/537.36
# 注意: "Mobile" 被移除
```

#### 2. 识别逻辑

```python
def detect_mobile_requesting_desktop(user_agent):
    """
    检测移动设备是否请求了桌面版本
    返回: True 如果是移动设备请求桌面，否则 False
    """
    ua_lower = user_agent.lower()

    # 检测移动操作系统
    is_ios = 'iphone' in ua_lower or 'ipod' in ua_lower
    is_android = 'android' in ua_lower

    # 检测 Mobile 标记
    has_mobile_mark = 'mobile' in ua_lower

    # 移动 OS 但没有 Mobile 标记 = 用户请求了桌面版本
    is_mobile_requesting_desktop = (is_ios or is_android) and not has_mobile_mark

    return is_mobile_requesting_desktop

def detect_device_respecting_user_choice(user_agent):
    """
    检测设备类型，尊重用户的"请求桌面站点"选择
    """
    if detect_mobile_requesting_desktop(user_agent):
        # 用户明确请求了桌面版本
        return {
            'device_type': 'desktop',
            'user_preference': 'desktop',
            'actual_device': 'mobile'  # 实际设备仍然是移动
        }

    # 标准检测
    from user_agents import parse
    ua = parse(user_agent)

    return {
        'device_type': 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop',
        'user_preference': None,
        'actual_device': 'mobile' if ua.is_mobile else 'desktop'
    }
```

#### 3. 其他识别信号

虽然不如 User-Agent 可靠，但可以结合使用：

```python
def get_additional_device_hints(request):
    """
    获取其他设备相关的请求头
    """
    hints = {
        'sec_ch_ua_mobile': request.headers.get('Sec-CH-UA-Mobile'),
        # ?1 = 移动设备
        # ?0 = 桌面设备

        'viewport_width': request.headers.get('Viewport-Width'),
        # 大多数浏览器不发送，但某些特殊情况会有

        'accept_language': request.headers.get('Accept-Language'),
        # 某些移动浏览器可能有不同的语言首选项

        'accept': request.headers.get('Accept'),
        # 某些 WebView 可能有不同的 Accept 头
    }

    return hints

def comprehensive_device_detection(request):
    """
    综合多个信号的设备检测
    """
    user_agent = request.headers.get('User-Agent', '')

    # 第一层: User-Agent 检测
    device_type = detect_device_respecting_user_choice(user_agent)['device_type']

    # 第二层: 其他信号验证
    hints = get_additional_device_hints(request)

    # 如果有 Sec-CH-UA-Mobile 头，可以验证
    if hints['sec_ch_ua_mobile'] == '?1':
        # 明确的移动设备信号
        if device_type == 'desktop' and user_agent:
            # 可能是用户请求的桌面版本
            log.info(f"Mobile device explicitly requesting desktop")

    return device_type
```

### 处理策略

| 场景 | User-Agent 特征 | 推荐处理 |
|------|---------------|---------|
| iOS Safari 桌面请求 | "iPhone" + 无 Mobile | 返回桌面版本 |
| Android Chrome 桌面请求 | "Android" + 无 Mobile | 返回桌面版本 |
| iPad 正常模式 | "iPad" + 无 Mobile | 返回移动版本 (平板默认) |
| iPad Pro 大屏 | "iPad" + 屏幕宽度 > 1024px | 可选返回桌面 |

---

## 隐私工具和 User-Agent 修改

### 常见隐私工具

| 工具 | 影响 | 处理方式 |
|------|------|---------|
| uBlock Origin | 可能自定义规则修改 UA | 接受修改后的 UA |
| Privacy Badger | 不修改 UA | 无影响 |
| Firefox 隐私增强 | "Resist Fingerprinting" 模式 | 接受通用 UA |
| DuckDuckGo 隐私 | 某些版本可能修改 | 接受修改 |
| VPN 客户端 | 可能修改或隐藏 | 尊重用户隐私 |
| User-Agent Switcher | 完全更换 UA | 按修改后的 UA 处理 |

### 修改的 User-Agent 特征

```python
def is_likely_modified_ua(user_agent):
    """
    启发式检测可能被隐私工具修改的 User-Agent
    """
    if not user_agent:
        return False

    suspicious_patterns = [
        'Mozilla/0.0',      # 明显虚假
        'Mozilla/6.0',      # 不存在的版本
        'Mozilla/7.0',      # 不存在的版本
        'Mozilla/9.0',      # 不存在的版本
    ]

    ua_upper = user_agent.upper()
    for pattern in suspicious_patterns:
        if pattern in ua_upper:
            return True

    # Firefox "Resist Fingerprinting" 通常会使用通用 UA
    if 'Firefox' in user_agent and 'Linux x86_64' in user_agent:
        # 这通常表示启用了 Resist Fingerprinting
        return True

    return False

def handle_modified_ua(user_agent):
    """
    处理可能被修改的 User-Agent
    """
    if is_likely_modified_ua(user_agent):
        log.info(f"Potentially modified UA detected: {user_agent}")

        # 尊重用户隐私，但使用保守的默认值
        # (倾向于显示桌面版本，这样功能最完整)
        return 'desktop'

    # 标准处理
    from user_agents import parse
    ua = parse(user_agent)
    return 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop'
```

### 推荐策略

1. **尊重隐私**: 不要尝试通过其他指纹识别技术绕过隐私工具
2. **保守默认**: 无法确定时，显示功能最完整的桌面版本
3. **用户控制**: 提供手动切换选项，让用户自己选择
4. **日志记录**: 记录可能被修改的 UA，用于分析

---

## 缺失或无法识别的 User-Agent

### 典型场景

#### 1. 完全缺失

```
GET / HTTP/1.1
Host: example.com
# User-Agent 头完全不存在
```

**可能原因**:
- 自定义客户端应用
- 网络代理删除了 User-Agent
- 隐私工具移除了识别信息

#### 2. 为空

```
User-Agent:
```

**可能原因**:
- 客户端实现错误
- 网络过滤器清理

#### 3. 无法识别但有效格式

```
User-Agent: CustomApp/1.0 (compatible)
User-Agent: MyBrowser/2.5
```

**特征**:
- 符合 User-Agent 格式
- 但库无法识别

#### 4. 格式完全不正确

```
User-Agent: xyz123abc
User-Agent: Mozilla/0.0
User-Agent: !!!invalid!!!
```

### 检测和处理

```python
def check_user_agent_quality(user_agent):
    """
    评估 User-Agent 字符串的质量
    返回: ('good'/'fair'/'poor', reason)
    """
    if not user_agent:
        return 'poor', 'missing'

    if not user_agent.strip():
        return 'poor', 'empty'

    quality_score = 0

    # 检查格式
    if user_agent.startswith('Mozilla/'):
        quality_score += 40

    # 检查长度
    if len(user_agent) > 20:
        quality_score += 20
    else:
        return 'poor', 'too_short'

    # 检查已知的浏览器标记
    known_browsers = ['Chrome', 'Firefox', 'Safari', 'Edge', 'Opera', 'MSIE']
    if any(browser in user_agent for browser in known_browsers):
        quality_score += 40

    if quality_score >= 80:
        return 'good', 'recognizable'
    elif quality_score >= 40:
        return 'fair', 'incomplete'
    else:
        return 'poor', 'unrecognizable'

def detect_device_with_quality_check(user_agent):
    """
    根据 UA 质量进行检测
    """
    quality, reason = check_user_agent_quality(user_agent)

    if quality == 'good':
        # 有效的 User-Agent，使用标准检测
        from user_agents import parse
        try:
            ua = parse(user_agent)
            return 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop'
        except:
            return 'desktop'

    elif quality == 'fair':
        # 格式可能有问题，但尝试检测
        from user_agents import parse
        try:
            ua = parse(user_agent)
            if ua.browser.family or ua.os.family:
                return 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop'
        except:
            pass
        # 如果仍然无法检测，使用保守默认
        return 'desktop'

    else:  # quality == 'poor'
        # 无法识别，使用默认值
        log.warning(f"Poor quality UA: {user_agent} (reason: {reason})")
        return 'desktop'  # FR-010: 默认桌面版本
```

### 处理检查清单

- [x] 检查 User-Agent 头是否存在
- [x] 检查是否为空字符串
- [x] 检查格式是否合理
- [x] 尝试解析
- [x] 解析失败时使用默认桌面版本
- [x] 记录无法识别的 UA 用于分析
- [x] 定期更新库以支持新设备

---

## 爬虫和机器人

### 识别

爬虫的 User-Agent 通常包含标识词：

```python
BOT_PATTERNS = {
    # 搜索引擎爬虫
    'googlebot': ['Googlebot', 'AdsBot-Google', 'Mediapartners-Google'],
    'bingbot': ['bingbot', 'msnbot', 'ms bot'],
    'baiduspider': ['Baiduspider'],
    'yandex': ['YandexBot'],
    'duckduckgo': ['DuckDuckBot'],
    'sogou': ['Sogou'],

    # 社交媒体爬虫
    'facebook': ['facebookexternalhit'],
    'twitter': ['Twitterbot'],
    'linkedin': ['LinkedInBot'],
    'pinterest': ['PinterestBot'],
    'instagram': ['InstagramBot'],

    # 监控和分析
    'uptime': ['UptimeRobot', 'Pingdom'],
    'monitoring': ['Monitor', 'Crawler'],

    # 开发者工具
    'curl': ['curl'],
    'wget': ['wget'],
    'python': ['python-requests', 'Python-Requests'],
}

def detect_bot(user_agent):
    """
    检测是否为爬虫
    返回: (is_bot, bot_type)
    """
    ua_upper = user_agent.upper()

    for bot_type, patterns in BOT_PATTERNS.items():
        for pattern in patterns:
            if pattern.upper() in ua_upper:
                return True, bot_type

    return False, None
```

### 处理策略

| 爬虫类型 | 处理方式 | 理由 |
|---------|--------|------|
| Google Bot | 返回有效 HTML | SEO 索引 |
| Bing Bot | 返回有效 HTML | SEO 索引 |
| 社交媒体爬虫 | 返回有效 HTML + 元标签 | 生成预览 |
| 监控工具 | 返回 200 OK | 确认可用性 |
| 自动化工具 | 返回有效 HTML | 允许自动化 |

### 代码示例

```python
def handle_bot_request(user_agent, request):
    """
    处理爬虫请求
    """
    is_bot, bot_type = detect_bot(user_agent)

    if not is_bot:
        # 普通用户，标准检测
        from user_agents import parse
        ua = parse(user_agent)
        return 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop'

    # 爬虫特殊处理
    log.info(f"Bot detected: {bot_type}")

    # 不同爬虫使用不同策略
    if bot_type == 'googlebot':
        # Google Bot 有移动和桌面版本
        if 'mobile' in user_agent.lower():
            return 'mobile'  # Google 移动爬虫
        else:
            return 'desktop'  # Google 桌面爬虫

    elif bot_type in ['bingbot', 'baiduspider']:
        # 搜索引擎爬虫
        return 'desktop'  # 返回完整的桌面版本

    elif bot_type in ['facebook', 'twitter', 'linkedin']:
        # 社交媒体爬虫
        # 返回包含 Open Graph 元标签的页面
        return 'social_preview'

    elif bot_type == 'uptime':
        # 监控工具：只需要 200 OK
        return 'monitoring'

    else:
        # 其他爬虫：返回桌面版本
        return 'desktop'
```

---

## 开发工具模拟

### 特点

开发者通过浏览器 DevTools 模拟移动设备时，User-Agent 会被修改为有效的、格式正确的字符串。

### 常见 DevTools 模拟

| 工具 | 特征 | 处理方式 |
|------|------|---------|
| Chrome DevTools | 使用有效的设备 UA | 按修改后 UA 处理 |
| Firefox Responsive | 使用有效的设备 UA | 按修改后 UA 处理 |
| Safari Web Inspector | 使用有效的设备 UA | 按修改后 UA 处理 |

### 推荐处理

```python
def handle_devtools_simulation(user_agent):
    """
    处理 DevTools 设备模拟

    由于 DevTools 使用有效的 UA，无需特殊处理
    直接按修改后的 UA 进行标准检测
    """
    from user_agents import parse

    try:
        ua = parse(user_agent)
        return 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop'
    except:
        return 'desktop'
```

---

## 综合处理策略

### 优先级决策树

```
User-Agent 检测决策树
│
├─ User-Agent 存在? ─ 否 ──> 返回 'desktop' (FR-010)
│
└─ 是 ──> User-Agent 为空? ─ 是 ──> 返回 'desktop'
            │
            └─ 否 ──> 是爬虫? ─ 是 ──> 特殊处理 (不返回 UI)
                       │
                       └─ 否 ──> 是 WebView? ─ 是 ──> 返回 'mobile' (记录应用)
                                  │
                                  └─ 否 ──> 质量检查 ──> 格式无效? ─ 是 ──> 返回 'desktop'
                                                        │
                                                        └─ 否 ──> 标准 UA 检测
                                                                  ├─ 移动设备桌面请求? ──> 返回 'desktop'
                                                                  ├─ 移动设备? ──> 返回 'mobile'
                                                                  └─ 桌面设备? ──> 返回 'desktop'
```

### 完整实现

```python
# app/utils/device_detector.py

from user_agents import parse
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)

# WebView 应用标识
WEBVIEW_APPS = {
    'wechat': ['MicroMessenger', 'MMWEBID'],
    'alipay': ['AlipayClient'],
    'qq': ['QQ/', 'QQBrowser'],
    'facebook': ['FBAN', 'FBAV'],
    'instagram': ['Instagram'],
    'line': ['Line'],
    'telegram': ['TelegramBot'],
    'dingtalk': ['DingTalk'],
    'douyin': ['Douyin', 'ByteDance'],
    'weibo': ['Weibo'],
}

# 爬虫标识
BOT_PATTERNS = {
    'googlebot': ['Googlebot'],
    'bingbot': ['bingbot', 'msnbot'],
    'baiduspider': ['Baiduspider'],
    'yandex': ['YandexBot'],
    'monitoring': ['UptimeRobot', 'Pingdom'],
    'social': ['facebookexternalhit', 'Twitterbot', 'LinkedInBot'],
}

class DeviceDetector:
    """综合的设备检测器"""

    @staticmethod
    def detect(user_agent, request_headers=None):
        """
        执行完整的设备检测

        返回:
        {
            'device_type': 'mobile'/'desktop'/'bot',
            'is_webview': bool,
            'webview_app': str | None,
            'is_bot': bool,
            'bot_type': str | None,
            'browser': str,
            'os': str,
            'confidence': float,
            'metadata': dict  # 额外信息
        }
        """

        # 1. 检查 User-Agent 存在
        if not user_agent or not user_agent.strip():
            logger.warning("Missing User-Agent")
            return DeviceDetector._create_response(
                'desktop', False, None, False, None,
                'Unknown', 'Unknown', 0.0, {'reason': 'missing'}
            )

        # 2. 检查是否为爬虫
        is_bot, bot_type = DeviceDetector._is_bot(user_agent)
        if is_bot:
            logger.info(f"Bot detected: {bot_type}")
            return DeviceDetector._create_response(
                'bot', False, None, True, bot_type,
                bot_type, 'Unknown', 0.95, {'reason': 'bot'}
            )

        # 3. 检查是否为 WebView
        is_webview, webview_app = DeviceDetector._is_webview(user_agent)

        # 4. 检查 UA 质量
        quality = DeviceDetector._check_ua_quality(user_agent)
        if quality == 'poor':
            logger.warning(f"Poor quality UA: {user_agent}")
            return DeviceDetector._create_response(
                'desktop', is_webview, webview_app, False, None,
                'Unknown', 'Unknown', 0.2, {'reason': 'poor_quality'}
            )

        # 5. 解析 User-Agent
        try:
            ua = parse(user_agent)
        except Exception as e:
            logger.error(f"Failed to parse UA: {e}")
            return DeviceDetector._create_response(
                'desktop', is_webview, webview_app, False, None,
                'Unknown', 'Unknown', 0.1, {'reason': 'parse_error'}
            )

        # 6. 检查移动设备请求桌面
        if DeviceDetector._is_mobile_requesting_desktop(user_agent):
            logger.info("Mobile device requesting desktop")
            return DeviceDetector._create_response(
                'desktop', is_webview, webview_app, False, None,
                ua.browser.family or 'Unknown',
                ua.os.family or 'Unknown',
                0.85, {'reason': 'mobile_requesting_desktop'}
            )

        # 7. 标准设备检测
        device_type = 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop'

        # WebView 内的设备总是视为移动
        if is_webview:
            device_type = 'mobile'

        return DeviceDetector._create_response(
            device_type, is_webview, webview_app, False, None,
            ua.browser.family or 'Unknown',
            ua.os.family or 'Unknown',
            0.85 if quality == 'good' else 0.70,
            {'reason': 'standard_detection'}
        )

    @staticmethod
    def _is_webview(user_agent):
        """检测 WebView"""
        ua_upper = user_agent.upper()
        for app, indicators in WEBVIEW_APPS.items():
            for ind in indicators:
                if ind.upper() in ua_upper:
                    return True, app
        return False, None

    @staticmethod
    def _is_bot(user_agent):
        """检测爬虫"""
        ua_upper = user_agent.upper()
        for bot_type, patterns in BOT_PATTERNS.items():
            for pattern in patterns:
                if pattern.upper() in ua_upper:
                    return True, bot_type
        return False, None

    @staticmethod
    def _is_mobile_requesting_desktop(user_agent):
        """检测移动设备请求桌面"""
        ua_lower = user_agent.lower()
        is_mobile_os = 'android' in ua_lower or 'iphone' in ua_lower
        has_mobile_mark = 'mobile' in ua_lower
        return is_mobile_os and not has_mobile_mark

    @staticmethod
    def _check_ua_quality(user_agent):
        """检查 UA 质量"""
        score = 0

        if user_agent.startswith('Mozilla/'):
            score += 40

        if len(user_agent) > 20:
            score += 20

        known_browsers = ['Chrome', 'Firefox', 'Safari', 'Edge', 'Opera']
        if any(b in user_agent for b in known_browsers):
            score += 40

        if score >= 80:
            return 'good'
        elif score >= 40:
            return 'fair'
        else:
            return 'poor'

    @staticmethod
    def _create_response(device_type, is_webview, webview_app, is_bot, bot_type,
                        browser, os_name, confidence, metadata):
        """创建返回对象"""
        return {
            'device_type': device_type,
            'is_webview': is_webview,
            'webview_app': webview_app,
            'is_bot': is_bot,
            'bot_type': bot_type,
            'browser': browser,
            'os': os_name,
            'confidence': confidence,
            'metadata': metadata
        }
```

---

## 测试清单

### 单元测试

- [ ] 测试 iOS 移动设备 (iPhone)
- [ ] 测试 iOS 平板 (iPad)
- [ ] 测试 Android 手机
- [ ] 测试 Android 平板
- [ ] 测试 iOS 请求桌面
- [ ] 测试 Android 请求桌面
- [ ] 测试微信 WebView (iOS)
- [ ] 测试微信 WebView (Android)
- [ ] 测试 Facebook WebView
- [ ] 测试其他 WebView (QQ, Alipay, Douyin)
- [ ] 测试 Google Bot (桌面)
- [ ] 测试 Google Bot (移动)
- [ ] 测试 Bing Bot
- [ ] 测试缺失 User-Agent
- [ ] 测试空 User-Agent
- [ ] 测试无法识别的 UA
- [ ] 测试修改后的 UA
- [ ] 测试 Chrome 桌面
- [ ] 测试 Safari 桌面
- [ ] 测试 Firefox 桌面

### 集成测试

- [ ] 从真实 iOS 设备访问
- [ ] 从真实 Android 设备访问
- [ ] 通过微信访问
- [ ] 使用 Chrome DevTools 模拟移动
- [ ] 使用 Safari 响应式设计模式
- [ ] 测试缓存行为
- [ ] 测试 API 响应
- [ ] 测试前后端一致性

### 性能测试

- [ ] 单个 UA 解析性能 (< 1ms)
- [ ] 缓存后解析性能 (< 0.3ms)
- [ ] 1000 个不同 UA 的解析时间
- [ ] 内存占用
- [ ] CPU 使用率

---

## 参考资源

### User-Agent 数据库
- [What is my Browser](https://www.whatismybrowser.com/)
- [MDN User-Agent](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/User-Agent)

### 标准和规范
- [RFC 7231 User-Agent](https://tools.ietf.org/html/rfc7231#section-5.5.3)
- [Sec-CH-UA 标准](https://wicg.github.io/ua-client-hints/)

### 工具和库
- [user-agents](https://github.com/selwin/python-user-agents)
- [ua-parser](https://github.com/ua-parser/uap-python)
- [WURFL](https://www.scientiamobile.com/)

---

**文档完成时间**: 2026-01-01
**版本**: 1.0
**状态**: 完成
