# 更新日志

本文档记录项目的所有重要变更。

## [2.0.0] - 2025-01-XX

### 🎉 重大更新：架构重构 + 双传输模式

本次更新实现了完整的架构重构，引入模块化设计和双传输模式，同时保持 100% 向后兼容。

### ✨ 新增功能

#### 双传输模式
- **直接模式** (DirectWebSocketTransport)
  - 直接建立 WebSocket 连接到闲鱼服务器
  - 无界面运行，资源占用低
  - 适合服务器部署（默认模式，与旧版本行为完全一致）
  
- **浏览器模式** (BrowserWebSocketTransport)
  - 通过 Chromium 浏览器打开闲鱼网页
  - 使用 CDP (Chrome DevTools Protocol) 拦截 WebSocket
  - 可视化界面，便于调试和监控
  - 支持无头模式和有头模式

#### 核心组件

**消息抽象层** (`messaging_core.py` - 459 行)
- `MessageType` 枚举：5 种消息类型分类
- `Message` 数据类：标准化消息对象
- `MessageTransport` 抽象基类：统一传输接口
- `XianyuMessageCodec`：闲鱼消息编解码器
- `MessageRouter`：消息路由分发器

**浏览器控制层**
- `BrowserController` (`browser_controller.py` - 273 行)
  - Playwright Chromium 生命周期管理
  - Cookie 注入/提取
  - 崩溃检测和自动恢复
  - 截图调试功能
  - CDP 会话管理
  
- `CDPInterceptor` (`cdp_interceptor.py` - 295 行)
  - WebSocket 事件监控
  - 消息拦截和注入
  - JavaScript 执行

**传输实现层** (`transports.py` - 441 行)
- `DirectWebSocketTransport`：保留所有原有逻辑
  - 心跳维护
  - Token 自动刷新
  - 连接重启
- `BrowserWebSocketTransport`：全新浏览器模式
  - 集成 BrowserController
  - 集成 CDPInterceptor
  - 可视化消息流

#### 配置管理
- 新增 13 个配置项（详见 `.env.example`）
- **传输模式配置**：
  - `USE_BROWSER_MODE`: 选择传输模式
- **浏览器配置**（7 项）：
  - `BROWSER_HEADLESS`: 无头模式开关
  - `BROWSER_DEBUG_PORT`: 调试端口
  - `BROWSER_USER_DATA_DIR`: 数据目录
  - `BROWSER_VIEWPORT_WIDTH`: 窗口宽度
  - `BROWSER_VIEWPORT_HEIGHT`: 窗口高度
  - `BROWSER_PROXY`: 代理服务器
- **直接模式配置**（4 项，保留原有配置）：
  - `HEARTBEAT_INTERVAL`
  - `HEARTBEAT_TIMEOUT`
  - `TOKEN_REFRESH_INTERVAL`
  - `TOKEN_RETRY_INTERVAL`

#### 测试框架
- 新增完整测试套件（100+ 测试用例）
- `test_messaging_core.py`：消息核心模块测试（200+ 行）
- `test_transports.py`：传输层测试（180+ 行）
- `test_integration.py`：集成测试（200+ 行）
- 支持测试覆盖率报告
- 支持 CI/CD 集成

#### 文档
- **MIGRATION_GUIDE.md**: 详细迁移指南
- **tests/README.md**: 测试文档
- **CHANGELOG.md**: 本文件
- 更新 README.md：
  - 新增「传输模式」章节
  - 更新安装步骤
  - 详细配置说明

### 🔄 改进

#### 架构优化
- **代码行数减少**: `main.py` 从 570 行减少到 390 行（-31%）
- **关注点分离**: 传输逻辑与业务逻辑完全解耦
- **依赖注入**: `XianyuLive` 通过构造函数接收 `transport` 和 `bot`
- **工厂模式**: `create_transport()` 根据配置创建传输实例
- **自动重连**: 新的 `run()` 方法支持连接断开后自动重连

#### 消息处理
- 使用 `XianyuMessageCodec` 统一编解码
- 消息类型自动分类（CHAT, TYPING, SYSTEM, ORDER, UNKNOWN）
- 标准化消息对象 `Message`
- 更清晰的错误处理和日志

#### 可扩展性
- 新增传输方式只需实现 `MessageTransport` 接口
- 支持注册多个消息处理器
- 支持全局和分类消息路由

### 🐛 修复
- 修复了原有代码中潜在的连接泄漏问题
- 改进了异常处理和错误隔离
- 优化了 Token 刷新逻辑

### 📦 依赖更新
- 新增 `playwright>=1.40.0`（可选，仅浏览器模式需要）
- 新增 `pytest-asyncio>=0.21.0`（测试依赖）

### ⚠️ 破坏性变更
**无破坏性变更**！本次更新 100% 向后兼容。

- 默认使用直接模式（`USE_BROWSER_MODE=false`）
- 所有原有配置继续有效
- 所有原有功能正常工作
- 无需修改任何代码或配置即可升级

### 📊 统计数据

| 指标 | 旧版本 | 新版本 | 变化 |
|------|--------|--------|------|
| 总代码行数 | ~570 | ~1,858 | +1,288 |
| main.py 行数 | ~570 | ~390 | -180 (-31%) |
| 模块数量 | 1 | 4 | +3 |
| 测试用例 | 0 | 100+ | +100+ |
| 支持的传输模式 | 1 | 2 | +1 |
| 配置项 | 9 | 22 | +13 |

### 🎯 文件清单

**新增文件**:
- `messaging_core.py` (459 行) - 消息抽象层
- `browser_controller.py` (273 行) - 浏览器控制
- `cdp_interceptor.py` (295 行) - CDP 拦截
- `transports.py` (441 行) - 传输实现
- `MIGRATION_GUIDE.md` - 迁移指南
- `CHANGELOG.md` - 本文件
- `tests/test_messaging_core.py` (200+ 行)
- `tests/test_transports.py` (180+ 行)
- `tests/test_integration.py` (200+ 行)
- `tests/conftest.py` - Pytest 配置
- `tests/README.md` - 测试文档

**修改文件**:
- `main.py` (570 → 390 行) - 重构为使用传输抽象
- `requirements.txt` - 新增依赖
- `.env.example` - 新增配置项
- `README.md` - 更新文档

### 🚀 升级指南
详见 [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md)

**最简升级步骤**：
```bash
# 1. 备份
cp -r ai_kefu ai_kefu_backup

# 2. 更新代码
git pull

# 3. 安装依赖
pip install -r requirements.txt

# 4. 运行（无需修改配置）
python main.py
```

### 👥 贡献者
- [@shaxiu](https://github.com/shaxiu) - 架构设计与实现
- [@cv-cat](https://github.com/cv-cat) - 技术支持

---

## [1.0.0] - 2024-XX-XX

### ✨ 初始版本

- 基础 AI 客服功能
- 直接 WebSocket 连接
- 意图识别和专家路由
- 阶梯议价系统
- 上下文记忆管理
- 人工接管模式

---

## 版本命名规范

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范：

- **主版本号 (Major)**: 不兼容的 API 变更
- **次版本号 (Minor)**: 向下兼容的功能新增
- **修订号 (Patch)**: 向下兼容的问题修正

示例：
- `1.0.0` → `2.0.0`: 重大架构变更（本次更新，但保持向后兼容）
- `2.0.0` → `2.1.0`: 新增功能
- `2.1.0` → `2.1.1`: Bug 修复
