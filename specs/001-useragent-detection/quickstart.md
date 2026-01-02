# 快速入门: User-Agent 设备检测

**功能**: 001-useragent-detection
**目标**: 快速理解、测试和部署 user-agent 设备检测功能

---

## 概览

此功能使用 user-agent 字符串自动检测访问设备类型,并提供相应的前端界面版本:
- **移动设备** (手机、平板) → 移动版界面
- **桌面设备** → 桌面版界面
- **未知设备** → 默认桌面版

---

## 快速开始 (5 分钟)

### 1. 安装依赖

```bash
# 进入项目目录
cd /Users/jimmypan/git_repo/XianyuAutoAgent/InventoryManager

# 安装 Python 依赖
pip install user-agents

# 或使用 requirements.txt
echo "user-agents==2.2.0" >> requirements.txt
pip install -r requirements.txt
```

### 2. 测试设备检测

```python
# 快速测试
python3 << 'EOF'
from user_agents import parse

# 测试移动设备
ua_mobile = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) ..."
ua = parse(ua_mobile)
print(f"Mobile: {ua.is_mobile}")  # True

# 测试桌面设备
ua_desktop = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."
ua = parse(ua_desktop)
print(f"Desktop: {ua.is_pc}")  # True
EOF
```

### 3. 运行开发服务器

```bash
# 启动后端
python app.py

# 另一个终端: 启动桌面前端 dev server
cd frontend
npm run dev  # 端口 5002

# 另一个终端: 启动移动前端 dev server
cd frontend-mobile
npm run dev  # 端口 5174
```

### 4. 测试浏览器访问

访问 `http://localhost:5001/` (或配置的端口):
- 使用桌面浏览器 → 看到桌面版
- 使用手机/平板 → 看到移动版
- 使用浏览器开发工具模拟设备 → 对应版本

---

## 本地测试设备检测

### 方法 1: 浏览器开发工具

**Chrome/Edge DevTools**:
1. 打开 DevTools (F12)
2. 点击 "Toggle device toolbar" 图标 (或 Ctrl+Shift+M)
3. 选择设备 (iPhone, iPad, Android 等)
4. 刷新页面

**Firefox Responsive Design Mode**:
1. 打开开发工具 (F12)
2. 点击 "Responsive Design Mode" 图标 (或 Ctrl+Shift+M)
3. 选择设备预设
4. 刷新页面

### 方法 2: curl 命令测试

```bash
# 测试移动设备 UA
curl -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1" \
  http://localhost:5001/

# 测试桌面 UA
curl -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36" \
  http://localhost:5001/

# 测试平板 UA (iPad)
curl -H "User-Agent: Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1" \
  http://localhost:5001/
```

### 方法 3: Python 测试脚本

```python
# test_device_detection.py
import requests

base_url = "http://localhost:5001"

test_cases = [
    ("iPhone", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"),
    ("iPad", "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"),
    ("Android Phone", "Mozilla/5.0 (Linux; Android 13; SM-S910B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"),
    ("Chrome Windows", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"),
    ("Safari macOS", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"),
]

for name, ua in test_cases:
    response = requests.get(base_url, headers={"User-Agent": ua})
    print(f"{name}: Status {response.status_code}, Content-Length {len(response.content)}")
```

运行: `python test_device_detection.py`

---

## 构建与部署

### 开发环境

```bash
# 1. 构建前端
make frontend-build-all

# 或分别构建
make frontend-build        # 桌面版
make frontend-mobile-build # 移动版

# 2. 启动开发服务器
python app.py
```

### 生产部署

```bash
# 1. 构建生产版本
NODE_ENV=production make frontend-build-all

# 2. 确保静态文件就位
ls -la static/vue-dist/
ls -la static/mobile-dist/

# 3. 启动生产服务器
gunicorn -w 4 -b 0.0.0.0:8000 app:app

# 或使用 Docker
docker build -t inventory-manager .
docker run -p 8000:8000 inventory-manager
```

---

## 常见问题排查

### 问题 1: 设备检测不正确

**症状**: 移动设备显示桌面版,或反之

**检查步骤**:
1. 查看后端日志中的 user-agent 字符串
2. 测试 user-agents 库是否正确识别:
   ```python
   from user_agents import parse
   ua = parse("你的 user-agent 字符串")
   print(f"is_mobile: {ua.is_mobile}, is_tablet: {ua.is_tablet}, is_pc: {ua.is_pc}")
   ```
3. 确认路由逻辑正确执行

**常见原因**:
- 浏览器隐私工具修改了 UA
- 移动浏览器的"请求桌面站点"模式
- 不常见的设备/浏览器

**解决方案**:
- 添加日志记录所有 UA 字符串
- 检查边界情况处理逻辑
- 如需要,添加手动切换选项

### 问题 2: 静态资源 404 错误

**症状**: 页面加载但 CSS/JS 文件找不到

**检查步骤**:
1. 确认构建输出目录:
   ```bash
   ls -la static/vue-dist/assets/
   ls -la static/mobile-dist/assets/
   ```
2. 检查 Vite 配置的 `base` path
3. 查看浏览器 Network 面板的请求路径

**解决方案**:
- 重新构建前端: `make frontend-build-all`
- 检查 `vite.config.ts` 中的 `base: '/'` 配置
- 确认后端静态资源路由正确

### 问题 3: 开发服务器代理问题

**症状**: 开发时 API 请求失败

**检查步骤**:
1. 确认后端 Flask 服务器运行
2. 检查 Vite dev server 配置中的 proxy 设置
3. 查看浏览器 Console 的错误信息

**解决方案**:
- 确保后端在正确端口运行
- 检查 `vite.config.ts` 中的 proxy 配置
- 使用绝对 URL 临时绕过代理测试

### 问题 4: user-agents 库未安装

**症状**: `ImportError: No module named 'user_agents'`

**解决方案**:
```bash
pip install user-agents

# 确认安装成功
python -c "import user_agents; print(user_agents.__version__)"
```

---

## 测试清单

### 功能测试

- [ ] ✅ iPhone 访问显示移动版
- [ ] ✅ iPad 访问显示移动版
- [ ] ✅ Android 手机访问显示移动版
- [ ] ✅ Android 平板访问显示移动版
- [ ] ✅ Windows Chrome 访问显示桌面版
- [ ] ✅ macOS Safari 访问显示桌面版
- [ ] ✅ Linux Firefox 访问显示桌面版

### 边界情况测试

- [ ] ✅ 微信内置浏览器访问 (基于 OS)
- [ ] ✅ 无 user-agent 头访问 (默认桌面版)
- [ ] ✅ 不识别的 user-agent 访问 (默认桌面版)
- [ ] ✅ 移动浏览器"请求桌面站点"模式
- [ ] ✅ 浏览器开发工具设备模拟

### 兼容性测试

- [ ] ✅ 旧 URL `/vue/` 仍可访问 (如保留)
- [ ] ✅ 旧 URL `/mobile/` 仍可访问 (如保留)
- [ ] ✅ 所有现有功能正常工作
- [ ] ✅ Session 在设备切换后保持

### 性能测试

- [ ] ✅ 首次页面加载时间 < 2秒
- [ ] ✅ 设备检测延迟 < 10ms
- [ ] ✅ 100 并发用户正常工作

---

## 配置选项

### 环境变量

```bash
# .env 文件
FLASK_ENV=development              # 环境: development | production
DEVICE_DETECTION_LOG=true          # 是否记录设备检测日志
DEFAULT_DEVICE_TYPE=desktop        # 默认设备类型 (无法识别时)
ENABLE_LEGACY_URLS=true            # 是否启用旧 URL 兼容
```

### 应用配置

```python
# config.py
class Config:
    # 设备检测配置
    DEVICE_DETECTION_CACHE_SIZE = 1024  # LRU 缓存大小
    DEVICE_DETECTION_TIMEOUT = 100      # 检测超时 (ms)
    DEFAULT_DEVICE_TYPE = 'desktop'     # 默认设备类型

    # 静态文件路径
    DESKTOP_DIST_PATH = 'static/vue-dist'
    MOBILE_DIST_PATH = 'static/mobile-dist'
```

---

## 监控与日志

### 关键指标

监控以下指标以确保功能正常:

1. **设备检测准确率**: 移动/桌面检测的正确率
2. **检测延迟**: user-agent 解析时间
3. **错误率**: 检测失败或异常的比例
4. **设备分布**: 移动 vs 桌面访问比例

### 日志示例

```python
# 添加到 app/routes/vue_app.py
import logging

logger = logging.getLogger(__name__)

@app.route('/')
def index():
    ua_string = request.headers.get('User-Agent', '')
    device_type = detect_device_type(ua_string)

    # 记录设备检测
    logger.info(f"Device detection: {device_type} | UA: {ua_string[:100]}")

    # 统计 (可选)
    metrics.increment(f'device.{device_type}')

    return serve_frontend(device_type)
```

### 日志查询

```bash
# 查看最近的设备检测日志
tail -f logs/app.log | grep "Device detection"

# 统计移动 vs 桌面比例
grep "Device detection" logs/app.log | grep -c "mobile"
grep "Device detection" logs/app.log | grep -c "desktop"
```

---

## 下一步

完成快速入门后:

1. **阅读完整文档**: [spec.md](./spec.md) - 功能规格说明
2. **查看研究结果**: [research.md](./research.md) - 技术决策和最佳实践
3. **理解实施计划**: [plan.md](./plan.md) - 完整实施策略
4. **执行任务**: [tasks.md](./tasks.md) - 具体实施步骤 (待生成)

---

## 参考资料

- [user-agents 库文档](https://pypi.org/project/user-agents/)
- [Flask 文档](https://flask.palletsprojects.com/)
- [Vite 配置指南](https://vitejs.dev/config/)
- [MDN User-Agent 参考](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/User-Agent)

---

**文档版本**: 1.0
**最后更新**: 2026-01-01
**状态**: 完成
