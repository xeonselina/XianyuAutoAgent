# INDEX — 功能域到文件的导航表

**用法**：改代码前先读本文件定位，禁止上来就全仓 glob/grep。
路径相对 `InventoryManager/`；`app/` 前缀已省略，例如本表中的 `routes/gantt_api.py`
实为 `app/routes/gantt_api.py`。前端列中 `PC` 指 `frontend/src/`、`移动` 指 `frontend-mobile/src/`。
**本表不含行号**（行号必腐坏）。定位请 grep 表格中给出的函数/类名。

## 1. 功能域 → 文件

| 域 | 关键词/别名 | 路由入口 | handler / service | 模型 | 前端 |
|---|---|---|---|---|---|
| 认证·会话·租户上下文 | auth 登录 session cookie csrf tenant 租户 绑定 | `routes/auth_api.py` | `auth.py`, `tenant_context.py`, `crypto.py`, `control/store.py`, `control/models.py` | `control/models.py` | PC `stores/auth.ts` `stores/tenant.ts` / 移动 `stores/auth.ts` |
| 平台管理·租户开通 | platform 平台 开通 provisioning 建库 | `routes/platform_api.py` | `provisioning.py`, `default_tenant_migration.py` | `control/models.py` | PC `views/PlatformTenantsView.vue` |
| 甘特图·排期重排 | gantt 甘特 排期 拖拽 重排 冲突 solver 档期 | `routes/gantt_api.py` | `handlers/gantt_handlers.py`; `services/gantt/{gantt_service,reorder_service,reorder_solver,reorder_types}.py` | `models/rental.py` | PC `components/GanttChart.vue` `views/GanttView.vue` / 移动 `components/GanttGrid.vue` |
| 设备·型号·生命周期 | device 设备 型号 lifecycle 生命周期 状态 | `routes/device_api.py`, `routes/device_model_api.py` | `handlers/device_handlers.py`, `handlers/device_model_handlers.py`; `services/device/*` | `models/device.py`, `models/device_model.py` | PC `composables/useDeviceManagement.ts` / 移动 `views/DeviceStatusView.vue` |
| 租赁单（核心） | rental 租赁 订单 booking 预约 damage 损伤 附件 | `routes/rental_api.py` | `handlers/rental_handlers.py`; `services/rental/rental_service.py`, `services/rental_service.py`; `utils/rental_validator.py` | `models/rental.py`（含同单 RentalBooking / 幂等 RentalBookingRequest）, `models/rental_accessory.py` | PC `components/BookingDialog.vue`, `components/rental/*` / 移动 `views/CreateRentalView.vue` `views/EditRentalView.vue` |
| 库存·仓库·调拨 | warehouse 仓库 库存 inventory 调拨 移库 | `routes/inventory_api.py`, `routes/settings_api.py` | `handlers/inventory_handlers.py`; `services/inventory_service.py`, `services/warehouse_movement_service.py`, `services/settings_service.py` | `models/warehouse.py` | PC `views/SettingsView.vue`, `components/WarehouseMovementDialog.vue` |
| 验货·检查清单 | inspection 验货 检查 checklist 清单 | `routes/inspection.py` | `services/inspection_service.py`, `services/checklist_generator.py` | `models/inspection_record.py`, `models/inspection_check_item.py` | PC `views/InspectionView.vue`, `components/inspection/*` |
| 发货·面单·物流 | shipping 发货 面单 waybill 顺丰 sf 快递 打印 追踪 | `routes/shipping_batch_api.py`, `routes/sf_tracking_api.py`, `routes/sf_test_api.py`, `routes/tracking_api.py` | `handlers/shipping_batch_handlers.py`; `services/shipping/*`（含 `services/shipping/shipment_group_service.py` 合单分组）, `services/printing/*`, `services/integration_resolver.py`; `utils/sf/sf_sdk_wrapper.py` | — | PC `views/BatchShippingView.vue` `views/ShippingOrderView.vue` `views/SFTrackingView.vue` / 移动 `views/BatchShippingView.vue` |
| 接力·续租 | relay 接力 续租 中转 case | `routes/relay_case_api.py` | `handlers/relay_case_handlers.py`; `services/relay/relay_case_service.py` | `models/rental_relay_case.py`, `models/rental_relay_binding.py` | PC `views/RelayManagementView.vue`, `components/relay/*` / 移动 `views/RelayManagementView.vue` |
| 统计·报表 | statistics 统计 报表 stats 数据 | `routes/statistics_api.py`, `routes/rental_stats_api.py` | `services/rental_statistics_service.py`; `scripts/rental_statistics.py` | `models/rental_statistics.py` | PC `views/RentalStatsView.vue`, `views/StatisticsView.vue` |
| 闲鱼对接·缺单告警 | xianyu 闲鱼 缺单 alert 告警 对账 shop 店铺 | `routes/xianyu_order_alert_api.py` | `handlers/xianyu_order_alert_handlers.py`; `services/xianyu_order_service.py`, `services/xianyu_order_reconciliation_service.py` | `models/xianyu_order_alert.py`, `models/xianyu_rental_alert.py`, `models/xianyu_shop.py` | PC `components/XianyuOrderAlertBar.vue`, `components/settings/XianyuShopSettings.vue` |
| 客户·历史订单 | customer 客户 历史订单 手机号 | `routes/customer_api.py` | — | — | PC `components/CustomerHistoryDialog.vue`, `utils/phoneExtractor.ts` / 移动 `views/CustomerHistoryView.vue` |
| 对外开放 API | external 外部 API 集成 openapi | `routes/external_api.py` | — | — | — |
| 定时任务·调度 | worker 定时 scheduler 调度 cron 对账 | — | `worker.py`, `utils/scheduler_tasks.py` | — | — |
| 审计日志 | audit 审计 日志 操作记录 | — | — | `models/audit_log.py` | — |
| 静态托管·路由分发 | vue 静态 首页 mobile UA 跳转 | `routes/vue_app.py`, `routes/web_pages.py` | — | — | PC `static/vue-dist/` / 移动 `static/vue-mobile-dist/` |

## 2. 蓝图注册链（找"某个 API 为什么没注册"看这里）

`app/__init__.py` 的 `create_app` 直接注册 9 个顶层蓝图：

```
auth_api, platform_api, settings_api, web, external_api(前缀 /external-api),
vue_app, tracking_api, device_model_api, statistics_api,
shipping_batch_api, sf_test_api, sf_tracking_api, inspection, rental_stats_api
```

**注意**：下面 8 个是**嵌套注册在 `web.bp` 之下**的（`routes/web.py`），不在顶层：

```
web_pages, gantt_api, device_api, rental_api, inventory_api,
customer_api, xianyu_order_alert_api, relay_case_api
```

worker 模式（`create_app(worker_mode=True)`）不注册任何蓝图、不加载静态资源与短信。

## 3. 已知死代码 —— 勿修、勿引用

| 路径 | 说明 |
|---|---|
| `routes/web_pages.py` 的 `/devices` `/rentals` | `render_template('devices.html'/'rentals.html')` 但模板不存在 → 访问必 500。**路由刻意保留未删**：删掉会把 500 变成 404，属行为变更，需单独决策 |
| `makefile.example` | 旧工具链遗留，52 个 target **全部不可用**；现役 Makefile 只有 6 个 target |
| `templates/error.html` | 服务端渲染现役只剩这一个模板；其余页面一律走 Vue 构建产物 |

已删除的死代码（2026-09，勿再寻找）：templates 下的 gantt.html 与 index.html、
static 下的旧移动端产物 mobile-dist（现役是 static/vue-mobile-dist）、
migrations_backup 目录、以及 frontend 目录下误放的 scheduler.py（0 字节空文件）。

## 4. 三个进程入口

| 入口 | 用途 | 关键点 |
|---|---|---|
| `run.py` | 生产 WSGI（gunicorn） | 首行必须 `gevent.monkey.patch_all()`，顺序不可改 |
| `app.py` | 开发 + Flask CLI，端口 5002 | 与 `run.py` 无调用关系 |
| `worker.py` | 定时任务 | 控制库 `GET_LOCK` 单实例互斥；发货调度 60s + 闲鱼对账 180s |
