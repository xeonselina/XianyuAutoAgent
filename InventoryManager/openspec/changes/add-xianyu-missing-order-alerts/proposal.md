# Change: 增加闲鱼漏录订单告警

## Why

闲鱼待发货订单如果未在库存管理中预定，就不会进入甘特图、面单打印和发货流程，可能造成漏发货。系统需要主动对账并在主要工作页面持续提醒。

## What Changes

- 每 10 分钟查询单店铺待发货且实付金额大于 50 元的闲鱼订单
- 将订单号与库存管理租赁记录对账
- 在甘特图顶部显示漏录订单警告条及关键信息
- 从警告条复用现有预定弹框完成补录
- 支持填写原因后永久忽略无需录入的订单
- 外部查询失败时保留上次成功缓存和错误状态

## Impact

- Affected specs: `xianyu-missing-order-alerts`（新增）
- Affected backend: 闲鱼客户端、对账服务、调度器、API、数据模型和迁移
- Affected frontend: 甘特图警告条、现有 `BookingDialog` 的订单号初始化能力
- External dependency: 闲管家订单列表 API

