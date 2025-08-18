# 腾讯文档API集成使用说明

## 概述

本系统支持从腾讯文档在线表格中读取库存数据，实现实时库存管理和档期查询。运营人员可以直接在腾讯文档中维护设备状态，系统会自动同步最新数据。

## 配置步骤

### 1. 获取腾讯文档访问权限

#### 方法1：使用访问令牌（推荐）
1. 登录腾讯文档
2. 打开你的库存表格
3. 点击右上角"分享"按钮
4. 选择"获取链接"
5. 在链接中找到表格ID（形如：`1ABC123DEF456`）
6. 设置访问权限为"任何人可查看"

#### 方法2：使用API密钥
1. 访问腾讯文档开发者平台
2. 创建应用并获取API密钥
3. 配置应用权限

### 2. 环境变量配置

在`.env`文件中添加以下配置：

```bash
# 库存数据源设置为腾讯文档
INVENTORY_DATA_SOURCE=tencent_docs

# 腾讯文档配置
TENCENT_DOCS_SHEET_ID=你的表格ID
TENCENT_DOCS_ACCESS_TOKEN=你的访问令牌或API密钥
TENCENT_DOCS_BASE_URL=https://docs.qq.com/openapi
TENCENT_DOCS_TIMEOUT=30
```

### 3. 表格结构要求

腾讯文档表格需要包含以下列（列名必须完全匹配）：

| 列名 | 说明 | 示例 |
|------|------|------|
| 设备ID | 设备的唯一标识符 | PHONE001 |
| 型号 | 设备型号 | iPhone 15 Pro |
| 发货时间 | 设备发货日期 | 2024-01-15 |
| 租赁开始时间 | 租赁开始日期 | 2024-01-16 |
| 租赁结束时间 | 租赁结束日期 | 2024-01-18 |
| 预计收货时间 | 设备归还后预计收货日期 | 2024-01-20 |
| 客户 | 租赁客户信息 | 张三 |
| 目的地 | 发货目的地 | 北京 |
| 备注 | 其他说明信息 | 客户要求加急 |

## 功能特性

### 1. 自动状态识别

系统会根据表格中的时间信息自动判断设备状态：

- **可用 (available)**: 设备当前可用，可以租赁
- **运输中 (shipping)**: 设备正在运输途中
- **已租出 (rented)**: 设备正在被租赁使用
- **归还中 (returning)**: 设备正在归还途中

### 2. 档期冲突检测

系统会自动检测指定日期范围内是否有档期冲突：

```python
# 检查2024年1月15-17日的档期
result = inventory_manager.check_availability("2024-01-15", "2024-01-17")
```

### 3. 智能缓存机制

- 数据缓存5分钟，减少API调用
- 支持强制刷新缓存
- 自动处理网络异常

### 4. 快递时效计算

系统内置全国主要城市的快递时效表：

```python
# 获取北京到深圳的快递时效
shipping_info = inventory_manager.get_shipping_time("北京")
# 返回: {"standard": 1, "express": 1, "safe_buffer": 1}
```

## 使用方法

### 1. 初始化库存管理器

```python
from utils.inventory_manager import InventoryManager

# 腾讯文档模式
inventory_mgr = InventoryManager(
    "tencent_docs",
    sheet_id="your_sheet_id",
    access_token="your_access_token"
)

# 本地模式（备用）
local_mgr = InventoryManager("local")
```

### 2. 查询库存状态

```python
# 获取所有设备
devices = inventory_mgr.get_inventory_data()

# 获取库存摘要
summary = inventory_mgr.get_inventory_summary()
print(f"总设备数: {summary['total']}")
print(f"可用设备: {summary['status_breakdown']['available']}")

# 搜索特定设备
iphones = inventory_mgr.search_devices(model="iPhone 15 Pro")
```

### 3. 档期查询

```python
# 检查档期可用性
availability = inventory_mgr.check_availability(
    start_date="2024-01-15",
    end_date="2024-01-17"
)

if availability["available_count"] > 0:
    print(f"有 {availability['available_count']} 台设备可用")
else:
    print("指定日期无可用设备")
```

### 4. 档期计算

```python
# 计算档期安排
schedule = inventory_mgr.calculate_schedule(
    desired_date="2024-01-15",
    return_date="2024-01-17",
    destination="北京"
)

print(f"建议发货时间: {schedule['ship_date']}")
print(f"预计收货时间: {schedule['receive_date']}")
print(f"实际租赁天数: {schedule['rental_days']}")
```

## 错误处理

### 常见错误及解决方案

#### 1. 表格访问权限错误
```
错误: 403 Forbidden
解决: 检查表格分享权限，确保设置为"任何人可查看"
```

#### 2. 表格ID错误
```
错误: 404 Not Found
解决: 检查TENCENT_DOCS_SHEET_ID是否正确
```

#### 3. 访问令牌过期
```
错误: 401 Unauthorized
解决: 重新获取访问令牌
```

#### 4. 网络连接超时
```
错误: Connection timeout
解决: 检查网络连接，增加TENCENT_DOCS_TIMEOUT值
```

## 性能优化

### 1. 缓存策略
- 启用缓存减少API调用
- 合理设置缓存过期时间
- 在数据更新后主动刷新缓存

### 2. 批量操作
- 避免频繁查询单个设备
- 使用批量查询减少网络请求
- 合理设置请求间隔

### 3. 异常处理
- 实现重试机制
- 设置合理的超时时间
- 提供降级方案（本地模式）

## 监控和日志

### 1. 日志记录
系统会记录以下关键操作：
- 数据同步状态
- API调用结果
- 错误和异常信息
- 性能指标

### 2. 健康检查
```python
from config.inventory_config import get_inventory_config

config = get_inventory_config()
validation = config.validate_config()

if not validation["valid"]:
    print("配置错误:", validation["errors"])
```

## 故障排除

### 1. 数据不同步
- 检查表格权限设置
- 验证访问令牌有效性
- 查看网络连接状态

### 2. 档期计算错误
- 确认日期格式正确
- 检查快递时效配置
- 验证设备状态逻辑

### 3. 性能问题
- 调整缓存配置
- 优化查询频率
- 检查网络延迟

## 技术支持

如果遇到问题，可以：
1. 查看系统日志
2. 检查配置有效性
3. 验证腾讯文档权限
4. 联系技术支持团队

## 更新日志

- v1.0.0: 初始版本，支持基本库存查询
- v1.1.0: 添加档期冲突检测
- v1.2.0: 集成快递时效计算
- v1.3.0: 优化缓存机制和错误处理
