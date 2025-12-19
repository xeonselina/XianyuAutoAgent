# 🚀 Xianyu AutoAgent - 智能闲鱼客服机器人系统

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/) [![LLM Powered](https://img.shields.io/badge/LLM-powered-FF6F61)](https://platform.openai.com/)

专为闲鱼平台打造的AI值守解决方案，实现闲鱼平台7×24小时自动化值守，支持多专家协同决策、智能议价和上下文感知对话。 


## 🌟 核心特性

### 智能对话引擎
| 功能模块   | 技术实现            | 关键特性                                                     |
| ---------- | ------------------- | ------------------------------------------------------------ |
| 上下文感知 | 会话历史存储        | 轻量级对话记忆管理，完整对话历史作为LLM上下文输入            |
| 专家路由   | LLM prompt+规则路由 | 基于提示工程的意图识别 → 专家Agent动态分发，支持议价/技术/客服多场景切换 |

### 业务功能矩阵
| 模块     | 已实现                        | 规划中                       |
| -------- | ----------------------------- | ---------------------------- |
| 核心引擎 | ✅ LLM自动回复<br>✅ 上下文管理 | 🔄 情感分析增强               |
| 议价系统 | ✅ 阶梯降价策略                | 🔄 市场比价功能               |
| 技术支持 | ✅ 网络搜索整合                | 🔄 RAG知识库增强              |
| 运维监控 | ✅ 基础日志                    | 🔄 钉钉集成<br>🔄  Web管理界面 |

## 🔌 传输模式

系统支持两种消息传输模式，可通过配置灵活切换：

### 🚀 直接模式 (Direct Mode)
- **工作原理**：直接建立 WebSocket 连接到闲鱼服务器
- **特点**：
  - ✅ 无界面运行，资源占用低
  - ✅ 适合服务器部署
  - ✅ 传统模式，稳定可靠
- **配置**：`.env` 文件中设置 `USE_BROWSER_MODE=false`

### 🌐 浏览器模式 (Browser Mode)
- **工作原理**：通过 Chromium 浏览器打开闲鱼网页，使用 CDP (Chrome DevTools Protocol) 拦截 WebSocket 消息
- **特点**：
  - ✅ 可视化界面，实时查看聊天
  - ✅ 更接近真实用户行为
  - ✅ 便于调试和监控
  - ⚠️ 需要安装 Playwright 和浏览器驱动
- **配置**：`.env` 文件中设置 `USE_BROWSER_MODE=true`

**选择建议**：
- 开发调试阶段 → 推荐使用**浏览器模式**（可视化）
- 生产部署阶段 → 推荐使用**直接模式**（稳定高效）

## 🎨效果图
<div align="center">
  <img src="./images/demo1.png" width="600" alt="客服">
  <br>
  <em>图1: 客服随叫随到</em>
</div>


<div align="center">
  <img src="./images/demo2.png" width="600" alt="议价专家">
  <br>
  <em>图2: 阶梯式议价</em>
</div>

<div align="center">
  <img src="./images/demo3.png" width="600" alt="技术专家"> 
  <br>
  <em>图3: 技术专家上场</em>
</div>

<div align="center">
  <img src="./images/log.png" width="600" alt="后台log"> 
  <br>
  <em>图4: 后台log</em>
</div>


## 🚴 快速开始

### 环境要求
- Python 3.8+

### 安装步骤

#### 1. 克隆仓库
```bash
git clone https://github.com/shaxiu/XianyuAutoAgent.git
cd XianyuAutoAgent/ai_kefu
```

#### 2. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

#### 3. （可选）安装 Playwright 浏览器驱动
> ⚠️ **仅在使用浏览器模式时需要安装**

```bash
# 安装 Playwright 浏览器
playwright install chromium

# 如果遇到权限问题，可能需要使用 sudo
# sudo playwright install chromium
```

#### 4. 配置环境变量
创建一个 `.env` 文件（可直接复制 `.env.example` 并重命名）：

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置以下必填项：

```ini
# ========== 必配项 ==========
# AI 模型配置
API_KEY=your_api_key_here                    # 从模型平台获取
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max

# 闲鱼账号
COOKIES_STR=your_cookies_here                # 从闲鱼网页端获取

# ========== 传输模式配置 ==========
USE_BROWSER_MODE=false                       # true=浏览器模式, false=直接模式

# ========== 浏览器模式配置（USE_BROWSER_MODE=true 时生效）==========
BROWSER_HEADLESS=false                       # false=显示浏览器窗口
BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=720

# ========== 可选配置 ==========
TOGGLE_KEYWORDS=。                           # 人工接管切换关键词
LOG_LEVEL=INFO                               # 日志级别
```

**获取 Cookie 方法**：
1. 在浏览器打开 https://www.goofish.com/
2. 按 F12 打开开发者工具
3. 切换到 Network 标签
4. 点击 Fetch/XHR
5. 刷新页面，点击任意请求
6. 在 Headers 中找到 Cookie，复制完整值

#### 5. 配置提示词（可选）
系统默认提供四个提示词模板，位于 `prompts/` 目录：

```bash
# 可以直接将 _example 后缀去掉使用
mv prompts/classify_prompt_example.txt prompts/classify_prompt.txt
mv prompts/price_prompt_example.txt prompts/price_prompt.txt
mv prompts/tech_prompt_example.txt prompts/tech_prompt.txt
mv prompts/default_prompt_example.txt prompts/default_prompt.txt
```

也可以根据需求自定义修改各个提示词文件。

### 使用方法

运行主程序：
```bash
python main.py
```

### 自定义提示词

可以通过编辑 `prompts` 目录下的文件来自定义各个专家的提示词：

- `classify_prompt.txt`: 意图分类提示词
- `price_prompt.txt`: 价格专家提示词
- `tech_prompt.txt`: 技术专家提示词
- `default_prompt.txt`: 默认回复提示词

## 🤝 参与贡献

欢迎通过 Issue 提交建议或 PR 贡献代码，请遵循 [贡献指南](https://contributing.md/)



## 🛡 注意事项

⚠️ 注意：**本项目仅供学习与交流，如有侵权联系作者删除。**

鉴于项目的特殊性，开发团队可能在任何时间**停止更新**或**删除项目**。

如需学习交流，请联系：[coderxiu@qq.com](https://mailto:coderxiu@qq.com/)

## 🧸特别鸣谢
本项目参考了以下开源项目：
https://github.com/cv-cat/XianYuApis

感谢<a href="https://github.com/cv-cat">@CVcat</a>的技术支持

## 📱 交流群
欢迎加入项目交流群，交流技术、分享经验、互助学习。
<div align="center">
  <table>
    <tr>
      <td align="center"><strong>交流群9（已满200）</strong></td>
      <td align="center"><strong>交流群10（推荐加入）</strong></td>
    </tr>
    <tr>
      <td><img src="./images/wx_group9-1.png" width="300px" alt="交流群1"></td>
      <td><img src="./images/wx_group10-1.png" width="300px" alt="交流群2"></td>
    </tr>
  </table>
</div>

## 💼 寻找机会

### <a href="https://github.com/shaxiu">@Shaxiu</a>
**🔍寻求方向**：**AI产品经理**  
**🛠️项目贡献：**：需求分析、agent方案设计与实现  
**📫 联系：** **email**:coderxiu@qq.com；**wx:** coderxiu

### <a href="https://github.com/cv-cat">@CVcat</a>
**🔍寻求方向**：**研发工程师**（python、java、逆向、爬虫）  
**🛠️项目贡献：**：闲鱼逆向工程  
**📫 联系：** **email:** 992822653@qq.com；**wx:** CVZC15751076989
## ☕ 请喝咖啡
您的☕和⭐将助力项目持续更新：

<div align="center">
  <img src="./images/wechat_pay.jpg" width="400px" alt="微信赞赏码"> 
  <img src="./images/alipay.jpg" width="400px" alt="支付宝收款码">
</div>


## 📈 Star 趋势
<a href="https://www.star-history.com/#shaxiu/XianyuAutoAgent&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=shaxiu/XianyuAutoAgent&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=shaxiu/XianyuAutoAgent&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=shaxiu/XianyuAutoAgent&type=Date" />
 </picture>
</a>


