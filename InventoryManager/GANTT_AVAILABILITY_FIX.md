# 甘特图可用设备统计逻辑修复总结

## 问题描述

原来甘特图日历上显示的"x 闲"（空闲设备数量）逻辑不正确，需要改为：**预测到指定日期，有多少台机器会是空闲的（不在任何 rental 的 shipouttime - shipintime 时间范围内）**。

## 修改内容

### 1. 修复库存服务的设备可用性判断逻辑

**文件**: `app/services/inventory_service.py`

**主要变更**:
- 修改了 `get_available_devices` 方法的核心逻辑
- **原逻辑问题**: 只检查最近一次租赁记录，且判断条件有误
- **新逻辑**: 检查所有租赁记录，判断是否在指定时间段内有物流时间冲突

**新的判断算法**:
```python
# 检查设备在指定时间段内是否有冲突的租赁记录
conflicting_rentals = Rental.query.filter(
    db.and_(
        Rental.device_id == device.id,
        Rental.status.in_(['pending', 'active', 'completed']),  # 不包括取消的租赁
        Rental.ship_out_time.isnot(None),  # 必须有寄出时间
        Rental.ship_in_time.isnot(None),   # 必须有收回时间
        # 检查时间段重叠：租赁的物流时间段与查询时间段重叠
        db.and_(
            Rental.ship_out_time < ship_in_time,   # 租赁寄出时间 < 查询收回时间
            Rental.ship_in_time > ship_out_time    # 租赁收回时间 > 查询寄出时间
        )
    )
).all()
```

**关键改进**:
1. **全量检查**: 检查所有租赁记录，不只是最近一次
2. **正确的时间重叠判断**: 使用标准的时间区间重叠算法
3. **物流时间优先**: 基于 `ship_out_time` 和 `ship_in_time` 而不是租赁时间
4. **状态过滤**: 只考虑有效的租赁状态，排除取消的租赁

### 2. 修复甘特图API的每日统计逻辑

**文件**: `app/routes/gantt_api.py`

**主要变更**:
- 简化了 `get_daily_stats` 方法中计算空闲设备数量的逻辑
- 移除了复杂的物流天数计算和日期调整
- 直接查询指定日期当天不被任何租赁物流时间占用的设备

**新的统计算法**:
```python
# 将目标日期转换为时间段（当天00:00到23:59）
target_start = datetime.combine(target_date, datetime.min.time())
target_end = datetime.combine(target_date, datetime.max.time())

# 查询在目标日期这一天不被任何租赁物流时间占用的设备
available_devices = InventoryService.get_available_devices(target_start, target_end)
available_count = len(available_devices)
```

**关键改进**:
1. **精确的日期范围**: 查询目标日期当天的完整时间段
2. **简化的逻辑**: 不再需要复杂的物流时间计算
3. **直接调用**: 复用修复后的 `get_available_devices` 方法

### 3. 添加顺丰API调试日志

**文件**: `app/utils/sf_express_api.py`, `app/utils/scheduler_tasks.py`

**主要变更**:
- 在 `_make_request` 方法中添加详细的请求和响应日志
- 在 `parse_route_response` 方法中添加解析过程日志
- 在 `manual_query_tracking` 中添加调试信息

**新增的调试日志**:
```python
logger.info(f"发送顺丰API请求: {service_code}")
logger.info(f"请求URL: {self.api_url}")
logger.info(f"请求数据: {request_data}")
logger.info(f"HTTP状态码: {response.status_code}")
logger.info(f"响应头: {dict(response.headers)}")
logger.info(f"原始响应内容: {response.text}")
logger.info(f"解析后的JSON响应: {result}")
```

**调试改进**:
1. **完整的请求日志**: 记录URL、参数、签名等所有请求信息
2. **详细的响应日志**: 记录HTTP状态码、响应头、原始内容
3. **解析过程日志**: 记录JSON解析的每个步骤
4. **错误堆栈**: 使用 `exc_info=True` 记录完整的错误堆栈

## 预期效果

### 1. 空闲设备统计更准确
- 甘特图日历上的"x 闲"现在反映真实的设备可用情况
- 基于实际的物流时间（shipouttime到shipintime）进行判断
- 考虑所有有效的租赁记录，不会遗漏

### 2. 设备档期查询更可靠
- `find_available_time_slot` 等功能会返回更准确的结果
- 避免推荐已被物流占用的设备
- 提高预定成功率

### 3. 顺丰接口问题更易排查
- 详细的调试日志帮助定位API调用问题
- 可以看到完整的请求和响应内容
- 便于验证签名和参数是否正确

## 测试建议

### 1. 验证空闲设备统计
1. 创建一些测试租赁记录，设置不同的 `ship_out_time` 和 `ship_in_time`
2. 在甘特图上查看不同日期的"x 闲"显示
3. 确认统计结果符合预期（不在物流时间范围内的设备被正确统计）

### 2. 验证档期查询
1. 尝试查找可用档期
2. 确认返回的设备确实在指定时间段内可用
3. 验证不会返回已被物流占用的设备

### 3. 排查顺丰接口问题
1. 在租赁编辑页面测试快递查询功能
2. 查看应用日志，确认能看到详细的请求和响应信息
3. 根据日志信息排查API配置或单号问题

## 注意事项

1. **时间精度**: 新的逻辑基于精确的时间比较，确保 `ship_out_time` 和 `ship_in_time` 字段的准确性很重要
2. **性能考虑**: 对于大量设备和租赁记录，可能需要考虑数据库索引优化
3. **数据完整性**: 确保租赁记录的物流时间字段被正确设置
4. **日志级别**: 顺丰API的详细日志可能产生大量输出，生产环境可根据需要调整日志级别

## 相关文件列表

- `app/services/inventory_service.py` - 核心库存逻辑修复
- `app/routes/gantt_api.py` - 甘特图API统计逻辑修复  
- `app/utils/sf_express_api.py` - 顺丰API调试日志
- `app/utils/scheduler_tasks.py` - 调度任务调试日志