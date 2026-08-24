# SaaS Main Lite Phase 2 Warehouse Business Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有实际库存和主/子租赁结构的前提下，加入 4 张业务配置表、仓库维度、成员/仓库设置、同仓租赁约束、跨仓影响预览与自动修正、验货入仓和便利的桌面/移动操作。

**Architecture:** `devices.warehouse_id` 表示设备当前实际位置，`rentals.warehouse_id` 固化履约仓库。仓库、SF、快麦和闲鱼店铺是 4 张新表；业务查询直接在现有 Service 上增加 warehouse filter。跨仓服务复用甘特图重排已有的签名预览思想，执行时重新校验并在单事务内移动设备、逐租赁全有或全无替换附件。

**Tech Stack:** Flask-SQLAlchemy、Alembic、MariaDB 10.11、现有 Service/Handler、Vue 3、Pinia、Element Plus、Vant、Vitest、pytest

**Spec:** `docs/superpowers/specs/2026-08-24-saas-main-lite-design.md` §§10–12、15、18.2–18.3、19

## Global Constraints

- 业务库新增表必须且只能是 `warehouses`、`warehouse_sf_configs`、`warehouse_kuaimai_configs`、`xianyu_shops`。
- 不添加 `tenant_id`、`device_models.inventory_mode`、logical inventory、stock ledger、reservation、movement 或 printer 表。
- 手机支架、三脚架继续是实际 `Device`，继续通过子 `Rental` 分配；手柄和镜头支架继续用现有布尔字段。
- 仓库不提供删除。仓库基础字段只有省、市、名称；顺丰和打印配置分表保存。
- 敏感配置字段永不回传原文；空字符串/缺字段表示保持原值，显式 `clear_secret=true` 也不在首版提供。
- 当前仓库只存在前端 Pinia 内存中，不新增用户偏好表；只有一仓时自动选择。
- `warehouse_id=all` 只允许列表/统计读取；设备和租赁写操作必须是具体整数仓库。
- 已发货或已有运单的租赁不得被跨仓自动修正。
- 历史已完成租赁保留原履约仓库；验货只移动实际 Device。

---

### Task 1: 用两条业务迁移加入 4 表与仓库/店铺外键

**Files:**
- Create: `InventoryManager/app/models/warehouse.py`
- Create: `InventoryManager/app/models/xianyu_shop.py`
- Create: `InventoryManager/migrations/versions/20260824_saas_lite_expand.py`
- Create: `InventoryManager/migrations/versions/20260824_saas_lite_contract.py`
- Create: `InventoryManager/tests/integration/test_saas_lite_business_migrations.py`
- Modify: `InventoryManager/app/models/__init__.py`
- Modify: `InventoryManager/app/models/device.py`
- Modify: `InventoryManager/app/models/rental.py`
- Modify: `InventoryManager/app/models/xianyu_order_alert.py`

**Interfaces:**
- `Warehouse(id, province, city, name, created_at, updated_at)`; name default由 service 生成 `province + city + '仓库'`。
- `WarehouseSFConfig(warehouse_id PK/FK, partner_id, checkword_ciphertext, monthly_card_ciphertext, test_mode, sender_name, sender_phone, sender_address, timestamps)`。
- `WarehouseKuaimaiConfig(warehouse_id PK/FK, app_id, app_secret_ciphertext, printer_sn, timestamps)`。
- `XianyuShop(id, name, app_key, app_secret_ciphertext, is_active, last_success_at, last_error, timestamps)`。
- `Device.warehouse_id` non-null；`Rental.warehouse_id` non-null；`Rental.xianyu_shop_id` nullable；`XianyuOrderAlert.xianyu_shop_id` non-null。

- [ ] **Step 1: 写迁移 RED 测试**

从当前 head `20260807_damage_notes` 建两类库：空库迁移链、带现有 Device/主子 Rental/Xianyu alert/sync state 的旧库。断言最终恰好新增 4 表，所有设备/租赁指向默认仓，所有旧告警指向默认店，sync state 的成功/错误字段复制后旧表删除，组合唯一约束存在。

```python
def test_contract_backfills_existing_rows(connection):
    assert connection.scalar(text("select count(*) from devices where warehouse_id is null")) == 0
    assert connection.scalar(text("select count(*) from rentals where warehouse_id is null")) == 0
    assert connection.scalar(text("select count(*) from xianyu_order_alerts where xianyu_shop_id is null")) == 0
    assert "xianyu_order_sync_state" not in inspect(connection).get_table_names()
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_saas_lite_business_migrations.py -q
```

- [ ] **Step 3: 写 expand migration 和模型**

`20260824_saas_lite_expand` 的 `down_revision = '20260807_damage_notes'`。创建 4 表，为 3 张旧表加可空外键；移除 `xianyu_order_alerts.order_no` 的单列 unique 前先建立普通索引。所有 FK 使用 `RESTRICT`/默认限制，不 cascade 删除仓库/店铺。

模型 `to_dict()` 只返回 `*_configured` 和可公开字段；SF 月结卡最多返回尾 4 位掩码，checkword/app_secret 不返回任何片段。

- [ ] **Step 4: 写 contract migration**

在同一业务库事务中创建一条占位默认仓库（省/市=`待配置`、名称=`默认仓库`）和一条停用默认店铺（名称=`默认闲鱼店铺`、app_key 空字符串），把所有现有 Device、主/子 Rental、alert 绑定；把全局 sync state 复制到默认店铺后删除旧表。

随后把 `devices.warehouse_id`、`rentals.warehouse_id`、`xianyu_order_alerts.xianyu_shop_id` 改为非空，并建立：

```python
sa.UniqueConstraint("xianyu_shop_id", "order_no", name="uq_xianyu_alert_shop_order")
sa.UniqueConstraint("xianyu_shop_id", "xianyu_order_no", name="uq_rental_shop_order")
```

contract downgrade 只恢复列/旧 sync state 的结构，不承诺还原已合并的多店数据；正式回滚遵循完整备份恢复。

- [ ] **Step 5: 运行迁移、模型和现有回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_saas_lite_business_migrations.py tests/integration/test_rental_api.py tests/integration/test_xianyu_order_alert_api.py -q
git diff --check
git add app/models migrations/versions/20260824_saas_lite_expand.py migrations/versions/20260824_saas_lite_contract.py tests/integration/test_saas_lite_business_migrations.py
git commit -m "feat: add warehouse and shop business schema"
```

---

### Task 2: 增加成员、仓库和配置设置 API

**Files:**
- Create: `InventoryManager/app/services/settings_service.py`
- Create: `InventoryManager/app/routes/settings_api.py`
- Create: `InventoryManager/tests/integration/test_settings_api.py`
- Modify: `InventoryManager/app/__init__.py`
- Modify: `InventoryManager/app/control/store.py`
- Modify: `InventoryManager/app/models/warehouse.py`

**Interfaces:**
- `GET/POST /api/settings/members`; `PATCH /api/settings/members/<id>`。
- `GET/POST /api/settings/warehouses`; `PATCH /api/settings/warehouses/<id>`。
- `PUT /api/settings/warehouses/<id>/sf`; `PUT /api/settings/warehouses/<id>/kuaimai`。
- 全部 endpoint 仅 tenant Admin；Operator 返回 `FORBIDDEN`。

- [ ] **Step 1: 写权限、字段和脱敏 RED 测试**

覆盖：省市必填、空 name 自动生成、省市变化不覆盖已自定义 name、partner_id 可跨仓重复、每仓配置 upsert、空 secret 保持原密文、Admin 成员增改禁用、禁止禁用/降级最后一个 active Admin、Operator 403、API 不含 ciphertext/secret。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_settings_api.py -q
```

- [ ] **Step 3: 实现 settings service**

成员写操作使用控制库事务；仓库/配置写操作使用当前租户业务 `db.session`。`SettingsService` 不做通用配置仓储，只提供明确方法：

```python
create_warehouse(province: str, city: str, name: str | None) -> Warehouse
update_warehouse(warehouse_id: int, payload: dict) -> Warehouse
upsert_sf_config(warehouse_id: int, payload: dict, secret_box: SecretBox) -> WarehouseSFConfig
upsert_kuaimai_config(warehouse_id: int, payload: dict, secret_box: SecretBox) -> WarehouseKuaimaiConfig
```

手机号仍保持全局唯一；最后 active Admin 校验和更新在同一控制库事务内锁定该租户成员行。

- [ ] **Step 4: 注册路由、运行回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_settings_api.py tests/integration/test_auth_api.py -q
git diff --check
git add app/services/settings_service.py app/routes/settings_api.py app/__init__.py app/control/store.py app/models/warehouse.py tests/integration/test_settings_api.py
git commit -m "feat: add tenant member and warehouse settings"
```

---

### Task 3: 将库存、甘特图、设备和租赁限制到履约仓库

**Files:**
- Create: `InventoryManager/tests/integration/test_warehouse_rental_flow.py`
- Modify: `InventoryManager/app/services/inventory_service.py`
- Modify: `InventoryManager/app/services/gantt/gantt_service.py`
- Modify: `InventoryManager/app/services/rental/rental_service.py`
- Modify: `InventoryManager/app/handlers/inventory_handlers.py`
- Modify: `InventoryManager/app/handlers/gantt_handlers.py`
- Modify: `InventoryManager/app/handlers/rental_handlers.py`
- Modify: `InventoryManager/app/routes/device_api.py`
- Modify: `InventoryManager/app/models/device.py`
- Modify: `InventoryManager/app/models/rental.py`

**Interfaces:**
- 列表查询统一接受可空 `warehouse_id`；`None` 由前端明确传当前仓，字符串 `all` 仅用于读接口。
- `RentalService.create_rental_with_accessories(data)` 要求具体 `warehouse_id`，可空 `xianyu_shop_id`。
- Device/Rental `to_dict()` 返回 `warehouse_id`；主租赁返回 `xianyu_shop_id`。

- [ ] **Step 1: 写同仓创建与筛选 RED 测试**

覆盖：仓 A 查询不见仓 B 设备、all 能看两仓、创建设备默认当前仓、租赁主设备/实际附件必须同仓、主子租赁写相同 warehouse_id、跨仓附件被拒绝且整单不落库、未来冲突检查只选指定仓设备、一个启用店铺自动绑定、多店时缺 shop_id 返回 400、非闲鱼订单允许空店铺。

```python
def test_rental_rejects_cross_warehouse_accessory(client, admin_session, devices):
    response = client.post(
        "/api/rentals",
        json={
            "warehouse_id": devices.main.warehouse_id,
            "device_id": devices.main.id,
            "accessories": [devices.other_warehouse_tripod.id],
            **rental_payload(),
        },
        headers=admin_session.csrf_headers,
    )
    assert response.status_code == 409
    assert response.json["code"] == "WAREHOUSE_MISMATCH"
    assert Rental.query.count() == 0
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_warehouse_rental_flow.py -q
```

- [ ] **Step 3: 在现有 service/handler 上增加参数**

不新建查询层。`InventoryService.query_available_inventory`、Gantt 数据/统计/slot、Rental list/create/update 和 Device list/create/update 直接增加 warehouse filter。写操作先加载仓库，再校验主设备和每个实际附件的 `warehouse_id`，最后统一 commit。

主租赁 xianyu 店铺规则在 RentalService 内实现：告警创建直接继承 alert shop；手工带闲鱼订单号时 1 个 active shop 自动选，多个 active shop 必填；普通线下订单忽略 shop 为空。

- [ ] **Step 4: 运行相关回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_warehouse_rental_flow.py tests/unit/test_rental_service.py tests/integration/test_rental_api.py tests/unit/test_gantt_device_eligibility.py tests/integration/test_gantt_reorder_api.py -q
git diff --check
git add app/services/inventory_service.py app/services/gantt/gantt_service.py app/services/rental/rental_service.py app/handlers app/routes/device_api.py app/models/device.py app/models/rental.py tests/integration/test_warehouse_rental_flow.py
git commit -m "feat: scope inventory and rentals to warehouses"
```

---

### Task 4: 实现跨仓影响预览和逐租赁原子修正

**Files:**
- Create: `InventoryManager/app/services/warehouse_movement_service.py`
- Create: `InventoryManager/tests/unit/test_warehouse_movement_service.py`
- Modify: `InventoryManager/app/routes/device_api.py`
- Modify: `InventoryManager/app/models/audit_log.py`

**Interfaces:**
- `WarehouseMovementService.preview(device_id: int, target_warehouse_id: int) -> dict`
- `WarehouseMovementService.execute(token: str) -> dict`
- `POST /api/devices/<id>/movement-preview {target_warehouse_id}`
- `POST /api/devices/<id>/move {token}`
- 返回 `auto_fixable[]`、`blocked[]`、`shortages[]`、`manual[]` 和签名 token。

- [ ] **Step 1: 写主设备、附件和并发变化 RED 测试**

覆盖：主设备移仓时租赁跟随并按 model_id 替换附件；附件单独移仓时租赁留原仓并替换附件；无 model_id 时用规范化 model；缺货时该租赁零修改；已有运单/已发货只进 manual；多个未来租赁按各自日期检查可用性；预览后数据变化使 token stale；审计记录 old/new warehouse 和 replacements。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_warehouse_movement_service.py -q
```

- [ ] **Step 3: 实现签名预览与执行**

参考现有 `GanttReorderService.preview/execute` 的签名方式，但只复用小型签名 helper，不抽出通用工作流。token payload 包含 device/target、受影响 rental/device ids、updated_at 指纹、replacement ids 和 10 分钟 expiry。

执行在一个业务事务中：重新锁定相关 Device/Rental，验证指纹；先移动实际 Device，再对每个可修复租赁验证全部 replacement，全部满足才更新该租赁及其子租赁。某一租赁 shortage 时该租赁不做部分替换，但不回滚其他已完整可修复租赁或真实设备移仓。

`AuditLog.log_action` 增加 `commit=False` 参数以允许加入现有事务，默认行为保持兼容。

- [ ] **Step 4: 运行测试和甘特图回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_warehouse_movement_service.py tests/integration/test_warehouse_rental_flow.py tests/integration/test_gantt_reorder_api.py -q
git diff --check
git add app/services/warehouse_movement_service.py app/routes/device_api.py app/models/audit_log.py tests/unit/test_warehouse_movement_service.py
git commit -m "feat: preview and repair warehouse movements"
```

---

### Task 5: 验货时同步主设备与实际附件仓位

**Files:**
- Create: `InventoryManager/tests/integration/test_inspection_warehouse.py`
- Modify: `InventoryManager/app/services/inspection_service.py`
- Modify: `InventoryManager/app/routes/inspection.py`
- Modify: `InventoryManager/app/models/inspection_record.py`

**Interfaces:**
- 验货创建 payload 增加 `receiving_warehouse_id` 和 `received_device_ids`。
- 默认 receiving warehouse 是主租赁 `warehouse_id`。
- 响应增加 `warehouse_impacts`，格式直接复用 Task 4 preview 摘要，不新增 inspection 表字段。

- [ ] **Step 1: 写验货事务 RED 测试**

覆盖：默认原履约仓；选择其他收货仓时移动主设备和本次收到的实际附件 Device；未收到附件不移动；手柄/镜头支架布尔字段不当作 Device；历史 Rental warehouse 不变；检查项或设备校验失败时记录与仓位都回滚；未来租赁影响返回预览。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_inspection_warehouse.py -q
```

- [ ] **Step 3: 合并为单事务实现**

移除 `InspectionService.create_inspection_record` 中的中途 commit。加载主租赁及子租赁，验证 `received_device_ids` 只能来自主设备和该租赁的实际附件；写 inspection/check items、更新 Device warehouse、写 audit log 后一次 commit。完成后再计算未来影响预览，不修改历史 rental warehouse。

- [ ] **Step 4: 运行验货与回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_inspection_warehouse.py tests/unit/test_checklist_generator.py tests/integration/test_rental_api.py -q
git diff --check
git add app/services/inspection_service.py app/routes/inspection.py app/models/inspection_record.py tests/integration/test_inspection_warehouse.py
git commit -m "feat: move inspected devices into receiving warehouse"
```

---

### Task 6: 增加当前仓、设置页和便利操作

**Files:**
- Create: `InventoryManager/frontend/src/stores/tenant.ts`
- Create: `InventoryManager/frontend/src/api/settings.ts`
- Create: `InventoryManager/frontend/src/components/AppHeader.vue`
- Create: `InventoryManager/frontend/src/views/SettingsView.vue`
- Create: `InventoryManager/frontend/src/components/settings/MemberSettings.vue`
- Create: `InventoryManager/frontend/src/components/settings/WarehouseSettings.vue`
- Create: `InventoryManager/frontend/src/components/WarehouseMovementDialog.vue`
- Create: `InventoryManager/frontend/tests/unit/warehouse-navigation.spec.ts`
- Create: `InventoryManager/frontend/tests/unit/warehouse-movement.spec.ts`
- Create: `InventoryManager/frontend-mobile/src/stores/tenant.ts`
- Modify: `InventoryManager/frontend/src/App.vue`
- Modify: `InventoryManager/frontend/src/router/index.ts`
- Modify: `InventoryManager/frontend/src/components/BookingDialog.vue`
- Modify: `InventoryManager/frontend/src/components/GanttChart.vue`
- Modify: `InventoryManager/frontend/src/views/InspectionView.vue`
- Modify: `InventoryManager/frontend-mobile/src/App.vue`
- Modify: `InventoryManager/frontend-mobile/src/views/CreateRentalView.vue`
- Modify: `InventoryManager/frontend-mobile/src/views/EditRentalView.vue`

**Interfaces:**
- tenant store: `warehouses`, `currentWarehouseId: number | 'all'`, `selectWarehouse()`；唯一仓自动选，多仓默认第一仓。
- 所有列表请求显式携带 `warehouse_id`，不依赖 localStorage。
- Settings 三个 tab 先提供成员与仓库；闲鱼 tab 显示“下一阶段配置”空态，不创建假数据。

- [ ] **Step 1: 写当前仓和跨仓交互 RED 测试**

测试：唯一仓无额外选择、多仓 header 可切换、Operator 无设置入口、Admin 设置字段脱敏/空 secret 保持、租赁设备/附件随当前仓刷新、验货默认原仓可改、跨仓 dialog 展示可修复/缺货/人工处理并以 token 确认。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/warehouse-navigation.spec.ts tests/unit/warehouse-movement.spec.ts
```

- [ ] **Step 3: 实现桌面端最小 UI**

AppHeader 只显示租户、仓库、角色、设置、退出；业务页面继续保留原布局。仓库编辑抽屉分基本信息/SF/快麦三段并显示配置状态。移动设备时必须先 preview，再显示清单，确认后用 token execute；stale 时自动重新预览。

- [ ] **Step 4: 实现移动端当前仓上下文**

移动端 header 提供仓库下拉；创建/编辑租赁发送具体 warehouse_id。移动端不实现成员、仓库、凭证设置和复杂跨仓管理，用户跳桌面端完成。

- [ ] **Step 5: 运行构建、后端相关回归并提交**

Run:

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/warehouse-navigation.spec.ts tests/unit/warehouse-movement.spec.ts
npm run type-check
npm run build-only
cd ../frontend-mobile
npm run build
cd ..
python -m pytest tests/integration/test_settings_api.py tests/integration/test_warehouse_rental_flow.py tests/integration/test_inspection_warehouse.py -q
git diff --check
git add frontend/src frontend/tests/unit/warehouse-navigation.spec.ts frontend/tests/unit/warehouse-movement.spec.ts frontend-mobile/src static/vue-dist static/vue-mobile-dist
git commit -m "feat: add warehouse-aware tenant interface"
```

---

### Task 7: 阶段 2 审查门

**Files:**
- Verify all files changed in Tasks 1–6.

**Interfaces:**
- Produces: 多仓租赁、库存、跨仓和验货完整纵向切片。

- [ ] **Step 1: 运行阶段完整回归**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit tests/integration -q
cd frontend && npm run test:run && npm run type-check && npm run build-only && cd ..
cd frontend-mobile && npm run build && cd ..
git diff --check
```

- [ ] **Step 2: 验证结构和规模**

Run:

```bash
rg -n "__tablename__" app/models | rg "warehouse|xianyu_shop"
rg -n "inventory_mode|logical_inventory|stock_event|printer_pool" app tests frontend/src
git diff --numstat my_xianyuagent/main...HEAD
git diff --name-status my_xianyuagent/main...HEAD
```

Expected: 只新增 4 张业务表；无逻辑库存/打印机池；业务迁移总数恰好 2 条；累计规模未触发总计划暂停门槛。

- [ ] **Step 3: 核对关键数据不变量**

在 MariaDB 集成库执行断言：所有 Device 有仓、所有 Rental 有仓、每组主子 Rental 同仓、所有 alert 有店、任何未来租赁的实际设备当前仓不一致都能被 movement preview 明确列出。发现不变量失败必须先补回归测试再修复。
