# Change: 集成闲鱼管家订单API

## Why
目前在创建或编辑租赁记录时,用户必须手动从闲鱼订单中输入客户收货信息(地址、电话、买家ID)。这种手动流程耗时且容易出错,需要在闲鱼平台和租赁管理系统之间切换,且缺少订单金额跟踪无法准确统计收入。

## What Changes
- 在Rental模型添加字段: xianyu_order_no、order_amount、buyer_id
- 创建XianyuOrderService服务类调用闲鱼管家API
- 添加后端API接口: POST /api/rentals/fetch-xianyu-order
- 前端租赁表单添加订单号输入和拉取按钮
- 实现表单自动填充逻辑(客户姓名、电话、地址、订单金额)
- 增强租赁统计功能,包含订单金额收入统计

## Impact
- Affected specs: xianyu-api-integration, rental-order-autofill, rental-revenue-tracking (新增)
- Affected code:
  - app/models/rental.py (Rental模型扩展)
  - app/services/xianyu_order_service.py (API服务)
  - app/handlers/rental_handlers.py (新增API接口)
  - templates/租赁表单相关模板 (UI更新)
  - scripts/rental_statistics.py (统计功能增强)
- Database: rentals表新增3个可空字段
- Dependencies: 需配置XIANYU_APP_KEY和XIANYU_APP_SECRET环境变量
