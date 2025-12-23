# 测试文档

本目录包含闲鱼 AI 客服系统的自动化测试。

## 测试结构

```
tests/
├── __init__.py              # 测试包初始化
├── conftest.py              # Pytest 配置和固件
├── test_messaging_core.py   # 消息核心模块测试
├── test_transports.py       # 传输层测试
├── test_integration.py      # 集成测试
└── README.md                # 本文件
```

## 测试覆盖范围

### 1. 消息核心模块测试 (`test_messaging_core.py`)

- ✅ `MessageType` 枚举测试
- ✅ `Message` 数据类测试
- ✅ `XianyuMessageCodec` 编解码测试
  - 消息编码
  - 消息解码
  - 消息分类
  - 消息数据提取
- ✅ `MessageRouter` 路由测试
  - 处理器注册
  - 消息分发
  - 错误隔离

### 2. 传输层测试 (`test_transports.py`)

- ✅ `DirectWebSocketTransport` 测试
  - 初始化配置
  - 连接状态管理
  - 消息发送
  - 断开连接
- ✅ `BrowserWebSocketTransport` 测试
  - 初始化配置
  - 浏览器控制
  - CDP 拦截
  - 连接状态管理
- ✅ `BrowserConfig` 配置测试
  - 默认配置
  - 环境变量加载
  - 参数解析

### 3. 集成测试 (`test_integration.py`)

- ✅ `XianyuLive` 主应用测试
  - 初始化流程
  - 人工接管模式
  - 上下文管理
  - 议价次数跟踪
- ✅ 传输工厂测试
  - 直接模式创建
  - 浏览器模式创建
  - 默认行为
- ✅ 端到端流程测试
  - 完整消息流程
  - 重连逻辑

## 运行测试

### 安装测试依赖

```bash
pip install pytest pytest-asyncio pytest-cov pytest-mock
```

### 运行所有测试

```bash
# 从项目根目录运行
cd /path/to/XianyuAutoAgent/ai_kefu
python -m pytest tests/ -v
```

### 运行特定测试文件

```bash
# 只运行消息核心测试
python -m pytest tests/test_messaging_core.py -v

# 只运行传输层测试
python -m pytest tests/test_transports.py -v

# 只运行集成测试
python -m pytest tests/test_integration.py -v
```

### 运行特定测试类或方法

```bash
# 运行特定测试类
python -m pytest tests/test_messaging_core.py::TestMessageType -v

# 运行特定测试方法
python -m pytest tests/test_messaging_core.py::TestMessageType::test_message_types -v
```

### 生成测试覆盖率报告

```bash
# 生成 HTML 覆盖率报告
python -m pytest tests/ --cov=. --cov-report=html

# 查看覆盖率报告
open htmlcov/index.html  # macOS
# 或
xdg-open htmlcov/index.html  # Linux
```

### 生成终端覆盖率报告

```bash
python -m pytest tests/ --cov=. --cov-report=term-missing
```

## 测试选项

```bash
# 显示详细输出
pytest tests/ -v

# 显示测试打印输出
pytest tests/ -s

# 只运行失败的测试
pytest tests/ --lf

# 并行运行测试（需要 pytest-xdist）
pytest tests/ -n auto

# 生成 JUnit XML 报告（CI/CD 集成）
pytest tests/ --junitxml=test-results.xml
```

## 编写新测试

### 测试命名规范

- 测试文件：`test_*.py`
- 测试类：`Test*`
- 测试方法：`test_*`

### 异步测试

使用 `pytest-asyncio` 标记异步测试：

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is True
```

### 使用固件 (Fixtures)

在 `conftest.py` 中定义的固件可以在所有测试中使用：

```python
def test_example(test_cookies, test_chat_id):
    # test_cookies 和 test_chat_id 来自 conftest.py
    assert test_cookies is not None
    assert test_chat_id is not None
```

## 持续集成

测试可以集成到 CI/CD 流程中：

```yaml
# GitHub Actions 示例
- name: Run tests
  run: |
    pip install pytest pytest-asyncio pytest-cov
    pytest tests/ --cov=. --cov-report=xml
```

## 常见问题

### Q: 测试失败，提示找不到模块

**A**: 确保从项目根目录运行测试，或者将项目根目录添加到 PYTHONPATH：

```bash
export PYTHONPATH=/path/to/XianyuAutoAgent/ai_kefu:$PYTHONPATH
pytest tests/
```

### Q: 异步测试报错

**A**: 确保安装了 `pytest-asyncio` 并且使用 `@pytest.mark.asyncio` 装饰器。

### Q: 如何跳过某些测试？

**A**: 使用 `@pytest.mark.skip` 装饰器：

```python
@pytest.mark.skip(reason="暂时跳过")
def test_something():
    pass
```

## 测试最佳实践

1. **隔离性**：每个测试应该独立运行，不依赖其他测试
2. **可重复性**：测试结果应该一致，不受外部环境影响
3. **清晰性**：测试名称应该清楚描述测试内容
4. **完整性**：测试应该覆盖正常情况和异常情况
5. **快速性**：单元测试应该快速运行，避免耗时操作

## 贡献测试

欢迎贡献新的测试用例！请确保：

1. 遵循现有的测试结构和命名规范
2. 添加清晰的测试文档字符串
3. 确保所有测试都能通过
4. 更新本 README 文档（如有需要）
