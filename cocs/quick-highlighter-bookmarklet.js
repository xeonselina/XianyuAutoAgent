// 快速元素高亮器 - 书签版本
// 将下面的代码作为书签的URL，可以在任何页面快速启动
javascript:(function(){
    // 检查是否已经加载
    if (window.quickHighlighter) {
        console.log('快速高亮器已存在，重新激活...');
        window.quickHighlighter.show();
        return;
    }

    // 创建快速高亮器类
    class QuickHighlighter {
        constructor() {
            this.highlights = [];
            this.colors = ['#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff', '#00ffff'];
            this.colorIndex = 0;
            this.panel = null;
            this.input = null;
            this.createPanel();
        }

        createPanel() {
            // 创建主面板
            this.panel = document.createElement('div');
            this.panel.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                width: 350px;
                background: #2d3748;
                border: 2px solid #4a5568;
                border-radius: 8px;
                padding: 15px;
                z-index: 999999;
                font-family: monospace;
                font-size: 12px;
                color: white;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            `;

            this.panel.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <h3 style="margin: 0; color: #48bb78;">🎯 快速高亮测试</h3>
                    <button id="qh-close" style="background: #e53e3e; color: white; border: none; border-radius: 3px; padding: 2px 6px; cursor: pointer;">✕</button>
                </div>
                
                <div style="margin-bottom: 10px;">
                    <input id="qh-input" type="text" placeholder="输入CSS选择器 (如: .btn, #header, div.container)" 
                           style="width: 100%; padding: 8px; border: 1px solid #4a5568; border-radius: 4px; background: #1a202c; color: white; font-family: monospace;">
                </div>
                
                <div style="display: flex; gap: 5px; margin-bottom: 10px; flex-wrap: wrap;">
                    <button id="qh-highlight" style="background: #48bb78; color: white; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-size: 11px;">高亮</button>
                    <button id="qh-clear" style="background: #ed8936; color: white; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-size: 11px;">清除</button>
                    <button id="qh-test-common" style="background: #667eea; color: white; border: none; border-radius: 4px; padding: 5px 10px; cursor: pointer; font-size: 11px;">测试常用</button>
                </div>
                
                <div id="qh-results" style="max-height: 200px; overflow-y: auto; background: #1a202c; padding: 8px; border-radius: 4px; margin-bottom: 10px;">
                    <div style="color: #a0aec0; font-size: 11px;">等待输入选择器...</div>
                </div>
                
                <div style="font-size: 10px; color: #a0aec0; line-height: 1.4;">
                    💡 提示：按Enter快速高亮 | 支持复杂选择器 | 不同颜色区分不同选择器
                </div>
            `;

            document.body.appendChild(this.panel);

            // 绑定事件
            this.input = document.getElementById('qh-input');
            document.getElementById('qh-highlight').onclick = () => this.highlight();
            document.getElementById('qh-clear').onclick = () => this.clear();
            document.getElementById('qh-close').onclick = () => this.hide();
            document.getElementById('qh-test-common').onclick = () => this.testCommon();
            
            this.input.onkeypress = (e) => {
                if (e.key === 'Enter') this.highlight();
            };

            this.input.focus();
        }

        highlight() {
            const selector = this.input.value.trim();
            if (!selector) return;

            try {
                const elements = document.querySelectorAll(selector);
                const color = this.colors[this.colorIndex % this.colors.length];
                this.colorIndex++;

                if (elements.length === 0) {
                    this.updateResults(`❌ "${selector}" - 未找到匹配元素`, '#e53e3e');
                    return;
                }

                // 创建高亮
                const highlightData = {
                    selector: selector,
                    color: color,
                    highlights: []
                };

                elements.forEach((element, index) => {
                    const highlight = document.createElement('div');
                    highlight.style.cssText = `
                        position: absolute;
                        background: ${color}40;
                        border: 2px solid ${color};
                        pointer-events: none;
                        z-index: 999998;
                        box-sizing: border-box;
                    `;
                    
                    const rect = element.getBoundingClientRect();
                    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                    const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
                    
                    highlight.style.top = (rect.top + scrollTop) + 'px';
                    highlight.style.left = (rect.left + scrollLeft) + 'px';
                    highlight.style.width = rect.width + 'px';
                    highlight.style.height = rect.height + 'px';

                    // 添加标签
                    const label = document.createElement('div');
                    label.style.cssText = `
                        position: absolute;
                        top: -20px;
                        left: 0;
                        background: ${color};
                        color: white;
                        padding: 1px 4px;
                        font-size: 9px;
                        border-radius: 2px;
                        white-space: nowrap;
                    `;
                    label.textContent = `${index + 1}`;
                    highlight.appendChild(label);

                    document.body.appendChild(highlight);
                    highlightData.highlights.push(highlight);
                });

                this.highlights.push(highlightData);
                this.updateResults(`✅ "${selector}" - 找到 ${elements.length} 个元素`, color);
                this.input.value = '';
                
            } catch (error) {
                this.updateResults(`❌ "${selector}" - 语法错误: ${error.message}`, '#e53e3e');
            }
        }

        clear() {
            this.highlights.forEach(data => {
                data.highlights.forEach(highlight => {
                    if (highlight.parentNode) highlight.remove();
                });
            });
            this.highlights = [];
            this.colorIndex = 0;
            this.updateResults('✅ 已清除所有高亮', '#48bb78');
        }

        testCommon() {
            const commonSelectors = [
                'button', '.btn', '#header', '#footer', 
                'nav', '.container', '.content', 'form',
                'input[type="text"]', 'a[href*="http"]'
            ];
            
            this.updateResults('🔍 开始测试常用选择器...', '#667eea');
            
            commonSelectors.forEach((selector, index) => {
                setTimeout(() => {
                    try {
                        const elements = document.querySelectorAll(selector);
                        if (elements.length > 0) {
                            this.input.value = selector;
                            this.highlight();
                        }
                    } catch (e) {}
                }, index * 500);
            });
        }

        updateResults(message, color = '#48bb78') {
            const results = document.getElementById('qh-results');
            const div = document.createElement('div');
            div.style.cssText = `color: ${color}; margin-bottom: 5px; font-size: 11px;`;
            div.textContent = message;
            results.appendChild(div);
            results.scrollTop = results.scrollHeight;
            
            // 保持最多20条记录
            if (results.children.length > 20) {
                results.removeChild(results.firstChild);
            }
        }

        show() {
            if (this.panel) this.panel.style.display = 'block';
        }

        hide() {
            if (this.panel) this.panel.style.display = 'none';
        }

        destroy() {
            this.clear();
            if (this.panel && this.panel.parentNode) {
                this.panel.remove();
            }
            delete window.quickHighlighter;
        }
    }

    // 创建实例
    window.quickHighlighter = new QuickHighlighter();
    
    // 添加便捷方法
    window.qh = (selector) => {
        window.quickHighlighter.input.value = selector;
        window.quickHighlighter.highlight();
    };

    console.log(`
🎯 快速元素高亮器已启动！

使用方法：
1. 在输入框中输入CSS选择器
2. 点击"高亮"按钮或按Enter键
3. 点击"测试常用"试试常见选择器
4. 或者在控制台使用: qh('.your-selector')

示例选择器：
- .btn (所有class包含btn的元素)
- #header (ID为header的元素)
- div.container p (container类div下的所有p元素)
- input[type="text"] (所有文本输入框)
- a[href*="github"] (链接包含github的a标签)
    `);
})();