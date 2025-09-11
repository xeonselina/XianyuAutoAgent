/**
 * 元素高亮测试器
 * 用于测试从 dom-inspector.js 提取的 CSS 选择器和 class 信息
 * 
 * 使用方法：
 * 1. 在浏览器控制台加载此脚本
 * 2. 调用 highlightElement('your-css-selector') 来高亮元素
 * 3. 调用 testSelectors(['selector1', 'selector2']) 来批量测试多个选择器
 * 4. 调用 clearHighlights() 清除所有高亮
 */

class ElementHighlighter {
    constructor() {
        this.highlights = [];
        this.colors = [
            '#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff', 
            '#00ffff', '#ffa500', '#800080', '#008000', '#ffc0cb'
        ];
        this.colorIndex = 0;
        this.infoPanel = null;
        this.createInfoPanel();
    }

    // 创建信息面板
    createInfoPanel() {
        this.infoPanel = document.createElement('div');
        this.infoPanel.id = 'element-highlighter-panel';
        this.infoPanel.style.cssText = `
            position: fixed;
            top: 10px;
            left: 10px;
            background: rgba(0, 0, 0, 0.9);
            color: white;
            padding: 15px;
            border-radius: 8px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            z-index: 1000001;
            max-width: 400px;
            max-height: 300px;
            overflow-y: auto;
            border: 2px solid #00ff00;
        `;
        this.infoPanel.innerHTML = `
            <div style="font-weight: bold; margin-bottom: 10px; color: #00ff00;">
                🎯 元素高亮测试器
            </div>
            <div style="margin-bottom: 5px;">等待输入选择器...</div>
            <div style="font-size: 10px; color: #ccc; margin-top: 10px;">
                使用 highlightElement('selector') 来高亮元素<br>
                使用 clearHighlights() 清除高亮
            </div>
        `;
        document.body.appendChild(this.infoPanel);
    }

    // 更新信息面板
    updateInfoPanel(info) {
        const existingInfo = this.infoPanel.querySelector('.info-content');
        if (existingInfo) {
            existingInfo.remove();
        }

        const infoDiv = document.createElement('div');
        infoDiv.className = 'info-content';
        infoDiv.innerHTML = info;
        this.infoPanel.appendChild(infoDiv);
    }

    // 高亮单个元素
    highlightElement(selector, customColor = null, label = null) {
        try {
            const elements = document.querySelectorAll(selector);
            
            if (elements.length === 0) {
                console.warn(`❌ 未找到匹配的元素: ${selector}`);
                this.updateInfoPanel(`
                    <div style="color: #ff6666;">
                        ❌ 选择器: ${selector}<br>
                        未找到匹配的元素
                    </div>
                `);
                return false;
            }

            const color = customColor || this.colors[this.colorIndex % this.colors.length];
            this.colorIndex++;

            const highlightInfo = {
                selector: selector,
                elements: [],
                color: color,
                label: label || `选择器 ${this.highlights.length + 1}`
            };

            elements.forEach((element, index) => {
                const highlight = this.createHighlight(element, color, `${highlightInfo.label}[${index}]`);
                highlightInfo.elements.push({
                    element: element,
                    highlight: highlight,
                    info: this.getElementInfo(element)
                });
            });

            this.highlights.push(highlightInfo);

            console.log(`✅ 高亮了 ${elements.length} 个元素:`, selector);
            console.log('匹配的元素:', elements);

            this.updateInfoPanel(`
                <div style="color: ${color};">
                    ✅ ${highlightInfo.label}: ${selector}<br>
                    找到 ${elements.length} 个匹配元素
                </div>
                ${this.generateSummary()}
            `);

            return true;
        } catch (error) {
            console.error(`❌ 选择器语法错误: ${selector}`, error);
            this.updateInfoPanel(`
                <div style="color: #ff6666;">
                    ❌ 选择器语法错误: ${selector}<br>
                    ${error.message}
                </div>
            `);
            return false;
        }
    }

    // 创建高亮覆盖层
    createHighlight(element, color, label) {
        const highlight = document.createElement('div');
        highlight.className = 'element-highlight';
        highlight.style.cssText = `
            position: absolute;
            background: ${color}40;
            border: 2px solid ${color};
            pointer-events: none;
            z-index: 999999;
            box-sizing: border-box;
        `;

        // 添加标签
        const labelElement = document.createElement('div');
        labelElement.style.cssText = `
            position: absolute;
            top: -25px;
            left: 0;
            background: ${color};
            color: white;
            padding: 2px 6px;
            font-size: 10px;
            font-family: Arial, sans-serif;
            border-radius: 3px;
            white-space: nowrap;
        `;
        labelElement.textContent = label;
        highlight.appendChild(labelElement);

        document.body.appendChild(highlight);
        this.positionHighlight(highlight, element);

        return highlight;
    }

    // 定位高亮层
    positionHighlight(highlight, element) {
        const rect = element.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
        
        highlight.style.top = (rect.top + scrollTop) + 'px';
        highlight.style.left = (rect.left + scrollLeft) + 'px';
        highlight.style.width = rect.width + 'px';
        highlight.style.height = rect.height + 'px';
    }

    // 获取元素信息
    getElementInfo(element) {
        return {
            tagName: element.tagName.toLowerCase(),
            id: element.id,
            className: element.className,
            textContent: element.textContent ? element.textContent.trim().substring(0, 30) + '...' : '',
            attributes: Array.from(element.attributes).map(attr => `${attr.name}="${attr.value}"`).join(' ')
        };
    }

    // 生成摘要信息
    generateSummary() {
        if (this.highlights.length === 0) return '';
        
        let summary = '<div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #333;">';
        summary += '<div style="color: #ccc; font-size: 10px;">当前高亮摘要:</div>';
        
        this.highlights.forEach((highlight, index) => {
            summary += `<div style="color: ${highlight.color}; font-size: 10px;">
                ${index + 1}. ${highlight.selector} (${highlight.elements.length}个)
            </div>`;
        });
        
        summary += '</div>';
        return summary;
    }

    // 批量测试多个选择器
    testSelectors(selectors) {
        console.group('🔍 批量测试选择器');
        
        const results = [];
        selectors.forEach((selector, index) => {
            const result = this.highlightElement(selector, null, `测试${index + 1}`);
            results.push({ selector, success: result });
        });

        console.log('测试结果:', results);
        console.groupEnd();

        return results;
    }

    // 测试类名选择器
    testClasses(classNames) {
        console.group('🎨 测试类名选择器');
        
        const selectors = classNames.map(className => {
            // 处理多个类名
            if (className.includes(' ')) {
                return '.' + className.split(' ').join('.');
            }
            return '.' + className;
        });

        const results = this.testSelectors(selectors);
        console.groupEnd();

        return results;
    }

    // 清除所有高亮
    clearHighlights() {
        this.highlights.forEach(highlightInfo => {
            highlightInfo.elements.forEach(elementInfo => {
                if (elementInfo.highlight && elementInfo.highlight.parentNode) {
                    elementInfo.highlight.remove();
                }
            });
        });

        this.highlights = [];
        this.colorIndex = 0;

        this.updateInfoPanel(`
            <div style="color: #00ff00;">
                ✅ 已清除所有高亮
            </div>
        `);

        console.log('✅ 已清除所有高亮');
    }

    // 显示详细信息
    showDetails() {
        if (this.highlights.length === 0) {
            console.log('没有高亮的元素');
            return;
        }

        console.group('📋 详细元素信息');
        this.highlights.forEach((highlightInfo, index) => {
            console.group(`${index + 1}. ${highlightInfo.selector} (${highlightInfo.elements.length}个元素)`);
            highlightInfo.elements.forEach((elementInfo, elemIndex) => {
                console.log(`元素 ${elemIndex + 1}:`, elementInfo.element);
                console.log('信息:', elementInfo.info);
            });
            console.groupEnd();
        });
        console.groupEnd();
    }

    // 销毁高亮器
    destroy() {
        this.clearHighlights();
        if (this.infoPanel && this.infoPanel.parentNode) {
            this.infoPanel.remove();
        }
        console.log('🗑️ 元素高亮器已销毁');
    }

    // 更新高亮位置（页面滚动时调用）
    updatePositions() {
        this.highlights.forEach(highlightInfo => {
            highlightInfo.elements.forEach(elementInfo => {
                this.positionHighlight(elementInfo.highlight, elementInfo.element);
            });
        });
    }
}

// 创建全局实例
window.elementHighlighter = new ElementHighlighter();

// 便捷方法
window.highlightElement = (selector, color, label) => {
    return window.elementHighlighter.highlightElement(selector, color, label);
};

window.testSelectors = (selectors) => {
    return window.elementHighlighter.testSelectors(selectors);
};

window.testClasses = (classNames) => {
    return window.elementHighlighter.testClasses(classNames);
};

window.clearHighlights = () => {
    window.elementHighlighter.clearHighlights();
};

window.showHighlightDetails = () => {
    window.elementHighlighter.showDetails();
};

// 监听页面滚动，更新高亮位置
window.addEventListener('scroll', () => {
    if (window.elementHighlighter) {
        window.elementHighlighter.updatePositions();
    }
});

window.addEventListener('resize', () => {
    if (window.elementHighlighter) {
        window.elementHighlighter.updatePositions();
    }
});

// 自动执行说明
console.log(`
🎯 元素高亮测试器已加载！

主要功能：
1. highlightElement('css-selector') - 高亮指定选择器的元素
2. testSelectors(['selector1', 'selector2']) - 批量测试多个选择器
3. testClasses(['class1', 'class2']) - 测试类名选择器
4. clearHighlights() - 清除所有高亮
5. showHighlightDetails() - 显示详细信息

使用示例：
highlightElement('.btn')                    // 高亮所有 .btn 元素
highlightElement('#header')                 // 高亮 ID 为 header 的元素
highlightElement('div.container p.text')    // 高亮复杂选择器
testClasses(['btn', 'container', 'active']) // 测试多个类名
testSelectors(['.btn', '#header', 'nav a']) // 测试多个选择器

特色功能：
- 不同颜色区分不同选择器
- 实时显示匹配元素数量
- 元素标签显示
- 滚动时自动更新位置
- 详细的控制台日志

现在你可以粘贴从 dom-inspector.js 提取的选择器来测试了！
`);