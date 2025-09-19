#!/usr/bin/env python3
"""
测试所有选择器在debug_pages HTML文件中的存在性
"""
import re

def test_selectors_in_html(html_file_path):
    """测试HTML文件中的所有选择器"""

    # 定义所有选择器 - 与dom_parser.py保持一致
    selectors = {
        # 消息列表容器 - 按优先级排序，最稳定的放在前面
        'message_container': [
            '.conversation-list--jDBLEMex',       # 对话列表容器（最稳定）- 聊天页面特有
            '.rc-virtual-list',                   # 虚拟列表容器（稳定）- 消息列表使用
            'ul.ant-list-items'                   # ant design列表容器（备选）
        ],
        # 消息项
        'message_item': [
            'li.ant-list-item',                   # ant design列表项
            '.conversation-item--JReyg97P'        # 对话项容器（更具体）
        ],
        # 发送者名称
        'sender_name': [
            'a[href*="personal?userId="]',        # 用户个人页面链接
            '.nick--RyNYtDXM'                     # 昵称容器类
        ],
        # 输入框
        'input_box': [
            'textarea[placeholder*="请输入消息"]', # 消息输入框
            'textarea',                           # 通用文本域（备选）
            'input[type="text"]'                  # 文本输入框（备选）
        ],
        # 发送按钮
        'send_button': [
            'button[class*="send"]',              # 包含send的按钮
            'button span',                        # 包含span的按钮
            'button'                              # 通用按钮（备选）
        ],
        # 未读消息标识
        'unread_message': [
            '.ant-scroll-number-only-unit.current', # 当前未读数字
            '.ant-badge-count',                   # 徽章计数
            '.ant-scroll-number-only-unit'        # 数字滚动单元
        ]
    }

    # 读取HTML文件
    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except Exception as e:
        print(f"读取文件失败: {e}")
        return

    print(f"HTML文件大小: {len(html_content)} 字符")
    print("=" * 60)

    # 测试每个选择器组
    for selector_group, selector_list in selectors.items():
        print(f"\n🔍 测试选择器组: {selector_group}")
        print("-" * 40)

        for selector in selector_list:
            result = test_single_selector(html_content, selector)
            status = "✅ 存在" if result['found'] else "❌ 不存在"
            print(f"  {selector:<35} {status}")

            if result['found']:
                print(f"    匹配数量: {result['count']}")
                if result['sample']:
                    # 显示匹配内容的前100个字符
                    sample = result['sample'][:100] + "..." if len(result['sample']) > 100 else result['sample']
                    print(f"    示例: {sample}")

    # 额外测试一些常见元素
    print(f"\n🔍 额外测试常见元素")
    print("-" * 40)

    common_elements = [
        'div',
        'span',
        'img',
        'button',
        'input',
        'textarea',
        'a',
        'ul',
        'li'
    ]

    for element in common_elements:
        count = html_content.count(f'<{element}')
        print(f"  <{element}>标签数量: {count}")

def test_single_selector(html_content, selector):
    """测试单个选择器"""
    result = {
        'found': False,
        'count': 0,
        'sample': None
    }

    try:
        if selector.startswith('.'):
            # class选择器
            if '.' in selector[1:]:  # 多个类名，如 .class1.class2
                class_names = selector[1:].split('.')
                # 构建匹配包含所有类名的正则表达式
                class_pattern = '.*?'.join([re.escape(cls) for cls in class_names])
                patterns = [
                    rf'class="[^"]*{class_pattern}[^"]*"',
                    rf"class='[^']*{class_pattern}[^']*'"
                ]
            else:
                # 单个类名
                class_name = selector[1:].replace('--', '--')  # CSS模块化类名
                patterns = [
                    rf'class="[^"]*{re.escape(class_name)}[^"]*"',
                    rf"class='[^']*{re.escape(class_name)}[^']*'"
                ]
        elif selector.startswith('#'):
            # ID选择器
            id_name = selector[1:]
            patterns = [
                rf'id="{re.escape(id_name)}"',
                rf"id='{re.escape(id_name)}'"
            ]
        elif '[' in selector:
            # 属性选择器
            if 'href*=' in selector:
                # a[href*="personal?userId="]
                attr_value = selector.split('"')[1]
                patterns = [rf'href="[^"]*{re.escape(attr_value)}[^"]*"']
            elif 'placeholder*=' in selector:
                # textarea[placeholder*="请输入消息"]
                attr_value = selector.split('"')[1]
                patterns = [rf'placeholder="[^"]*{re.escape(attr_value)}[^"]*"']
            elif 'class*=' in selector:
                # button[class*="send"]
                attr_value = selector.split('"')[1]
                patterns = [rf'class="[^"]*{re.escape(attr_value)}[^"]*"']
            elif 'type=' in selector:
                # input[type="text"]
                attr_value = selector.split('"')[1]
                patterns = [rf'type="{re.escape(attr_value)}"']
            else:
                patterns = []
        elif ' ' in selector:
            # 复合选择器 (如 button span)
            if selector == 'button span':
                # 查找button标签中包含span的情况
                button_pattern = r'<button[^>]*>.*?<span.*?</button>'
                matches = re.findall(button_pattern, html_content, re.DOTALL)
                if matches:
                    result['found'] = True
                    result['count'] = len(matches)
                    result['sample'] = matches[0]
                return result
            else:
                patterns = []
        else:
            # 标签选择器或复杂选择器
            if selector == 'ul.ant-list-items':
                patterns = [r'<ul[^>]*class="[^"]*ant-list-items[^"]*"']
            elif selector == 'li.ant-list-item':
                patterns = [r'<li[^>]*class="[^"]*ant-list-item[^"]*"']
            else:
                patterns = [rf'<{re.escape(selector)}']

        # 执行匹配
        for pattern in patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            if matches:
                result['found'] = True
                result['count'] = len(matches)
                result['sample'] = matches[0]
                break

    except Exception as e:
        print(f"    测试选择器 {selector} 时出错: {e}")

    return result

if __name__ == "__main__":
    html_file = "/Users/jimmypan/git_repo/XianyuAutoAgent/cocs/debug_pages/debug_pages.html"
    test_selectors_in_html(html_file)