# Gevent SSL RecursionError 修复说明

## 问题描述

在 x86 服务器上运行容器时，拉取闲鱼订单会触发 `RecursionError: maximum recursion depth exceeded`。

错误日志显示：
```
MonkeyPatchWarning: Monkey-patching ssl after ssl has already been imported may lead to errors, including RecursionError on Python 3.6.
It may also silently lead to incorrect behaviour on Python 3.7.
Please monkey-patch earlier.

Modules that had direct imports (NOT patched):
['aiohttp.connector', 'aiohttp.client_reqrep', 'urllib3.util.ssl_', ...]
```

## 根本原因

1. Gunicorn 使用 gevent worker 模式
2. 某些模块（urllib3, aiohttp）在 gevent monkey patch 之前就被导入
3. 这导致 SSL 处于半 patch 状态，在某些操作（如 HTTPS 请求）时触发递归错误
4. 问题在服务器上出现但本地 Mac 不出现，可能与模块加载顺序和时机有关

## 解决方案

### 1. 在 run.py 最开始进行 monkey patch (最关键)

**文件**: `run.py`

```python
#!/usr/bin/env python3
"""
WSGI entry point for gunicorn
"""

# CRITICAL: Monkey patch MUST be done before any other imports
# This prevents SSL-related RecursionError when using gevent workers
import gevent.monkey
gevent.monkey.patch_all()

from app import create_app
# ... rest of code
```

**原因**: 确保在导入 Flask app 和所有依赖之前完成 monkey patch

### 2. 禁用应用预加载

**文件**: `gunicorn_config.py`

```python
# 预加载应用
# 注意：设置为 False 以避免在主进程中预加载应用导致的 SSL monkey patch 问题
# 每个 worker 会独立加载应用，确保 monkey patch 在导入模块之前完成
preload_app = False
```

**原因**:
- `preload_app = True` 会在主进程中加载应用
- 导致在 fork worker 之前就导入了 SSL 相关模块
- 设置为 `False` 让每个 worker 独立加载，确保 monkey patch 生效

**权衡**:
- 缺点: 每个 worker 独立加载应用，启动稍慢，内存占用略高
- 优点: 避免 SSL 递归错误，确保 gevent 正常工作

### 3. 添加详细日志记录

**文件**: `app/services/xianyu_order_service.py`

在所有 HTTP 请求位置添加了详细日志，记录：
- Python 版本
- Requests 库版本
- Gevent 版本和当前 greenlet
- SSL/OpenSSL 版本
- 完整的异常堆栈（包括 RecursionError）

**目的**: 方便诊断和监控问题

## 执行顺序（修复后）

### 使用 Gunicorn 启动时

1. Gunicorn 读取 `gunicorn_config.py`
2. **执行 `gevent.monkey.patch_all()`** (第一次 patch)
3. Gunicorn fork worker 进程（因为 preload_app = False）
4. Worker 导入 `run:app`
5. `run.py` 执行 **`gevent.monkey.patch_all()`** (第二次 patch，幂等安全)
6. 导入 `from app import create_app`
7. 创建 Flask 应用实例

此时所有 SSL 相关模块都在 monkey patch 之后导入，避免递归错误。

## 验证步骤

### 1. 重新构建镜像

```bash
cd InventoryManager
make build-x86
```

### 2. 启动容器

```bash
make build-and-run-x86
```

或在服务器上：
```bash
docker run -d -p 5002:5002 [环境变量...] inventory-manager:x86-local
```

### 3. 检查日志

```bash
docker logs <container_id>
```

**期望结果**:
- 不再出现 `MonkeyPatchWarning`
- 能够正常拉取闲鱼订单
- 不再有 `RecursionError`

### 4. 测试闲鱼订单拉取

触发订单拉取功能，观察日志中的 `[REQUEST]` 标记：
```
[REQUEST START] 准备发送闲鱼API请求
[REQUEST] Python版本: 3.10.x
[REQUEST] Gevent版本: 24.2.1
[REQUEST] SSL版本: OpenSSL...
[REQUEST] 正在调用 requests.post()...
[REQUEST SUCCESS] requests.post() 调用完成
```

## 相关文件

修改的文件：
1. `run.py` - 添加早期 monkey patch
2. `gunicorn_config.py` - 设置 preload_app = False
3. `app/services/xianyu_order_service.py` - 添加详细日志

## 技术细节

### Gevent Monkey Patching

- Gevent 使用协程（greenlets）实现并发
- Monkey patch 将标准库的阻塞 I/O 替换为非阻塞版本
- 必须在导入标准库模块**之前**完成 patch
- 如果在导入后 patch，会导致不一致状态和递归错误

### 为什么 Mac 上没问题？

可能的原因：
1. 模块加载顺序因系统而异（macOS vs Linux）
2. Python 包的版本略有差异
3. Docker 运行时环境不同
4. 时机问题：Mac 上恰好在正确的时机完成了 patch

### preload_app 的影响

- `True`: 主进程加载应用，fork 到 workers（Copy-on-Write 省内存）
- `False`: 每个 worker 独立加载应用（占用更多内存，但避免共享状态问题）

对于 gevent + SSL 的场景，`False` 更安全。

## 参考资料

- [Gevent Issue #1016: Monkey patching after SSL import](https://github.com/gevent/gevent/issues/1016)
- [Gunicorn Gevent Worker](https://docs.gunicorn.org/en/stable/design.html#async-workers)
- [Gevent Monkey Patching Guide](http://www.gevent.org/api/gevent.monkey.html)
