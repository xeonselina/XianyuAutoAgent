# Change: 手机甘特图显示闲鱼订单提醒

## Why

PC 甘特图已提醒漏录订单及退款/关闭后仍保留的档期，手机甘特图目前没有这些提醒。使用手机处理订单时，操作员可能漏补录或继续履行已关闭订单。

## What Changes

- 在手机甘特图顶部显示与 PC 相同的漏录、关闭、退款核对提醒及对账状态。
- 展开后展示订单和档期明细，提供补录/补齐、查看档期、确认删除、填写原因后永久忽略及立即检查入口。
- 从提醒进入现有手机新建租赁页时带入店铺和订单号；完成录入、删除或返回甘特图后刷新提醒。
- 复用现有订单提醒和租赁 API，不变更服务端数据结构。

## Impact

- Affected specs: `xianyu-missing-order-alerts`, `xianyu-rental-alerts`（增加手机端要求）
- Affected code: `frontend-mobile/src/views/GanttView.vue`, `frontend-mobile/src/views/CreateRentalView.vue`, 手机提醒组件、租赁类型及移动端验证。
- Backend/API: 复用现有接口；不新增迁移。
