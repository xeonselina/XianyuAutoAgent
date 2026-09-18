# Change: 同收件地址合单发货及租赁日期编辑

## Why
多台机器发往同一收件地址时需要一次预约、一张地址联及逐台内容联；租赁编辑需要调整起租日和寄出时间。用户已明确要求实现。

## What Changes
- 已选待发货主机按仓库、寄出日期、快递类型、实际收件地址和电话分组；接力单不参与。
- 同组一次顺丰下单，原子保存共享运单号；重复预约拒绝。
- 打印按仓库和运单号去重地址联，并补全同票设备的逐台内容联，地址联标明总台数。
- PC 和移动端展示分组；开始日期和寄出时间可独立修改，沿用库存冲突校验。

## Impact
- Affected specs: batch-print-ui
- Affected code: shipping handlers/services, rental edit, PC/mobile batch shipping.
- 无数据库迁移；已预约的不同运单不追溯合并。日期编辑不修改已向快递提交的取件预约时间。
