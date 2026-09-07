# SaaS Main Lite Phase 3 Integrations and Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让顺丰、快麦和闲鱼显式使用租赁仓库或绑定店铺的配置，并用独立轻量 worker 每 60 秒处理预约发货、每 180 秒同步各租户闲鱼店铺。

**Architecture:** 三个现有集成客户端改为构造时注入已解密配置，单个 `IntegrationResolver` 负责从当前租户业务库解析仓库/店铺并实例化客户端。Worker 使用控制库筛选 active 且未过期租户，以 MariaDB advisory lock 保证单实例，再顺序绑定各租户业务库执行两个固定任务。

**Tech Stack:** 现有 SF SDK wrapper、requests、快麦 API、Flask-SQLAlchemy、MariaDB GET_LOCK、schedule 1.2、Vue 3、Element Plus、Vitest、pytest

**Spec:** `docs/superpowers/specs/2026-08-24-saas-main-lite-design.md` §§13–16、19–20

## Global Constraints

- 不建立通用 external config 表、client registry、outbox、job、attempt、lease 或 retry 表。
- SF 下单、打印、轨迹全部从 Rental.warehouse_id 解析；手工轨迹无法匹配 Rental 时必须传具体 warehouse_id。
- 顺丰寄件人姓名、电话、详细地址必须来自仓库 SF 配置，不允许硬编码默认值。
- 闲鱼客户端只使用店铺 app_key/app_secret 和全局 `XIANYU_API_DOMAIN`，删除 seller_id 和闲鱼独立寄件配置。
- 任何 secret、月结卡、完整手机号/地址、验证码和签名原文不得进入日志、API 或异常文本。
- Worker 只运行两个任务；不顺带迁移旧的小时轨迹 scheduler。轨迹查询继续由现有手工/页面流程触发。
- 单个租户、仓库、店铺或租赁失败必须记录脱敏 ID 并继续；不得让一个失败终止全轮。
- 同一进程内任务顺序运行且不重叠；第二个 worker 无法取得 advisory lock 时应明确退出，不作为 standby 常驻。

---

### Task 1: 将三个集成客户端改为显式配置并集中解析

**Files:**
- Create: `InventoryManager/app/services/integration_resolver.py`
- Create: `InventoryManager/tests/unit/test_integration_resolver.py`
- Modify: `InventoryManager/app/services/shipping/sf_express_service.py`
- Modify: `InventoryManager/app/services/shipping/sf_tracking_service.py`
- Modify: `InventoryManager/app/services/printing/kuaimai_service.py`
- Modify: `InventoryManager/app/services/xianyu_order_service.py`
- Modify: `InventoryManager/config.py`

**Interfaces:**
- `SFExpressService(sf_config: SFServiceConfig)`；字段为 partner_id/checkword/monthly_card/test_mode/sender_name/sender_phone/sender_address/province/city。
- `KuaimaiPrintService(config: KuaimaiServiceConfig)`；字段为 app_id/app_secret/printer_sn。
- `XianyuOrderService(shop_config: XianyuShopConfig, api_domain: str)`；字段只有 shop_id/app_key/app_secret。
- `IntegrationResolver.sf_for_rental(rental)`, `sf_for_warehouse(id)`, `kuaimai_for_rental(rental)`, `xianyu_for_rental(rental)`, `xianyu_for_shop(shop)`。

- [ ] **Step 1: 写配置来源与缺失配置 RED 测试**

建立同租户两个仓库和两个店铺，各自使用不同 secret；断言 resolver 返回对应客户端，partner_id 允许相同；缺失任一必填配置抛出 `ConfigurationIncomplete` 且只带 warehouse/shop id 和缺失字段名；构造客户端期间不读旧业务凭证环境变量。

```python
def test_sf_resolution_uses_rental_warehouse(resolver, rental_a, rental_b):
    assert resolver.sf_for_rental(rental_a).config.sender_name == "仓A寄件人"
    assert resolver.sf_for_rental(rental_b).config.sender_name == "仓B寄件人"

def test_xianyu_service_does_not_read_seller_id(monkeypatch, resolver, shop):
    monkeypatch.setenv("XIANYU_SELLER_ID", "must-not-be-used")
    client = resolver.xianyu_for_shop(shop)
    assert not hasattr(client, "seller_id")
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_integration_resolver.py -q
```

- [ ] **Step 3: 改造现有构造器**

在各自 service 模块内定义不可变 dataclass，不新建通用 credential 类型。删除 `os.getenv` 业务凭证读取、全局 singleton getter 和硬编码 SF sender。`XIANYU_API_DOMAIN` 仍是 app config 全局值，由 resolver 传入并校验为主机名，不允许任意 URL scheme/path。

- [ ] **Step 4: 实现小型 resolver**

resolver 直接查询 Warehouse/SF/Kuaimai/XianyuShop 模型并用 Phase 1 `SecretBox` 解密，返回具体客户端。API-facing 方法把 `ConfigurationIncomplete` 映射为 `CONFIG_INCOMPLETE`，其他外部失败映射 `EXTERNAL_SERVICE_ERROR`。

- [ ] **Step 5: 运行单元回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_integration_resolver.py tests/unit/test_xianyu_order_service.py tests/unit/test_sf_tracking_service.py -q
git diff --check
git add app/services/integration_resolver.py app/services/shipping app/services/printing/kuaimai_service.py app/services/xianyu_order_service.py config.py tests/unit/test_integration_resolver.py
git commit -m "refactor: resolve integrations by warehouse and shop"
```

---

### Task 2: 按租赁仓库完成顺丰下单、轨迹与快麦打印

**Files:**
- Create: `InventoryManager/tests/integration/test_warehouse_shipping.py`
- Modify: `InventoryManager/app/services/shipping/waybill_print_service.py`
- Modify: `InventoryManager/app/handlers/shipping_batch_handlers.py`
- Modify: `InventoryManager/app/handlers/rental_handlers.py`
- Modify: `InventoryManager/app/routes/sf_test_api.py`
- Modify: `InventoryManager/app/routes/sf_tracking_api.py`
- Modify: `InventoryManager/app/services/shipping/sf_tracking_service.py`
- Modify: `InventoryManager/app/utils/sf/sf_sdk_wrapper.py`

**Interfaces:**
- `build_sf_client_order_id(tenant_id: int, rental_id: int) -> str` 固定返回 `t{tenant_id}-r{rental_id}`。
- `validate_shipping_preflight(rental) -> None` 检查仓库、主设备、全部实际附件、SF 配置和已有运单。
- 手工轨迹 `POST /api/sf-tracking/query {tracking_no, warehouse_id?}`。
- 批量打印仍按 rental ids 输入，但内部按 warehouse 分组并逐仓使用唯一 printer_sn。

- [ ] **Step 1: 写双仓端到端 RED 测试**

覆盖：仓 A/B 下单使用各自 partner/monthly/sender；稳定 client order id 重试不变；主设备或附件仓位不一致返回 `WAREHOUSE_MISMATCH` 且不调用 SF；已有运单不重复下单；缺配置返回 `CONFIG_INCOMPLETE`；打印按仓分组；手工轨迹匹配租赁自动选仓，无法匹配缺 warehouse_id 则 400；不存在硬编码电话后四位。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_warehouse_shipping.py -q
```

- [ ] **Step 3: 实现统一发货前校验**

把校验放入现有 `waybill_print_service.py`，供单笔、批量和预约发货复用；不新建发货状态机。检查 `rental.parent_rental_id is None`、所有相关 Device warehouse、完整 sender/config、tracking number。每条失败直接返回对应错误，批量继续处理其他 rental。

- [ ] **Step 4: 修改路由与 SDK 调用**

所有 SF/Kuaimai 实例由 resolver 获得。删除 `SENDER_PHONE_LAST4='4947'` 和 `SF_CHECKPHONENO` 依赖；轨迹若 SF 必须校验手机号后四位，从匹配 rental 的收/寄件信息中按当前接口要求计算，无法安全得到时要求用户输入，不使用全局默认。

`sf_test_api` 在 production 默认 404；测试 endpoint 只能 `TESTING=true` 或开发配置启用，避免生产绕过业务前置校验。

- [ ] **Step 5: 运行发货/打印/租赁回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_warehouse_shipping.py tests/unit/test_sf_tracking_service.py tests/integration/test_rental_api.py -q
git diff --check
git add app/services/shipping app/handlers/shipping_batch_handlers.py app/handlers/rental_handlers.py app/routes/sf_test_api.py app/routes/sf_tracking_api.py app/utils/sf/sf_sdk_wrapper.py tests/integration/test_warehouse_shipping.py
git commit -m "feat: ship and print with warehouse credentials"
```

---

### Task 3: 实现多闲鱼店铺、店铺告警和立即同步

**Files:**
- Create: `InventoryManager/app/routes/xianyu_shop_api.py`
- Create: `InventoryManager/tests/integration/test_xianyu_multi_shop.py`
- Create: `InventoryManager/frontend/src/components/settings/XianyuShopSettings.vue`
- Create: `InventoryManager/frontend/tests/unit/xianyu-shop-settings.spec.ts`
- Modify: `InventoryManager/app/__init__.py`
- Modify: `InventoryManager/app/services/xianyu_order_reconciliation_service.py`
- Modify: `InventoryManager/app/handlers/xianyu_order_alert_handlers.py`
- Modify: `InventoryManager/app/routes/xianyu_order_alert_api.py`
- Modify: `InventoryManager/app/models/xianyu_order_alert.py`
- Modify: `InventoryManager/app/services/settings_service.py`
- Modify: `InventoryManager/frontend/src/views/SettingsView.vue`
- Modify: `InventoryManager/frontend/src/api/settings.ts`

**Interfaces:**
- `GET/POST /api/settings/xianyu-shops`; `PATCH /api/settings/xianyu-shops/<id>`；Admin only。
- `POST /api/settings/xianyu-shops/<id>/sync`；返回该店铺同步摘要。
- `XianyuOrderReconciliationService.reconcile_shop(shop_id: int) -> ReconciliationResult`。
- Alert list/ignore/create-rental 全部携带/使用 `xianyu_shop_id`。

- [ ] **Step 1: 写双店与失败缓存 RED 测试**

覆盖：两个店可有相同 order_no；只与同店 Rental 对账；完整分页成功才替换该店 pending alerts 和更新 last_success_at；任一页失败保留原 alerts/last_success_at 并写脱敏 last_error；停用店不自动同步但历史发货仍可读取绑定配置；从 alert 创建 Rental 继承店铺；立即同步仅 Admin。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_xianyu_multi_shop.py tests/integration/test_xianyu_order_alert_api.py -q
```

- [ ] **Step 3: 改造对账为显式 shop**

`reconcile_shop` 先用 resolver 建 client 并完整拉取分页，成功后在单事务内 upsert/delete 该 shop 的 pending alerts；ignored 保留。失败只更新该 shop `last_error` 并 rollback alert 变化。不要重新创建 sync state 表。

闲鱼发货从 Rental.xianyu_shop_id 解析 client，寄件信息从 Rental.warehouse_id 的 SF sender 配置读取；没有店铺的线下单跳过闲鱼通知。

- [ ] **Step 4: 实现设置 UI**

店铺列表展示 name/app_key/is_active/最近成功/最近错误/配置状态；secret 输入留空保持原值。提供新增、编辑、启停、单店立即同步。前端不显示 seller_id/API domain 字段，API domain 只来自全局环境。

- [ ] **Step 5: 运行前后端验证并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/integration/test_xianyu_multi_shop.py tests/integration/test_xianyu_order_alert_api.py tests/unit/test_xianyu_order_reconciliation_service.py -q
cd frontend
npm run test:run -- tests/unit/xianyu-shop-settings.spec.ts
npm run type-check
npm run build-only
cd ..
git diff --check
git add app/routes/xianyu_shop_api.py app/services app/handlers/xianyu_order_alert_handlers.py app/routes/xianyu_order_alert_api.py app/models/xianyu_order_alert.py app/__init__.py tests/integration/test_xianyu_multi_shop.py frontend/src frontend/tests/unit/xianyu-shop-settings.spec.ts static/vue-dist
git commit -m "feat: sync orders per xianyu shop"
```

---

### Task 4: 建立只含两个任务的独立 Worker

**Files:**
- Create: `InventoryManager/worker.py`
- Create: `InventoryManager/tests/unit/test_worker.py`
- Modify: `InventoryManager/app/utils/scheduler_tasks.py`
- Delete: `InventoryManager/app/utils/scheduler.py`
- Modify: `InventoryManager/app/__init__.py`
- Modify: `InventoryManager/Makefile`

**Interfaces:**
- `Worker.acquire_lock() -> bool`, `run_scheduled_shipping_cycle()`, `run_xianyu_sync_cycle()`, `run_forever()`。
- Worker command: `python worker.py`。
- Advisory lock 固定名 `inventory-manager-worker-v1`，在控制库专用 connection 生命周期内持有。

- [ ] **Step 1: 写调度、锁和失败隔离 RED 测试**

使用 fake clock/schedule/control store/tenant binder，覆盖：只选 provisioning active + tenant active + 未过期；shipping 60 秒；Xianyu 180 秒；同一轮逐租户；单租户/单店异常继续；第二 worker GET_LOCK=0 立即退出；任务串行不重叠；退出释放 lock/engine/session。

```python
def test_worker_registers_only_two_jobs(worker, fake_schedule):
    worker.register_jobs()
    assert [(job.interval, job.unit) for job in fake_schedule.jobs] == [
        (60, "seconds"), (180, "seconds")
    ]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_worker.py -q
```

- [ ] **Step 3: 提取可重入的两个 task 函数**

`process_scheduled_shipments_for_current_tenant()` 查询 due 主 Rental。每条先调用闲鱼发货（若绑定店铺），外部失败则保持 `scheduled_for_shipping` 并 rollback 该条；成功才更新主子状态/ship time 并 commit。

`reconcile_active_shops_for_current_tenant()` 顺序调用 Task 3 `reconcile_shop`，单店异常捕获后继续。删除 scheduler_tasks 中模块导入时创建 SF 全局客户端、文件锁和与这两个任务无关的调度入口；保留仍被手工轨迹页面调用的纯查询函数到对应 tracking service。

- [ ] **Step 4: 实现 worker 进程**

启动时创建 app/control store/engine registry，使用控制库 connection 执行：

```sql
SELECT GET_LOCK('inventory-manager-worker-v1', 0)
```

取得后先各运行一次 cycle，再注册 `schedule.every(60).seconds` 和 `schedule.every(180).seconds`；主循环 `run_pending()` 后短暂等待，不新增依赖。每个 tenant 用显式 app context + tenant binding，finally remove business session/reset context。

- [ ] **Step 5: 删除 APScheduler 路径并更新开发命令**

确认 `app/__init__.py` 不启动 scheduler 后删除旧 `app/utils/scheduler.py`。Makefile 将 scheduler 相关命令替换为单一 `run-worker: python worker.py`，不添加 Compose 或 Redis 命令。

- [ ] **Step 6: 运行 worker/业务回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_worker.py tests/integration/test_xianyu_multi_shop.py tests/integration/test_warehouse_shipping.py -q
rg -n "apscheduler|APScheduler|BackgroundScheduler" app requirements.txt worker.py
git diff --check
git add worker.py app/utils/scheduler_tasks.py app/utils/scheduler.py app/__init__.py Makefile tests/unit/test_worker.py
git commit -m "feat: run shipping and shop sync in lightweight worker"
```

Expected: `rg` 无命中，提交包含对旧 scheduler 文件的删除。

---

### Task 5: 清理敏感日志并加入回归门禁

**Files:**
- Create: `InventoryManager/tests/unit/test_sensitive_logging.py`
- Modify: `InventoryManager/app/services/printing/kuaimai_service.py`
- Modify: `InventoryManager/app/services/shipping/sf_express_service.py`
- Modify: `InventoryManager/app/services/shipping/sf_tracking_service.py`
- Modify: `InventoryManager/app/services/xianyu_order_service.py`
- Modify: `InventoryManager/app/auth.py`
- Modify: `InventoryManager/app/utils/sf/sf_sdk_wrapper.py`

**Interfaces:**
- `mask_phone(value) -> 138****8000`，短值全部隐藏。
- 外部异常 API 只返回稳定错误码和可公开摘要；详细 traceback 也不得含 request body/credential。

- [ ] **Step 1: 写 caplog RED 测试**

向 SF/Kuaimai/Xianyu/SMS 注入唯一 canary secret、手机号、地址、验证码和月结卡，分别触发成功/HTTP 错误/JSON 错误/exception；断言 `caplog.text`、API response 和 exception string 都不包含 canary，允许内部 tenant/warehouse/shop/rental id。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_sensitive_logging.py -q
```

Expected: 当前快麦 secret 和部分外部请求日志导致失败。

- [ ] **Step 3: 删除或降级敏感日志**

保留 endpoint path、HTTP status、外部业务 code、内部 IDs 和异常类型；删除请求/响应 body、完整 URL query、凭证、个人信息。统一使用 `mask_phone`，不建立通用日志框架。

- [ ] **Step 4: 运行安全与集成回归并提交**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit/test_sensitive_logging.py tests/unit/test_integration_resolver.py tests/integration/test_warehouse_shipping.py tests/integration/test_xianyu_multi_shop.py tests/integration/test_auth_api.py -q
git diff --check
git add app/services app/auth.py app/utils/sf/sf_sdk_wrapper.py tests/unit/test_sensitive_logging.py
git commit -m "fix: redact integration and authentication logs"
```

---

### Task 6: 阶段 3 审查门

**Files:**
- Verify all files changed in Tasks 1–5.

**Interfaces:**
- Produces: 可按仓发货/打印、按店同步且从 app 分离的 worker。

- [ ] **Step 1: 运行阶段完整回归**

Run:

```bash
cd InventoryManager
python -m pytest tests/unit tests/integration -q
cd frontend && npm run test:run && npm run type-check && npm run build-only && cd ..
cd frontend-mobile && npm run build && cd ..
git diff --check
```

- [ ] **Step 2: 扫描过度设计和遗留全局凭证**

Run:

```bash
rg -n "SF_PARTNER_ID|SF_CHECKWORD|SF_MONTHLY_CARD|KUAIMAI_APP_SECRET|XIANYU_APP_KEY|XIANYU_APP_SECRET|XIANYU_SELLER_ID|XIANYU_SHIP_" app
rg -n "outbox|event_bus|Celery|APScheduler|job_attempt|lease|fence|generation" app tests worker.py
git diff --numstat my_xianyuagent/main...HEAD
```

Expected: app 生产代码不再读取租户业务凭证环境变量；只允许 `XIANYU_API_DOMAIN` 全局读取；无通用任务/事件设施。

- [ ] **Step 3: 审查外部调用幂等与失败边界**

确认 SF 重试使用同一 `t{tenant_id}-r{rental_id}`；已存在 tracking 不重复下单；预约闲鱼通知失败不改 shipped；对账分页失败不覆盖 alerts；批量单条失败继续；worker 第二实例退出。发现缺口先补失败测试再修复。
