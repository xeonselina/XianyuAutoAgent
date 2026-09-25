# 快麦云打印集成

## Purpose

按当前仓库配置和 `KuaimaiPrintService` 源码定义打印服务。快麦凭据存在租户业务库的仓库配置表中；页面的打印机列表只是该仓库已设置的 SN，不是实时云打印机列表。

## Requirements

### Requirement: 快麦客户端按履约仓库解析

`IntegrationResolver.kuaimai_for_rental` MUST 用租赁保存的 `warehouse_id` 取得该仓 `WarehouseKuaimaiConfig`，完整要求 `app_id,app_secret_ciphertext,printer_sn`；密钥用专用 purpose 解密，空值或解密失败抛 `ConfigurationIncomplete`。客户端实例固定保存 `app_id,app_secret,default_printer_sn`，不使用全局 `KUAIMAI_APP_ID` 或把 A 仓密钥回退给 B 仓。

#### Scenario: 只配置 A 仓
- **WHEN** B 仓租赁请求打印，只有 A 仓有快麦配置
- **THEN** B 仓项因配置不完整失败，A 仓打印机不能代替它执行

### Requirement: 快麦请求按当前参数签名

`_generate_sign(params)` MUST 把参数按 key 排序，拼接 `app_secret + key1value1... + app_secret`，对 UTF-8 字节求 MD5 小写十六进制。调用 API 时加入本地墙钟格式 `YYYY-MM-DD HH:mm:ss` 的 `timestamp`、`appId`，再加入 `sign`，以 JSON POST 到 `http://cloud.kuaimai.com` 的固定方法路径，`Content-Type: application/json`，超时 30 秒。业务成功以响应 `status=true` 判断，并返回 `data`；网络异常转换成“快麦API请求失败”。

#### Scenario: 签名输入顺序不同
- **WHEN** 两组参数包含相同键值但插入顺序不同
- **THEN** 签名相同，且请求体包含 `appId,timestamp,sign`

### Requirement: 限流只按快麦业务码或文案重试一次

当快麦 JSON 响应 `status=false` 且 `code=6027`，或文案含“限流／过于频繁”时，服务 MUST 等待 2 秒后最多重调一次；普通业务错误不重试。HTTP 请求异常由当前服务直接报错，不能假设所有 HTTP 429 都会按业务限流逻辑重试。第二次仍失败则打印调用方得到通用错误。

#### Scenario: 快麦业务码 6027
- **WHEN** 首次快麦业务响应为 6027，第二次成功
- **THEN** 中间等待 2 秒并只发起一次重试；结果取第二次 `data`

### Requirement: 图像打印固定使用仓库打印机 SN

`print_image(base64_image,copies=1,width=76,height=130)` MUST 把图像嵌入 `<page><render ...><img x='1' y='1'>...</img></render></page>`，向 `/api/cloud/print/tsplXmlWrite` 提交 `sn,xmlStr,printTimes`。成功取 `data.jobId` 返回 `{success:true,job_id}`；缺 SN 返回 `{success:false,error:'当前仓库未配置打印机SN'}`，其它异常返回通用“快麦打印服务调用失败”。当前公开打印流程不支持在一次请求中传另一个打印机 ID。

#### Scenario: PDF 有两页
- **WHEN** 面单转换得到两张图像
- **THEN** 每页向同一个仓库配置 SN 提交一次打印，各打印一份；任何一页失败使该面单打印结果失败

### Requirement: 打印机读取接口返回配置而非云端发现

`GET /api/shipping-batch/printers?warehouse_id=<具体 ID>` MUST 校验租户会话、仓库和快麦配置；成功返回 `data.printers=[{id:SN,sn:SN,name:'默认打印机',is_default:true}]` 及“快麦打印机通过SN直接配置”。缺具体仓库或 `all` 返回 400，配置不全返回 400 `CONFIG_INCOMPLETE`。当前服务内存在 `get_print_status(job_id)` 对 `/api/cloud/print/result` 的封装，但没有面向用户的打印任务追踪页面或实时打印机缓存。

#### Scenario: 全仓视图取打印机
- **WHEN** 请求 `warehouse_id=all`
- **THEN** 返回 400“请指定仓库”，不会列所有仓库的 SN

## 代码依据

`app/services/printing/kuaimai_service.py`、`app/services/integration_resolver.py`、`app/handlers/shipping_batch_handlers.py`、`app/models/warehouse.py`。验收要模拟 HTTP 成功／业务失败／业务限流／网络失败，并确认密钥和打印机不会跨仓库泄漏。
