# 设备、型号、仓库与移仓

## Purpose

从设备／型号模型、设备 API、库存查询和移仓服务反推。与 `rental-management` 共用设备 ID、生命周期和占用规则。

## Requirements

### Requirement: 设备拥有正式型号和可追踪生命周期

每个设备 MUST 保存名称、唯一序列号、旧型号字符串、可空正式型号 ID、是否库存附件、当前仓库及生命周期。生命周期仅 `active,sold,decommissioned,damaged,retired`，只有 `active` 可作为新租赁选择；售出、损坏、停用和退役须从可出租统计中排除。旧 `status` 字段不得作为设备生命周期替代。

#### Scenario: 售出后查看历史租赁
- **WHEN** 一台有历史租赁的设备标记 sold
- **THEN** 设备与旧租赁仍可读取，新租赁不能选它，生命周期汇总的可出租数下降

### Requirement: 型号库决定设备类型和租赁组合

型号库 MUST 有唯一编码 `name`、显示名、启用状态、主机／附件类型、可选父型号、默认附件、设备价值、允许的旧镜头组合及自由租赁组合。创建设备必须用 `model_id`，设备 `model` 字符串同步型号编码，`is_accessory` 与型号类型一致。型号停用后不可用于新设备，但保留原设备可编辑时的型号。已有设备引用或关联附件的型号不可删除；未归类旧 `model` 分组可批量归入一个启用型号。

#### Scenario: 旧设备按型号编码归类
- **WHEN** 管理员把未设置 `model_id`、旧 `model` 文本相同的一组设备归入正式型号
- **THEN** 一次事务更新组内所有设备的 `model_id,model,is_accessory`，响应包含更新数

#### Scenario: 删除被引用的型号
- **WHEN** 型号已有设备引用或子附件型号
- **THEN** 返回 409 `MODEL_IN_USE`，提示先停用或处理关联

### Requirement: 设备增删改与生命周期分开

`POST /api/devices` MUST 要求名称、序列号、正式型号及具体仓库，默认生命周期 `active`；序列号不得重复。`PUT /api/devices/<id>` 可改名称、序列号和正式型号，但不能直接改 `warehouse_id`、旧 `model` 或旧 `status`；移仓走预览／执行接口。设备存在任何租赁记录时不能删除。生命周期专用 PUT 可设状态与原因，快速标售接口可单独标 sold。

#### Scenario: 直接编辑仓库字段
- **WHEN** PUT 设备请求带 `warehouse_id`
- **THEN** 返回 400，要求使用跨仓移动功能，不留下部分设备更改

### Requirement: 库存查询保留旧响应差异

`GET /api/devices` MUST 可按分页、关键词、名称、型号、序列号、生命周期、主机／附件和仓库筛选；单页最多 100。通用词 `q` 同时模糊匹配设备名、序列号、旧型号。查询返回直接分页对象而非通用 `success/data` 壳。单条设备 GET、PUT、DELETE 与生命周期旧接口使用 `{success,data?,error?}`。租赁下拉须读取全部相关分页并自行按型号／设备名自然排序。

#### Scenario: 搜索“机身”
- **WHEN** GET `/api/devices?q=机身&is_accessory=false`
- **THEN** 只返回主设备中名称、序列号或型号含该词的分页结果

### Requirement: 仓库写入不能凭全仓库视图猜测

仓库读取允许具体 ID、`all` 或缺省，返回当前租户的仓库数据；写入 MUST 要求具体的整数仓库 ID，仅租户恰有一个仓库时自动选它。管理员可建仓、改省市与名称，并分别配置每仓的顺丰、快麦与退件联系人；读取只暴露配置完成状态。设备当前仓库与租赁履约仓库分别保存。

#### Scenario: 多仓库新增设备缺省仓库
- **WHEN** 租户有两个仓库且 POST `/api/devices` 未提供 `warehouse_id`
- **THEN** 返回 400“请指定仓库”

### Requirement: 移仓必须先预览后执行

跨仓移动 MUST 先 POST `/api/devices/<id>/movement-preview` 得到来源、目标、`auto_fixable,blocked,shortages,manual` 列表和签名 token。预览找出受影响的未来租赁，优先用同型号、同仓且无档期冲突的设备自动替换；不能自动修复的订单必须明确列出。执行 POST `/api/devices/<id>/move` 只接受预览 token，校验租户、设备、仓库与相关设备／租赁快照；任一状态变更返回 409 要求重预览。成功时设备仓库与可自动修复租赁／附件一事务更新。

#### Scenario: 预览后其他操作占用备选设备
- **WHEN** 预览选择的替代设备在执行前被另一租赁占用
- **THEN** 执行返回 409，源设备仓库与所有受影响租赁均不改变

#### Scenario: 使用另一个租户的 token
- **WHEN** 租户 B 使用租户 A 生成的移仓预览 token
- **THEN** 拒绝执行，不访问 A 的业务库

### Requirement: 生命周期汇总与列表可按仓库筛选

汇总 MUST 分别给 `active,sold,decommissioned,damaged,retired,total` 数量、`active_and_online`、`excluded_from_statistics` 与 `available_for_rental`；当前后二者由生命周期直接计算，不等同于档期空闲数。状态列表可选 `all` 或五种生命周期，并返回设备详情与可用／统计排除标记。

#### Scenario: 一台 active 设备正在出租
- **WHEN** 查询生命周期汇总
- **THEN** 它仍计入 `available_for_rental`，档期是否空闲由库存可用性接口另算

### Requirement: 型号编码和类型的修改边界固定

创建正式型号 MUST 提供 1–50 字的编码与 1–100 字的显示名；编码首位只能是字母或数字，余下只能含字母、数字、点、横线、下划线，并以大小写不敏感方式查重。创建后编码不可改；主型号可关联附件型号，附件的父型号只能指向主型号且不可指向自身。已有设备引用的型号不可改主机／附件类型；仍有关联附件的主型号也不可改类型。设备价值须是 0–99999999.99 的数字或空值。

#### Scenario: 修改已使用型号的类型
- **WHEN** 某型号已有设备，管理员把 `is_accessory=false` 改为 true
- **THEN** 返回 409 `MODEL_CONFLICT`，设备与型号类型均保持原样

#### Scenario: 修改型号编码
- **WHEN** 更新请求把 `name=X200U` 改为另一个编码
- **THEN** 返回 400，既有设备的旧编码不会被静默迁移

### Requirement: 主型号镜头组合和租赁组合保持一致

主型号 MUST 至少有一个允许的旧镜头组合，默认组合必须在允许列表中；列表去重且每项须属于系统 `LENS_COMBO_VALUES`。主型号另存一至 50 个租赁组合，每个有唯一的大小写不敏感名称、稳定 ID、启用状态和最多 50 个发货物品；物品名不超过 150 字，数量为 1–999 的整数。至少一个组合启用，默认组合 ID 必须指向启用项。更新现有组合的 ID 只能来自该型号已有 ID；新组合服务端生成 `pkg_` UUID，并可通过客户端临时 ID 指定默认项。附件型号清空镜头组合和租赁组合。未直接提交新组合时，旧镜头组合配置变化可生成兼容租赁组合。

#### Scenario: 默认组合被停用
- **WHEN** 管理员提交两个组合，却把 `default_rental_package_id` 指向其中停用的一项
- **THEN** 返回 400，原型号配置不变

#### Scenario: 附件型号收到租赁组合
- **WHEN** 创建库存附件型号并附带主机镜头和租赁组合字段
- **THEN** 附件的这些主机专用配置被清空，附件可关联一个有效主型号

### Requirement: 型号库与旧型号组的排序和归类可预期

`GET /api/device-models/library` MUST 把正式型号按主机先于附件、显示名、ID 排序，附 `device_count,accessory_count`；旧组只收 `model_id` 为空且旧 `model` 文本非空的设备，按去空格小写归并，再按数量降序、名称排序。`assign-legacy` 只能指向 active 型号，匹配同一归一化组的所有设备并一事务改 `model_id,model,is_accessory`；没有目标或没有旧组返回 404。

#### Scenario: 旧文本大小写不同
- **WHEN** 未归类设备分别写 ` X200U ` 和 `x200u`
- **THEN** 型号库显示一个旧组；归类成功后两台设备均指向同一正式型号

### Requirement: 设备普通编辑不能绕过正式型号和移仓接口

`PUT /api/devices/<id>` MUST 只允许通过 `model_id` 选择正式型号；只传旧 `model` 返回 400。已有正式型号时，单独传 `is_accessory` 不能与型号类型矛盾；没有正式型号的历史设备仍可单独改该布尔。名称、序列号更新需去空格后非空，序列号按其它设备查重；已有停用型号仅允许保持原 ID，不可选另一个停用型号。旧 `status` 参数返回 400。普通编辑成功不改变仓库和生命周期。

#### Scenario: 保持原停用型号编辑名称
- **WHEN** 设备关联的型号已停用，编辑仅改设备名称并继续提交原 `model_id`
- **THEN** 可以保存；若改选另一停用型号则返回 400

### Requirement: 移仓预览令牌和失败模式明确

移仓预览 MUST 使用 `warehouse-device-movement-v1` 签名 salt，令牌有效 600 秒，包含租户 ID、源设备、目标仓、修复操作和相关仓库／设备／租赁快照。执行按相关仓库、设备、租赁 ID 排序锁定；令牌过期、设备 ID 不符、租户不符或快照变化均返回 409 并要求重预览。请求 JSON 缺失、缺目标仓或缺令牌返回 400。验货跨仓的未来订单修复另用 `receipt_repair` 模式，但仍受相同快照和原子提交要求。

#### Scenario: 十分钟后提交旧令牌
- **WHEN** 从预览起超过 600 秒后调用 `/api/devices/<id>/move`
- **THEN** 返回 409，设备仓库和租赁安排保持原状

### Requirement: 内部可用库存按物流占用窗口计算

`GET /api/inventory/available` MUST 要求 `start_date,end_date` 且通过公共日期范围校验，按起始日 19:00 到结束日 12:00 查询；`device_type` 是设备名大小写不敏感的子串筛选，仓库可选。只返回当前租户、非附件且生命周期 active、在该窗口与未取消有效租赁的寄出／收回半开区间不冲突的设备。响应 `data` 每项含 `id,name,serial_number,lifecycle_status,warehouse_id,location:null`。该接口虽在源码注释称“无需认证”，实际全局 `/api/*` 边界仍要求租户会话，不能按注释暴露。

#### Scenario: 物流占用交叠但租期未交叠
- **WHEN** 设备租期与查询租期不重叠，寄出到收回窗口却有交集
- **THEN** 内部可用库存不返回该设备

### Requirement: 可用设备优先级反映最近收回时间

库存服务 MUST 先列无此前收回记录的设备；有记录的设备按“最近一次 `ship_in_time <= 查询寄出时间`”计算小时差，4–24 小时组排其后，**当前代码组内用负小时差排序，因此间隔较长者先**；超过 24 小时组再后且较短差先，少于 4 小时组最后且较短差先。相同优先级保留数据库原始顺序。`check_device_availability` 对指定 ID 返回 `available` 和 `device_info` 或冲突租赁列表；重叠条件是旧寄出 `<` 新收回且旧收回 `>` 新寄出，编辑时可排除一条租赁 ID。

#### Scenario: 两台空闲设备一台刚归还
- **WHEN** 一台从无订单，另一台在 6 小时前收回，第三台在 2 小时前收回
- **THEN** 可用设备候选顺序为无此前收回、6 小时、2 小时；是否最终允许新建仍由租赁提交校验决定

### Requirement: 设备列表、单条详情和生命周期接口保留不同字段集合

普通列表的每个 `Device.to_dict()` MUST 返回 `id,name,serial_number,model,model_id,device_model,is_accessory,warehouse_id,lifecycle_status,lifecycle_reason,lifecycle_date,created_at,updated_at`；`device_model` 为嵌套型号或 null。旧 `GET /api/devices/<id>` 的 `data` 只含 `id,name,serial_number,model,is_accessory,warehouse_id,lifecycle_status,created_at,updated_at`，不可假定它与列表项目完全相同。普通列表按生命周期日期 null 优先、非 null 日期倒序、创建日期倒序分页。生命周期汇总含五状态与 total，另给 `active_and_online,excluded_from_statistics,available_for_rental`；这里两个 active 数量相同，**不检查档期占用**。生命周期列表按日期 null 优先、非 null 日期倒序、创建日期倒序，给每项补 `is_in_service,is_excluded_from_statistics`，并在顶层给 `total,filter`。

#### Scenario: active 设备已被同期租出
- **WHEN** 一台 active 主设备已有占用订单，请求生命周期汇总与可用档期查询
- **THEN** 生命周期汇总仍把它计入 `available_for_rental`，档期查询可判不可用；两个字段口径保持分离

### Requirement: 生命周期接口只修改设备经营状态

`PUT /api/devices/<id>/lifecycle` MUST 接 `lifecycle_status` 与可选 `lifecycle_reason`，调用设备模型的状态转换，成功回 `id,name,lifecycle_status,lifecycle_reason,lifecycle_date,is_in_service,is_excluded_from_statistics`。`PUT .../mark-sold` 接可选 `reason`，未给时用“设备已销售”；已 sold 时返回 400，成功返回更小的设备摘要。两种操作保留历史租赁，`lifecycle_date` 用本次转换时间而不是租期终点；普通 `PUT /api/devices/<id>` 不可用旧 `status` 字段代替此操作。

#### Scenario: 重复快速标售
- **WHEN** 一台已 sold 的设备再次调用 `mark-sold`
- **THEN** 返回 400“设备已处于已销售状态”，旧租赁和首次标售状态不改变

## 数据字典与核心 API

`devices`：`id` 自增、`name` varchar100、`serial_number` varchar100 唯一、`model` varchar50、`model_id` 可空、`is_accessory`、非空 `warehouse_id`、生命周期状态／原因／日期、UTC 创建／更新时间。`device_models`：唯一 `name` varchar50、`display_name` varchar100、`description`、`is_active`、`is_accessory`、`parent_model_id`、`default_accessories` JSON 文本、`device_value` decimal(10,2)、`allowed_lens_combos`、`default_lens_combo`、`rental_packages` JSON 文本、`default_rental_package_id`。`warehouses` 与集成配置字段见 `tenant-access`。

| 路径 | 数据契约 |
|---|---|
| `GET /api/devices` | 查询 `page,per_page,q,name,model,serial_number,lifecycle_status,is_accessory,warehouse_id`；返回 `{devices,total,pages,current_page,per_page,has_next,has_prev}` |
| `POST /api/devices/search` | 相同筛选放 JSON；`status` 参数拒绝 |
| `GET/POST /api/devices`、`GET/PUT/DELETE /api/devices/<id>` | 创建设备 201；读取／更新／删除按当前租户 ID，历史旧路径错误键可能为 `error` |
| `PUT /api/devices/<id>/lifecycle`、`PUT .../mark-sold` | 更改生命周期、记录时间与原因 |
| `GET /api/devices/lifecycle/summary`、`GET .../list` | 生命周期数量及设备列表；可选仓库 |
| `POST /api/devices/<id>/movement-preview`、`POST .../move` | 预览签名 token；执行 token 且返回移仓摘要 |
| `GET /api/device-models` | `{success:true,data:[启用主型号及其启用附件]}` |
| `GET /api/device-models/library` | `{models:[含停用型号／引用数],legacy_groups:[未归类旧文本组]}` 位于通用 `data` 中 |
| `GET /api/device-models/<id>/accessories` | 启用附件型号 |
| `POST/PUT/DELETE /api/device-models` | 管理员维护正式型号；冲突 409 |
| `POST /api/device-models/assign-legacy` | `{legacy_model,model_id}` → 更新数与型号 |
| `GET /api/warehouses` | 当前租户所有仓库非密钥信息，供导航选择 |

## 页面契约

PC `/devices` 提供设备列表、筛选、主机／附件、生命周期标签、创建／编辑／删除、标售与跨仓移动弹窗；型号库从设置与设备管理可维护。移动 `/mobile/device-status` 展示仓库内设备生命周期与状态操作；两端均需反映同一数据库状态。PC 租赁创编和移动租赁创编的设备下拉排序及冲突状态见 `rental-management`，不能从本页列表排序推断租赁下拉排序。

## 代码依据与验收

依据：`app/models/{device,device_model,warehouse}.py`、`app/routes/{device_api,device_model_api,inventory_api,settings_api}.py`、`app/services/device/`、`app/services/inventory_service.py`、`app/services/warehouse_movement_service.py`、PC `DeviceManagementView.vue`、移动 `DeviceStatusView.vue`、`WarehouseMovementDialog.vue`。验收须覆盖型号创建／停用／删除限制、旧型号归类、设备序列号唯一、生命周期与租赁占用区别、双仓库读写、跨仓预览过期回滚，以及历史设备仍可读。
