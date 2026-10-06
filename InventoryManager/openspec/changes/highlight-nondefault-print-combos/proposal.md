# Change: 打印面单突出非默认镜头组合

## Why
打包时只看设备名容易拿错非默认镜头组合，地址联和内容联都需要清楚标出实际组合。

## What Changes
- 地址联的顺丰备注在每台设备名后显示订单保存的组合名称，非默认组合用醒目的黑色括号标出。
- 内容联保留独立组合行，对非默认组合绘制黑色矩形边框。
- 按型号当前默认租赁组合判断；旧订单用镜头枚举和型号默认镜头兼容判断。打印不改订单数据。

## Impact
- Affected specs: `sf-waybill-api`, `shipping-fulfillment`
- Affected code: `app/services/shipping/sf_express_service.py`, `app/services/printing/`
