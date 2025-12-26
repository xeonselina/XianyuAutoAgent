# 定时任务调度器修复说明

## 问题描述

用户观察到容器日志里每5分钟会显示5条"开始处理预约发货任务"日志，但没有显示后续的日志（如"没有需要发货的订单"或"找到X个待发货订单"），表明存在以下问题：

1. **多实例运行问题**：Gunicorn配置了4个worker，每个worker都初始化了调度器，导致定时任务被重复执行
2. **异常未捕获问题**：数据库查询可能因缺少应用上下文或其他原因失败，但异常没有被完整捕获和记录

## 根本原因分析

### 1. 多Worker重复执行

**问题**：
- `gunicorn_config.py` 配置了 `workers = 4`
- 每个worker都会调用 `create_app()`
- `create_app()` 中调用 `init_scheduler(app)`
- 导致4个worker都启动了调度器，定时任务被执行了4-5次

**证据**：
- 用户看到5条"开始处理预约发货任务"日志

### 2. 缺少应用上下文

**问题**：
- SQLAlchemy查询需要在Flask应用上下文中执行
- 定时任务在后台线程中运行，可能没有应用上下文
- 导致 `Rental.query.filter(...).all()` 抛出异常

**证据**：
- 有"开始处理预约发货任务"日志
- 但没有后续的"正在查询数据库..."或"找到X个待发货订单"日志

### 3. 异常处理不完整

**问题**：
- `process_scheduled_shipments()` 函数没有 try-except 包裹数据库查询
- 虽然外层 `scheduler_tasks.py` 有异常处理，但具体的错误信息没有记录

## 修复方案

### 1. 添加文件锁机制 - 防止多实例运行

**文件**: `app/utils/scheduler.py`

**修改内容**：
```python
import fcntl
import os

lock_file_path = '/tmp/inventory_scheduler.lock'

try:
    lock_file = open(lock_file_path, 'w')
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    logger.info(f'获取调度器锁成功，进程 {os.getpid()} 将启动调度器')

    # 创建并启动调度器...

except BlockingIOError:
    # 无法获取锁，说明其他进程已经启动了调度器
    logger.info(f'进程 {os.getpid()} 无法获取调度器锁，跳过调度器初始化（其他worker已启动）')
    return
```

**原理**：
- 使用文件锁（fcntl.LOCK_EX | fcntl.LOCK_NB）
- 第一个获取锁的worker启动调度器
- 其他worker获取锁失败，跳过调度器初始化
- 确保只有一个调度器实例运行

### 2. 确保在应用上下文中运行

**文件**: `app/utils/scheduler.py`

**修改内容**：
```python
def run_with_app_context():
    with app.app_context():
        logger.info(f'[Worker {os.getpid()}] 开始执行定时发货任务')
        try:
            return process_scheduled_shipments()
        except Exception as e:
            logger.error(f'[Worker {os.getpid()}] 定时发货任务执行失败: {e}', exc_info=True)
            return {'total': 0, 'success': 0, 'failed': 0, 'error': str(e)}

scheduler.add_job(
    func=run_with_app_context,  # 使用包装函数
    ...
)
```

**效果**：
- 所有数据库操作都在Flask应用上下文中执行
- 避免 "No application context" 错误

### 3. 添加完整的异常处理和详细日志

**文件**: `app/services/shipping/scheduler_shipping_task.py`

**修改内容**：
```python
def process_scheduled_shipments():
    import traceback

    logger.info("开始处理预约发货任务")

    try:
        # 查询需要发货的租赁记录
        logger.info("正在查询数据库...")
        rentals = Rental.query.filter(...).all()

        logger.info(f"数据库查询完成，找到 {len(rentals)} 条记录")

        if not rentals:
            logger.info("没有需要发货的订单")
            return {...}

        logger.info(f"找到 {len(rentals)} 个待发货订单")

        # 处理订单...

    except Exception as e:
        logger.error(f"预约发货任务执行异常: {type(e).__name__}: {e}")
        logger.error(f"完整堆栈:\n{traceback.format_exc()}")
        return {'total': 0, 'success': 0, 'failed': 0, 'error': str(e)}
```

**效果**：
- 捕获所有异常并记录详细信息
- 添加步骤日志，方便定位问题
- 即使失败也会返回结果，不会导致调度器崩溃

## 预期日志输出

### 修复前（问题日志）
```
[Worker 8] 开始处理预约发货任务
[Worker 9] 开始处理预约发货任务
[Worker 10] 开始处理预约发货任务
[Worker 11] 开始处理预约发货任务
[Worker 12] 开始处理预约发货任务
（没有后续日志，说明异常了）
```

### 修复后（正常日志）

**启动时**：
```
进程 8 无法获取调度器锁，跳过调度器初始化（其他worker已启动）
进程 9 无法获取调度器锁，跳过调度器初始化（其他worker已启动）
获取调度器锁成功，进程 10 将启动调度器
已添加定时发货任务: 每5分钟执行一次
定时调度器已启动
进程 11 无法获取调度器锁，跳过调度器初始化（其他worker已启动）
```

**执行任务时（无订单）**：
```
[Worker 10] 开始执行定时发货任务
开始处理预约发货任务
正在查询数据库...
数据库查询完成，找到 0 条记录
没有需要发货的订单
```

**执行任务时（有订单）**：
```
[Worker 10] 开始执行定时发货任务
开始处理预约发货任务
正在查询数据库...
数据库查询完成，找到 3 条记录
找到 3 个待发货订单
处理租赁记录 123
Rental 123 顺丰下单成功
Rental 123 闲鱼发货通知成功
...
预约发货任务完成: {'total': 3, 'success': 3, 'failed': 0, 'skipped': 0}
```

**执行任务时（出错）**：
```
[Worker 10] 开始执行定时发货任务
开始处理预约发货任务
正在查询数据库...
预约发货任务执行异常: OperationalError: (mysql.connector.errors.DatabaseError) ...
完整堆栈:
Traceback (most recent call last):
  ...
```

## 验证步骤

1. **重新构建镜像**：
   ```bash
   make build-x86
   ```

2. **启动容器并观察启动日志**：
   ```bash
   docker logs <container_id> | grep "调度器"
   ```

   应该看到：
   - 只有1个"获取调度器锁成功"
   - 其他3个worker显示"跳过调度器初始化"

3. **等待5分钟，观察定时任务日志**：
   ```bash
   docker logs <container_id> | grep "预约发货任务"
   ```

   应该看到：
   - 只有1条"开始执行定时发货任务"
   - 有后续的"正在查询数据库..."日志
   - 有"没有需要发货的订单"或"找到X个待发货订单"日志

4. **测试异常场景**：
   - 临时关闭数据库连接
   - 观察是否有详细的错误日志

## 技术细节

### 文件锁机制

- **类型**: 独占锁（LOCK_EX）+ 非阻塞（LOCK_NB）
- **位置**: `/tmp/inventory_scheduler.lock`
- **生命周期**: 进程存活期间一直持有
- **跨进程**: 文件锁在操作系统层面，所有进程共享

### 应用上下文

- **作用**: 提供Flask app实例、数据库连接、请求上下文等
- **必要性**: SQLAlchemy session需要应用上下文
- **实现**: `with app.app_context():`

### Worker隔离

- Gunicorn fork多个worker进程
- 每个worker独立运行Python解释器
- 只有获取文件锁的worker运行调度器
- 其他worker正常处理HTTP请求

## 相关文件

修改的文件：
1. `app/utils/scheduler.py` - 添加文件锁和应用上下文
2. `app/services/shipping/scheduler_shipping_task.py` - 添加异常处理和详细日志

## 注意事项

1. **文件锁路径**: `/tmp/inventory_scheduler.lock` 在容器重启后会丢失，这是正常的
2. **进程ID日志**: 日志中的进程ID会在容器重启后改变
3. **调试模式**: 如果需要调试，可以临时修改 `max_instances=1` 为更大的值
4. **性能影响**: 文件锁检查非常快（微秒级），对性能影响可忽略
