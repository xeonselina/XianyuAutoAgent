# 元素高亮测试工具使用说明

这套工具可以帮你测试从 `dom-inspector.js` 提取的 CSS 选择器和 class 信息，通过高亮网页元素来验证选择器的正确性。

## 工具文件

1. **`dom-inspector.js`** - DOM元素检查器（已有）
   - 鼠标悬停查看元素
   - 点击获取CSS选择器和XPath
   - 自动复制到剪贴板

2. **`element-highlighter.js`** - 完整版元素高亮器
   - 功能最完整，适合深度测试
   - 支持批量测试多个选择器
   - 详细的信息面板和日志

3. **`quick-highlighter-bookmarklet.js`** - 快速高亮器书签版
   - 轻量级，可作为浏览器书签
   - 简洁的UI界面
   - 快速测试选择器

## 使用方法

### 方法一：使用完整版高亮器 (推荐深度测试)

1. **加载脚本**
   ```javascript
   // 在浏览器控制台粘贴 element-highlighter.js 的全部内容
   ```

2. **基本使用**
   ```javascript
   // 高亮单个选择器
   highlightElement('.btn')
   highlightElement('#header')
   highlightElement('div.container p.text')
   
   // 批量测试多个选择器
   testSelectors(['.btn', '#nav', 'form input'])
   
   // 测试类名
   testClasses(['active', 'btn-primary', 'container'])
   
   // 清除高亮
   clearHighlights()
   
   // 查看详细信息
   showHighlightDetails()
   ```

3. **高级功能**
   ```javascript
   // 自定义颜色和标签
   highlightElement('.btn', '#ff0000', '按钮元素')
   
   // 测试从dom-inspector复制的选择器
   highlightElement('body > div.main-container > header.site-header > nav.primary-nav > ul.nav-menu > li:nth-child(2) > a')
   ```

### 方法二：使用快速高亮器书签版 (推荐快速测试)

1. **创建书签**
   - 复制 `quick-highlighter-bookmarklet.js` 的全部内容
   - 创建新书签，将内容作为URL
   - 书签名称：`🎯 快速高亮器`

2. **使用**
   - 在任何网页点击书签
   - 在弹出的面板中输入CSS选择器
   - 按Enter或点击"高亮"按钮
   - 支持控制台快捷命令：`qh('.your-selector')`

## 典型工作流程

### 1. 提取选择器
```javascript
// 首先运行 dom-inspector.js
inspectDOM()
// 点击目标元素，获取CSS选择器
// 例如得到：div.product-card .price-info span.price
```

### 2. 测试选择器
```javascript
// 使用高亮器测试提取的选择器
highlightElement('div.product-card .price-info span.price')

// 如果匹配元素过多或过少，可以调整选择器
highlightElement('.product-card .price')  // 简化版本
highlightElement('div.product-card .price-info span.price.current')  // 更精确版本
```

### 3. 批量验证
```javascript
// 测试多个提取的选择器
const extractedSelectors = [
    '.product-title',
    '.product-price',
    '.product-image img',
    '.add-to-cart-btn',
    '.product-rating .stars'
];

testSelectors(extractedSelectors);
```

### 4. 优化选择器
```javascript
// 如果某个选择器匹配元素过多，可以增加约束
highlightElement('.btn')  // 匹配所有按钮（可能太宽泛）
highlightElement('.product-card .btn.add-to-cart')  // 更具体的选择器

// 如果选择器太复杂，可以简化
highlightElement('body > div.main > section.products > div.product-list > div:nth-child(3) > h2')  // 复杂
highlightElement('.product-list h2')  // 简化但仍然准确
```

## 常用选择器示例

### 基本选择器
```javascript
highlightElement('div')        // 所有div元素
highlightElement('.className') // 所有包含className的元素
highlightElement('#elementId') // ID为elementId的元素
```

### 属性选择器
```javascript
highlightElement('input[type="text"]')     // 所有文本输入框
highlightElement('a[href*="github"]')      // 链接包含github的a标签
highlightElement('img[alt]')               // 有alt属性的图片
highlightElement('button[disabled]')       // 被禁用的按钮
```

### 组合选择器
```javascript
highlightElement('nav ul li a')           // 导航菜单链接
highlightElement('.container > .row')     // 容器的直接子行元素
highlightElement('.card + .card')         // 相邻的卡片元素
highlightElement('p:first-child')         // 第一个p元素
```

### 电商网站常用选择器
```javascript
// 商品相关
highlightElement('.product-card .title')
highlightElement('.price .current-price')
highlightElement('.product-image img')
highlightElement('.rating .stars')
highlightElement('.add-to-cart')

// 导航相关
highlightElement('.navbar .nav-link')
highlightElement('.breadcrumb a')
highlightElement('.category-menu li')

// 表单相关
highlightElement('form input[required]')
highlightElement('.form-group label')
highlightElement('button[type="submit"]')
```

## 调试技巧

### 1. 逐步细化选择器
```javascript
highlightElement('div')           // 从最宽泛开始
highlightElement('div.product')   // 添加类名约束
highlightElement('div.product .title')  // 添加后代约束
```

### 2. 使用开发者工具配合
- 在Elements面板中右键元素 → Copy → Copy selector
- 将复制的选择器粘贴到高亮器中测试
- 对比浏览器生成的选择器和自己提取的选择器

### 3. 处理动态内容
```javascript
// 对于动态加载的内容，可能需要等待加载完成
setTimeout(() => {
    highlightElement('.dynamic-content .item');
}, 2000);
```

### 4. 测试响应式设计
```javascript
// 在不同屏幕尺寸下测试相同选择器
// 调整浏览器窗口大小后，选择器可能匹配不同的元素
```

## 常见问题

### Q: 选择器在一个页面有效，在另一个页面无效？
A: 可能是网站结构不一致，需要使用更灵活的选择器或针对不同页面使用不同选择器。

### Q: 选择器匹配了太多元素？
A: 增加更具体的约束条件，如添加父级选择器或属性选择器。

### Q: 选择器太复杂难以维护？
A: 尽量使用语义化的类名和ID，避免依赖nth-child等位置选择器。

### Q: 动态生成的内容无法匹配？
A: 确保在内容加载完成后再测试选择器，或使用更稳定的选择器（如data-*属性）。

## 性能提示

- 避免使用过于宽泛的选择器（如 `*` 或单独的标签名）
- 优先使用ID选择器，其次是类选择器
- 避免深层嵌套的选择器
- 测试完成后记得清除高亮以释放内存

---

通过这套工具，你可以有效地测试和优化从网页中提取的CSS选择器，确保爬虫或自动化脚本能准确定位目标元素。