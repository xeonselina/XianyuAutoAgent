# 🚀 快速开始指南

5 分钟快速上手闲鱼 AI 客服系统！

## 📋 前置要求

- Python 3.8+
- 闲鱼账号
- AI 模型 API Key（推荐：通义千问）

## ⚡ 快速安装

### 1. 克隆项目

```bash
git clone https://github.com/shaxiu/XianyuAutoAgent.git
cd XianyuAutoAgent/ai_kefu
```

### 2. 安装依赖

```bash
# 使用 Makefile（推荐）
make install

# 或手动安装
pip install -r requirements.txt

# 安装 Chromium 浏览器
playwright install chromium
```

### 3. 配置环境

```bash
# 复制配置模板
cp .env.example .env

# 编辑配置文件
nano .env  # 或使用您喜欢的编辑器
```

**必填配置**：
```ini
# 通义千问 API Key
API_KEY=your_api_key_here
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max

# 浏览器配置
BROWSER_HEADLESS=false  # 显示浏览器窗口（推荐调试时使用）
```

**可选配置**：
```ini
# 闲鱼 Cookie（可选，不设置则使用浏览器保存的会话）
COOKIES_STR=your_cookies_here
```

### 4. 获取 Cookie（可选）

**注意**：这是可选步骤。如果不提供 Cookie，系统会使用浏览器保存的会话，首次运行时需要手动登录。

如果想提供 Cookie：

1. 浏览器打开 https://www.goofish.com/
2. 按 F12 打开开发者工具
3. 切换到 Network 标签
4. 刷新页面，点击任意请求
5. 在 Headers 中找到 Cookie，复制完整值
6. 粘贴到 `.env` 文件的 `COOKIES_STR` 变量中

### 5. 配置提示词（可选）

```bash
# 复制示例提示词
mv prompts/classify_prompt_example.txt prompts/classify_prompt.txt
mv prompts/price_prompt_example.txt prompts/price_prompt.txt
mv prompts/tech_prompt_example.txt prompts/tech_prompt.txt
mv prompts/default_prompt_example.txt prompts/default_prompt.txt

# 根据需要编辑提示词文件
```

### 6. 启动系统

```bash
# 使用 Makefile
make run-xianyu

# 或直接运行
python main.py
```

**看到以下日志表示启动成功**：
```
INFO | 使用浏览器模式 (BrowserWebSocketTransport)
INFO | 正在启动浏览器...
INFO | 💡 提示：请在浏览器中点击进入消息中心或任意聊天
INFO | 📡 已启动全局页面监控（包括刷新检测和弹窗检测）
```

**接下来的步骤**：
1. 浏览器会自动打开闲鱼首页
2. 如果未提供 COOKIES_STR，请手动登录闲鱼账号
3. 点击进入消息中心或任意聊天
4. 系统会自动检测 WebSocket 连接并开始工作

**看到以下提示表示连接成功**：
```
INFO | ✅ WebSocket 连接已建立
INFO | 🎉 浏览器 WebSocket 传输建立成功！
```

## 🎯 功能测试

启动系统后，在闲鱼上给自己发送消息，测试以下功能：

### 1. 自动回复
- 用户：你好
- 预期：AI 自动回复

### 2. 人工接管
- 卖家发送：`。`（句号）
- 预期：切换到人工模式，AI 停止自动回复
- 再次发送：`。`
- 预期：切换回自动模式

### 3. 议价功能
- 用户：能便宜点吗？
- 预期：AI 根据议价策略回复

### 4. 技术问题
- 用户：这个怎么用？
- 预期：AI 提供技术支持

## 📊 日志说明

### 正常运行日志
```
INFO  | 用户 ID: xxx, 商品: xxx, 会话: xxx, 消息: xxx
INFO  | 机器人回复: xxx
```

### 人工接管日志
```
INFO  | 🔴 已接管会话 xxx (商品: xxx)
INFO  | 🟢 已恢复会话 xxx 的自动回复 (商品: xxx)
```

### 调试日志
```bash
# 开启调试模式
# 编辑 .env
LOG_LEVEL=DEBUG
```

## 🔧 常见问题

### Q1: 系统无法建立 WebSocket 连接

**可能原因**：
1. 未手动在浏览器中进入消息中心
2. 浏览器未登录闲鱼账号
3. 页面加载未完成

**解决方案**：
- 确保在浏览器中手动登录闲鱼
- 点击进入消息中心或任意聊天页面
- 如果已进入，尝试刷新页面（F5）

**查看详细日志**：
```bash
# 设置日志级别为 DEBUG
LOG_LEVEL=DEBUG
```

### Q2: AI 不回复

**可能原因**：
1. API Key 错误 → 检查 .env 中的 API_KEY
2. 模型服务不可用 → 检查 MODEL_BASE_URL
3. 会话处于人工接管模式 → 发送 `。` 切换回自动模式

**解决方案**：
```bash
# 检查配置
make check-env

# 查看日志
tail -f logs/xianyu_*.log
```

### Q3: Playwright 安装失败

**解决方案**：
```bash
# 方法1: 手动安装
playwright install chromium

# 方法2: 使用镜像（国内网络）
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
playwright install chromium

# 方法3: 使用代理
export HTTP_PROXY=http://your-proxy:port
export HTTPS_PROXY=http://your-proxy:port
playwright install chromium
```

### Q4: 浏览器用户数据目录权限问题

**解决方案**：
```bash
# 删除旧的用户数据目录
rm -rf browser_data/

# 重新启动系统
python main.py
```

### Q5: 提示缺少模块

**解决方案**：
```bash
# 重新安装依赖
make install

# 或手动安装
pip install -r requirements.txt
```

## 📖 进阶配置

### 浏览器配置

```ini
# 浏览器窗口大小
BROWSER_VIEWPORT_WIDTH=1920
BROWSER_VIEWPORT_HEIGHT=1080

# 无头模式（不显示浏览器窗口）
BROWSER_HEADLESS=true

# 浏览器代理
BROWSER_PROXY=http://proxy:port
```

### 消息处理配置

```ini
# 消息过期时间（毫秒）
MESSAGE_EXPIRE_TIME=600000  # 10分钟

# 人工接管超时时间（秒）
MANUAL_MODE_TIMEOUT=7200  # 2小时

# 人工接管切换关键词
TOGGLE_KEYWORDS=。
```

### 日志配置

```ini
# 日志级别（DEBUG, INFO, WARNING, ERROR）
LOG_LEVEL=INFO

# 日志文件位置
# 默认保存在 logs/ 目录，按日期分割，保留30天
```

## 🧪 运行测试

```bash
# 安装测试依赖
make install-dev

# 运行所有测试
make test

# 运行单元测试
make test-unit

# 运行集成测试
make test-integration

# 查看测试覆盖率
make test-cov
```

## 🐳 Docker 部署（可选）

```bash
# 构建镜像
make docker-build

# 启动服务
make docker-up

# 查看日志
make docker-logs

# 停止服务
make docker-down
```

## 📚 更多文档

- [README.md](./README.md) - 完整文档
- [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) - 迁移指南
- [CHANGELOG.md](./CHANGELOG.md) - 更新日志
- [tests/README.md](./tests/README.md) - 测试文档

## 💬 获取帮助

- **Issues**: https://github.com/shaxiu/XianyuAutoAgent/issues
- **Email**: coderxiu@qq.com
- **微信群**: 见 README.md

## 🎉 开始使用

现在您已经完成了所有设置，可以开始使用了！

**推荐流程**：
1. ✅ 首次运行时使用非无头模式（BROWSER_HEADLESS=false），便于调试
2. ✅ 根据需要调整提示词和配置
3. ✅ 测试各项功能确保正常工作
4. ✅ 稳定后可以切换到无头模式（BROWSER_HEADLESS=true）用于生产环境

祝使用愉快！🚀
