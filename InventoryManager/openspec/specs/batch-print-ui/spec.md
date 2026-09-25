# 批量发货页面的打印交互

## Purpose

从当前 PC `BatchShippingView.vue`、发货处理器和 `WaybillPrintService` 反推打印行为。打印设备由履约仓库配置决定，页面不会从云端选打印机。本规格同时界定“发货单”浏览器页面与顺丰快递面单的两条操作路径。

## Requirements

### Requirement: 面单按钮只计可打印包裹

PC `/batch-shipping` MUST 在选择日期并加载到非空租赁表后显示“批量打印快递面单 (N)”按钮。仅 `status=scheduled_for_shipping` 且同时有 `ship_out_tracking_no,scheduled_ship_time` 的行符合条件；N 为唯一 `(warehouse_id,ship_out_tracking_no)` 的包裹数，不是设备行数。无符合行或当前仓为 `all` 时按钮禁用。日期默认不选，未选日期点“预览订单”提示先选日期；切仓时清除原表和选择，并按当前日期重新查询。

#### Scenario: 两台设备共用一票
- **WHEN** 日期结果有两条同仓、同运单、已预约的租赁，另有一条无预约时间
- **THEN** 面单按钮显示 `(1)`；点击时提交前两条 ID，第三条不进打印请求

### Requirement: 发货单按钮走独立浏览器打印页

同页“批量打印发货单”按钮 MUST 在具体仓且订单表非空时，把日期范围放进 `/batch-shipping-order?start_date=...&end_date=...` 并在新标签打开。它不是快麦面单请求，也不使用 `/api/shipping-batch/print-waybills` 的结果弹窗。表内预约发货仅勾选非 `shipped/scheduled_for_shipping`、非接力后单且属于当前仓的行；打印面单不依赖这个勾选集合。

#### Scenario: 未勾选任何行仍打印已有运单
- **WHEN** 表里有已预约且带单号的租赁，但预约发货复选框没有选项
- **THEN** 面单按钮仍可用；打印请求取所有符合面单条件的租赁

### Requirement: 点击面单按钮立即提交并展示最终结果

点击面单按钮 MUST 直接打开结果对话框并 POST `/api/shipping-batch/print-waybills`，body 仅含 `rental_ids`；不出现云打印机下拉，也不传 `printer_sn`，后端默认 `include_shipping_slips=true`，按履约仓配置的快麦 SN 打印。对话框初始进度为 0，请求完成后置 100；当前页面没有逐张实时进度。结果标题显示“地址联 X 张 / 内容联 Y 张 / 失败 Z 台”；有失败时列逐台结果并保持弹窗，全部成功时通知成功并在约 2 秒后自动关闭。失败项不提供弹窗内一键重试；重新触发需用户再次操作。

#### Scenario: 未配置当前仓快麦
- **WHEN** 租赁已有顺丰运单但所在仓缺快麦配置，操作员点击面单按钮
- **THEN** 后端逐项给出配置失败；页面显示失败汇总，不跳到其它仓库打印机

### Requirement: 服务端按包裹去重打印地址联、按租赁打印内容联

批量 API MUST 拒绝空 ID 和超过 100 个原始 ID；服务先展开同包裹主租赁，按首次出现顺序去重设备 ID。对同仓同运单包裹只调用一次顺丰 PDF 与快麦地址联打印，并复用该结果；若启用内容联，则每条主租赁各打印一张发货单。面单失败时跳过该行内容联。返回 `total` 为展开后的设备行数、`parcel_count` 为实际包裹键数、`waybill_success_count` 为成功包裹数、`slip_success_count` 为成功内容联行数、`failed_count` 为失败设备行数，另含每条 `results`。HTTP 成功并不意味着全部设备打印成功，调用方要看计数字段。

#### Scenario: 一票双机的第二张内容联失败
- **WHEN** 两台设备共用运单，地址联成功，第一张内容联成功而第二张失败
- **THEN** `parcel_count=1,waybill_success_count=1,slip_success_count=1,failed_count=1,total=2`；逐条结果标出第二台 `slip_success=false`

### Requirement: 表内单笔打印仍使用同一批量 API

表中 MUST 仅为已预约且有寄出运单号的行显示“打印”链接；点击后以单条 `rental_ids` 调批量 API。顺丰或快麦任一失败显示错误提示，成功显示“面单打印成功”。打印服务不以 `shipped` 状态本身拒绝重打；页面可见入口则比服务的允许范围更窄。

#### Scenario: 预约行单笔打印
- **WHEN** 操作员点击一条已预约且有运单号的“打印”
- **THEN** 请求只传该租赁 ID，结果由 `failed_count` 决定成功或失败提示

## 响应与源码

`POST /api/shipping-batch/print-waybills` 成功响应 `data={total,parcel_count,waybill_success_count,slip_success_count?,failed_count,results}`。逐条结果含 `rental_id,waybill_success,slip_success`；失败可能在 `error` 或 `slip_error` 而非 `message`。PC 弹窗当前只读取 `result.message` 作为失败详情，因此部分失败行会缺具体文字；复刻当前外观时不能凭旧归档规格假定详细错误已经显示。

依据：`frontend/src/views/BatchShippingView.vue`、`app/handlers/shipping_batch_handlers.py`、`app/services/shipping/waybill_print_service.py`、`app/services/shipping/shipment_group_service.py`。
