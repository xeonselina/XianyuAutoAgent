# 迁移指南

本文档帮助您从旧版本（单体架构）迁移到新版本（分层架构 + 双传输模式）。

## 版本对比

| 特性 | 旧版本 | 新版本 |
|------|--------|--------|
| 架构 | 单体架构 | 分层架构 |
| 传输模式 | 仅直接 WebSocket | 直接模式 + 浏览器模式 |
| 代码行数 (main.py) | ~570 行 | ~390 行 |
| 可扩展性 | 低 | 高 |
| 可视化调试 | ❌ | ✅ (浏览器模式) |
| 向后兼容 | - | ✅ 完全兼容 |

## 迁移策略

新版本**完全向后兼容**旧版本。如果您不做任何配置更改，系统将以直接模式运行，行为与旧版本完全一致。

### 推荐迁移路径

```
阶段 1: 无缝升级（0 配置更改）
  ↓
阶段 2: 体验浏览器模式（可选）
  ↓  
阶段 3: 根据需求选择模式
```

## 阶段 1: 无缝升级

### 1.1 备份现有代码

```bash
# 备份当前版本
cp -r /path/to/ai_kefu /path/to/ai_kefu_backup
```

### 1.2 更新代码

```bash
# 拉取最新代码
cd /path/to/XianyuAutoAgent
git pull origin main

# 或者直接下载最新版本
```

### 1.3 安装新依赖

```bash
cd ai_kefu
pip install -r requirements.txt
```

> **注意**: 如果您不打算使用浏览器模式，无需安装 Playwright。

### 1.4 验证配置文件

检查您的 `.env` 文件，确保包含所需配置：

```bash
# 查看现有配置
cat .env
```

**必需的配置项**（与旧版本相同）：
```ini
API_KEY=your_api_key
COOKIES_STR=your_cookies
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen-max
```

**新增的可选配置项**（默认值确保向后兼容）：
```ini
# 传输模式（默认 false，即直接模式）
USE_BROWSER_MODE=false
```

### 1.5 运行测试

```bash
# 启动系统
python main.py
```

**预期行为**：
- ✅ 系统应该正常启动
- ✅ 日志显示 "使用直接模式 (DirectWebSocketTransport)"
- ✅ 所有功能与旧版本行为一致

### 1.6 验证功能

- ✅ 能够接收闲鱼消息
- ✅ AI 自动回复正常
- ✅ 人工接管功能正常
- ✅ 上下文记忆正常
- ✅ 议价功能正常

如果以上都正常，**迁移完成**！您可以继续使用直接模式，或者进入阶段 2 体验浏览器模式。

## 阶段 2: 体验浏览器模式（可选）

### 2.1 安装 Playwright

```bash
# 安装 Playwright 浏览器驱动
playwright install chromium
```

### 2.2 配置浏览器模式

编辑 `.env` 文件，添加或修改以下配置：

```ini
# 启用浏览器模式
USE_BROWSER_MODE=true

# 显示浏览器窗口（便于观察）
BROWSER_HEADLESS=false

# 浏览器窗口大小
BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=720
```

### 2.3 启动浏览器模式

```bash
python main.py
```

**预期行为**：
- ✅ 日志显示 "使用浏览器模式 (BrowserWebSocketTransport)"
- ✅ Chromium 浏览器窗口自动打开
- ✅ 自动导航到 https://www.goofish.com/
- ✅ 可以在浏览器中看到实时聊天

### 2.4 浏览器模式优势

- **可视化调试**: 实时查看消息收发
- **真实环境**: 更接近真实用户行为
- **便于开发**: 方便观察和调试问题

### 2.5 切换回直接模式

如果浏览器模式不适合您的场景，随时可以切换回直接模式：

```ini
# 编辑 .env
USE_BROWSER_MODE=false
```

## 阶段 3: 生产部署建议

### 开发环境配置

```ini
# 使用浏览器模式，便于调试
USE_BROWSER_MODE=true
BROWSER_HEADLESS=false
LOG_LEVEL=DEBUG
```

### 生产环境配置

```ini
# 使用直接模式，稳定高效
USE_BROWSER_MODE=false
LOG_LEVEL=INFO

# 心跳和 Token 配置
HEARTBEAT_INTERVAL=15
HEARTBEAT_TIMEOUT=5
TOKEN_REFRESH_INTERVAL=3600
```

## 常见问题

### Q1: 迁移后系统无法启动

**A**: 检查以下几点：
1. 确保安装了所有依赖：`pip install -r requirements.txt`
2. 检查 `.env` 配置是否正确
3. 查看错误日志，定位具体问题

### Q2: 浏览器模式启动失败

**A**: 可能的原因：
1. 未安装 Playwright：运行 `playwright install chromium`
2. 系统缺少浏览器依赖：
   ```bash
   # Ubuntu/Debian
   sudo apt-get install libnss3 libatk1.0-0 libatk-bridge2.0-0
   ```
3. 切换回直接模式继续使用：`USE_BROWSER_MODE=false`

### Q3: 新旧版本功能对比

**A**: 新版本完全兼容旧版本功能：
- ✅ 所有旧功能保持不变
- ✅ 新增浏览器模式（可选）
- ✅ 代码更加模块化，便于维护
- ✅ 更好的扩展性

### Q4: 如何回滚到旧版本？

**A**: 参见下方「回滚方案」章节。

### Q5: 性能有影响吗？

**A**: 
- **直接模式**: 性能与旧版本完全一致
- **浏览器模式**: 额外的浏览器进程会占用更多资源（~100-200MB 内存）

### Q6: 配置文件需要大量修改吗？

**A**: 不需要！如果不修改任何配置，系统默认使用直接模式，行为与旧版本完全相同。

## 回滚方案

如果迁移过程中遇到问题，可以快速回滚到旧版本。

### 方法 1: 使用备份恢复

```bash
# 停止新版本
pkill -f "python main.py"

# 恢复备份
rm -rf /path/to/ai_kefu
cp -r /path/to/ai_kefu_backup /path/to/ai_kefu

# 重启旧版本
cd /path/to/ai_kefu
python main.py
```

### 方法 2: Git 回滚

```bash
# 查看提交历史
git log --oneline

# 回滚到特定版本（替换 <commit-id>）
git checkout <commit-id>

# 重新安装旧版本依赖
pip install -r requirements.txt

# 重启
python main.py
```

### 方法 3: 保留新代码，禁用新功能

新版本设计了完全向后兼容，无需回滚代码即可恢复旧行为：

```ini
# .env 配置
USE_BROWSER_MODE=false  # 使用直接模式（旧版本行为）
```

## 迁移检查清单

使用以下清单确保迁移成功：

### 迁移前

- [ ] 备份现有代码和配置
- [ ] 记录当前系统运行状态
- [ ] 准备测试用例

### 迁移中

- [ ] 更新代码到最新版本
- [ ] 安装新依赖 `pip install -r requirements.txt`
- [ ] 检查 `.env` 配置文件
- [ ] （可选）安装 Playwright：`playwright install chromium`

### 迁移后

- [ ] 验证系统能正常启动
- [ ] 测试消息接收功能
- [ ] 测试 AI 自动回复
- [ ] 测试人工接管模式
- [ ] 测试上下文记忆
- [ ] 测试议价功能
- [ ] （可选）测试浏览器模式
- [ ] 监控系统运行 24 小时

## 技术架构变更说明

### 代码结构对比

#### 旧版本 (main.py ~570 行)
```
main.py
  ├── WebSocket 连接管理
  ├── 心跳维护
  ├── Token 刷新
  ├── 消息解析
  ├── 消息处理
  └── 业务逻辑
```

#### 新版本（分层架构）
```
传输层 (transports.py)
  ├── DirectWebSocketTransport
  └── BrowserWebSocketTransport

抽象层 (messaging_core.py)
  ├── MessageTransport 接口
  ├── XianyuMessageCodec
  └── MessageRouter

浏览器层
  ├── BrowserController (browser_controller.py)
  └── CDPInterceptor (cdp_interceptor.py)

应用层 (main.py ~390 行)
  ├── XianyuLive
  └── create_transport()
```

### 主要改进

1. **关注点分离**: 传输逻辑与业务逻辑解耦
2. **可扩展性**: 新增传输方式只需实现 MessageTransport 接口
3. **可测试性**: 各层独立测试，100+ 单元测试覆盖
4. **可维护性**: 代码模块化，职责清晰

## 获得帮助

如果迁移过程中遇到问题：

1. **查看日志**: 设置 `LOG_LEVEL=DEBUG` 获取详细日志
2. **查看文档**: 
   - README.md - 用户文档
   - tests/README.md - 测试文档
   - .env.example - 配置示例
3. **提交 Issue**: https://github.com/shaxiu/XianyuAutoAgent/issues
4. **联系开发者**: coderxiu@qq.com

## 总结

新版本提供：
- ✅ **0 配置迁移**: 不改配置，行为与旧版本完全一致
- ✅ **完全向后兼容**: 所有旧功能正常工作
- ✅ **新增可选功能**: 浏览器模式随时可用
- ✅ **更好的架构**: 模块化设计，便于维护和扩展

**建议迁移步骤**:
1. 阶段 1：无缝升级（使用直接模式）
2. 验证所有功能正常
3. 根据需求决定是否启用浏览器模式

迁移过程安全、简单、可逆！
