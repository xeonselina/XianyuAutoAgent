# 租赁归还验货

## Purpose

从验货路由、检查项生成器、验货服务与 PC 页面反推。验货关联主租赁、实物设备、库存附件及实际收货仓库。

## Requirements

### Requirement: 最近租赁查询以设备为入口

系统 MUST 能按设备 ID 或设备名称查找该设备 `start_date < 今天` 且起租日期最新的一条租赁，并返回完整租赁及动态检查清单。设备不存在或无历史租赁分别返回 404。此“最近”按开始日期排序，不要求状态已完成。

#### Scenario: 找到历史租赁
- **WHEN** 操作员输入设备名查询，设备有两条过去起租记录
- **THEN** 返回开始日期较晚的一条及当时租赁配置生成的清单

### Requirement: 检查清单由租赁快照生成

清单 MUST 依序包含六个基础项：手机、镜头无严重磕碰；屏幕贴膜或贴纸；摄像头各焦段无白色十字；镜头镜片清晰，无雾无破裂；镜头拆装顺滑；充电头和充电线。勾选配套手柄、镜头支架时各加一项；有库存附件子租赁时合并成“个性化附件：<名称以顿号连接>”；代传照片加一项；有损坏备注时最后加“处理用户反馈：<备注>”，默认未勾。

#### Scenario: 有损坏备注
- **WHEN** 租赁包含手柄、手机支架与损坏备注
- **THEN** 清单为六个基础项、手柄、个性化附件和损坏处理项，损坏项不得默认勾选

### Requirement: 验货记录保存检查项和正常／异常判定

`POST /api/inspections` MUST 接受主租赁 ID、该主机设备 ID 和合法 `check_items`；可选实际收货仓和实际收到的库存附件 ID。所有检查项勾选才记 `normal`，任一未勾记 `abnormal`。记录保存检查项名称、勾选状态与顺序。子租赁不能单独作为验货主租赁，收到的实物 ID 必须属于主租赁或其库存附件。

#### Scenario: 未收到的非本单设备
- **WHEN** 提交另一租赁的附件 ID 到 `received_device_ids`
- **THEN** 返回 400，验货记录与仓库都不改变

### Requirement: 验货入仓及租赁状态必须原子同步

服务端 MUST 按仓库、设备、租赁顺序锁定相关记录，复核读取快照；锁定期间变化返回 409 要求重试。实际收到的主机／附件移动到所选收货仓，未指定时使用租赁履约仓。若主租赁为 shipped 或 returned，验货时把当前仍为 shipped 的主子租赁改为 returned。跨仓收到设备会生成未来租赁的移仓修复预览摘要；任何预览失败都回滚验货、检查项、设备仓位和状态变化。写审计记录。

#### Scenario: 收货仓改变且未来档期受影响
- **WHEN** 设备从原仓归还至另一仓并影响未来已预约租赁
- **THEN** 验货响应带 `warehouse_impacts`，实物仓位与状态在同一事务提交；预览计算失败时全部回滚

### Requirement: 历史验货可筛选并更新

`GET /api/inspections` MUST 支持设备名模糊筛选、`normal/abnormal` 状态、分页，页码小于 1 归一为 1、每页不在 1–100 回退 20。详情 GET 返回关联租赁、设备和检查项。PUT 可更新勾选状态，并按全部勾选重新计算验货状态。

#### Scenario: 修改漏检项
- **WHEN** 操作员在历史记录中把唯一未勾的项目改为已勾
- **THEN** 该记录变为 normal，清单其余项和租赁关联不丢失

### Requirement: 验货创建参数和收货设备集合严格验证

创建验货 MUST 要求 `rental_id,device_id` 为非布尔正整数且 `check_items` 为非空数组。每个检查项需 `name,is_checked,order`：名称为非空文本且最多 1020 字，勾选必须布尔，排序为 0–2147483647 的非布尔整数。`received_device_ids` 省略视空数组，显式提供时需为正整数数组并去重；主机始终视为收到，列表中只能额外包含本主租赁及其子租赁的设备 ID。收货仓未给时使用租赁履约仓；给出时必须是有效正整数且仓库存在。

#### Scenario: 无收货附件列表
- **WHEN** 主机租赁带两件库存附件，创建验货时省略 `received_device_ids`
- **THEN** 主机可入仓，附件不因清单列有名称就自动移动仓位

### Requirement: 验货仅自动推进已寄出的租赁状态

主租赁状态为 `shipped` 或 `returned` 时，服务 MUST 遍历该主租赁及子租赁，把其中仍是 `shipped` 的记录改为 `returned`；`not_shipped` 或 `scheduled_for_shipping` 主租赁不因验货而自动变 returned。响应 `warehouse_impacts` 仅在实际设备跨仓移动时产生，包含后续需修复的未来租赁摘要；创建结果还含检查项与验货状态。

#### Scenario: 未发货记录被验货
- **WHEN** 主租赁当前为 `not_shipped`，操作员提交全勾检查项
- **THEN** 可生成 normal 验货记录，但租赁状态不被自动改成 returned

### Requirement: 验货查询和历史修改保留旧 API 细节

按设备名称查最近租赁 MUST 精确匹配 `Device.name` 的第一台设备，再取该设备开始日期早于今天且日期最新的租赁；按 ID 查同样不检查是否已发货。找不到设备时旧响应含 `error=Device not found`，无租赁含 `error=No rental found`，均为 404。历史 PUT 接 `{check_items:[{id,is_checked}]}`，仅更新确属当前验货记录的检查项 ID，其它 ID 忽略；然后用所有已存项重新算 normal／abnormal，更新时间采用本地 `datetime.now()`。列表按创建时间倒序，响应 `data.records` 和 `data.pagination`。

#### Scenario: 修改请求夹带另一验货记录的检查项
- **WHEN** PUT 某验货记录时提交另一记录的检查项 ID
- **THEN** 另一记录不改变；当前记录状态仅由自己的检查项计算

## 数据及 API

`inspection_record`：`id,rental_id,device_id,status(normal/abnormal),inspector_user_id`（预留）、创建和更新时间；`inspection_check_item`：`id,inspection_record_id,item_name,is_checked,item_order`，删除父记录时子项级联。验货记录的时间戳当前使用 `datetime.now()`，与租赁模型 UTC 默认不同，复刻时需明确这一历史差异。

| 路径 | 结果 |
|---|---|
| `GET /api/inspections/rental/latest/<device_id>`、`GET /api/inspections/rental/latest/by-name/<name>` | `{success:true,data:{rental,checklist}}`；不存在 404 |
| `POST /api/inspections` | `{rental_id,device_id,check_items,receiving_warehouse_id?,received_device_ids?}` → 201 记录详情及 `warehouse_impacts` |
| `GET /api/inspections/<id>` | 记录、租赁、设备、检查项 |
| `PUT /api/inspections/<id>` | 更新 `check_items` 勾选 |
| `GET /api/inspections` | `device_name,status,page,per_page` → 分页记录 |

PC `/inspection` 先选择设备／租赁，显示动态检查清单、收货仓和实物附件，然后保存；`/inspection-records` 浏览与筛选历史。移动端当前没有独立的验货路由，不能凭 PC 功能假定移动端已有同样页面。

## 代码依据与验收

依据：`app/routes/inspection.py`、`app/services/{inspection_service,checklist_generator,warehouse_movement_service}.py`、`app/models/{inspection_record,inspection_check_item}.py`、`frontend/src/views/{InspectionView,InspectionRecordsView}.vue`。验收覆盖清单顺序、损坏备注默认未勾、错误设备拒绝、并发变更 409、跨仓原子性、正常／异常重新计算和分页边界。
