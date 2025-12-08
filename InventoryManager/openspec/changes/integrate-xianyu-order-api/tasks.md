# 实施任务: 集成闲鱼管家订单API

## 任务列表

### 1. 数据库变更
- [ ] 创建数据库迁移脚本,添加以下字段到rentals表:
  - `xianyu_order_no` VARCHAR(50) NULL
  - `order_amount` DECIMAL(10,2) NULL
  - `buyer_id` VARCHAR(100) NULL
- [ ] 在开发环境执行迁移,验证字段正确添加
- [ ] 验证历史数据不受影响,所有现有功能正常工作

### 2. 模型层更新
- [ ] 更新`app/models/rental.py`中的Rental模型:
  - 添加xianyu_order_no、order_amount、buyer_id字段定义
  - 为新字段添加注释(comment参数)
- [ ] 更新Rental.to_dict()方法,包含新字段
- [ ] 编写单元测试验证模型字段正确序列化

### 3. 闲鱼API服务实现
- [ ] 创建或增强`app/services/xianyu_order_service.py`:
  - 实现XianyuOrderService类
  - 实现get_order_detail(order_no)方法
  - 实现签名生成genSign()方法
  - 实现API请求request()方法
- [ ] 添加环境变量配置支持:
  - XIANYU_APP_KEY
  - XIANYU_APP_SECRET
  - XIANYU_API_DOMAIN (默认: https://open.goofish.pro)
- [ ] 实现错误处理:
  - 网络连接错误
  - API返回错误(无效订单号等)
  - 超时处理
- [ ] 添加日志记录用于调试和监控
- [ ] 编写单元测试(可使用mock模拟API响应)

### 4. 后端API接口
- [ ] 在`app/handlers/rental_handlers.py`或创建新的handler添加:
  - handle_fetch_xianyu_order()方法
- [ ] 实现接口逻辑:
  - 验证订单号参数
  - 调用XianyuOrderService获取订单详情
  - 转换订单数据为前端需要的格式
  - 处理pay_amount转换(分到元)
  - 组合地址字段
- [ ] 添加路由到`app/routes.py`或相应的蓝图:
  - POST /api/rentals/fetch-xianyu-order
  - 请求体: {"order_no": "订单号"}
  - 响应: 订单详情JSON
- [ ] 实现请求验证和错误响应
- [ ] 编写API集成测试

### 5. 租赁创建/更新逻辑增强
- [ ] 更新`app/handlers/rental_handlers.py`中的handle_create_rental():
  - 接受并保存xianyu_order_no
  - 接受并保存order_amount
  - 接受并保存buyer_id
- [ ] 更新handle_web_update_rental():
  - 支持更新订单相关字段
  - 保持向后兼容,允许这些字段为NULL
- [ ] 验证数据完整性和约束

### 6. 前端表单UI更新
- [ ] 找到租赁表单模板文件(可能在templates/目录)
- [ ] 在表单中添加订单号输入字段:
  - 位置: 在开始日期、结束日期、物流时间字段之后
  - 标签: "闲鱼订单号"
  - 字段名: xianyu_order_no
- [ ] 添加"拉取订单信息"按钮:
  - 位置: 订单号字段旁边
  - 按钮文本: "拉取订单信息"
  - 禁用条件: 订单号为空
- [ ] 添加订单金额显示字段(只读或可编辑):
  - 标签: "订单金额(元)"
  - 字段名: order_amount
- [ ] 添加买家ID字段(可选,可能隐藏):
  - 标签: "买家ID"
  - 字段名: buyer_id

### 7. 前端自动填充逻辑
- [ ] 实现JavaScript函数fetchXianyuOrder():
  - 获取订单号输入值
  - 调用后端API: POST /api/rentals/fetch-xianyu-order
  - 显示加载状态(禁用按钮,显示加载图标)
- [ ] 实现自动填充逻辑fillFormWithOrderData(orderData):
  - 填充customer_name = orderData.receiver_name
  - 填充customer_phone = orderData.receiver_mobile
  - 填充buyer_id = orderData.buyer_eid
  - 组合并填充destination = `${prov_name}${city_name}${area_name}${town_name}${address}`
  - 转换并填充order_amount = orderData.pay_amount / 100
  - 保存order_no到隐藏字段或表单状态
- [ ] 实现错误处理和用户反馈:
  - 成功提示: "订单信息已成功获取"
  - 错误提示: 显示具体错误信息
  - 网络错误提示: "网络连接失败,请稍后重试"
- [ ] (可选)实现数据覆盖确认:
  - 如果表单字段已有数据,显示确认对话框

### 8. 租赁统计功能增强
- [ ] 更新`scripts/rental_statistics.py`或相应的统计服务:
  - 添加总收入计算: SUM(order_amount)
  - 添加平均订单金额计算: AVG(order_amount)
  - 统计有/无订单金额的记录数
- [ ] 更新统计API响应,包含收入数据
- [ ] 更新统计页面UI显示收入信息

### 9. 测试
- [ ] 端到端测试:
  - 创建新租赁并使用有效订单号拉取信息
  - 编辑现有租赁并拉取订单信息
  - 测试无效订单号的错误处理
  - 测试API不可用时的降级处理
- [ ] 数据测试:
  - 验证历史数据(无订单金额)正常显示
  - 验证新数据(有订单金额)正确保存和显示
  - 验证统计功能正确计算收入
- [ ] 边界条件测试:
  - 订单号为空
  - 订单详情部分字段为空
  - 地址组件全部为空
  - pay_amount为0

### 10. 文档和部署
- [ ] 更新项目文档:
  - 记录新的环境变量配置
  - 更新API文档,添加新的接口
  - 更新用户手册,说明如何使用订单拉取功能
- [ ] 准备部署清单:
  - 数据库迁移脚本
  - 环境变量配置说明
  - 回滚方案
- [ ] 在测试环境验证完整流程
- [ ] 准备生产环境部署

## 依赖关系
- 任务2依赖任务1(模型更新需要数据库字段存在)
- 任务4依赖任务3(API接口需要服务层实现)
- 任务7依赖任务4和任务6(前端逻辑需要后端接口和UI元素)
- 任务8依赖任务2(统计需要模型包含新字段)
- 任务9依赖任务1-8(测试需要所有功能实现完成)

## 可并行执行的任务
- 任务3(闲鱼API服务)和任务6(前端UI)可以并行开发
- 任务2(模型更新)完成后,任务5(租赁逻辑)和任务8(统计)可以并行开发

## 验证要点
每个任务完成后应验证:
- 代码通过lint检查
- 相关测试通过
- 不破坏现有功能
- 符合项目代码规范
