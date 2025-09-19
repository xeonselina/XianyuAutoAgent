#!/usr/bin/env python3
"""
测试Playwright为什么找不到静态HTML中存在的元素
"""
import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright, Page


class PlaywrightElementTester:
    def __init__(self):
        self.selectors_to_test = [
            '.conversation-list--jDBLEMex',
            '.rc-virtual-list',
            'ul.ant-list-items',
            'li.ant-list-item',
            '.conversation-item--JReyg97P'
        ]

    async def run_test(self, page: Page):
        """运行完整的元素检测测试"""
        print("🔍 开始Playwright元素检测测试")
        print("=" * 60)

        # 1. 基本页面信息
        await self._check_page_info(page)

        # 2. 页面加载状态
        await self._check_page_state(page)

        # 3. DOM元素统计
        await self._check_dom_stats(page)

        # 4. 测试每个选择器
        await self._test_selectors(page)

        # 5. 与静态HTML对比
        await self._compare_with_static_html(page)

    async def _check_page_info(self, page: Page):
        """检查基本页面信息"""
        print("\n📋 基本页面信息")
        print("-" * 30)

        url = page.url
        title = await page.title()

        print(f"URL: {url}")
        print(f"标题: {title}")

    async def _check_page_state(self, page: Page):
        """检查页面加载状态"""
        print("\n⏳ 页面加载状态")
        print("-" * 30)

        # 检查document.readyState
        ready_state = await page.evaluate("document.readyState")
        print(f"document.readyState: {ready_state}")

        # 检查是否有loading指示器
        loading_elements = await page.evaluate("""
            () => {
                const loadingSelectors = [
                    '.loading', '.spinner', '.ant-spin',
                    '[class*="loading"]', '[class*="spin"]'
                ];

                const found = [];
                for (const selector of loadingSelectors) {
                    const elements = document.querySelectorAll(selector);
                    if (elements.length > 0) {
                        found.push({
                            selector: selector,
                            count: elements.length,
                            visible: Array.from(elements).some(el => el.offsetParent !== null)
                        });
                    }
                }
                return found;
            }
        """)

        if loading_elements:
            print("发现加载指示器:")
            for loading in loading_elements:
                print(f"  - {loading['selector']}: {loading['count']}个 (可见: {loading['visible']})")
        else:
            print("未发现加载指示器")

    async def _check_dom_stats(self, page: Page):
        """检查DOM元素统计"""
        print("\n📊 DOM元素统计")
        print("-" * 30)

        stats = await page.evaluate("""
            () => {
                return {
                    total_elements: document.querySelectorAll('*').length,
                    div_count: document.querySelectorAll('div').length,
                    span_count: document.querySelectorAll('span').length,
                    ul_count: document.querySelectorAll('ul').length,
                    li_count: document.querySelectorAll('li').length,
                    ant_elements: document.querySelectorAll('[class*="ant"]').length,
                    conversation_elements: document.querySelectorAll('[class*="conversation"]').length,
                    rc_elements: document.querySelectorAll('[class*="rc-"]').length
                };
            }
        """)

        for key, value in stats.items():
            print(f"{key}: {value}")

    async def _test_selectors(self, page: Page):
        """测试每个选择器"""
        print("\n🎯 选择器测试结果")
        print("-" * 30)

        for selector in self.selectors_to_test:
            print(f"\n测试选择器: {selector}")

            # 方法1: JavaScript querySelector
            js_result = await page.evaluate(f"""
                () => {{
                    const element = document.querySelector('{selector}');
                    if (element) {{
                        return {{
                            found: true,
                            tagName: element.tagName,
                            className: element.className,
                            id: element.id,
                            visible: element.offsetParent !== null,
                            display: window.getComputedStyle(element).display,
                            visibility: window.getComputedStyle(element).visibility
                        }};
                    }}
                    return {{ found: false }};
                }}
            """)

            print(f"  JS查询: {'✅' if js_result['found'] else '❌'}")
            if js_result['found']:
                print(f"    标签: {js_result['tagName']}")
                print(f"    类名: {js_result['className'][:50]}...")
                print(f"    可见: {js_result['visible']}")
                print(f"    display: {js_result['display']}")
                print(f"    visibility: {js_result['visibility']}")

            # 方法2: Playwright query_selector
            try:
                pw_element = await page.query_selector(selector)
                print(f"  PW query_selector: {'✅' if pw_element else '❌'}")
            except Exception as e:
                print(f"  PW query_selector: ❌ (错误: {e})")

            # 方法3: Playwright wait_for_selector (短超时)
            try:
                pw_wait_element = await page.wait_for_selector(selector, timeout=1000, state='attached')
                print(f"  PW wait_for_selector: {'✅' if pw_wait_element else '❌'}")
            except Exception as e:
                print(f"  PW wait_for_selector: ❌ (错误: {type(e).__name__})")

    async def _compare_with_static_html(self, page: Page):
        """与静态HTML对比"""
        print("\n🔄 与静态HTML对比")
        print("-" * 30)

        # 读取静态HTML
        try:
            with open('/Users/jimmypan/git_repo/XianyuAutoAgent/cocs/debug_pages/debug_pages.html', 'r', encoding='utf-8') as f:
                static_html = f.read()
        except Exception as e:
            print(f"无法读取静态HTML: {e}")
            return

        # 获取当前页面HTML
        current_html = await page.content()

        print(f"静态HTML大小: {len(static_html)} 字符")
        print(f"当前HTML大小: {len(current_html)} 字符")
        print(f"大小差异: {len(current_html) - len(static_html)} 字符")

        # 检查关键元素在两个HTML中的存在情况
        for selector in self.selectors_to_test:
            if selector.startswith('.'):
                class_name = selector[1:]
                static_found = class_name in static_html
                current_found = class_name in current_html

                print(f"\n{selector}:")
                print(f"  静态HTML中: {'✅' if static_found else '❌'}")
                print(f"  当前HTML中: {'✅' if current_found else '❌'}")

                if static_found and not current_found:
                    print(f"  ⚠️ 元素在静态HTML中存在但当前页面中不存在！")
                elif not static_found and current_found:
                    print(f"  ⚠️ 元素在当前页面中存在但静态HTML中不存在！")

    async def save_current_page_html(self, page: Page):
        """保存当前页面HTML用于对比"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"/Users/jimmypan/git_repo/XianyuAutoAgent/cocs/debug_pages/current_page_{timestamp}.html"

        html_content = await page.content()
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"当前页面HTML已保存到: {filename}")
        return filename


async def run_standalone_test():
    """运行独立测试"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 导航到闲鱼页面
        print("导航到闲鱼页面...")
        await page.goto("https://www.goofish.com/")

        # 等待页面加载
        await page.wait_for_load_state('networkidle')

        # 运行测试
        tester = PlaywrightElementTester()
        await tester.run_test(page)

        # 保存当前页面HTML
        await tester.save_current_page_html(page)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(run_standalone_test())