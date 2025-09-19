#!/usr/bin/env python3
"""
在现有浏览器会话中调试元素检测问题
"""
import asyncio
from playwright.async_api import Page


async def debug_element_detection(page: Page):
    """调试元素检测问题"""
    print("🔍 开始调试元素检测问题")
    print("=" * 60)

    # 测试的选择器
    selectors = [
        '.conversation-list--jDBLEMex',
        '.rc-virtual-list',
        'ul.ant-list-items',
        'li.ant-list-item',
        '.conversation-item--JReyg97P'
    ]

    # 1. 基本页面信息
    print(f"\n📋 当前页面: {page.url}")
    print(f"📋 页面标题: {await page.title()}")

    # 2. 检查页面加载状态
    ready_state = await page.evaluate("document.readyState")
    print(f"📋 document.readyState: {ready_state}")

    # 3. 统计关键元素
    element_stats = await page.evaluate("""
        () => {
            return {
                total: document.querySelectorAll('*').length,
                divs: document.querySelectorAll('div').length,
                uls: document.querySelectorAll('ul').length,
                lis: document.querySelectorAll('li').length,
                ant_elements: document.querySelectorAll('[class*="ant"]').length,
                conversation_elements: document.querySelectorAll('[class*="conversation"]').length,
                rc_elements: document.querySelectorAll('[class*="rc-"]').length
            };
        }
    """)

    print(f"\n📊 元素统计:")
    for key, value in element_stats.items():
        print(f"  {key}: {value}")

    # 4. 详细测试每个选择器
    print(f"\n🎯 选择器详细测试:")
    for selector in selectors:
        print(f"\n--- 测试 {selector} ---")

        # JavaScript查询
        js_result = await page.evaluate(f"""
            (selector) => {{
                const elements = document.querySelectorAll(selector);
                const result = {{
                    count: elements.length,
                    elements: []
                }};

                for (let i = 0; i < Math.min(elements.length, 3); i++) {{
                    const el = elements[i];
                    const style = window.getComputedStyle(el);
                    result.elements.push({{
                        tagName: el.tagName,
                        className: el.className,
                        id: el.id,
                        visible: el.offsetParent !== null,
                        display: style.display,
                        visibility: style.visibility,
                        opacity: style.opacity,
                        text: el.textContent ? el.textContent.substring(0, 50) : ''
                    }});
                }}

                return result;
            }}
        """, selector)

        print(f"  JS查询结果: 找到 {js_result['count']} 个元素")
        for i, el_info in enumerate(js_result['elements']):
            print(f"    元素{i+1}: {el_info['tagName']}")
            print(f"      类名: {el_info['className'][:50]}...")
            print(f"      可见: {el_info['visible']} (display:{el_info['display']}, visibility:{el_info['visibility']}, opacity:{el_info['opacity']})")
            if el_info['text']:
                print(f"      文本: {el_info['text']}...")

        # Playwright query_selector测试
        try:
            pw_element = await page.query_selector(selector)
            print(f"  Playwright query_selector: {'✅ 成功' if pw_element else '❌ 返回None'}")
        except Exception as e:
            print(f"  Playwright query_selector: ❌ 异常 - {e}")

        # Playwright wait_for_selector测试
        try:
            pw_wait_element = await page.wait_for_selector(selector, timeout=1000, state='attached')
            print(f"  Playwright wait_for_selector(attached): {'✅ 成功' if pw_wait_element else '❌ 返回None'}")
        except Exception as e:
            print(f"  Playwright wait_for_selector(attached): ❌ 超时/异常 - {type(e).__name__}")

        try:
            pw_wait_visible = await page.wait_for_selector(selector, timeout=1000, state='visible')
            print(f"  Playwright wait_for_selector(visible): {'✅ 成功' if pw_wait_visible else '❌ 返回None'}")
        except Exception as e:
            print(f"  Playwright wait_for_selector(visible): ❌ 超时/异常 - {type(e).__name__}")

    # 5. 检查页面是否在iframe中
    print(f"\n🔍 检查iframe情况:")
    iframe_info = await page.evaluate("""
        () => {
            const iframes = document.querySelectorAll('iframe');
            return {
                count: iframes.length,
                frames: Array.from(iframes).map(iframe => ({
                    src: iframe.src,
                    name: iframe.name,
                    id: iframe.id,
                    className: iframe.className
                }))
            };
        }
    """)

    print(f"  发现 {iframe_info['count']} 个iframe")
    for i, frame_info in enumerate(iframe_info['frames']):
        print(f"    iframe{i+1}: src={frame_info['src'][:50]}...")

    # 6. 检查当前页面是否是我们期望的聊天页面
    print(f"\n🔍 页面类型检测:")
    page_type = await page.evaluate("""
        () => {
            const url = window.location.href;
            const hasChat = url.includes('im') || url.includes('chat') || url.includes('message');
            const hasConversation = !!document.querySelector('[class*="conversation"]');
            const hasMessageContainer = !!document.querySelector('[class*="message"]');
            const hasIM = !!document.querySelector('[class*="im-"]');

            return {
                url: url,
                hasChat: hasChat,
                hasConversation: hasConversation,
                hasMessageContainer: hasMessageContainer,
                hasIM: hasIM,
                likely_chat_page: hasConversation || hasMessageContainer || hasIM
            };
        }
    """)

    print(f"  当前URL: {page_type['url']}")
    print(f"  URL包含聊天关键词: {page_type['hasChat']}")
    print(f"  有对话元素: {page_type['hasConversation']}")
    print(f"  有消息容器: {page_type['hasMessageContainer']}")
    print(f"  有IM元素: {page_type['hasIM']}")
    print(f"  可能是聊天页面: {page_type['likely_chat_page']}")

    # 7. 保存当前页面快照用于对比
    timestamp = await page.evaluate("Date.now()")
    html_content = await page.content()

    debug_file = f"/Users/jimmypan/git_repo/XianyuAutoAgent/cocs/debug_pages/current_debug_{timestamp}.html"
    with open(debug_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"\n💾 当前页面HTML已保存到: {debug_file}")
    print(f"💾 页面大小: {len(html_content)} 字符")

    return {
        'selectors_found': js_result['count'] > 0,
        'page_type': page_type,
        'debug_file': debug_file
    }


# 如果你想在现有的goofish_browser.py中调用，可以这样用：
# from debug_element_detection import debug_element_detection
# result = await debug_element_detection(self.page)