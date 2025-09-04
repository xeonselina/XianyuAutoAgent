/**
 * 
 * 1. 在浏览器中加载脚本：
  // 方法1：在控制台直接粘贴脚本内容
  // 方法2：创建书签
  javascript:(function(){var script=document.createElement('script');script.src='file:///Users/jimmypan/git_repo/XianyuAutoAgent/cocs/dom-inspector
  .js';document.head.appendChild(script);})();
  2. 启动检查器：
  inspectDOM()
  3. 使用流程：
    - 鼠标悬停查看元素高亮
    - 点击选择元素
    - 元素信息自动复制到剪贴板
    - 按ESC退出

  更好的替代方案：
  - 浏览器开发者工具的元素选择器 (Ctrl/Cmd+Shift+C)
  - Chrome扩展如"Selector Gadget"
  - XPath Helper等浏览器扩展

  这个脚本会输出CSS选择器、XPath、元素属性等，方便你更新DOM解析规则。
 * 
 */

// DOM元素检查器 - 帮助获取鼠标指向的DOM元素信息
class DOMInspector {
    constructor() {
        this.isActive = false;
        this.overlay = null;
        this.infoBox = null;
        this.currentElement = null;
        this.handleMouseMove = this.handleMouseMove.bind(this);
        this.handleClick = this.handleClick.bind(this);
        this.handleKeyPress = this.handleKeyPress.bind(this);
    }

    // 启动检查器
    start() {
        if (this.isActive) return;
        
        this.isActive = true;
        this.createOverlay();
        this.createInfoBox();
        
        document.addEventListener('mousemove', this.handleMouseMove, true);
        document.addEventListener('click', this.handleClick, true);
        document.addEventListener('keydown', this.handleKeyPress, true);
        
        console.log('DOM检查器已启动 - 移动鼠标查看元素，点击选择，按ESC退出');
    }

    // 停止检查器
    stop() {
        if (!this.isActive) return;
        
        this.isActive = false;
        
        document.removeEventListener('mousemove', this.handleMouseMove, true);
        document.removeEventListener('click', this.handleClick, true);
        document.removeEventListener('keydown', this.handleKeyPress, true);
        
        if (this.overlay) {
            this.overlay.remove();
            this.overlay = null;
        }
        
        if (this.infoBox) {
            this.infoBox.remove();
            this.infoBox = null;
        }
        
        console.log('DOM检查器已停止');
    }

    // 创建高亮覆盖层
    createOverlay() {
        this.overlay = document.createElement('div');
        this.overlay.style.cssText = `
            position: absolute;
            background: rgba(255, 0, 0, 0.3);
            border: 2px solid #ff0000;
            pointer-events: none;
            z-index: 999999;
            box-sizing: border-box;
        `;
        document.body.appendChild(this.overlay);
    }

    // 创建信息显示框
    createInfoBox() {
        this.infoBox = document.createElement('div');
        this.infoBox.style.cssText = `
            position: fixed;
            top: 10px;
            right: 10px;
            background: rgba(0, 0, 0, 0.9);
            color: white;
            padding: 10px;
            border-radius: 5px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            z-index: 1000000;
            max-width: 400px;
            word-wrap: break-word;
            pointer-events: none;
        `;
        document.body.appendChild(this.infoBox);
    }

    // 处理鼠标移动
    handleMouseMove(e) {
        if (!this.isActive) return;
        
        e.stopPropagation();
        e.preventDefault();
        
        const element = document.elementFromPoint(e.clientX, e.clientY);
        if (!element || element === this.overlay || element === this.infoBox) return;
        
        this.currentElement = element;
        this.highlightElement(element);
        this.updateInfoBox(element);
    }

    // 处理点击事件
    handleClick(e) {
        if (!this.isActive) return;
        
        e.stopPropagation();
        e.preventDefault();
        
        if (this.currentElement) {
            this.selectElement(this.currentElement);
        }
    }

    // 处理按键事件
    handleKeyPress(e) {
        if (e.key === 'Escape') {
            this.stop();
        }
    }

    // 高亮元素
    highlightElement(element) {
        const rect = element.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
        
        this.overlay.style.top = (rect.top + scrollTop) + 'px';
        this.overlay.style.left = (rect.left + scrollLeft) + 'px';
        this.overlay.style.width = rect.width + 'px';
        this.overlay.style.height = rect.height + 'px';
    }

    // 更新信息框
    updateInfoBox(element) {
        const info = this.getElementInfo(element);
        this.infoBox.innerHTML = `
            <div><strong>标签:</strong> ${info.tagName}</div>
            <div><strong>ID:</strong> ${info.id || '无'}</div>
            <div><strong>Class:</strong> ${info.className || '无'}</div>
            <div><strong>文本:</strong> ${info.textContent}</div>
            <div><strong>CSS选择器:</strong> ${info.cssSelector}</div>
            <div><strong>XPath:</strong> ${info.xpath}</div>
            <div style="margin-top: 10px; font-size: 10px; color: #ccc;">
                点击选择 | ESC退出
            </div>
        `;
    }

    // 获取元素信息
    getElementInfo(element) {
        return {
            tagName: element.tagName.toLowerCase(),
            id: element.id,
            className: element.className,
            textContent: element.textContent ? element.textContent.trim().substring(0, 50) + '...' : '',
            cssSelector: this.getCSSSelector(element),
            xpath: this.getXPath(element)
        };
    }

    // 生成CSS选择器
    getCSSSelector(element) {
        if (!element || element === document) return '';
        
        // 如果有ID，优先使用ID
        if (element.id) {
            return `#${element.id}`;
        }
        
        let selector = element.tagName.toLowerCase();
        
        // 添加类名
        if (element.className) {
            const classes = element.className.trim().split(/\s+/).join('.');
            selector += `.${classes}`;
        }
        
        // 如果不是唯一的，添加父级选择器
        if (document.querySelectorAll(selector).length > 1) {
            const parent = element.parentElement;
            if (parent) {
                const parentSelector = this.getCSSSelector(parent);
                selector = `${parentSelector} > ${selector}`;
            }
        }
        
        return selector;
    }

    // 生成XPath
    getXPath(element) {
        if (!element || element === document) return '';
        
        if (element.id) {
            return `//*[@id="${element.id}"]`;
        }
        
        const parts = [];
        
        while (element && element.nodeType === Node.ELEMENT_NODE) {
            let index = 1;
            let sibling = element.previousSibling;
            
            while (sibling) {
                if (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName === element.tagName) {
                    index++;
                }
                sibling = sibling.previousSibling;
            }
            
            const tagName = element.tagName.toLowerCase();
            const part = index > 1 ? `${tagName}[${index}]` : tagName;
            parts.unshift(part);
            
            element = element.parentElement;
        }
        
        return '/' + parts.join('/');
    }

    // 选择元素并输出信息
    selectElement(element) {
        const info = this.getElementInfo(element);
        
        console.group('🎯 选中的DOM元素信息:');
        console.log('Element:', element);
        console.log('Tag Name:', info.tagName);
        console.log('ID:', info.id || '无');
        console.log('Class:', info.className || '无');
        console.log('Text Content:', info.textContent);
        console.log('CSS Selector:', info.cssSelector);
        console.log('XPath:', info.xpath);
        console.log('HTML:', element.outerHTML.substring(0, 200) + '...');
        console.groupEnd();
        
        // 将信息复制到剪贴板
        const clipboardText = `
DOM元素信息:
标签: ${info.tagName}
ID: ${info.id || '无'}
Class: ${info.className || '无'}
CSS选择器: ${info.cssSelector}
XPath: ${info.xpath}
HTML: ${element.outerHTML}
        `.trim();
        
        navigator.clipboard.writeText(clipboardText).then(() => {
            console.log('✅ 元素信息已复制到剪贴板');
        }).catch(() => {
            console.log('❌ 复制到剪贴板失败，请手动复制控制台中的信息');
        });
        
        this.stop();
    }
}

// 全局实例
window.domInspector = new DOMInspector();

// 便捷方法
window.inspectDOM = () => {
    window.domInspector.start();
};

window.stopInspect = () => {
    window.domInspector.stop();
};

// 自动执行说明
console.log(`
🔍 DOM检查器已加载！

使用方法：
1. inspectDOM() - 启动检查器
2. stopInspect() - 停止检查器
3. 或者直接：window.domInspector.start()

启动后：
- 移动鼠标查看元素高亮
- 点击元素选择并获取详细信息
- 按ESC键退出检查模式
- 选中的元素信息会自动复制到剪贴板

示例：inspectDOM()
`);