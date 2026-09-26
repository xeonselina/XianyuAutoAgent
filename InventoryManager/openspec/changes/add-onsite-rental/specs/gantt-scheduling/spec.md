## MODIFIED Requirements

### Requirement: 档期查找保留物流缓冲

`POST /api/rentals/find-slot` 对快递租赁 MUST 要求 `start_date,end_date,logistics_days,model,is_accessory`，可指定仓库；起止日可同一天。快递寄出日为起租日减 `1+logistics_days`，收回日为还租日加相同天数；查找占用使用寄出日 19:00 到收回日 12:00。现场租赁 MUST 接受单一使用日，按该日整天查找，不要求时间或物流天数。两种方式都只候选 active、指定主机／附件类型及正式型号 ID 的设备；找到返回第一台和全部可用设备、占用日期及总数，无候选 404。创建 API 会用最终提交日期或时间再次校验，因此此查询不预留设备。

#### Scenario: 两台候选
- **WHEN** 快递租赁指定型号同仓有两台设备在计算区间空闲
- **THEN** 返回 `device,available_devices,total_available=2,ship_out_date,ship_in_date`

#### Scenario: 现场当天查档期
- **WHEN** 现场单查询 10 日的设备
- **THEN** 候选按 10 日整天与两种履约方式的有效占用比较，不加前后一天

### Requirement: 每日空闲与寄出数量使用不同候选集

`available_count` MUST 先以当前 active 主设备为候选，再扣除在当天与有效占用时间相交、状态为 `not_shipped/scheduled_for_shipping/shipped/returned` 的唯一设备数；同设备重叠多单只扣一次。未归还的逾期现场设备不得被计为空闲。`ship_out_count` 与 `accessory_ship_out_count` 则只按当天有 `ship_out_time`、履约方式为 `courier` 且状态为 `not_shipped/scheduled_for_shipping` 的租赁行分别计数，不受 `available_count` 候选集合限制。仓库筛选寄出记录按租赁履约仓库；型号筛选附件寄出按其父主机型号判断。单日请求只返回当天统计对象；范围请求返回 `{start_date,end_date,stats:{YYYY-MM-DD:每日统计}}`。

#### Scenario: 同设备同日两条占用
- **WHEN** 一台 active 主设备有两条同一天重叠占用
- **THEN** 空闲数量只减 1；两条待寄出快递订单若都在当天寄出则寄出计数可为 2

#### Scenario: 同日现场和快递单
- **WHEN** 一台设备在同一天同时有现场占用及快递占用
- **THEN** 当天空闲主机数最多减一；寄出数量只统计快递单，现场单在甘特上有独立标识
