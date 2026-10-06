# 顺丰云面单 PDF 获取

## Purpose

描述现役 `SFExpressService.get_waybill_pdf` 的请求、下载与错误映射。创建顺丰运单、批量预约与接力发货另见 `shipping-fulfillment`。

## Requirements

### Requirement: 面单必须基于已有运单和收件信息

读取 PDF 前 MUST 检查主租赁已有 `ship_out_tracking_no`，否则返回 `{success:false,message:'缺少运单号'}`；客户名、电话或目的地缺失则返回“缺少收件人信息”。面单服务按租赁履约仓的顺丰配置实例执行；上层打印服务在此之前还要核对主设备与实际附件仓库一致，并解析同仓快麦配置。

#### Scenario: 没有寄出运单
- **WHEN** 尚未预约生成运单的租赁请求打印面单
- **THEN** 不调用顺丰云打印，返回“缺少运单号”

### Requirement: 顺丰云打印使用固定模板和租赁备注

服务 MUST 调 `COM_RECE_CLOUD_PRINT_WAYBILLS`，请求 `language='zh-CN'`、一个 `documents` 条目（`masterWaybillNo`、`isPrintLogo='true'`、`remark`）、`templateCode='fm_76130_standard_Y45WBDEO'`、`version='2.0'`、`fileType='pdf'`、`sync=1`。备注含同票设备台数、客户名、主设备编号、勾选的手柄／转接环、库存附件型号及寄出／寄还日期；寄还日期后注明“16:00前”。目的地解析会计算收件人、电话与地址以做基础兼容，但此云打印请求的 `documents` 实际只提交运单号及备注，不能把旧规格所称的整套 `orderId`／联系人字段当作当前请求。

#### Scenario: 一票双机带附件
- **WHEN** 面单对应同一包裹两台主机且首台含手柄和库存附件
- **THEN** 备注中的机器数为 2，并列首台设备号与附件；请求只含一个面单文件条目

### Requirement: 顺丰业务结果必须再下载 PDF

外层 `apiResultCode` MUST 等于 `A1000` 且解析后的 `apiResultData.success=true`，从 `obj.files[0]` 取得 `url,token`；缺文件返回“未获取到面单文件”。下载向该 URL 发 GET，头为 `X-Auth-Token: <token>`、超时 30 秒，成功把响应字节作为 `pdf_data` 返回 `{success:true,message:'获取成功'}`。顺丰业务失败、JSON 解析异常或下载异常在当前顶层统一返回“顺丰服务调用失败”；该方法没有代码实现的指数退避或两次重试。

#### Scenario: 云打印返回空 files
- **WHEN** 顺丰外层与内层均成功，但 `obj.files=[]`
- **THEN** 返回失败“未获取到面单文件”，不向快麦提交图像

### Requirement: 下载错误不能改变租赁或运单状态

取面单 PDF 与打印是读取既有运单的后续操作；失败时 MUST 保留 `ship_out_tracking_no` 和 `scheduled_ship_time`，且不能把订单标已发货。打印服务把顺丰失败映射成逐条 `EXTERNAL_SERVICE_ERROR`，批量操作可继续处理其它包裹。

#### Scenario: 下载超时
- **WHEN** PDF URL GET 超时
- **THEN** 当前包裹报告打印失败，原租赁仍保留预约与运单号；其它包裹继续

### Requirement: 地址联标明每台设备的实际租赁组合
顺丰云打印备注 MUST 在包裹中每台设备名后紧跟该订单保存的组合名称；组合不是该设备型号的默认组合时 MUST 用黑色醒目括号围住组合名称，默认组合正常显示。没有组合数据时只显示设备名。打印失败时不得改写租赁、组合或运单数据。PC 批量打印和移动端发货流程共用此服务，各履约仓的规则相同。

#### Scenario: 非默认组合的单机包裹
- **WHEN** 操作员打印一台设备的地址联，订单组合不同于该型号的默认组合
- **THEN** 顺丰备注中的设备名后显示带黑色醒目括号的订单组合名称

#### Scenario: 默认组合与同票多机
- **WHEN** 操作员打印含默认和非默认组合两台设备的同票地址联
- **THEN** 备注依次显示两台设备及各自的组合名称，只有非默认组合带醒目括号

## 代码依据

`app/services/shipping/sf_express_service.py`、`app/services/shipping/waybill_print_service.py`、`app/services/shipping/shipment_group_service.py`。旧归档规格里“网络错误最多重试两次”与当前代码不符。
