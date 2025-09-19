#!/usr/bin/env python3
"""
提取咸鱼IM页面的具体HTML结构
"""
import re
from bs4 import BeautifulSoup


def extract_body_content():
    """提取body内容"""

    print("🔍 提取咸鱼IM页面的body内容...")

    # 读取HTML文件
    try:
        with open('/Users/jimmypan/git_repo/XianyuAutoAgent/cocs/debug_pages/debug_pages.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
    except Exception as e:
        print(f"❌ 无法读取HTML文件: {e}")
        return

    # 解析HTML
    soup = BeautifulSoup(html_content, 'html.parser')

    # 提取body内容
    body = soup.find('body')
    if not body:
        print("❌ 未找到body元素")
        return

    print(f"📊 body内容长度: {len(str(body))} 字符")

    # 寻找联系人列表相关结构
    print("\n🎯 寻找联系人列表结构...")

    # 搜索包含"通知消息"的元素
    notification_elements = body.find_all(string=re.compile("通知消息"))
    print(f"找到 {len(notification_elements)} 个'通知消息'文本")

    if notification_elements:
        for i, elem in enumerate(notification_elements):
            print(f"\n--- 通知消息 {i+1} ---")
            analyze_element_structure(elem)

    # 搜索包含"光影租界"的元素
    guangying_elements = body.find_all(string=re.compile("光影租界"))
    print(f"\n找到 {len(guangying_elements)} 个'光影租界'文本")

    if guangying_elements:
        for i, elem in enumerate(guangying_elements):
            print(f"\n--- 光影租界 {i+1} ---")
            analyze_element_structure(elem)

    # 寻找所有conversation-item
    conversation_items = body.find_all(class_=re.compile("conversation-item"))
    print(f"\n🎯 找到 {len(conversation_items)} 个conversation-item元素")

    for i, item in enumerate(conversation_items[:3]):  # 只分析前3个
        print(f"\n--- conversation-item {i+1} ---")
        print(f"classes: {item.get('class')}")
        print(f"text: {item.get_text(strip=True)[:100]}...")

        # 查找子元素结构
        analyze_conversation_item_structure(item)

    # 寻找徽章元素
    print(f"\n🎯 寻找徽章元素...")
    badge_elements = body.find_all(class_=re.compile("badge|count"))
    print(f"找到 {len(badge_elements)} 个徽章元素")

    for i, badge in enumerate(badge_elements[:5]):
        print(f"  [{i+1}] {badge.name}.{'.'.join(badge.get('class', []))}: '{badge.get_text(strip=True)}'")


def analyze_element_structure(text_element):
    """分析文本元素的结构"""

    current = text_element.parent
    level = 0

    while current and level < 8:
        tag_info = current.name
        if current.get('class'):
            classes = current.get('class', [])
            tag_info += f".{'.'.join(classes)}"
        if current.get('id'):
            tag_info += f"#{current.get('id')}"

        # 获取元素的文本内容（只取前50个字符）
        element_text = current.get_text(strip=True)[:50]
        if element_text:
            tag_info += f" → '{element_text}...'"

        print(f"    {'  ' * level}├─ {tag_info}")

        current = current.parent
        level += 1


def analyze_conversation_item_structure(item):
    """分析conversation-item的内部结构"""

    print("  内部结构:")

    # 递归遍历所有子元素
    def walk_children(element, level=0):
        if level > 5:  # 限制深度
            return

        for child in element.children:
            if child.name:  # 只处理标签元素
                tag_info = child.name
                if child.get('class'):
                    classes = child.get('class', [])
                    tag_info += f".{'.'.join(classes)}"

                child_text = child.get_text(strip=True)
                if child_text and len(child_text) < 100:
                    tag_info += f" → '{child_text}'"
                elif child_text:
                    tag_info += f" → '{child_text[:50]}...'"

                print(f"    {'  ' * level}├─ {tag_info}")

                # 检查是否有特殊属性或内容
                if any(cls in ' '.join(child.get('class', [])) for cls in ['badge', 'count', 'avatar', 'name']):
                    print(f"    {'  ' * level}   ⭐ 重要元素")

                walk_children(child, level + 1)

    walk_children(item)


def generate_updated_selectors():
    """生成更新的选择器"""

    print("\n💡 生成更新的选择器配置:")

    selectors = {
        "登录检测": {
            "description": "判断是否已登录的选择器",
            "selectors": [
                "html.page-im",  # HTML根元素class
                ".conversation-item--JReyg97P",  # 联系人项目
                ".content-container--gIWgkNkm"  # 内容容器
            ]
        },
        "联系人列表": {
            "description": "联系人列表相关选择器",
            "selectors": [
                ".conversation-item--JReyg97P",  # 联系人项目
                ".sidebar-container--VCaOz9df",  # 侧边栏容器
                ".content-container--gIWgkNkm"  # 内容容器
            ]
        },
        "新消息标记": {
            "description": "新消息通知标记",
            "selectors": [
                ".ant-badge",  # Ant Design徽章
                ".ant-badge-count",  # 徽章计数
                ".ant-badge-count-sm",  # 小尺寸徽章计数
                "sup.ant-scroll-number"  # 滚动数字
            ]
        },
        "联系人信息": {
            "description": "联系人相关信息选择器",
            "selectors": [
                ".conversation-item--JReyg97P div",  # 联系人内部div
                "[class*='avatar']",  # 头像
                "[class*='user']"  # 用户相关
            ]
        }
    }

    for category, config in selectors.items():
        print(f"\n  📋 {category}:")
        print(f"      描述: {config['description']}")
        print(f"      选择器:")
        for selector in config['selectors']:
            print(f"        - '{selector}'")


if __name__ == "__main__":
    extract_body_content()
    generate_updated_selectors()