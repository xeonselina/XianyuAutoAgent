# Change: 打印面单突出非默认镜头组合

## Why
打包人员通常先看地址联的设备名，再用内容联核对镜头。非默认组合如果只以普通文字出现，容易按型号默认镜头配货；两联都需要突出订单保存的实际组合，降低拿错镜头的风险。

## What Changes
- 地址联的顺丰备注在每台设备名后显示订单保存的组合名称，非默认组合用醒目的黑色括号标出。
- 内容联保留独立组合行，对非默认组合绘制黑色矩形边框。
- 按型号当前默认租赁组合判断；旧订单用镜头枚举和型号默认镜头兼容判断。打印不改订单数据。

## Impact
- Affected specs: `sf-waybill-api`, `shipping-fulfillment`
- Affected code: `app/services/shipping/sf_express_service.py`, `app/services/printing/`
