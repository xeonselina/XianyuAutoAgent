#!/usr/bin/env python3
"""
分析咸鱼IM页面HTML，找出登录判断和新消息识别的patterns
"""
import re
import json
from bs4 import BeautifulSoup
from collections import defaultdict


def analyze_im_page():
    """分析IM页面HTML结构"""

    print("🔍 开始分析咸鱼IM页面HTML结构...")

    # 读取HTML文件
    try:
        with open('/Users/jimmypan/git_repo/XianyuAutoAgent/cocs/debug_pages/debug_pages.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
    except Exception as e:
        print(f"❌ 无法读取HTML文件: {e}")
        return

    print(f"📊 HTML文件大小: {len(html_content)} 字符")

    # 使用BeautifulSoup解析
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. 寻找联系人相关的pattern
    print("\n🎯 1. 分析联系人列表patterns...")
    analyze_contact_patterns(soup, html_content)

    # 2. 寻找消息相关的pattern
    print("\n🎯 2. 分析消息patterns...")
    analyze_message_patterns(soup, html_content)

    # 3. 寻找新消息标记patterns
    print("\n🎯 3. 分析新消息标记patterns...")
    analyze_notification_patterns(soup, html_content)

    # 4. 寻找登录状态判断patterns
    print("\n🎯 4. 分析登录状态patterns...")
    analyze_login_patterns(soup, html_content)


def analyze_contact_patterns(soup, html_content):
    """分析联系人列表patterns"""

    # 搜索包含联系人名字的元素
    target_names = ['光影租界', '火山谦虚的山茶', '要好货1818', '消息通知']

    contact_info = {}

    for name in target_names:
        print(f"\n🔍 搜索联系人: {name}")

        # 在HTML中搜索这个名字
        pattern = re.escape(name)
        matches = list(re.finditer(pattern, html_content))

        if matches:
            print(f"  找到 {len(matches)} 个匹配")

            for i, match in enumerate(matches[:2]):  # 只分析前2个匹配
                start_pos = max(0, match.start() - 500)
                end_pos = min(len(html_content), match.end() + 500)
                context = html_content[start_pos:end_pos]

                # 分析周围的HTML结构
                analyze_surrounding_structure(context, name, match.start() - start_pos)
        else:
            print(f"  ❌ 未找到")

    # 寻找可能的联系人列表容器
    print(f"\n🔍 寻找联系人列表容器...")

    # 常见的联系人列表选择器
    potential_containers = [
        'div[class*="contact"]',
        'div[class*="conversation"]',
        'div[class*="chat"]',
        'ul[class*="list"]',
        'div[class*="sidebar"]',
        '[class*="user"]'
    ]

    for selector in potential_containers:
        elements = soup.select(selector)
        if elements:
            print(f"  📋 {selector}: 找到 {len(elements)} 个元素")
            for i, elem in enumerate(elements[:3]):
                print(f"    [{i+1}] class='{elem.get('class', [])}' tag='{elem.name}'")


def analyze_surrounding_structure(context, name, name_pos):
    """分析名字周围的HTML结构"""

    print(f"\n    📍 分析 '{name}' 周围的结构:")

    # 解析这一段HTML
    try:
        soup = BeautifulSoup(context, 'html.parser')

        # 找到包含名字的元素
        elements_with_name = soup.find_all(string=re.compile(re.escape(name)))

        for elem_text in elements_with_name[:1]:  # 只分析第一个
            parent = elem_text.parent

            # 向上查找包含元素的结构
            current = parent
            level = 0
            while current and level < 5:
                tag_info = f"{current.name}"
                if current.get('class'):
                    tag_info += f".{'.'.join(current.get('class', []))}"
                if current.get('id'):
                    tag_info += f"#{current.get('id')}"

                print(f"      {'  ' * level}├─ {tag_info}")

                # 检查是否有兄弟元素（可能是其他联系人）
                if level == 2:  # 在适当层级检查兄弟元素
                    siblings = current.find_next_siblings()
                    if siblings:
                        print(f"      {'  ' * level}   兄弟元素: {len(siblings)} 个")

                current = current.parent
                level += 1

    except Exception as e:
        print(f"      ⚠️ 解析错误: {e}")


def analyze_message_patterns(soup, html_content):
    """分析消息patterns"""

    # 寻找可能的消息容器
    message_selectors = [
        'div[class*="message"]',
        'div[class*="conversation"]',
        'li[class*="item"]',
        '[class*="bubble"]',
        '[class*="content"]'
    ]

    for selector in message_selectors:
        elements = soup.select(selector)
        if elements:
            print(f"  📝 {selector}: 找到 {len(elements)} 个元素")

            # 分析前几个元素的结构
            for i, elem in enumerate(elements[:3]):
                classes = elem.get('class', [])
                text_content = elem.get_text(strip=True)[:50]

                print(f"    [{i+1}] classes: {classes}")
                if text_content:
                    print(f"         text: '{text_content}...'")


def analyze_notification_patterns(soup, html_content):
    """分析新消息通知patterns"""

    # 寻找徽章、红点、数字等新消息标记
    notification_patterns = [
        # 徽章相关
        r'badge[^"]*',
        r'count[^"]*',
        r'unread[^"]*',
        r'notification[^"]*',
        # 数字相关
        r'(\d+)',
        # 红点相关
        r'dot[^"]*',
        r'indicator[^"]*'
    ]

    print("  🔔 搜索新消息标记patterns:")

    # 搜索class名称patterns
    class_pattern = r'class="([^"]*)"'
    all_classes = re.findall(class_pattern, html_content)

    # 统计相关的class
    relevant_classes = defaultdict(int)

    for class_str in all_classes:
        classes = class_str.split()
        for cls in classes:
            # 检查是否包含通知相关关键词
            cls_lower = cls.lower()
            if any(keyword in cls_lower for keyword in ['badge', 'count', 'unread', 'dot', 'notification', 'indicator', 'num']):
                relevant_classes[cls] += 1

    # 输出相关类名
    if relevant_classes:
        print("    📊 发现的通知相关class:")
        for cls, count in sorted(relevant_classes.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"      {cls}: {count}次")

    # 搜索特定的徽章元素
    badge_elements = soup.select('[class*="badge"], [class*="count"], [class*="unread"], [class*="dot"]')
    print(f"    🎯 徽章类元素: {len(badge_elements)} 个")

    for i, elem in enumerate(badge_elements[:5]):
        classes = elem.get('class', [])
        text = elem.get_text(strip=True)
        print(f"      [{i+1}] {elem.name}.{'.'.join(classes)}: '{text}'")


def analyze_login_patterns(soup, html_content):
    """分析登录状态判断patterns"""

    print("  🔐 分析登录状态指标:")

    # 检查页面标题和基本信息
    title = soup.find('title')
    if title:
        print(f"    📄 页面标题: '{title.get_text(strip=True)}'")

    # 检查HTML根元素的class
    html_elem = soup.find('html')
    if html_elem:
        html_classes = html_elem.get('class', [])
        print(f"    🏷️ HTML class: {html_classes}")

    # 寻找用户信息相关元素
    user_indicators = [
        '[class*="user"]',
        '[class*="avatar"]',
        '[class*="profile"]',
        '[class*="account"]'
    ]

    for selector in user_indicators:
        elements = soup.select(selector)
        if elements:
            print(f"    👤 {selector}: {len(elements)} 个元素")

    # 检查是否有登录相关的元素
    login_indicators = soup.select('[class*="login"], [class*="signin"], [class*="auth"]')
    print(f"    🔑 登录相关元素: {len(login_indicators)} 个")

    # 检查页面URL模式（从meta或script中推断）
    url_patterns = re.findall(r'https?://[^"\'>\s]+', html_content)
    im_urls = [url for url in url_patterns if 'im' in url or 'chat' in url or 'message' in url]
    print(f"    🌐 IM相关URL: {len(im_urls)} 个")


def generate_selectors():
    """基于分析结果生成选择器建议"""

    print("\n💡 基于分析生成的选择器建议:")

    suggestions = {
        "登录检测": [
            "html.page-im",  # 基于HTML class
            "[class*='conversation']",
            "[class*='contact']",
            "[class*='user']"
        ],
        "联系人列表": [
            "div[class*='contact']",
            "div[class*='conversation']",
            "ul[class*='list']",
            "li[class*='item']"
        ],
        "新消息标记": [
            "[class*='badge']",
            "[class*='count']",
            "[class*='unread']",
            "[class*='dot']",
            "[class*='notification']"
        ],
        "消息内容": [
            "div[class*='message']",
            "div[class*='content']",
            "[class*='bubble']"
        ]
    }

    for category, selectors in suggestions.items():
        print(f"\n  📋 {category}:")
        for selector in selectors:
            print(f"    - {selector}")


if __name__ == "__main__":
    analyze_im_page()
    generate_selectors()