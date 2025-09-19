#!/usr/bin/env python3
"""
分析静态HTML文件与实际页面的差异，找出为什么Playwright找不到元素
"""
import re
from datetime import datetime


def analyze_selector_differences():
    """分析选择器差异"""

    # 测试的选择器
    selectors = {
        'message_container': [
            '.conversation-list--jDBLEMex',
            '.rc-virtual-list',
            'ul.ant-list-items'
        ],
        'message_item': [
            'li.ant-list-item',
            '.conversation-item--JReyg97P'
        ]
    }

    # 读取静态HTML
    try:
        with open('/Users/jimmypan/git_repo/XianyuAutoAgent/cocs/debug_pages/debug_pages.html', 'r', encoding='utf-8') as f:
            static_html = f.read()
    except Exception as e:
        print(f"❌ 无法读取静态HTML: {e}")
        return

    print("🔍 静态HTML分析")
    print("=" * 60)
    print(f"📊 文件大小: {len(static_html)} 字符")

    # 分析每个选择器组
    for group_name, selector_list in selectors.items():
        print(f"\n🎯 {group_name} 选择器组分析")
        print("-" * 40)

        for selector in selector_list:
            analyze_single_selector(static_html, selector)

    # 分析可能的问题
    print(f"\n🔧 潜在问题分析")
    print("-" * 40)
    analyze_potential_issues(static_html)


def analyze_single_selector(html_content, selector):
    """分析单个选择器"""
    print(f"\n📍 分析选择器: {selector}")

    if selector.startswith('.'):
        # CSS类选择器
        class_name = selector[1:]

        # 查找包含该类名的所有元素
        if '.' in class_name:  # 多类名，如 .class1.class2
            class_parts = class_name.split('.')
            # 构建正则表达式，查找同时包含所有类名的元素
            pattern = r'class="[^"]*'
            for part in class_parts:
                pattern += f'[^"]*{re.escape(part)}[^"]*'
            pattern += r'"'
        else:
            # 单类名
            pattern = rf'class="[^"]*{re.escape(class_name)}[^"]*"'

        matches = re.findall(pattern, html_content)
        print(f"  ✅ 找到 {len(matches)} 个匹配")

        if matches:
            for i, match in enumerate(matches[:3]):  # 只显示前3个
                print(f"    {i+1}. {match}")

                # 查找完整的元素标签
                # 向前查找标签开始
                match_pos = html_content.find(match)
                tag_start = html_content.rfind('<', 0, match_pos)
                tag_end = html_content.find('>', match_pos) + 1
                full_tag = html_content[tag_start:tag_end]

                print(f"       完整标签: {full_tag[:100]}...")

                # 检查元素的显示状态
                check_element_visibility(html_content, match_pos)
        else:
            print(f"  ❌ 未找到匹配")
            # 尝试模糊匹配
            fuzzy_matches = find_fuzzy_matches(html_content, class_name)
            if fuzzy_matches:
                print(f"  🔍 可能的相似类名:")
                for fuzzy in fuzzy_matches[:5]:
                    print(f"    - {fuzzy}")

    elif selector.startswith('ul.'):
        # ul标签+类名
        class_name = selector[3:]  # 去掉 'ul.'
        pattern = rf'<ul[^>]*class="[^"]*{re.escape(class_name)}[^"]*"[^>]*>'
        matches = re.findall(pattern, html_content)
        print(f"  ✅ 找到 {len(matches)} 个ul.{class_name}元素")

        for i, match in enumerate(matches):
            print(f"    {i+1}. {match}")


def find_fuzzy_matches(html_content, target_class):
    """查找相似的类名"""
    # 提取所有类名
    class_pattern = r'class="([^"]*)"'
    all_classes = re.findall(class_pattern, html_content)

    fuzzy_matches = []
    target_words = target_class.lower().split('-')

    for class_attr in all_classes:
        classes = class_attr.split()
        for cls in classes:
            # 检查是否包含目标类名的部分单词
            cls_lower = cls.lower()
            for word in target_words:
                if len(word) > 3 and word in cls_lower and cls not in fuzzy_matches:
                    fuzzy_matches.append(cls)
                    break

    return list(set(fuzzy_matches))


def check_element_visibility(html_content, match_pos):
    """检查元素可见性相关的样式"""
    # 在匹配位置周围查找style属性
    start_search = max(0, match_pos - 500)
    end_search = min(len(html_content), match_pos + 500)
    context = html_content[start_search:end_search]

    # 查找style属性
    style_patterns = [
        r'style="([^"]*display[^"]*)"',
        r'style="([^"]*visibility[^"]*)"',
        r'style="([^"]*opacity[^"]*)"'
    ]

    for pattern in style_patterns:
        matches = re.findall(pattern, context)
        if matches:
            print(f"       样式: {matches[0][:50]}...")


def analyze_potential_issues(html_content):
    """分析潜在问题"""

    issues = []

    # 1. 检查是否有大量动态内容
    script_count = html_content.count('<script')
    if script_count > 10:
        issues.append(f"⚠️ 发现 {script_count} 个script标签，页面可能有大量动态内容")

    # 2. 检查是否有React/Vue等框架
    if 'react' in html_content.lower() or 'vue' in html_content.lower():
        issues.append("⚠️ 页面可能使用React/Vue框架，DOM可能是动态生成的")

    # 3. 检查是否有loading状态
    loading_indicators = [
        'loading', 'spinner', 'skeleton', 'placeholder'
    ]
    for indicator in loading_indicators:
        if indicator in html_content.lower():
            issues.append(f"⚠️ 发现 '{indicator}' 关键词，页面可能还在加载中")

    # 4. 检查CSS模块化
    modular_css_count = len(re.findall(r'class="[^"]*--[A-Za-z0-9]+', html_content))
    if modular_css_count > 50:
        issues.append(f"⚠️ 发现 {modular_css_count} 个CSS模块化类名，类名可能会动态变化")

    # 5. 检查是否在iframe中
    if '<iframe' in html_content:
        iframe_count = html_content.count('<iframe')
        issues.append(f"⚠️ 发现 {iframe_count} 个iframe，目标元素可能在iframe中")

    # 6. 检查页面结构是否完整
    if '</body>' not in html_content:
        issues.append("⚠️ HTML结构不完整，可能只是页面片段")

    # 输出问题
    if issues:
        for issue in issues:
            print(f"  {issue}")
    else:
        print("  ✅ 未发现明显问题")

    # 输出解决建议
    print(f"\n💡 解决建议:")
    print("  1. 检查页面是否完全加载完成（等待所有Ajax请求）")
    print("  2. 使用更长的等待时间")
    print("  3. 检查元素是否在iframe中")
    print("  4. 考虑使用更稳定的选择器（如data-testid）")
    print("  5. 在查找元素前等待特定的网络请求完成")


def compare_html_sizes():
    """比较不同时间保存的HTML文件大小"""
    import os
    import glob

    debug_dir = '/Users/jimmypan/git_repo/XianyuAutoAgent/cocs/debug_pages'
    html_files = glob.glob(f"{debug_dir}/*.html")

    print(f"\n📁 debug_pages目录中的HTML文件:")
    for file_path in sorted(html_files):
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        print(f"  {file_name}: {file_size} 字节")


if __name__ == "__main__":
    analyze_selector_differences()
    compare_html_sizes()