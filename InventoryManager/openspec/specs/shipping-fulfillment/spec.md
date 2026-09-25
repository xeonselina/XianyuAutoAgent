# 预约发货、合包、面单与物流追踪

## Purpose

从批量发货处理器、顺丰／快麦集成、合包、打印与物流追踪代码反推。细分的顺丰面单、快麦、PDF 和批量打印 UI 规格已经另存在同级目录，本文件定义它们之间的真实业务编排。

## Requirements

### Requirement: 发货前必须核对履约仓库和收件信息

主租赁及其库存附件当前仓库 MUST 与租赁履约仓库相同；新建顺丰订单前必须有客户名、电话、收件地址，且不得已有寄出运单号。顺丰和快麦配置按租赁的履约仓库解析，缺少某仓凭据不得回退到另一仓。顺丰发件地址由仓库省市与详细地址拼接，避免重复前缀。

#### Scenario: 库存附件跨仓
- **WHEN** 主机在履约仓，某件库存附件已在另一仓
- **THEN** 顺丰下单前返回仓库不匹配，不产生外部运单

### Requirement: 待发货订单按实际包裹分组

有运单号的主租赁 MUST 按同仓库、相同运单号合组。未发货且无运单号的主租赁，若收件地址去空白、电话标准化、仓库、快递类型及计划发货日相同，则合成待寄包裹；缺地址／电话、子租赁、非待发货订单单独成组。接力后单被批量流程排除，不得由仓库重复寄出。组内按租赁 ID 升序，组顺序稳定。

#### Scenario: 同单两台同址同日
- **WHEN** 两条待发货主租赁有相同仓库、地址、电话、快递类型与寄出日
- **THEN** 预约顺丰时只创建一个包裹和运单，响应两条租赁结果但 `shipment_count=1`

### Requirement: 批量预约逐包裹原子处理

`POST /api/shipping-batch/schedule` MUST 接受最多 100 个整数租赁 ID 和 ISO 预约时间。每包先锁成员并复核合包资格、状态 `not_shipped` 与发货前置条件，再调用顺丰；成功后组员统一写运单号、预约时间和 `scheduled_for_shipping`。某包失败只回滚该包，后续包仍可处理，结果按租赁逐条给成功或错误码，并区分 `scheduled_count`（台数）与 `shipment_count`（包裹数）。不能把失败包显示为全批成功。

#### Scenario: 一包成功一包失败
- **WHEN** 两个包裹中第二包顺丰配置缺失
- **THEN** 第一包租赁完成预约，第二包保持原状态；响应 `results` 和 `failed_rentals` 列出各自结果

### Requirement: 快递类型和打印配置由发货接口管理

每条租赁 `express_type_id` MUST 仅支持 1 特快、2 标快、263 半日达；`PATCH /api/shipping-batch/express-type` 更新选定租赁。`GET /api/shipping-batch/printers` 要求具体仓库，返回该仓快麦默认打印机 SN，不得在 `all` 模式凭其它仓配置打印。批量打印最多 100 条；可选择是否交替打印发货单，返回总数、包裹数、面单成功数、失败数、逐条结果及必要时发货单成功数。

#### Scenario: 全仓库状态请求打印机配置
- **WHEN** `warehouse_id=all` 请求打印机
- **THEN** 返回 400“请指定仓库”

### Requirement: 闲鱼发货只在订单和运单完整时触发

`POST /api/shipping-batch/ship-to-xianyu/<rental_id>` MUST 要求闲鱼订单号、寄出运单号和状态为 `not_shipped` 或 `scheduled_for_shipping`；外部平台确认成功后才改租赁为 `shipped`，空寄出时间补当前 UTC。另一单条路径 `/api/rentals/<id>/ship-to-xianyu` 由租赁处理器实现，具体状态限制／响应形状以其代码契约为准。

#### Scenario: 闲鱼外部服务失败
- **WHEN** 闲鱼返回发货失败
- **THEN** 租赁状态及寄出时间保持原值

### Requirement: 顺丰追踪与设备状态更新时间有独立入口

`/api/sf-tracking/list` MUST 列出在请求日期窗口内有寄出运单号的租赁，默认今天前后各 4 天，并可按仓库筛选；`/query` 和 `/batch-query` 查询顺丰状态。旧 `/api/tracking/query`、`/batch-query` 仍支持手工查询，但 `/update-now`、`/scheduler-status` 以及设备在线状态刷新入口已明确返回 410。用户可从 PC 顺丰追踪页查询，但外部追踪服务失败不得伪称快递已妥投。

#### Scenario: 默认追踪窗口
- **WHEN** 不给 `start_date,end_date` 请求 `/api/sf-tracking/list`
- **THEN** 查询今天前 4 天到后 4 天且有寄出运单号的租赁

### Requirement: 合包键及接力排除具有精确优先级

已有寄出运单号的主租赁 MUST 先按 `(仓库 ID,去空格运单号)` 合组，不因收件地址已更改拆包。未有运单时，只在主租赁且 `not_shipped` 并有非空解析地址、电话时，按 `(仓库 ID,express_type_id 或 2,寄出日,去所有空白的地址,去空白括号横线的电话)` 合组；寄出日优先 `ship_out_time.date()`，缺时使用 `start_date`。接力后单即使地址相同仍强制单独成组并在批量预约校验时拒绝。组内与组间顺序以租赁 ID 升序首次出现决定。

#### Scenario: 已有同一运单而地址修改
- **WHEN** 两条同仓主租赁已有同一运单号，后一条收件地址被修改
- **THEN** 批量打印仍按一个已确认包裹处理，不能再次创建新顺丰订单

### Requirement: 预约发货输入与部分失败码稳定

批量预约 MUST 拒绝空 ID、无预约时间、超过 100 个 ID、非整数 ID 或无法解析的 ISO 时间；带时区时间转上海业务时间，无时区时间按上海本地处理。不存在的 ID 在逐条结果中返回“租赁记录不存在”。每包复核后，配置缺失用 `CONFIG_INCOMPLETE`，履约仓不符用 `WAREHOUSE_MISMATCH`，状态或选中集合变化用 `VALIDATION_ERROR`，顺丰失败用 `EXTERNAL_SERVICE_ERROR`。外层 HTTP 可为 200 且 `data.failed_rentals` 非空；客户端必须读逐条结果。

#### Scenario: 三台中一台不存在
- **WHEN** 提交两个有效 ID 和一个不存在的 ID
- **THEN** 不存在 ID 进入失败列表；有效租赁按包裹各自处理，`scheduled_count` 只数成功台数

### Requirement: 批量状态统计与快递类型更新保留现役实现

`GET /api/shipping-batch/status` MUST 优先采用逗号分隔的 `rental_ids`；否则仅在 `start_date,end_date` 都存在时按 `ship_out_time` 过滤，均不提供则统计当前租户全部租赁行。`total` 是查到行数，`waybill_recorded` 数非空寄出单号，`scheduled` 数非空预约时间，`shipped` 数状态恰为 shipped。`PATCH /api/shipping-batch/express-type` 只校验租赁存在和类型为 1/2/263，当前端点没有额外发货状态限制；未来如要添加限制需先变更规格。

#### Scenario: 只给开始日期请求批量状态
- **WHEN** 调用 `/status?start_date=...` 而无结束日期及 ID 列表
- **THEN** 当前实现返回全租户统计；复刻不能误写成只筛该日

### Requirement: 顺丰追踪新旧查询路径的响应不能混同

`GET /api/sf-tracking/list` MUST 用寄出时间而非租赁起止日期筛选有寄出运单号的记录，按寄出时间降序，返回 `rental_id,customer_name,customer_phone,destination,device_name,ship_out_tracking_no,ship_out_time,status`。`POST /api/sf-tracking/query` 接 `tracking_no` 或 `tracking_number`，可附 `warehouse_id,phone_last4`；确定未找到时 HTTP 200 且 `success=false,data.status=not_found`，配置缺失为 400、仓库不确定为 409、上游故障为 502。其批量查询上限 100，返回成功字典、错误单号和逐项错误明细。旧 `/api/tracking/query` 成功使用 `tracking_info` 键，旧批量最多 50 个并返回 `results`，不能改成新端点响应结构。

#### Scenario: 查询真实不存在的运单
- **WHEN** 顺丰确认查询不到指定运单
- **THEN** 新查询端点返回 200、`success=false`、`status=not_found` 与空轨迹；调用方不当作网络故障重试

### Requirement: 已移除的自动物流和在线状态入口明确返回 410

`POST /api/tracking/update-now`、`GET /api/tracking/scheduler-status`、`POST /api/device/update-status`、`POST /api/device/force-update-status`、`GET /api/device/status-summary` MUST 返回 410，提示自动轨迹调度或设备在线／离线功能已移除。后台 worker 不运行这些旧在线状态任务。

#### Scenario: 旧客户端触发在线状态刷新
- **WHEN** 调用 `/api/device/update-status`
- **THEN** 返回 410，不改变设备生命周期，也不启动后台刷新

### Requirement: 浏览器发货单与快麦热敏内容联使用各自排版

PC 单笔 `/shipping/:id` MUST 按订单保存的租赁组合快照生成主设备及组合物品行，旧订单则按 `lens_combo` 回退充电头、镜头和手提包等品名；展示店铺名、同单已录台数、CODE128 订单识别码、买家／电话／收货地址、器材、寄出与租赁日期、结束日次日 16:00 前的归还期限、履约仓寄回联系人及底部两张教程二维码。无该仓寄回联系人时禁用打印按钮。单笔浏览器打印采用 A4、约 1.5cm 页边。批量 `/batch-shipping-order` 由日期 query 再查订单，每条生成一页 A4、8mm 页边；当前批量页面主设备表格使用型号／设备名和默认附件，不调用单笔页面的组合快照行生成器。两页均从当前租户和仓库读取店名／寄回联系人，不能携带其它租户店名。

#### Scenario: 修改型号组合后重印旧单
- **WHEN** 旧租赁已保存自由租赁组合快照，之后管理员修改型号当前组合
- **THEN** 单笔出货单仍按租赁快照列商品；批量出货单维持其当前独立表格口径

### Requirement: 快麦内容联每台生成带当前租户品牌的热敏 PNG

服务端内容联 MUST 用共享渲染器按租赁 ID 生成 76mm、203DPI、约 607px 宽的图像：每次请求从当前租户上下文取得店铺名（无名时“发货单”）并逐行居中换行，后接 `R-<id>`；显示收货人、设备号、下单时租赁组合名称或旧镜头枚举、非配套库存附件、该包裹第几台／共几台、运单、租期结束日次日 16:00 前的归还时限及仓库寄回地址／姓名／电话，底部左右放“安装拍摄教程”“照片传输教程”二维码。以捆绑标记表示的手柄和转接环不作为库存附件另列。图像裁剪到内容高度后以灰度增强和 Floyd–Steinberg 抖动转 1-bit PNG base64，再交快麦以 76×130mm 打印。共享单例不得缓存上一租户店名。

#### Scenario: 两租户轮流打印
- **WHEN** A 租户打印内容联后 B 租户用同一 Web 进程打印
- **THEN** B 内容联页眉只显示 B 店名；无租户名的测试／兼容上下文回退“发货单”，不显示 A 店名

## HTTP 编排契约

| 路径 | 输入／响应 |
|---|---|
| `GET /api/rentals/by-ship-date` | 日期窗口候选，主租赁按待发货寄出时间／预约时间／已发货时间分类，带合包和接力元数据 |
| `POST /api/shipping-batch/schedule` | `{rental_ids:[整数],scheduled_time:ISO}` → `{scheduled_count,shipment_count,failed_rentals,results}` |
| `GET /api/shipping-batch/status` | 可选 `rental_ids` 或日期窗口 → `{total,waybill_recorded,scheduled,shipped}` |
| `PATCH /api/shipping-batch/express-type` | `{rental_id,express_type_id}` |
| `GET /api/shipping-batch/printers` | 具体 `warehouse_id` → `{printers:[{id,sn,name,is_default}],message}` |
| `POST /api/shipping-batch/print-waybills` | `{rental_ids,include_shipping_slips}` → `{total,parcel_count,waybill_success_count,failed_count,results,slip_success_count?}` |
| `POST /api/shipping-batch/ship-to-xianyu/<id>` | 确认闲鱼发货并改状态 |
| `GET/POST /api/sf-tracking/{list,query,batch-query}` | 列表或按运单追踪，旧 JSON 响应格式 |
| `POST /api/tracking/{query,batch-query}` | 旧手工查询；批量上限 50 个，逐条结果 |
| `/api/tracking/{update-now,scheduler-status}`、`/api/device/{update-status,force-update-status,status-summary}` | 自动轨迹更新和设备在线状态已移除，返回 410 |

预约时间使用 `app/utils/business_time.py` 以 Asia/Shanghai 业务墙钟写入旧无时区 DATETIME：带时区输入先转换上海时间，无偏移输入当作上海时间。租赁通用状态接口的自动时间仍由其自身规则处理，不要把两种时间语义混淆。

## 页面契约

PC `/batch-shipping` 选择日期、仓库、候选租赁和预约时间，显示合包／接力排除、逐台和逐包结果；`/batch-shipping-order` 是新标签中的批量发货单，`/shipping/:id` 是单条发货单，`/sf-tracking` 查询快递状态。移动端有 `/mobile/batch-shipping`，显示适合手机的候选与提交。PC 面单弹窗点击后立即按仓库配置的默认快麦 SN 打印，地址联按包裹、内容联按设备交替输出；当前弹窗没有打印机选择和失败项一键重试，具体见 `batch-print-ui`。

## 代码依据与验收

依据：`app/handlers/shipping_batch_handlers.py`、`app/services/shipping/*`、`app/services/printing/*`、`app/services/integration_resolver.py`、`app/routes/{shipping_batch_api,sf_tracking_api,tracking_api}.py`、`frontend/src/views/{BatchShippingView,BatchShippingOrderView,ShippingOrderView,SFTrackingView}.vue`、`frontend-mobile/src/views/BatchShippingView.vue`。验收覆盖同地址合包、运单号合包、接力后单排除、局部失败、配置按仓库隔离、面单打印数、时区和闲鱼失败不改状态。
