"""
设备检测工具模块

基于 user-agent 字符串检测访问设备类型
使用 user-agents 库进行解析和识别
"""

from functools import lru_cache
from typing import Dict, Optional
from user_agents import parse


@lru_cache(maxsize=1024)
def detect_device_type(ua_string: str) -> str:
    """
    检测设备类型

    Args:
        ua_string: User-Agent 字符串

    Returns:
        'mobile': 移动设备 (手机或平板)
        'desktop': 桌面设备

    默认返回 'desktop' 当:
    - ua_string 为空
    - 无法识别的设备
    - 解析出错
    """
    if not ua_string:
        return 'desktop'  # 默认桌面版

    try:
        ua = parse(ua_string)

        # 平板和手机都视为移动设备
        if ua.is_mobile or ua.is_tablet:
            return 'mobile'
        else:
            return 'desktop'
    except Exception as e:
        # 任何解析错误都默认返回桌面
        print(f"Error parsing UA: {e}")
        return 'desktop'


def get_device_info(ua_string: str) -> Dict:
    """
    获取详细的设备信息

    Args:
        ua_string: User-Agent 字符串

    Returns:
        包含设备详细信息的字典
    """
    if not ua_string:
        return {
            'type': 'desktop',
            'device': 'Unknown',
            'os': 'Unknown',
            'browser': 'Unknown',
            'is_mobile': False,
            'is_tablet': False,
            'is_pc': True,
            'os_version': 'Unknown',
            'browser_version': 'Unknown',
        }

    try:
        ua = parse(ua_string)

        # 构建版本字符串
        os_version = "Unknown"
        if ua.os.version_string:
            os_version = ua.os.version_string
        elif ua.os.major:
            os_version = f"{ua.os.major}"
            if ua.os.minor:
                os_version += f".{ua.os.minor}"

        browser_version = "Unknown"
        if ua.browser.version_string:
            browser_version = ua.browser.version_string
        elif ua.browser.major:
            browser_version = f"{ua.browser.major}"
            if ua.browser.minor:
                browser_version += f".{ua.browser.minor}"

        return {
            'type': 'mobile' if (ua.is_mobile or ua.is_tablet) else 'desktop',
            'device': ua.device.family or 'Unknown',
            'os': ua.os.family or 'Unknown',
            'browser': ua.browser.family or 'Unknown',
            'is_mobile': ua.is_mobile,
            'is_tablet': ua.is_tablet,
            'is_pc': ua.is_pc,
            'os_version': os_version,
            'browser_version': browser_version,
        }
    except Exception as e:
        print(f"Error getting device info: {e}")
        return {
            'type': 'desktop',
            'device': 'Unknown',
            'os': 'Unknown',
            'browser': 'Unknown',
            'is_mobile': False,
            'is_tablet': False,
            'is_pc': True,
            'os_version': 'Unknown',
            'browser_version': 'Unknown',
        }


def is_webview(ua_string: str) -> Optional[str]:
    """
    检测是否为应用内浏览器 (WebView)

    Args:
        ua_string: User-Agent 字符串

    Returns:
        应用名称 (如 'wechat', 'facebook') 或 None
    """
    if not ua_string:
        return None

    # WebView 应用指纹列表
    webview_apps = {
        'wechat': ['MicroMessenger'],
        'qq': ['QQ/', 'QQBrowser'],
        'alipay': ['Alipay'],
        'facebook': ['FBAN/FB4A', 'FBAV/'],
        'instagram': ['Instagram'],
        'line': ['Line'],
        'dingtalk': ['DingTalk', 'Dingtalk'],
        'baidu': ['baidubrowser', 'BaiduBrowser'],
        'uc': ['UCBrowser', 'UBrowser'],
    }

    for app_name, indicators in webview_apps.items():
        if any(indicator in ua_string for indicator in indicators):
            return app_name

    return None
